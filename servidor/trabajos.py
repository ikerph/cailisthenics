"""Cola de trabajos: subir no puede ser lo mismo que esperar.

Un vídeo de 30 s tarda entre 6 y 14 s en procesarse. Meter eso en el request
significa una conexión móvil abierta todo ese rato, un timeout de proxy a los 30
s y ninguna forma de enseñar progreso. Así que el POST devuelve un `job_id` al
instante y el cliente pregunta por él.

El estado vive en memoria a propósito. En la beta hay un proceso, no hay cuentas
y el histórico se guarda en el móvil: una base de datos aquí solo añadiría un
sitio más donde quedan restos de vídeos de gente.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import contador
import metricas

from . import anotado
from .errores import Fallo, clasificar
from .esquemas import payload_analisis


class Estado(str, Enum):
    EN_COLA = "en_cola"
    PROCESANDO = "procesando"
    HECHO = "hecho"
    ERROR = "error"


VIDA_S = 15 * 60
"""[s] Lo que sobrevive un trabajo terminado.

No es una cuestión de memoria: es que el vídeo anotado es un vídeo de una
persona identificable, y cuanto menos tiempo esté en un disco ajeno, mejor. El
cliente tiene ese cuarto de hora para recogerlo.
"""

TRABAJADORES = 2
"""La pose es CPU pura. Más hilos que núcleos útiles no acelera nada: solo hace
que todos los usuarios esperen a la vez en vez de por turnos."""


@dataclass
class Trabajo:
    """Un vídeo en curso o terminado."""

    id: str
    device_id: str
    estado: Estado = Estado.EN_COLA
    progreso: float = 0.0
    creado: float = field(default_factory=time.monotonic)
    terminado: float | None = None

    ruta_video: Path | None = None
    """El vídeo subido. Se borra en cuanto termina el análisis, salga bien o mal."""

    ruta_anotado: Path | None = None
    payload: dict | None = None
    fallo: Fallo | None = None

    @property
    def vencido(self) -> bool:
        return (
            self.terminado is not None
            and time.monotonic() - self.terminado > VIDA_S
        )


class Cola:
    """Registro de trabajos y los hilos que los ejecutan."""

    def __init__(self, trabajadores: int = TRABAJADORES) -> None:
        self._trabajos: dict[str, Trabajo] = {}
        self._cerrojo = threading.Lock()
        self._ejecutor = ThreadPoolExecutor(
            max_workers=trabajadores, thread_name_prefix="analisis"
        )

    # --- consulta ---

    def obtener(self, job_id: str) -> Trabajo | None:
        self.purgar()
        with self._cerrojo:
            return self._trabajos.get(job_id)

    def purgar(self) -> None:
        """Tira los trabajos vencidos y borra lo que dejaron en disco."""
        with self._cerrojo:
            vencidos = [t for t in self._trabajos.values() if t.vencido]
            for trabajo in vencidos:
                del self._trabajos[trabajo.id]
        for trabajo in vencidos:
            _borrar(trabajo.ruta_anotado)
            _borrar(trabajo.ruta_video)

    # --- alta ---

    def encolar(
        self,
        ruta_video: Path,
        device_id: str,
        anotar: bool,
        base_url_anotado: str,
    ) -> Trabajo:
        self.purgar()
        trabajo = Trabajo(id=uuid.uuid4().hex, device_id=device_id, ruta_video=ruta_video)
        with self._cerrojo:
            self._trabajos[trabajo.id] = trabajo
        self._ejecutor.submit(self._procesar, trabajo, anotar, base_url_anotado)
        return trabajo

    # --- ejecución ---

    def _procesar(self, trabajo: Trabajo, anotar: bool, base_url_anotado: str) -> None:
        video = trabajo.ruta_video
        try:
            trabajo.estado = Estado.PROCESANDO

            # La pose es el 80 % del tiempo; el resto del progreso se reparte
            # entre el análisis y el render, que van mucho más rápido.
            def avance_pose(fraccion: float) -> None:
                trabajo.progreso = 0.80 * fraccion

            puntos, detectado, fps = contador.extraer_pose(video, avance_pose)
            resultado = contador.contar_puntos(puntos, detectado, fps, contador.PASO)
            trabajo.progreso = 0.85
            serie = metricas.analizar(resultado)
            trabajo.progreso = 0.90

            url_anotado = None
            if anotar:
                def avance_render(fraccion: float) -> None:
                    trabajo.progreso = 0.90 + 0.10 * fraccion

                destino = video.with_name(f"anotado_{trabajo.id}")
                trabajo.ruta_anotado = anotado.anotar(
                    video, resultado, destino, progreso=avance_render
                )
                url_anotado = f"{base_url_anotado}/{trabajo.id}"

            trabajo.payload = payload_analisis(
                serie, resultado, job_id=trabajo.id, video_anotado_url=url_anotado
            )
            trabajo.progreso = 1.0
            trabajo.estado = Estado.HECHO

        except Exception as error:  # noqa: BLE001 - se clasifica, no se traga
            trabajo.fallo = clasificar(error)
            trabajo.estado = Estado.ERROR
            if trabajo.fallo.codigo == "DESCONOCIDO":
                # Un fallo sin clasificar es un bug nuestro: al log entero, que
                # al usuario solo le llega el consejo genérico.
                import traceback

                traceback.print_exc()
        finally:
            # Pase lo que pase, el vídeo original no se queda. Es la mitad del
            # problema de datos personales resuelta de un `finally`: lo que no
            # está guardado no hay que protegerlo, ni borrarlo a mano, ni
            # explicarlo en una política de privacidad.
            _borrar(video)
            trabajo.ruta_video = None
            trabajo.terminado = time.monotonic()

    def olvidar(self, job_id: str) -> bool:
        """Saca un trabajo del registro y borra sus ficheros. Ahora, no al vencer."""
        with self._cerrojo:
            trabajo = self._trabajos.pop(job_id, None)
        if trabajo is None:
            return False
        _borrar(trabajo.ruta_anotado)
        _borrar(trabajo.ruta_video)
        return True

    def apagar(self) -> None:
        """Espera a los trabajos en curso y borra todo lo que quede en disco."""
        self._ejecutor.shutdown(wait=True)
        with self._cerrojo:
            trabajos = list(self._trabajos.values())
            self._trabajos.clear()
        for trabajo in trabajos:
            _borrar(trabajo.ruta_anotado)
            _borrar(trabajo.ruta_video)


def _borrar(ruta: Path | None) -> None:
    """Borra sin quejarse si ya no está."""
    if ruta is None:
        return
    try:
        Path(ruta).unlink(missing_ok=True)
    except OSError:
        pass
