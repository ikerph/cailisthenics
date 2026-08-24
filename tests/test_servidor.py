"""FASE 2: el backend.

El test que sujeta todo lo demás es `test_todos_los_valueerror_estan_clasificados`.
El catálogo de errores reconoce los fallos por un trozo del texto del mensaje, y
ese acoplamiento se pudre solo: alguien reescribe un mensaje en `contador.py`,
nadie se entera, y a partir de ahí el usuario recibe "algo falló" en vez de la
instrucción concreta. Ese test lee los `raise ValueError` del código fuente y
comprueba que ninguno cae en `DESCONOCIDO`.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import contador
import metricas
from servidor import errores, seguridad
from servidor.api import app
from servidor.seguridad import CABECERA
from servidor.esquemas import a_json, limpiar, payload_analisis
from tests import sintetico

RAIZ = Path(__file__).resolve().parent.parent


# --- clasificación de errores ---------------------------------------------


def mensajes_valueerror(fuente: Path) -> list[str]:
    """Los mensajes de todos los `raise ValueError(...)` de un fichero.

    Se leen del AST, no de una lista escrita a mano, para que añadir un error
    nuevo al pipeline haga fallar el test hasta que se le dé una instrucción al
    usuario.
    """
    arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    mensajes: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Raise) or not isinstance(nodo.exc, ast.Call):
            continue
        funcion = nodo.exc.func
        if not (isinstance(funcion, ast.Name) and funcion.id == "ValueError"):
            continue
        if not nodo.exc.args:
            continue
        texto = _texto_de(nodo.exc.args[0])
        if texto:
            mensajes.append(texto)
    return mensajes


def _texto_de(nodo: ast.expr) -> str:
    """La parte literal de una cadena, aunque sea una f-string concatenada."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        # Solo los trozos constantes: los `{}` se sustituyen en tiempo de
        # ejecución y no forman parte de lo que el catálogo reconoce.
        return "".join(
            t.value for t in nodo.values if isinstance(t, ast.Constant) and isinstance(t.value, str)
        )
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        return _texto_de(nodo.left) + _texto_de(nodo.right)
    return ""


@pytest.mark.parametrize("modulo", ["contador.py", "metricas.py"])
def test_todos_los_valueerror_estan_clasificados(modulo: str) -> None:
    mensajes = mensajes_valueerror(RAIZ / modulo)
    assert mensajes, f"no se encontró ningún ValueError en {modulo}"

    sin_clasificar = [
        m for m in mensajes if errores.clasificar(ValueError(m)) is errores.DESCONOCIDO
    ]
    assert not sin_clasificar, (
        f"estos ValueError de {modulo} llegarían al usuario como 'algo falló':\n  "
        + "\n  ".join(sin_clasificar)
    )


def test_cada_fallo_dice_que_hacer() -> None:
    """Una instrucción, no un diagnóstico: tiene que caber en una pantalla y
    decirle a alguien qué cambiar."""
    todos = [f for _, f in errores.CATALOGO] + [
        errores.DESCONOCIDO,
        errores.VIDEO_DEMASIADO_GRANDE,
        errores.FORMATO_NO_SOPORTADO,
        errores.TRABAJO_NO_ENCONTRADO,
        errores.SIN_VIDEO_ANOTADO,
    ]
    for fallo in todos:
        assert fallo.codigo.isupper()
        assert 10 < len(fallo.titulo) < 60
        assert len(fallo.instruccion) > 40


def test_una_excepcion_que_no_es_del_pipeline_no_se_disfraza() -> None:
    """Un `KeyError` es un bug nuestro, no algo que el usuario pueda arreglar."""
    assert errores.clasificar(KeyError("puntos")) is errores.DESCONOCIDO


# --- saneado de NaN --------------------------------------------------------


def test_los_nan_salen_como_null() -> None:
    sucio = {
        "a": float("nan"),
        "b": float("inf"),
        "c": [1.0, float("-inf"), 3.0],
        "d": np.array([np.nan, 2.0]),
        "e": np.float64("nan"),
    }
    limpio = limpiar(sucio)
    assert limpio == {"a": None, "b": None, "c": [1.0, None, 3.0], "d": [None, 2.0], "e": None}


def test_el_json_es_json_valido() -> None:
    """`json.dumps` escribe `NaN` a pelo, que no es JSON y revienta el cliente
    Dart a mitad de la respuesta. Aquí no puede pasar."""
    altura = sintetico.senal(1.4, 5, 30.0)
    resultado = sintetico.resultado_de(altura)
    serie = metricas.analizar(resultado)
    payload = payload_analisis(serie, resultado, job_id="x", video_anotado_url=None)

    crudo = a_json(payload).decode()
    assert "NaN" not in crudo
    assert "Infinity" not in crudo

    # `parse_constant` salta si aparece NaN/Infinity: es el cinturón además de
    # los tirantes, porque un JSON así lo relee Python pero no Dart.
    def prohibido(constante: str) -> None:
        raise AssertionError(f"constante no válida en JSON: {constante}")

    vuelta = json.loads(crudo, parse_constant=prohibido)
    assert vuelta["conteo"]["n_total"] == serie.n_total


def test_el_payload_trae_lo_que_el_cliente_necesita() -> None:
    altura = sintetico.senal(1.4, 6, 30.0)
    resultado = sintetico.resultado_de(altura)
    serie = metricas.analizar(resultado)
    payload = json.loads(
        a_json(payload_analisis(serie, resultado, job_id="x", video_anotado_url=None))
    )

    # Sin la barra y el umbral el gráfico no explica por qué contó lo que contó.
    for clave in ("barra_y_px", "barra_bu", "umbral_bu", "umbral_v_bu_s"):
        assert clave in payload["referencias"]
    # Los keypoints son el dataset: el vídeo se borra, si no viajan no existen.
    assert len(payload["keypoints"]) == len(altura)
    assert len(payload["keypoints"][0]) == 33
    assert len(payload["senal"]["altura_bu"]) == len(altura)
    assert len(payload["senal"]["fases"]) == len(altura)
    assert payload["limitaciones"] == metricas.LIMITACIONES
    assert payload["version_pipeline"]


# --- API -------------------------------------------------------------------


CLAVE = "clave-de-pruebas-larga-y-aleatoria"


@pytest.fixture
def cliente(monkeypatch):
    """Cliente con la clave puesta en todas las peticiones.

    Va en el constructor y no en cada llamada para que ningún test se olvide y
    acabe probando el 401 sin querer. Que la clave sea obligatoria lo cubre
    `tests/test_seguridad.py`.
    """
    monkeypatch.setenv(seguridad.VARIABLE, CLAVE)
    with TestClient(app, headers={CABECERA: CLAVE}) as c:
        yield c


def test_salud(cliente) -> None:
    cuerpo = cliente.get("/salud").json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["limitaciones"] == metricas.LIMITACIONES


def test_trabajo_inexistente_da_404_con_instruccion(cliente) -> None:
    respuesta = cliente.get("/estado/nohay")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["codigo"] == "TRABAJO_NO_ENCONTRADO"


def test_formato_rechazado(cliente) -> None:
    respuesta = cliente.post(
        "/analizar",
        files={"video": ("serie.txt", b"no soy un video", "text/plain")},
        data={"device_id": "test"},
    )
    assert respuesta.status_code == 415
    assert respuesta.json()["error"]["codigo"] == "FORMATO_NO_SOPORTADO"


def test_video_ilegible_da_instruccion_no_stack_trace(cliente) -> None:
    """Un MP4 que no lo es: el pipeline falla y el cliente recibe qué hacer."""
    respuesta = cliente.post(
        "/analizar",
        files={"video": ("serie.mp4", b"\x00" * 2048, "video/mp4")},
        data={"device_id": "test"},
    )
    assert respuesta.status_code == 202
    job = respuesta.json()["job_id"]

    cuerpo = _esperar(cliente, job)
    assert cuerpo["estado"] == "error"
    assert cuerpo["error"]["codigo"] in {"VIDEO_ILEGIBLE", "VIDEO_VACIO", "FPS_INVALIDO"}
    assert cuerpo["error"]["instruccion"]
    assert "Traceback" not in json.dumps(cuerpo)


def _esperar(cliente, job: str, intentos: int = 600) -> dict:
    """Sondea `/estado` como haría el cliente."""
    import time

    for _ in range(intentos):
        cuerpo = cliente.get(f"/estado/{job}").json()
        if cuerpo.get("estado") in {"hecho", "error"}:
            return cuerpo
        time.sleep(0.1)
    raise AssertionError(f"el trabajo {job} no terminó")


# --- extremo a extremo con vídeo real --------------------------------------

VIDEO = RAIZ / "bandicam 2026-08-17 10-44-07-429.mp4"


@pytest.mark.skipif(not VIDEO.exists(), reason="hace falta un vídeo de prueba")
def test_analisis_completo_y_el_video_se_borra(cliente) -> None:
    with VIDEO.open("rb") as f:
        respuesta = cliente.post(
            "/analizar",
            files={"video": (VIDEO.name, f, "video/mp4")},
            data={"device_id": "test-e2e", "anotar": "false"},
        )
    assert respuesta.status_code == 202
    job = respuesta.json()["job_id"]

    cuerpo = _esperar(cliente, job)
    assert cuerpo["estado"] == "hecho", cuerpo
    assert cuerpo["conteo"]["n_total"] == 3
    assert cuerpo["conteo"]["n_validas"] == 3
    assert cuerpo["senal"]["altura_bu"]
    assert cuerpo["referencias"]["umbral_bu"] is not None

    # Lo que de verdad importa de esta fase: el vídeo no se queda en el servidor.
    trabajo = app.state.cola.obtener(job)
    assert trabajo.ruta_video is None
    restos = list((Path(__import__("tempfile").gettempdir()) / "cai").glob("*"))
    assert not any(r.is_file() and r.stat().st_size > 1024 * 1024 for r in restos), (
        f"quedaron vídeos en el servidor: {restos}"
    )


@pytest.mark.skipif(not VIDEO.exists(), reason="hace falta un vídeo de prueba")
def test_video_anotado_a_720p(cliente) -> None:
    import cv2

    with VIDEO.open("rb") as f:
        job = cliente.post(
            "/analizar",
            files={"video": (VIDEO.name, f, "video/mp4")},
            data={"device_id": "test-anotado", "anotar": "true"},
        ).json()["job_id"]

    cuerpo = _esperar(cliente, job)
    assert cuerpo["estado"] == "hecho", cuerpo
    assert cuerpo["video_anotado_url"]

    ruta = app.state.cola.obtener(job).ruta_anotado
    captura = cv2.VideoCapture(str(ruta))
    alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    captura.release()

    assert alto <= 720
    # H.264 con croma 4:2:0 necesita dimensiones pares o ffmpeg ni arranca.
    assert alto % 2 == 0 and ancho % 2 == 0

    assert cliente.get(f"/video/{job}").status_code == 200
    assert cliente.delete(f"/estado/{job}").status_code == 200
    assert not Path(ruta).exists()
