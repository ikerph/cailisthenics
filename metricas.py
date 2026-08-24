"""
FASE 1 - Métricas de fase sobre un `Resultado` del contador.

    Resultado (señal de altura + keypoints) -> fases por velocidad
                                            -> métricas por repetición
                                            -> métricas por serie

Las fases se detectan por VELOCIDAD, no por umbral de altura. Un umbral de
altura obliga a elegir un punto medio arbitrario del recorrido y se rompe en
cuanto el atleta no baja del todo; la velocidad dice lo que de verdad se
pregunta -si en este instante está subiendo, bajando o parado- sin depender de
dónde esté.

La derivada sale de un Savitzky-Golay con `deriv=1`: ajusta un polinomio local y
devuelve su derivada en un solo paso. Filtrar y luego diferenciar emborrona el
instante del cambio de fase, que es justo lo que aquí se está midiendo.

Decisiones que vienen medidas de FASE 0 (`experimentos/FASE0_RESULTADOS.md`),
no elegidas a ojo:

- Una fase es el TIEMPO TOTAL EN MOVIMIENTO entre sus dos extremos, no el tramo
  contiguo alrededor del pico de velocidad. La excéntrica real de una dominada
  no es monótona -caída rápida, freno a media altura, deriva lenta hasta el dead
  hang- y la velocidad vuelve a cruzar el umbral por el medio. Con la definición
  contigua la dispersión entre muestreos era del ±33 %; con esta, ±10 %.
- Los cruces del umbral se interpolan a sub-muestra. A 15 Hz una muestra es
  1/15 s sobre una fase de 0,7 s: un 9 %, del orden del efecto que se mide.
- La ventana del Savitzky-Golay se fija en SEGUNDOS y se convierte a muestras,
  para que el suavizado no dependa del `paso`.

Lo que estas métricas NO son: ver `LIMITACIONES`.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from scipy.signal import savgol_filter

import contador
from contador import (
    HOMBRO_DER,
    HOMBRO_IZQ,
    MUNECA_DER,
    MUNECA_IZQ,
    NARIZ,
    Resultado,
)

__all__ = [
    "LIMITACIONES",
    "MetricasRepeticion",
    "MetricasSerie",
    "analizar",
    "version_pipeline",
]


# --- versión del pipeline --------------------------------------------------

VERSION_METRICAS = 1
"""Sube cuando cambie la DEFINICIÓN de alguna métrica.

No es un número decorativo: es lo que permite saber que una serie guardada hace
tres meses no es comparable con una de hoy. El día que se pase de nariz a
barbilla, o que cambie el criterio de fase, los datos viejos siguen siendo
válidos pero dejan de ser la misma magnitud, y sin esto no hay forma de
distinguirlos en el histórico.
"""


def version_pipeline(resultado: Resultado, modelo: str | None = None) -> str:
    """Identificador de todo lo que puede cambiar el valor de una métrica.

    Se construye a partir de las constantes de verdad, no de una cadena escrita
    a mano que se olvidaría de actualizar.
    """
    modelo = modelo or contador.MODELO_MEDIAPIPE
    return (
        f"m{VERSION_METRICAS}"
        f"-nariz-{modelo}"
        f"-p{resultado.paso}"
        f"-margen{contador.MARGEN_BU:.2f}"
        f"-corte{contador.CORTE_HZ:.1f}"
    )


LIMITACIONES = (
    "Se sigue la nariz, no la barbilla: la extensión de cuello puede inflar el "
    "resultado. Vista frontal: no se mide extensión de codo ni kipping. Las "
    "duraciones de fase son tiempo en movimiento, no tiempo entre extremos: las "
    "pausas no cuentan."
)
"""El texto que la app enseña siempre. Vive aquí para que el backend, el cliente
y cualquier informe digan exactamente lo mismo."""


# --- parámetros del detector -----------------------------------------------

VENTANA_DERIVADA_S = 0.40
"""[s] Ventana del Savitzky-Golay, en segundos y no en muestras: así el
suavizado es el mismo con `paso=1` que con `paso=2`."""

ORDEN_SG = 3

PERCENTIL_V_REF = 90
"""La escala de velocidad de la serie es el percentil 90 de |v|, no el máximo:
un solo frame malo no debe fijar el umbral de todas las repeticiones."""

FRAC_UMBRAL_V = 0.10
"""Umbral de fase, como fracción de la escala de velocidad de la serie.

Relativo a la propia serie, nunca un valor absoluto en bu/s: un atleta explosivo
y uno que sube lento no comparten escala y el mismo número los clasificaría
distinto.

El valor sale de un barrido, no de la intuición. Subirlo acorta las dos fases y
aplana el ratio medido -recorta proporcionalmente más la fase larga que la
corta-; bajarlo reduce ese sesgo pero deja entrar temblor como si fuera
movimiento, y el acuerdo entre muestreos empeora:

    frac    sesgo máx. sobre ratio real    |dif| p1-p2 en la serie limpia
    0,05              10,8 %                          0,050
    0,10              13,6 %                          0,024   <- elegido
    0,15              15,8 %                          0,027
    0,20              19,9 %                          0,028

Aun con 0,10 queda sesgo: un ratio real de 2,50 se mide 2,16. Es sistemático y
afecta igual a todas las series, así que las comparaciones entre sesiones son
válidas; el número absoluto no es el tempo real.
"""

CONCENTRICA, PAUSA, EXCENTRICA = 1, 0, -1
"""Etiqueta de cada muestra en `MetricasSerie.fases`."""


# --- resultados ------------------------------------------------------------


@dataclass(frozen=True)
class MetricasRepeticion:
    """Una repetición, medida."""

    numero: int
    instante_s: float
    """Instante del pico. Con pausa arriba la cresta es plana y este instante
    baila hasta medio segundo entre muestreos (FASE 0): sirve para localizar la
    repetición en el vídeo, no como medida de precisión."""

    rom_bu: float
    """Recorrido de ESTA repetición, en anchuras de hombros. Del pico al más
    alto de sus dos valles: el recorrido que se completó en los dos sentidos."""

    t_subida_s: float
    t_bajada_s: float
    """Tiempo EN MOVIMIENTO de cada fase. Las pausas no cuentan."""

    ratio_ecc_con: float
    v_pico_concentrica: float
    """[bu/s] Extremo instantáneo: es lo más sensible al muestreo de todo esto,
    ±17 % entre `paso=1` y `paso=2` (FASE 0). No se enseña a pelo."""

    margen_bu: float
    valida: bool
    truncada: bool
    """Alguna fase toca el borde de la señal: la duración es un mínimo, no la
    real. Se excluye de las medias de la serie."""

    desnivel_hombros_bu: float
    """Hombro derecho menos izquierdo en el pico, en bu. Positivo = el hombro
    izquierdo de la IMAGEN está más alto. Coordenadas de imagen, no anatómicas:
    si el vídeo va en espejo, izquierda y derecha están cambiadas."""

    desviacion_nariz_bu: float
    """Nariz respecto al punto medio de las muñecas, en horizontal y en bu.
    Positivo = la nariz se va hacia la derecha de la imagen."""


@dataclass(frozen=True)
class MetricasSerie:
    """La serie entera."""

    version_pipeline: str
    fps: float
    paso: int
    escala_px_bu: float
    """Anchura biacromial mediana en píxeles. Es la regla de medir: si cambia
    mucho entre sesiones, lo que cambió fue la distancia a la cámara."""

    recorrido_bu: float
    umbral_v_bu_s: float
    repeticiones: list[MetricasRepeticion]

    rom_medio_bu: float
    rom_sd_bu: float
    t_subida_media_s: float
    t_subida_sd_s: float
    t_bajada_media_s: float
    t_bajada_sd_s: float
    ratio_medio: float
    ratio_sd: float
    v_pico_media: float
    v_pico_sd: float

    caida_velocidad: float
    """[bu/s por repetición] Pendiente de la regresión de la velocidad pico
    concéntrica contra el número de repetición. Negativa = la serie se está
    frenando. Es la métrica diferencial del producto: un contador lo tiene
    cualquiera, esto no.

    Aguanta `paso=2` aunque la v_pico de una repetición suelta no lo aguante:
    la regresión promedia el ruido de cada punto (FASE 0)."""

    caida_velocidad_pct: float
    """La misma caída en % sobre la velocidad ajustada de la primera repetición.
    Es lo que se le enseña a una persona: "-18 % del principio al final"."""

    caida_velocidad_r2: float
    """Cuánto de la variación explica la recta. Con r² bajo la pendiente existe
    pero no describe nada: la serie no se frena, va a saltos."""

    desnivel_hombros_medio_bu: float
    desnivel_hombros_sd_bu: float
    desviacion_nariz_media_bu: float
    desviacion_nariz_sd_bu: float

    fases: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int8), repr=False)
    """Etiqueta por muestra de la señal: +1 concéntrica, -1 excéntrica, 0 pausa.
    Para pintar el gráfico sin recalcular nada en el cliente."""

    limitaciones: str = LIMITACIONES

    @property
    def n_total(self) -> int:
        return len(self.repeticiones)

    @property
    def n_validas(self) -> int:
        return sum(1 for r in self.repeticiones if r.valida)

    @property
    def n_usadas(self) -> int:
        """Repeticiones que entran en las medias: las no truncadas."""
        return sum(1 for r in self.repeticiones if not r.truncada)


# --- señal -----------------------------------------------------------------


def _ventana_impar(segundos: float, fps: float, n_muestras: int) -> int:
    """Ventana del Savitzky-Golay en muestras: impar, > orden y que quepa."""
    ancho = int(round(segundos * fps))
    if ancho % 2 == 0:
        ancho += 1
    ancho = max(ancho, ORDEN_SG + 2)
    if ancho % 2 == 0:
        ancho += 1
    if ancho > n_muestras:
        ancho = n_muestras if n_muestras % 2 else n_muestras - 1
    return ancho


def velocidad(altura: np.ndarray, fps_senal: float) -> np.ndarray:
    """Derivada de la altura, en bu/s, por Savitzky-Golay."""
    ancho = _ventana_impar(VENTANA_DERIVADA_S, fps_senal, altura.size)
    if ancho <= ORDEN_SG:
        return np.gradient(altura) * fps_senal
    return savgol_filter(
        altura, ancho, ORDEN_SG, deriv=1, delta=1.0 / fps_senal, mode="interp"
    )


def valles_de(altura: np.ndarray, picos: np.ndarray) -> list[tuple[int, int]]:
    """Valle izquierdo y derecho de cada pico: cada repetición es valle->pico->valle.

    El valle se busca como el mínimo entre picos vecinos. Así hay exactamente un
    valle entre repetición y repetición -no dos candidatos que haya que
    desempatar- y los extremos del vídeo quedan cubiertos.
    """
    limites: list[tuple[int, int]] = []
    ultimo = altura.size - 1
    for k, pico in enumerate(picos):
        pico = int(pico)
        desde = 0 if k == 0 else int(picos[k - 1])
        hasta = ultimo if k == len(picos) - 1 else int(picos[k + 1])
        limites.append(
            (
                desde + int(np.argmin(altura[desde : pico + 1])),
                pico + int(np.argmin(altura[pico : hasta + 1])),
            )
        )
    return limites


def _indice_cruce(senal: np.ndarray, umbral: float, dentro: int, fuera: int) -> float:
    """Índice sub-muestra donde `senal` cruza `umbral` entre esas dos muestras."""
    a, b = float(senal[fuera]), float(senal[dentro])
    if b == a:
        return float(dentro)
    return fuera + (umbral - a) / (b - a) * (dentro - fuera)


def _tiempo_en_movimiento(
    v: np.ndarray, desde: int, hasta: int, umbral: float, signo: int, fps_senal: float
) -> tuple[float, bool] | None:
    """Tiempo total con ``signo*v > umbral`` dentro de ``[desde, hasta]``.

    Suma todos los tramos, no solo el que rodea al pico de velocidad. Ver el
    docstring del módulo: la fase real se parte en dos y quedarse con un trozo
    convierte el muestreo en una lotería.
    """
    if hasta <= desde:
        return None
    firmada = signo * v
    seg = firmada[desde : hasta + 1]
    dentro = seg > umbral
    if not dentro.any():
        return None

    total = 0.0
    truncada = False
    i = 0
    while i < seg.size:
        if not dentro[i]:
            i += 1
            continue
        a = i
        while i + 1 < seg.size and dentro[i + 1]:
            i += 1
        inicio_abs, fin_abs = desde + a, desde + i

        if inicio_abs > 0:
            t_ini = _indice_cruce(firmada, umbral, inicio_abs, inicio_abs - 1)
        else:
            t_ini, truncada = float(inicio_abs), True
        if fin_abs < v.size - 1:
            t_fin = _indice_cruce(firmada, umbral, fin_abs, fin_abs + 1)
        else:
            t_fin, truncada = float(fin_abs), True

        total += (t_fin - t_ini) / fps_senal
        i += 1
    return total, truncada


# --- asimetría bilateral ---------------------------------------------------


def escala_biacromial(puntos: np.ndarray) -> float:
    """Anchura de hombros mediana, en píxeles: la regla de medir.

    Misma definición que `contador.contar_puntos`. Si allí cambia, aquí también:
    las dos tienen que dar el mismo número o las métricas dejan de estar en la
    misma escala que el umbral de validez.
    """
    anchuras = np.linalg.norm(
        puntos[:, HOMBRO_IZQ, :] - puntos[:, HOMBRO_DER, :], axis=1
    )
    anchuras = anchuras[np.isfinite(anchuras) & (anchuras > 0)]
    if anchuras.size == 0:
        raise ValueError("no se ven los dos hombros en ningún frame de la serie")
    return float(np.median(anchuras))


def _asimetria(fila: np.ndarray, escala: float) -> tuple[float, float]:
    """Desnivel de hombros y desviación lateral de la nariz en un frame.

    La asimetría bilateral es la única cosa que la vista frontal mide MEJOR que
    la lateral: de perfil un hombro tapa al otro. De frente se ve el desnivel
    directamente, y se ve si el atleta se escora hacia una mano.

    `NaN` si el frame no tiene los puntos: mejor un hueco que un cero que se
    confunda con simetría perfecta.
    """
    hombro_izq, hombro_der = fila[HOMBRO_IZQ], fila[HOMBRO_DER]
    # "y" crece hacia abajo: der - izq positivo = el izquierdo está más arriba.
    desnivel = (hombro_der[1] - hombro_izq[1]) / escala

    nariz_x = fila[NARIZ][0]
    munecas_x = np.array([fila[MUNECA_IZQ][0], fila[MUNECA_DER][0]])
    with np.errstate(invalid="ignore"):
        medio = np.nanmean(munecas_x) if np.isfinite(munecas_x).any() else np.nan
    desviacion = (nariz_x - medio) / escala

    return float(desnivel), float(desviacion)


# --- estadística -----------------------------------------------------------


def _media(valores) -> float:
    v = np.asarray(list(valores), dtype=float)
    v = v[np.isfinite(v)]
    return float(v.mean()) if v.size else float("nan")


def _sd(valores) -> float:
    """Desviación muestral (ddof=1). NaN con menos de dos datos: con una sola
    repetición no hay dispersión que reportar, y un 0 mentiría."""
    v = np.asarray(list(valores), dtype=float)
    v = v[np.isfinite(v)]
    return float(np.std(v, ddof=1)) if v.size >= 2 else float("nan")


def _regresion(y: np.ndarray) -> tuple[float, float, float]:
    """Pendiente, ordenada en el origen y r² de ``y`` contra su índice.

    Con menos de tres puntos no se devuelve pendiente: dos puntos siempre dan
    una recta perfecta y llamar a eso "fatiga" es inventarse el dato.
    """
    y = np.asarray(y, dtype=float)
    validos = np.isfinite(y)
    if validos.sum() < 3:
        return float("nan"), float("nan"), float("nan")
    x = np.arange(y.size, dtype=float)[validos]
    y = y[validos]
    pendiente, corte = np.polyfit(x, y, 1)
    residuos = y - (pendiente * x + corte)
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residuos**2)) / total if total > 0 else float("nan")
    return float(pendiente), float(corte), r2


# --- análisis --------------------------------------------------------------


def analizar(resultado: Resultado, modelo: str | None = None) -> MetricasSerie:
    """Métricas por repetición y por serie a partir de un `Resultado`.

    Args:
        resultado: lo que devuelve `contador.contar`.
        modelo: nombre del modelo de pose usado, solo para `version_pipeline`.

    Raises:
        ValueError: si el `Resultado` no trae señal ni repeticiones, o si no se
            ven los hombros en ningún frame.
    """
    altura, tiempo = resultado.altura, resultado.tiempo
    if altura.size == 0 or tiempo.size == 0:
        raise ValueError("el resultado no trae señal de altura")

    fps_senal = resultado.fps / max(resultado.paso, 1)
    t0 = float(tiempo[0])
    inicio = int(round(t0 * fps_senal))

    # El Resultado guarda los puntos del vídeo ENTERO -dibujar los necesita- y
    # la señal solo del tramo colgado. Este es el desfase entre los dos índices.
    puntos_serie = resultado.puntos[inicio : inicio + altura.size]
    if puntos_serie.shape[0] == 0:
        raise ValueError("el resultado no trae keypoints del tramo analizado")
    escala = escala_biacromial(puntos_serie)

    v = velocidad(altura, fps_senal)
    umbral_v = FRAC_UMBRAL_V * float(np.percentile(np.abs(v), PERCENTIL_V_REF))
    recorrido = float(np.percentile(altura, 95) - np.percentile(altura, 5))

    fases = np.where(v > umbral_v, CONCENTRICA, np.where(v < -umbral_v, EXCENTRICA, PAUSA))

    picos = np.clip(
        np.array(
            [round((rep.instante_s - t0) * fps_senal) for rep in resultado.repeticiones],
            dtype=int,
        ),
        0,
        altura.size - 1,
    )

    reps: list[MetricasRepeticion] = []
    for rep, pico, (izq, der) in zip(
        resultado.repeticiones, picos, valles_de(altura, picos)
    ):
        pico = int(pico)
        subida = _tiempo_en_movimiento(v, izq, pico, umbral_v, +1, fps_senal)
        bajada = _tiempo_en_movimiento(v, pico, der, umbral_v, -1, fps_senal)
        if subida is None or bajada is None:
            # Un pico sin subida o sin bajada por encima del umbral no tiene
            # fases que medir. Se deja el hueco en vez de inventar un número.
            t_sub = t_baj = float("nan")
            truncada = True
        else:
            (t_sub, trunc_sub), (t_baj, trunc_baj) = subida, bajada
            truncada = trunc_sub or trunc_baj

        desnivel, desviacion = _asimetria(puntos_serie[pico], escala)
        reps.append(
            MetricasRepeticion(
                numero=rep.numero,
                instante_s=rep.instante_s,
                rom_bu=float(altura[pico] - max(altura[izq], altura[der])),
                t_subida_s=t_sub,
                t_bajada_s=t_baj,
                ratio_ecc_con=(
                    t_baj / t_sub if np.isfinite(t_sub) and t_sub > 0 else float("nan")
                ),
                v_pico_concentrica=(
                    float(np.max(v[izq : pico + 1])) if pico > izq else float("nan")
                ),
                margen_bu=rep.margen_bu,
                valida=rep.esValida,
                # Una repetición pegada al borde del vídeo tiene la fase cortada.
                truncada=truncada or izq == 0 or der == altura.size - 1,
                desnivel_hombros_bu=desnivel,
                desviacion_nariz_bu=desviacion,
            )
        )

    return _resumir(
        reps,
        version=version_pipeline(resultado, modelo),
        fps=resultado.fps,
        paso=resultado.paso,
        escala=escala,
        recorrido=recorrido,
        umbral_v=umbral_v,
        fases=fases.astype(np.int8),
    )


def _resumir(
    reps: list[MetricasRepeticion],
    *,
    version: str,
    fps: float,
    paso: int,
    escala: float,
    recorrido: float,
    umbral_v: float,
    fases: np.ndarray,
) -> MetricasSerie:
    """Agrega las repeticiones en métricas de serie.

    Las medias se calculan solo sobre las repeticiones NO truncadas: una fase
    cortada por el final del vídeo es un mínimo, no una medida, y metida en una
    media la baja sin que nadie se entere.
    """
    usadas = [r for r in reps if not r.truncada]
    v_picos = np.array([r.v_pico_concentrica for r in usadas], dtype=float)
    pendiente, corte, r2 = _regresion(v_picos)

    # En porcentaje sobre la velocidad AJUSTADA de la primera repetición, no
    # sobre la medida: la medida trae el ruido de un punto suelto y haría que el
    # porcentaje dependiera de lo bien que saliera esa repetición concreta.
    if np.isfinite(pendiente) and np.isfinite(corte) and corte > 0:
        caida_pct = 100.0 * pendiente * (len(usadas) - 1) / corte
    else:
        caida_pct = float("nan")

    return MetricasSerie(
        version_pipeline=version,
        fps=fps,
        paso=paso,
        escala_px_bu=escala,
        recorrido_bu=recorrido,
        umbral_v_bu_s=umbral_v,
        repeticiones=reps,
        rom_medio_bu=_media(r.rom_bu for r in usadas),
        rom_sd_bu=_sd(r.rom_bu for r in usadas),
        t_subida_media_s=_media(r.t_subida_s for r in usadas),
        t_subida_sd_s=_sd(r.t_subida_s for r in usadas),
        t_bajada_media_s=_media(r.t_bajada_s for r in usadas),
        t_bajada_sd_s=_sd(r.t_bajada_s for r in usadas),
        ratio_medio=_media(r.ratio_ecc_con for r in usadas),
        ratio_sd=_sd(r.ratio_ecc_con for r in usadas),
        v_pico_media=_media(r.v_pico_concentrica for r in usadas),
        v_pico_sd=_sd(r.v_pico_concentrica for r in usadas),
        caida_velocidad=pendiente,
        caida_velocidad_pct=caida_pct,
        caida_velocidad_r2=r2,
        desnivel_hombros_medio_bu=_media(r.desnivel_hombros_bu for r in usadas),
        desnivel_hombros_sd_bu=_sd(r.desnivel_hombros_bu for r in usadas),
        desviacion_nariz_media_bu=_media(r.desviacion_nariz_bu for r in usadas),
        desviacion_nariz_sd_bu=_sd(r.desviacion_nariz_bu for r in usadas),
        fases=fases,
    )
