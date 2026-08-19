"""
IDEALMENTE VIDEOS A 1080p y 30FPS

VER 0.1
Cuenta dominadas en un vídeo y dice cuántas son válidas.

    vídeo -> pose (nariz, hombros, muñecas)
          -> altura de la nariz en anchuras de hombros
          -> picos por prominencia = repeticiones
          -> las que pasan la barra = válidas

Se sigue la nariz porque arriba la barra tapa la barbilla, y se mide en anchuras
de hombros para que el mismo umbral valga en 4K y en 480p. La barra es la recta
que une las dos muñecas: las manos están agarradas a ella.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

__all__ = ["Repeticion", "Resultado", "contar", "dibujar"]

# Índices de MediaPipe Pose (Mediapipe KEYPOINTS).
NARIZ, HOMBRO_IZQ, HOMBRO_DER, MUNECA_IZQ, MUNECA_DER = 0, 11, 12, 15, 16

MODELO = "lite"
"""El modelo de pose. Se elige el ligero porque tarda una quinta parte que
``heavy``, y eso es lo que permite enseñar el resultado en directo en vez de
hacer esperar dos minutos.

Tiene un coste conocido y no es el conteo: medido sobre los tres vídeos
etiquetados, ``lite`` acierta el *número* de repeticiones igual que ``heavy``
—3, 7 y 18 en los dos—, pero sitúa la nariz sistemáticamente entre 0,06 y 0,17
anchuras de hombros más abajo respecto a la recta de las manos. No es ruido que
el filtro quite: es un sesgo, y se come las repeticiones que pasaban la barra
por poco. En ``fp.mp4``, el vídeo con repeticiones al límite, ``heavy`` da las
5 válidas etiquetadas a mano y ``lite`` da 3.

Para recuperar ese veredicto se cambia esta constante por ``"heavy"``. El
intermedio (``"full"``) no sirve de nada: mismo sesgo y más lento."""

CARPETA_MODELOS = Path("models")
MODELO_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{nombre}/float16/1/pose_landmarker_{nombre}.task"
)

PASO = 2
"""Se analiza uno de cada dos frames. Sale gratis: una dominada son 0,25-0,7 Hz
y a 15 Hz de muestreo la señal sigue estando dos órdenes de magnitud por debajo
del límite de Nyquist, así que con el mismo modelo el veredicto es idéntico en
los tres vídeos —los márgenes se mueven menos de 0,05 anchuras de hombros— y va
al doble de rápido.

No conviene subirlo sin bajar :data:`CORTE_HZ` a la vez: con ``PASO = 4`` el
corte queda pegado a Nyquist y el filtro deja de filtrar, sin avisar de nada.

El vídeo anotado se escribe entero igualmente, manteniendo el esqueleto en los
frames saltados."""

MIN_VISIBILIDAD = 0.5
"""Por debajo de esta confianza el keypoint se descarta: MediaPipe no deja
vacíos los puntos ocluidos, se los inventa."""

DESFASE_MUNECA_BU = 0.20
"""Cuánto queda la barra por encima del keypoint de muñeca, en anchuras de
hombros: la mano la envuelve por arriba, así que el punto cae en el lado de
abajo."""

MARGEN_BU = DESFASE_MUNECA_BU + 0.20
"""Cuánto tiene que superar la nariz a la recta de las manos para dar la
repetición por válida: el desfase de la muñeca más otros 0,20 porque la
barbilla va por detrás de la nariz."""

CORTE_HZ = 3.0
"""Corte del filtro. Una dominada son 0,25-0,7 Hz; el resto es temblor del
estimador de pose."""

PROMINENCIA = 0.4
"""Cuánto tiene que sobresalir un pico de sus valles para contar, como fracción
del recorrido típico. Mirar la prominencia y no un umbral fijo es lo que evita
contar cinco veces un temblor y dejar de contar a quien no extiende los brazos."""

# Dataclass congelada, instancia inmutable
# Al declarar dataclass me escribe solo el __init__, __repr__ y el __eq__
@dataclass(frozen=True)
class Repeticion:
    """Una repetición"""
    numero: int
    instante_s: float
    margen_bu: float
    """Cuánto le sobra a la nariz sobre el umbral de validez, en anchuras de
    hombros (bu). Positivo = la barbilla pasó la barra."""

    # Método que se lee como atributo
    # repeticion.valida() -> true o false, según la propia instancia
    @property
    def valida(self) -> bool:
        return self.margen_bu > 0
    """Si la nariz ha pasado el umbral de validez (distancia bu positiva) -> True"""


@dataclass(frozen=True)
class Resultado:
    """El conteo, con los puntos por si se quiere dibujar el vídeo anotado."""

    repeticiones: list[Repeticion]
    puntos: np.ndarray = field(default_factory=lambda: np.empty((0, 33, 2)), repr=False)
    fps: float = 30.0
    """Los fps del vídeo original, no los del análisis."""
    paso: int = 1
    """Cada cuántos frames del original hay una fila en ``puntos``."""
    barra_y_px: float = float("nan")
    """Altura de la barra en la imagen, en píxeles."""
    altura: np.ndarray = field(default_factory=lambda: np.empty(0), repr=False)
    """La señal: altura de la nariz en anchuras de hombros, ya filtrada."""
    tiempo: np.ndarray = field(default_factory=lambda: np.empty(0), repr=False)
    """Segundo del vídeo original de cada muestra de ``altura``."""
    barra_bu: float = float("nan")
    """La barra, en la misma escala y con el mismo cero que la señal."""
    umbral_bu: float = float("nan")
    """Altura que la nariz tiene que superar para que la barbilla pase."""

    @property
    def total(self) -> int:
        return len(self.repeticiones)

    @property
    def validas(self) -> int:
        return sum(1 for r in self.repeticiones if r.valida)


def contar(video: str | Path, progreso=None) -> Resultado:
    """Cuenta las dominadas de un vídeo.

    No hay que decirle dónde empieza la serie: se queda con el tramo más largo
    en que el sujeto está colgado de la barra.

    Args:
        video: ruta del vídeo.
        progreso: se llama con la fracción de vídeo procesada, de 0 a 1.

    Raises:
        ValueError: si ahí no hay nadie haciendo dominadas.
    """
    puntos, detectado, fps = extraer_pose(video, progreso)
    return contar_puntos(puntos, detectado, fps, PASO)


def contar_puntos(
    puntos: np.ndarray, detectado: np.ndarray, fps: float, paso: int = 1
) -> Resultado:
    """El conteo propiamente dicho, sobre los puntos ya extraídos.

    ``fps`` es el del vídeo original y ``paso`` cada cuántos frames suyos hay
    una fila en ``puntos``, así que la señal va a ``fps / paso``: todo lo que
    mide tiempo —el filtro, la duración mínima del tramo, los huecos— usa esa
    frecuencia, y solo al escribir instantes se vuelve a segundos del original.
    """
    fps_senal = fps / paso
    inicio, fin = _tramo_colgado(puntos, detectado, fps_senal)
    todos, puntos = puntos, puntos[inicio:fin]

    anchuras = np.linalg.norm(puntos[:, HOMBRO_IZQ] - puntos[:, HOMBRO_DER], axis=1)
    anchuras = anchuras[np.isfinite(anchuras) & (anchuras > 0)]
    if anchuras.size < 5:
        raise ValueError("no se ven los hombros: sin ellos no hay regla de medir")
    # Una sola escala para todo el vídeo: si se recalculase frame a frame, la
    # regla de medir cambiaría de tamaño con el propio movimiento.
    escala = float(np.median(anchuras))

    manos_y = float(
        np.nanmedian(np.concatenate([puntos[:, MUNECA_IZQ, 1], puntos[:, MUNECA_DER, 1]]))
    )
    if not np.isfinite(manos_y):
        raise ValueError("no se ven las muñecas: no se puede situar la barra")

    nariz_y = _rellenar(puntos[:, NARIZ, 1])
    # y crece hacia abajo: el percentil 95 es lo más bajo que llegó la nariz, y
    # es más robusto que el mínimo ante un frame suelto.
    suelo = float(np.percentile(nariz_y, 95))
    altura = _filtrar((suelo - nariz_y) / escala, fps_senal)

    recorrido = float(np.percentile(altura, 95) - np.percentile(altura, 5))
    if recorrido < 0.30:
        raise ValueError(
            f"la nariz solo recorre {recorrido:.2f} anchuras de hombros: "
            "ahí no hay dominadas"
        )

    # La barra y el umbral salen del mismo sitio —la recta de las manos, en la
    # escala de la señal— y se separan solo en cuánto hay que superarla.
    manos_bu = (suelo - manos_y) / escala
    umbral = manos_bu + MARGEN_BU
    return Resultado(
        repeticiones=[
            Repeticion(
                numero=numero,
                instante_s=(inicio + i) / fps_senal,
                margen_bu=float(altura[i] - umbral),
            )
            for numero, i in enumerate(_picos(altura, PROMINENCIA * recorrido), start=1)
        ],
        puntos=todos,
        fps=fps,
        paso=paso,
        barra_y_px=manos_y - DESFASE_MUNECA_BU * escala,
        altura=altura,
        tiempo=(inicio + np.arange(altura.size)) / fps_senal,
        barra_bu=manos_bu + DESFASE_MUNECA_BU,
        umbral_bu=umbral,
    )


def _tramo_colgado(puntos: np.ndarray, detectado: np.ndarray, fps: float) -> tuple[int, int]:
    """Frames ``[inicio, fin)`` del tramo más largo con el sujeto en la barra.

    Está colgado mientras las dos muñecas queden por encima de los hombros: se
    cumple durante toda la dominada —por muy alto que suba, los hombros nunca
    pasan de las manos— y no se cumple andando hacia la barra. Los huecos de
    menos de un segundo se unen para no partir la serie en cada repetición, pero
    solo si en ellos se seguía viendo a la persona: si se pierde el track, puede
    haber otro plano u otra persona.
    """
    munecas = _media_visible(puntos[:, [MUNECA_IZQ, MUNECA_DER], 1])
    hombros = _media_visible(puntos[:, [HOMBRO_IZQ, HOMBRO_DER], 1])
    colgado = np.flatnonzero(detectado & (munecas < hombros))
    if colgado.size == 0:
        raise ValueError(
            "en ningún frame se ven las dos manos por encima de los hombros: el "
            "sujeto no llega a colgarse, o no se le ve entero en el encuadre"
        )

    hueco_max = max(int(round(fps)), 1)
    tramos: list[tuple[int, int]] = []
    principio = anterior = int(colgado[0])
    for i in map(int, colgado[1:]):
        if i - anterior - 1 > hueco_max or not detectado[anterior + 1 : i].all():
            tramos.append((principio, anterior + 1))
            principio = i
        anterior = i
    tramos.append((principio, anterior + 1))

    inicio, fin = max(tramos, key=lambda t: t[1] - t[0])
    if (fin - inicio) / fps < 3.0:
        raise ValueError(
            f"el tramo colgado más largo dura {(fin - inicio) / fps:.1f} s y hacen "
            "falta 3. ¿Se ve al sujeto entero durante la serie?"
        )
    return inicio, fin


def _media_visible(par: np.ndarray) -> np.ndarray:
    """Media de los dos lados usando solo el que se vea; ``NaN`` si ninguno."""
    with warnings.catch_warnings():
        # Un frame sin ninguno de los dos lados avisa de "media de vacío" y
        # devuelve NaN, que es justo lo que aquí hace falta.
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(par, axis=1)


def _rellenar(valores: np.ndarray) -> np.ndarray:
    """Interpola los frames sin dato: el filtro no admite ``NaN``."""
    validos = np.isfinite(valores)
    if not validos.any():
        raise ValueError("no se ve la nariz en ningún frame del tramo")
    if validos.all():
        return valores
    indices = np.arange(valores.size)
    return np.interp(indices, indices[validos], valores[validos])


def _filtrar(altura: np.ndarray, fps: float, orden: int = 4) -> np.ndarray:
    """Butterworth paso bajo de fase cero.

    De fase cero porque ``filtfilt`` pasa el filtro hacia delante y hacia atrás,
    y así los picos no se desplazan en el tiempo. Como eso lo aplica dos veces,
    se sube el corte nominal para que el efectivo sea el pedido.
    """
    nyquist = fps / 2.0
    corte = min(CORTE_HZ / (2.0**0.5 - 1) ** (1 / (2 * orden)), 0.95 * nyquist)
    b, a = butter(orden, corte / nyquist, btype="low")
    if altura.size <= 3 * max(len(a), len(b)):
        return altura
    return filtfilt(b, a, altura)


def _picos(altura: np.ndarray, prominencia_minima: float) -> np.ndarray:
    """Índices de los picos que cuentan como repetición.

    La señal se acolcha con su mínimo en los dos extremos para que una
    repetición que el vídeo corta a la mitad siga siendo un pico.
    """
    suelo = float(altura.min())
    indices, _ = find_peaks(
        np.concatenate([[suelo], altura, [suelo]]), prominence=prominencia_minima
    )
    return np.clip(indices - 1, 0, altura.size - 1)


def descargar_modelo(nombre: str = MODELO) -> Path:
    """Ruta del modelo de pose, bajándolo la primera vez (5-30 MB)."""
    destino = CARPETA_MODELOS / f"pose_landmarker_{nombre}.task"
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        url = MODELO_URL.format(nombre=nombre)
        urllib.request.urlretrieve(url, destino)  # noqa: S310 (URL fija)
    return destino


def extraer_pose(
    video: str | Path, progreso=None, modelo: str = MODELO, paso: int = PASO
) -> tuple[np.ndarray, np.ndarray, float]:
    """Pasa el vídeo por MediaPipe: ``(puntos (n, 33, 2), detectado (n,), fps)``.

    Es lo único lento de todo el proceso. Un punto vale ``NaN`` cuando el modelo
    no lo ve con confianza.

    Con ``paso > 1`` solo se estima la pose en uno de cada ``paso`` frames y
    ``puntos`` sale con esa longitud; ``fps`` sigue siendo el del vídeo, que es
    lo que hace falta para volver a segundos. Los frames saltados se decodifican
    igual —es barato al lado de la pose— porque saltar buscando posición en un
    vídeo comprimido no es fiable.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    paso = max(int(paso), 1)
    ruta_modelo = descargar_modelo(modelo)

    captura = cv2.VideoCapture(str(video))
    if not captura.isOpened():
        raise ValueError(f"no se puede abrir el vídeo: {video}")
    fps = float(captura.get(cv2.CAP_PROP_FPS))
    ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT))
    if not np.isfinite(fps) or fps <= 0:
        captura.release()
        raise ValueError(f"el vídeo declara un fps inválido ({fps})")

    opciones = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(ruta_modelo)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )
    filas: list[np.ndarray] = []
    detectado: list[bool] = []
    with vision.PoseLandmarker.create_from_options(opciones) as detector:
        indice = 0
        while True:
            ok, imagen = captura.read()
            if not ok:
                break
            if indice % paso == 0:
                marco = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB),
                )
                # El modo VIDEO exige timestamps crecientes; también hace que el
                # modelo siga a la persona entre frames en vez de redetectarla.
                # El timestamp va en tiempo del original aunque se salten
                # frames, para que el seguimiento sepa cuánto ha pasado.
                resultado = detector.detect_for_video(marco, int(indice * 1000 / fps))
                filas.append(_puntos_del_frame(resultado, ancho, alto))
                detectado.append(bool(resultado.pose_landmarks))
            indice += 1
            if progreso and total and indice % 15 == 0:
                progreso(min(indice / total, 1.0))
    captura.release()

    if not filas:
        raise ValueError("el vídeo no tiene ningún frame")
    return np.stack(filas), np.asarray(detectado, dtype=bool), fps


def _puntos_del_frame(resultado, ancho: int, alto: int) -> np.ndarray:
    """Los 33 puntos de un frame en píxeles; ``NaN`` los que no son fiables."""
    salida = np.full((33, 2), np.nan)
    if not resultado.pose_landmarks:
        return salida
    for indice, p in enumerate(resultado.pose_landmarks[0][:33]):
        if min(p.visibility, p.presence) >= MIN_VISIBILIDAD:
            # x e y vienen normalizados por separado: hay que multiplicar por el
            # ancho y el alto reales o las distancias salen deformadas.
            salida[indice] = (p.x * ancho, p.y * alto)
    return salida


# --- vídeo anotado ---------------------------------------------------------

CONEXIONES = (
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (24, 26), (26, 28),
    (27, 31), (28, 32),
)
"""Huesos del esqueleto, solo para dibujarlo."""

USADOS = (NARIZ, HOMBRO_IZQ, HOMBRO_DER, MUNECA_IZQ, MUNECA_DER)

CODECS = (("VP80", ".webm"), ("mp4v", ".mp4"))
"""Reserva para cuando no hay ffmpeg. Va sin ``avc1`` a propósito: OpenCV acepta
el fourcc de H.264 y ``isOpened()`` devuelve ``True`` aunque el codificador no
haya llegado a cargarse, así que el fallo no se detecta aquí y el fichero sale
inservible. Lo que sí produce un WebM válido es VP8; MPEG-4 queda de último
recurso, aunque el navegador no siempre lo reproduzca."""


def _ffmpeg() -> str | None:
    """Ruta a un ffmpeg utilizable, o ``None``.

    ``imageio-ffmpeg`` trae uno propio con libx264 dentro del entorno de Python,
    así que no hace falta instalar nada en el sistema ni ponerlo en el PATH.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


class _EscritorFFmpeg:
    """Frames BGR crudos por stdin, H.264 en MP4 al otro lado.

    Es lo que hace que el vídeo se vea dentro de la app y no solo se pueda
    descargar: H.264 en MP4 lo reproduce cualquier navegador, mientras que lo
    que OpenCV sabe escribir depende de con qué códecs venga compilado.
    """

    def __init__(self, ruta: Path, fps: float, ancho: int, alto: int, exe: str) -> None:
        self.ruta = ruta
        orden = [
            exe, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{ancho}x{alto}", "-r", f"{fps:.6f}", "-i", "-",
            "-an",
            # H.264 exige lados pares y el navegador exige yuv420p; se rellena
            # en vez de reescalar para no mover ni un píxel de la medida.
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            # El índice al principio: si no, el navegador tiene que descargar
            # el fichero entero antes de poder empezar a reproducir.
            "-movflags", "+faststart",
            str(ruta),
        ]
        self._proceso = subprocess.Popen(
            orden, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )

    def write(self, imagen: np.ndarray) -> None:
        try:
            self._proceso.stdin.write(imagen.tobytes())
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError(f"ffmpeg se cerró mientras se escribía: {self._error()}") from error

    def release(self) -> None:
        if self._proceso.poll() is None:
            try:
                self._proceso.stdin.close()
            except OSError:
                pass
        codigo = self._proceso.wait()
        if codigo != 0:
            raise RuntimeError(f"ffmpeg falló (código {codigo}): {self._error()}")

    def _error(self) -> str:
        try:
            return (self._proceso.stderr.read() or b"").decode(errors="replace").strip()[:300]
        except Exception:
            return "sin detalle"

_FUENTE = cv2.FONT_HERSHEY_SIMPLEX

TRAZO_BARRA, HUECO_BARRA = 14, 10
"""Largo del trazo y del hueco de la línea de la barra, en píxeles."""


def dibujar(
    video: str | Path, resultado: Resultado, destino: str | Path, progreso=None
) -> Path:
    """Escribe una copia del vídeo con el esqueleto y el marcador encima.

    Sirve para comprobar de un vistazo que el modelo está siguiendo al sujeto y
    no a alguien que pasa por el fondo del gimnasio. El esqueleto entero va
    apagado y encendidos los cinco puntos que el contador usa de verdad.

    Args:
        video: el vídeo original.
        resultado: lo devuelto por :func:`contar`, que trae los puntos.
        destino: ruta de salida; la extensión la decide el códec disponible.
        progreso: se llama con la fracción escrita, de 0 a 1.

    Returns:
        La ruta escrita.
    """
    captura = cv2.VideoCapture(str(video))
    if not captura.isOpened():
        raise ValueError(f"no se puede abrir el vídeo: {video}")
    ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # Se escribe a los fps del original y con todos sus frames: en modo rápido
    # la pose va a saltos, así que el esqueleto se mantiene hasta la siguiente
    # fila en vez de parpadear.
    filas = len(resultado.puntos)
    total = filas * resultado.paso
    escritor, ruta = _abrir_escritor(Path(destino), resultado.fps, ancho, alto)

    picos = [
        (int(round(r.instante_s * resultado.fps)), r.valida) for r in resultado.repeticiones
    ]
    try:
        indice = 0
        while True:
            ok, imagen = captura.read()
            if not ok:
                break
            fila = indice // resultado.paso
            if fila < filas:
                _dibujar_esqueleto(imagen, resultado.puntos[fila])
            _dibujar_barra(imagen, resultado.barra_y_px)
            hechas = sum(1 for pico, _ in picos if pico <= indice)
            validas = sum(1 for pico, valida in picos if valida and pico <= indice)
            # Sin tildes: las fuentes Hershey de OpenCV no tienen glifos acentuados.
            _dibujar_marcador(imagen, f"{hechas} realizadas  |  {validas} validas")
            escritor.write(imagen)
            indice += 1
            if progreso and total and indice % 15 == 0:
                progreso(min(indice / total, 1.0))
    finally:
        captura.release()
        escritor.release()
    return ruta


def _abrir_escritor(destino: Path, fps: float, ancho: int, alto: int):
    """H.264 por ffmpeg si lo hay; si no, el primer códec que OpenCV acepte."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    exe = _ffmpeg()
    if exe:
        ruta = destino.with_suffix(".mp4")
        return _EscritorFFmpeg(ruta, fps, ancho, alto, exe), ruta
    for codec, extension in CODECS:
        ruta = destino.with_suffix(extension)
        escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*codec), fps, (ancho, alto))
        if escritor.isOpened():
            return escritor, ruta
        escritor.release()
    raise RuntimeError(f"OpenCV no puede escribir vídeo con ninguno de {[c for c, _ in CODECS]}")


def _dibujar_esqueleto(imagen: np.ndarray, puntos: np.ndarray) -> None:
    """Huesos apagados y encendidos los cinco puntos que se usan."""
    for a, b in CONEXIONES:
        if np.isfinite(puntos[a]).all() and np.isfinite(puntos[b]).all():
            cv2.line(imagen, _px(puntos[a]), _px(puntos[b]), (150, 150, 150), 1, cv2.LINE_AA)
    for indice, punto in enumerate(puntos):
        if np.isfinite(punto).all():
            usado = indice in USADOS
            color = (255, 200, 80) if usado else (200, 200, 200)
            cv2.circle(imagen, _px(punto), 4 if usado else 2, color, -1, cv2.LINE_AA)


def _dibujar_barra(imagen: np.ndarray, y_px: float) -> None:
    """La barra, deducida de las manos y por tanto fija en la imagen.

    Es la comprobación más útil del vídeo anotado: la línea tiene que caer sobre
    la barra que se ve. Si no cae, la medida está mal y el número no vale.
    """
    if not np.isfinite(y_px):
        return
    y = int(np.clip(y_px, 1, imagen.shape[0] - 2))
    # A trazos y al 50%: una línea opaca taparía justo la barra contra la que
    # hay que comprobarla. El rótulo va después del mezclado, opaco, para que
    # se siga leyendo.
    capa = imagen.copy()
    for x in range(0, imagen.shape[1], TRAZO_BARRA + HUECO_BARRA):
        fin = min(x + TRAZO_BARRA, imagen.shape[1] - 1)
        cv2.line(capa, (x, y), (fin, y), (70, 170, 255), 2, cv2.LINE_AA)
    cv2.addWeighted(capa, 0.5, imagen, 0.5, 0, imagen)
    (largo, _alto), _base = cv2.getTextSize("BARRA", _FUENTE, 0.45, 1)
    x = imagen.shape[1] - largo - 8
    texto_y = y + 18 if y < imagen.shape[0] - 24 else y - 8
    cv2.putText(imagen, "BARRA", (x + 1, texto_y + 1), _FUENTE, 0.45, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(imagen, "BARRA", (x, texto_y), _FUENTE, 0.45, (70, 170, 255), 1, cv2.LINE_AA)


def _dibujar_marcador(imagen: np.ndarray, texto: str) -> None:
    """Banda superior semitransparente con el recuento."""
    panel = imagen.copy()
    cv2.rectangle(panel, (0, 0), (imagen.shape[1], 34), (18, 18, 22), -1)
    cv2.addWeighted(panel, 0.6, imagen, 0.4, 0, imagen)
    cv2.putText(imagen, texto, (10, 23), _FUENTE, 0.6, (245, 245, 245), 1, cv2.LINE_AA)


def _px(punto: np.ndarray) -> tuple[int, int]:
    return int(punto[0]), int(punto[1])
