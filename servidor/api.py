"""FASE 2 - El backend. Un endpoint que importa: `POST /analizar`.

    POST /analizar          vídeo multipart  -> {job_id}
    GET  /estado/{job_id}   -> progreso, y el análisis entero cuando termina
    GET  /video/{job_id}    -> el vídeo anotado, si se pidió
    GET  /salud             -> para el arranque del cliente

Arrancar:

    uvicorn servidor.api:app --host 0.0.0.0 --port 8000

Lo que este servidor NO guarda: el vídeo. Se borra en cuanto termina el
análisis. Lo que devuelve -keypoints y métricas- se guarda en el móvil.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from metricas import LIMITACIONES, VERSION_METRICAS

from .errores import (
    FORMATO_NO_SOPORTADO,
    SIN_VIDEO_ANOTADO,
    TRABAJO_NO_ENCONTRADO,
    VIDEO_DEMASIADO_GRANDE,
)
from .esquemas import a_json, payload_fallo
from .seguridad import ExigirClave, clave_requerida
from .trabajos import Cola, Estado

TAMANO_MAXIMO = 200 * 1024 * 1024
"""[bytes] Un minuto de 1080p30 de móvil ronda los 100 MB. El doble deja
margen sin invitar a subir la sesión entera."""

EXTENSIONES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

@asynccontextmanager
async def ciclo(app: FastAPI):
    """La cola vive lo que vive la app, no lo que vive el import.

    Con un singleton de módulo, `apagar()` deja el ThreadPoolExecutor cerrado
    para siempre: el proceso sigue en pie, acepta vídeos y los tira con
    "cannot schedule new futures after shutdown". En producción se nota al
    recargar; en los tests, en cuanto hay más de un cliente.
    """
    # Se lee al arrancar, no en cada petición: si falta, el servidor no llega
    # a levantarse en vez de quedarse abierto a internet sin que nadie lo note.
    app.state.clave = clave_requerida()
    app.state.cola = Cola()
    yield
    # Al parar el servidor no se dejan vídeos de nadie en el disco.
    app.state.cola.apagar()


app = FastAPI(
    title="cAI-listhenics",
    version=f"m{VERSION_METRICAS}",
    description=(
        "Analiza vídeos de dominadas. El vídeo se borra del servidor en cuanto "
        "termina el análisis; solo viajan de vuelta keypoints y métricas."
    ),
    lifespan=ciclo,
)

# Todas las peticiones pasan por aquí antes que por ningún endpoint.
app.add_middleware(ExigirClave)


def cola_de(peticion: Request) -> Cola:
    """La cola de esta app. Que se pida explícitamente evita que un test -o un
    segundo `FastAPI`- acabe compartiendo hilos sin querer."""
    return peticion.app.state.cola


def _json(payload: dict, estado: int = 200) -> Response:
    """Respuesta con el saneado de NaN puesto: ver `esquemas.a_json`."""
    return Response(
        content=a_json(payload), media_type="application/json", status_code=estado
    )


@app.get("/salud")
def salud() -> JSONResponse:
    """Comprueba que el servidor está y qué versión de pipeline gasta.

    El cliente lo llama al arrancar: si la versión no es la de las series que
    tiene guardadas, sabe que lo nuevo y lo viejo no son comparables.
    """
    return JSONResponse(
        {
            "estado": "ok",
            "version_metricas": VERSION_METRICAS,
            "limitaciones": LIMITACIONES,
            "tamano_maximo_bytes": TAMANO_MAXIMO,
        }
    )


@app.post("/analizar")
async def analizar(
    peticion: Request,
    video: UploadFile = File(..., description="El vídeo de la serie"),
    device_id: str = Form(..., description="Identificador local del dispositivo"),
    anotar: bool = Form(False, description="Generar además el vídeo anotado a 720p"),
) -> Response:
    """Encola un vídeo y devuelve el `job_id` para preguntar por él.

    Devuelve 202: aceptado, todavía no hecho. El cliente pasa a `/estado`.
    """
    extension = Path(video.filename or "").suffix.lower()
    if extension not in EXTENSIONES:
        return _json(payload_fallo(FORMATO_NO_SOPORTADO), estado=415)

    destino = Path(tempfile.gettempdir()) / "cai" / f"{os.urandom(8).hex()}{extension}"
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Se copia por trozos y se corta en cuanto pasa del límite: leer el fichero
    # entero en memoria para luego rechazarlo es justo lo que hay que evitar.
    escritos = 0
    with destino.open("wb") as salida:
        while trozo := await video.read(1024 * 1024):
            escritos += len(trozo)
            if escritos > TAMANO_MAXIMO:
                salida.close()
                destino.unlink(missing_ok=True)
                return _json(payload_fallo(VIDEO_DEMASIADO_GRANDE), estado=413)
            salida.write(trozo)

    base = str(peticion.url_for("video_anotado", job_id="x")).rsplit("/", 1)[0]
    trabajo = cola_de(peticion).encolar(destino, device_id, anotar, base)
    return _json(
        {"job_id": trabajo.id, "estado": trabajo.estado.value, "progreso": 0.0},
        estado=202,
    )


@app.get("/estado/{job_id}")
def estado(peticion: Request, job_id: str) -> Response:
    """Progreso del análisis, y el análisis entero cuando está.

    El cliente pregunta cada segundo. Mientras `estado` sea `en_cola` o
    `procesando` solo vienen el estado y el progreso; cuando pasa a `hecho`, la
    misma respuesta trae ya el resultado completo y no hace falta otra llamada.
    """
    trabajo = cola_de(peticion).obtener(job_id)
    if trabajo is None:
        return _json(payload_fallo(TRABAJO_NO_ENCONTRADO, job_id=job_id), estado=404)

    if trabajo.estado is Estado.ERROR:
        cuerpo = payload_fallo(trabajo.fallo, job_id=job_id)
        cuerpo["estado"] = trabajo.estado.value
        # 200, no 5xx: el análisis falló, la petición no. Un 500 haría que el
        # cliente reintentara en vez de enseñar la instrucción al usuario.
        return _json(cuerpo)

    if trabajo.estado is Estado.HECHO:
        cuerpo = dict(trabajo.payload or {})
        cuerpo["estado"] = trabajo.estado.value
        cuerpo["progreso"] = 1.0
        return _json(cuerpo)

    return _json(
        {
            "job_id": job_id,
            "estado": trabajo.estado.value,
            "progreso": round(trabajo.progreso, 3),
        }
    )


@app.get("/video/{job_id}", name="video_anotado")
def video_anotado(peticion: Request, job_id: str) -> Response:
    """El vídeo anotado a 720p, si se pidió al encolar."""
    trabajo = cola_de(peticion).obtener(job_id)
    if trabajo is None:
        return _json(payload_fallo(TRABAJO_NO_ENCONTRADO, job_id=job_id), estado=404)
    ruta = trabajo.ruta_anotado
    if ruta is None or not Path(ruta).exists():
        return _json(payload_fallo(SIN_VIDEO_ANOTADO, job_id=job_id), estado=404)
    return FileResponse(
        ruta,
        media_type="video/mp4" if ruta.suffix == ".mp4" else "video/webm",
        filename=f"analisis_{job_id}{ruta.suffix}",
    )


@app.delete("/estado/{job_id}")
def olvidar(peticion: Request, job_id: str) -> Response:
    """Borra el trabajo y su vídeo anotado antes de que venza.

    El cliente lo llama cuando ya ha guardado el resultado en el móvil: no hay
    razón para que una copia siga aquí quince minutos más.
    """
    if not cola_de(peticion).olvidar(job_id):
        return _json(payload_fallo(TRABAJO_NO_ENCONTRADO, job_id=job_id), estado=404)
    return _json({"job_id": job_id, "estado": "olvidado"})
