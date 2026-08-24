"""
FASE 0 - Experimento de `paso`. Standalone: NO forma parte de la app.

Pregunta: ¿PASO=2 (15 Hz efectivos) sirve para las métricas de fase, o hace
falta PASO=1 (30 Hz)?

Contar repeticiones a 15 Hz es gratis -Nyquist sobra por dos órdenes de
magnitud- pero medir *duraciones de fase* es otra cosa: la concéntrica de una
dominada dura 0,6-1,0 s, así que a 15 Hz son ~10-15 muestras. Ahí un error de
una muestra ya es un 7-10 % del ratio. Este script mide si ese error importa.

Criterio de decisión (del spec):

    si la diferencia entre pasos < variabilidad del ratio ENTRE repeticiones
    de la misma serie, entonces paso=2 vale para todo.

La lógica: si cambiar el muestreo mueve el ratio menos de lo que lo mueve el
propio atleta de una repetición a la siguiente, el muestreo no es el cuello de
botella y no tiene sentido pagar el doble de tiempo de pose.

Uso
---
    python experimentos/fase0_paso.py <carpeta_de_videos>
    python experimentos/fase0_paso.py . --salida resultados/fase0 --diagnostico
    python experimentos/fase0_paso.py . --definicion contigua
    python experimentos/fase0_paso.py --autotest    # sin vídeos: valida el detector

El autotest va primero: mide señales sintéticas de ratio conocido a 30 y a 15 Hz
y dice cuánto se mueve el ratio solo por el muestreo. Ese número es el suelo del
experimento; en vídeo real la diferencia entre pasos no puede salir menor.

Salidas en `--salida`:

    repeticiones.csv    una fila por repetición emparejada, con los dos pasos
    series.csv          una fila por vídeo y brazo
    ba_*.png            Bland-Altman de ratio, t_subida y t_bajada
    diag_*.png          con --diagnostico: señal, velocidad y fases de cada serie
    informe.txt         lo mismo que sale por pantalla

Necesita, además de lo de la app: matplotlib (solo para las gráficas; sin él
el script sigue y emite los CSV).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from contador import Resultado, contar_puntos, extraer_pose  # noqa: E402


# --- parámetros del detector de fases --------------------------------------

VENTANA_DERIVADA_S = 0.40
"""[s] Ventana del Savitzky-Golay. En SEGUNDOS, no en muestras: es lo que hace
que paso=1 y paso=2 vean el mismo suavizado y que la comparación mida el
muestreo y no el filtro."""

ORDEN_SG = 3

PERCENTIL_V_REF = 90
"""La velocidad de referencia de la serie es el percentil 90 de |v|, no el
máximo: un solo frame malo no debe fijar el umbral."""

FRAC_UMBRAL_V = 0.15
"""Umbral de fase = 15 % de la velocidad de referencia. Relativo a la serie,
nunca absoluto: un atleta lento y uno explosivo no comparten escala."""

TOLERANCIA_EMPAREJADO_S = 0.60
"""[s] Dos picos de brazos distintos son la misma repetición si caen a menos de
esto. Media dominada."""

EXTENSIONES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}


# --- estructuras -----------------------------------------------------------


@dataclass
class Rep:
    """Una repetición medida en un brazo del experimento."""

    numero: int
    t_pico_s: float
    rom_bu: float
    t_subida_s: float
    t_bajada_s: float
    ratio: float
    v_pico_con: float
    margen_bu: float
    valida: bool
    truncada: bool
    """La fase toca el borde de la señal: la duración es un mínimo, no la real."""


@dataclass
class Brazo:
    """Un vídeo procesado con un `paso` concreto."""

    etiqueta: str
    paso: int
    fps_senal: float
    v_ref: float
    umbral_v: float
    recorrido_bu: float
    reps: list[Rep]
    n_contadas: int
    """Repeticiones que contó `contador`, antes de descartar las no medibles."""
    segundos_pose: float = 0.0


# --- detector de fases -----------------------------------------------------


def _ventana_impar(segundos: float, fps: float, n_muestras: int) -> int:
    """Ventana del SG en muestras: impar, > ORDEN_SG y que quepa en la señal."""
    ancho = int(round(segundos * fps))
    if ancho % 2 == 0:
        ancho += 1
    ancho = max(ancho, ORDEN_SG + 2 if (ORDEN_SG + 2) % 2 else ORDEN_SG + 3)
    if ancho > n_muestras:
        ancho = n_muestras if n_muestras % 2 else n_muestras - 1
    return ancho


def velocidad(altura: np.ndarray, fps_senal: float) -> np.ndarray:
    """Derivada de la altura por Savitzky-Golay, en bu/s.

    Un solo paso: ajusta un polinomio local y devuelve su derivada, en vez de
    diferenciar y luego suavizar, que emborrona el instante del cambio de fase.
    """
    ancho = _ventana_impar(VENTANA_DERIVADA_S, fps_senal, altura.size)
    if ancho <= ORDEN_SG:
        return np.gradient(altura) * fps_senal
    return savgol_filter(
        altura, ancho, ORDEN_SG, deriv=1, delta=1.0 / fps_senal, mode="interp"
    )


def _refinar_extremo(y: np.ndarray, i: int) -> float:
    """Índice sub-muestra del extremo, por parábola sobre los tres puntos.

    A 15 Hz media muestra son 33 ms: no es despreciable cuando lo que se compara
    es justo el muestreo.
    """
    if i <= 0 or i >= y.size - 1:
        return float(i)
    curvatura = y[i - 1] - 2.0 * y[i] + y[i + 1]
    if curvatura == 0:
        return float(i)
    correccion = 0.5 * (y[i - 1] - y[i + 1]) / curvatura
    return float(i) + float(np.clip(correccion, -0.5, 0.5))


def valles_de(altura: np.ndarray, picos: np.ndarray) -> list[tuple[int, int]]:
    """Para cada pico, el mínimo a su izquierda y a su derecha: valle->pico->valle.

    El mínimo se busca entre picos vecinos, así que hay exactamente un valle
    entre repetición y repetición y los extremos del vídeo quedan cubiertos.
    """
    limites: list[tuple[int, int]] = []
    ultimo = altura.size - 1
    for k, pico in enumerate(picos):
        pico = int(pico)
        desde = 0 if k == 0 else int(picos[k - 1])
        hasta = ultimo if k == len(picos) - 1 else int(picos[k + 1])
        izq = desde + int(np.argmin(altura[desde : pico + 1]))
        der = pico + int(np.argmin(altura[pico : hasta + 1]))
        limites.append((izq, der))
    return limites


def _tramo_sobre_umbral(
    v: np.ndarray, desde: int, hasta: int, umbral: float, signo: int
) -> tuple[int, int] | None:
    """Tramo contiguo con ``signo*v > umbral`` que contiene el extremo de velocidad.

    Se ancla en el extremo y crece hacia los lados: así una pausa a mitad de la
    concéntrica no parte la fase en dos trozos que luego habría que volver a unir.
    """
    if hasta <= desde:
        return None
    seg = signo * v[desde : hasta + 1]
    dentro = seg > umbral
    if not dentro.any():
        return None
    k = int(np.argmax(seg))
    a = b = k
    while a > 0 and dentro[a - 1]:
        a -= 1
    while b < seg.size - 1 and dentro[b + 1]:
        b += 1
    return desde + a, desde + b


def _indice_cruce(senal: np.ndarray, umbral: float, dentro: int, fuera: int) -> float:
    """Índice sub-muestra en que ``senal`` cruza ``umbral`` entre esas dos muestras.

    Sin esto el experimento mediría la cuantización del muestreo -1/15 s sobre
    una fase de 0,7 s es un 9 %- en vez de la diferencia real entre pasos.
    """
    a, b = float(senal[fuera]), float(senal[dentro])
    if b == a:
        return float(dentro)
    fraccion = (umbral - a) / (b - a)
    return fuera + fraccion * (dentro - fuera)


def _duracion_fase(
    v: np.ndarray, a: int, b: int, umbral: float, signo: int, fps_senal: float
) -> tuple[float, bool]:
    """Duración del tramo ``[a, b]`` con los dos cruces interpolados."""
    firmada = signo * v
    truncada = False
    if a > 0:
        i_ini = _indice_cruce(firmada, umbral, a, a - 1)
    else:
        i_ini, truncada = float(a), True
    if b < v.size - 1:
        i_fin = _indice_cruce(firmada, umbral, b, b + 1)
    else:
        i_fin, truncada = float(b), True
    return (i_fin - i_ini) / fps_senal, truncada


def _tiempo_acumulado(
    v: np.ndarray, desde: int, hasta: int, umbral: float, signo: int, fps_senal: float
) -> tuple[float, bool] | None:
    """Tiempo TOTAL con ``signo*v > umbral`` dentro de ``[desde, hasta]``.

    La otra definición -el tramo contiguo alrededor del extremo- se rompe con la
    excéntrica real de una dominada, que no es monótona: caída rápida, meseta y
    deriva lenta hasta el dead hang. La velocidad vuelve a cruzar el umbral a
    mitad del descenso y el tramo contiguo se queda solo con el primer trozo;
    que ese cruce marginal caiga de un lado o de otro depende del muestreo, así
    que el experimento acabaría midiendo su propia fragilidad.

    Sumar todos los trozos es inmune a eso, y de paso deja fuera las pausas: lo
    que devuelve es tiempo EN MOVIMIENTO, no tiempo entre extremos.
    """
    if hasta <= desde:
        return None
    seg = signo * v[desde : hasta + 1]
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
        duracion, trunc = _duracion_fase(
            v, desde + a, desde + i, umbral, signo, fps_senal
        )
        total += duracion
        truncada |= trunc
        i += 1
    return total, truncada


def medir_fases(
    resultado: Resultado, etiqueta: str = "", definicion: str = "acumulada"
) -> Brazo | None:
    """Saca t_subida, t_bajada y ratio de cada repetición de un `Resultado`."""
    altura, tiempo = resultado.altura, resultado.tiempo
    if altura.size < 8 or not resultado.repeticiones:
        return None

    fps_senal = resultado.fps / max(resultado.paso, 1)
    t0 = float(tiempo[0])

    # De vuelta del instante en segundos al índice de la muestra: el Resultado
    # guarda el instante, no el índice, y aquí hace falta el índice.
    picos = np.clip(
        np.array(
            [round((rep.instante_s - t0) * fps_senal) for rep in resultado.repeticiones],
            dtype=int,
        ),
        0,
        altura.size - 1,
    )

    v = velocidad(altura, fps_senal)
    v_ref = float(np.percentile(np.abs(v), PERCENTIL_V_REF))
    umbral_v = FRAC_UMBRAL_V * v_ref
    recorrido = float(np.percentile(altura, 95) - np.percentile(altura, 5))

    reps: list[Rep] = []
    for rep, pico, (izq, der) in zip(
        resultado.repeticiones, picos, valles_de(altura, picos)
    ):
        pico = int(pico)
        if definicion == "contigua":
            con = _tramo_sobre_umbral(v, izq, pico, umbral_v, +1)
            exc = _tramo_sobre_umbral(v, pico, der, umbral_v, -1)
            subida = (
                _duracion_fase(v, con[0], con[1], umbral_v, +1, fps_senal) if con else None
            )
            bajada = (
                _duracion_fase(v, exc[0], exc[1], umbral_v, -1, fps_senal) if exc else None
            )
        else:
            subida = _tiempo_acumulado(v, izq, pico, umbral_v, +1, fps_senal)
            bajada = _tiempo_acumulado(v, pico, der, umbral_v, -1, fps_senal)

        if subida is None or bajada is None:
            # Pico sin subida o sin bajada por encima del umbral: no hay fase
            # medible. Se descarta en vez de inventar un número.
            continue
        (t_sub, trunc_sub), (t_baj, trunc_baj) = subida, bajada
        if t_sub <= 0 or t_baj <= 0:
            continue

        reps.append(
            Rep(
                numero=rep.numero,
                t_pico_s=t0 + _refinar_extremo(altura, pico) / fps_senal,
                rom_bu=float(altura[pico] - max(altura[izq], altura[der])),
                t_subida_s=t_sub,
                t_bajada_s=t_baj,
                ratio=t_baj / t_sub,
                v_pico_con=float(np.max(v[izq : pico + 1])),
                margen_bu=rep.margen_bu,
                valida=rep.esValida,
                truncada=trunc_sub or trunc_baj or izq == 0 or der == altura.size - 1,
            )
        )

    if not reps:
        return None
    return Brazo(
        etiqueta=etiqueta,
        paso=resultado.paso,
        fps_senal=fps_senal,
        v_ref=v_ref,
        umbral_v=umbral_v,
        recorrido_bu=recorrido,
        reps=reps,
        n_contadas=len(resultado.repeticiones),
    )


# --- pose con caché --------------------------------------------------------


def _clave_cache(video: Path, modelo: str, paso: int) -> str:
    est = video.stat()
    limpio = "".join(c if c.isalnum() else "_" for c in video.stem)
    return f"{limpio}_{est.st_size}_{int(est.st_mtime)}_{modelo}_p{paso}"


def pose_de(
    video: Path, modelo: str, paso: int, cache: Path | None
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Keypoints del vídeo a ese `paso`, cacheados en disco.

    La pose es lo único caro del pipeline y este experimento la pide dos veces
    por vídeo; sin caché no se puede iterar sobre el análisis.
    """
    destino = cache / f"{_clave_cache(video, modelo, paso)}.npz" if cache else None
    if destino is not None and destino.exists():
        with np.load(destino) as datos:
            return datos["puntos"], datos["detectado"], float(datos["fps"]), 0.0

    reloj = time.perf_counter()
    puntos, detectado, fps = extraer_pose(video, modelo=modelo, paso=paso)
    segundos = time.perf_counter() - reloj

    if destino is not None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            destino, puntos=puntos, detectado=detectado, fps=np.float64(fps)
        )
    return puntos, detectado, fps, segundos


# --- emparejado y estadística ----------------------------------------------


def emparejar(a: list[Rep], b: list[Rep], tolerancia: float) -> list[tuple[Rep, Rep]]:
    """Repeticiones de dos brazos que son la misma, por cercanía del pico.

    Voraz sobre las distancias ordenadas. Si un brazo cuenta una repetición que
    el otro no, se queda sin pareja y sale en el informe como discrepancia de
    conteo, que es un resultado en sí mismo.
    """
    distancias = sorted(
        (abs(x.t_pico_s - y.t_pico_s), i, j)
        for i, x in enumerate(a)
        for j, y in enumerate(b)
    )
    usados_a: set[int] = set()
    usados_b: set[int] = set()
    parejas: list[tuple[int, int]] = []
    for distancia, i, j in distancias:
        if distancia > tolerancia or i in usados_a or j in usados_b:
            continue
        usados_a.add(i)
        usados_b.add(j)
        parejas.append((i, j))
    return [(a[i], b[j]) for i, j in sorted(parejas)]


def _media(valores) -> float:
    v = np.asarray(list(valores), dtype=float)
    v = v[np.isfinite(v)]
    return float(v.mean()) if v.size else float("nan")


def _sd(valores) -> float:
    """Desviación muestral (ddof=1); NaN con menos de dos datos."""
    v = np.asarray(list(valores), dtype=float)
    v = v[np.isfinite(v)]
    return float(np.std(v, ddof=1)) if v.size >= 2 else float("nan")


def sd_intra_agrupada(por_serie: list[list[float]]) -> tuple[float, int]:
    """SD del ratio DENTRO de cada serie, agrupada entre series.

    Es la vara de medir del experimento: cuánto varía el ratio de una repetición
    a la siguiente del mismo atleta en la misma serie.
    """
    numerador = 0.0
    grados = 0
    for valores in por_serie:
        v = np.asarray(valores, dtype=float)
        v = v[np.isfinite(v)]
        if v.size < 2:
            continue
        numerador += (v.size - 1) * float(np.var(v, ddof=1))
        grados += v.size - 1
    if grados == 0:
        return float("nan"), 0
    return float(np.sqrt(numerador / grados)), grados


@dataclass
class Acuerdo:
    """Bland-Altman de una magnitud entre dos brazos."""

    magnitud: str
    n: int
    sesgo: float
    sd_dif: float
    loa_bajo: float
    loa_alto: float
    medias: np.ndarray
    diferencias: np.ndarray


def bland_altman(parejas: list[tuple[float, float]], magnitud: str) -> Acuerdo:
    """Sesgo y límites de acuerdo. ``dif = segundo - primero`` (paso2 - paso1)."""
    finitos = [(x, y) for x, y in parejas if np.isfinite(x) and np.isfinite(y)]
    if not finitos:
        vacio = np.empty(0)
        nan = float("nan")
        return Acuerdo(magnitud, 0, nan, nan, nan, nan, vacio, vacio)
    datos = np.asarray(finitos, dtype=float)
    medias = datos.mean(axis=1)
    difs = datos[:, 1] - datos[:, 0]
    sesgo = float(difs.mean())
    sd = _sd(difs)
    margen = 1.96 * sd if np.isfinite(sd) else float("nan")
    return Acuerdo(
        magnitud, difs.size, sesgo, sd, sesgo - margen, sesgo + margen, medias, difs
    )


# --- gráficas --------------------------------------------------------------


def grafica_bland_altman(acuerdo: Acuerdo, sd_intra: float, destino: Path) -> bool:
    """Bland-Altman a PNG. Devuelve False si no hay matplotlib o no hay datos."""
    if acuerdo.n < 2:
        return False
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    figura, eje = plt.subplots(figsize=(7.0, 4.6), dpi=140)
    eje.scatter(acuerdo.medias, acuerdo.diferencias, s=28, alpha=0.75, color="#1f77b4")
    eje.axhline(0, color="#999999", lw=0.8)
    eje.axhline(acuerdo.sesgo, color="#d62728", lw=1.4, label=f"sesgo {acuerdo.sesgo:+.4f}")
    for limite, etiqueta in (
        (acuerdo.loa_alto, f"LoA {acuerdo.loa_alto:+.4f}"),
        (acuerdo.loa_bajo, f"LoA {acuerdo.loa_bajo:+.4f}"),
    ):
        if np.isfinite(limite):
            eje.axhline(limite, color="#d62728", lw=1.0, ls="--", label=etiqueta)

    # La banda de referencia: si la nube cabe dentro, el muestreo mueve menos
    # que el propio atleta entre repeticiones.
    if np.isfinite(sd_intra):
        eje.axhspan(
            -sd_intra,
            sd_intra,
            color="#2ca02c",
            alpha=0.12,
            label=f"±SD intra-serie ({sd_intra:.3f})",
        )

    eje.set_xlabel(f"media de los dos pasos - {acuerdo.magnitud}")
    eje.set_ylabel("paso 2 - paso 1")
    eje.set_title(f"Bland-Altman: {acuerdo.magnitud}  (n={acuerdo.n})")
    eje.legend(fontsize=8, loc="best")
    figura.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(destino)
    plt.close(figura)
    return True


def grafica_diagnostico(
    resultado: Resultado, brazo: Brazo, destino: Path, titulo: str
) -> bool:
    """Señal, velocidad y fases detectadas de una serie, para mirarla con los ojos.

    Cuando un ratio sale absurdo hay que poder ver si la culpa es del atleta o
    del detector, y para eso no hay tabla que valga.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    altura, tiempo = resultado.altura, resultado.tiempo
    fps_senal = brazo.fps_senal
    v = velocidad(altura, fps_senal)
    picos = np.clip(
        np.array(
            [round((r.instante_s - tiempo[0]) * fps_senal) for r in resultado.repeticiones],
            dtype=int,
        ),
        0,
        altura.size - 1,
    )

    figura, (arriba, abajo) = plt.subplots(
        2, 1, figsize=(13, 6.4), dpi=130, sharex=True, height_ratios=[2, 1]
    )
    arriba.plot(tiempo, altura, color="#1f77b4", lw=1.2)
    arriba.axhline(resultado.umbral_bu, color="#ff7f0e", lw=1.0, ls="--", label="umbral validez")
    for izq, der in valles_de(altura, picos):
        arriba.plot(tiempo[izq], altura[izq], "v", color="#7f7f7f", ms=5)
        arriba.plot(tiempo[der], altura[der], "v", color="#7f7f7f", ms=5)
    arriba.plot(tiempo[picos], altura[picos], "o", color="#d62728", ms=5, label="picos")
    for r in brazo.reps:
        arriba.annotate(
            f"{r.numero}\n{r.ratio:.2f}",
            (r.t_pico_s, altura[picos[min(r.numero - 1, picos.size - 1)]]),
            textcoords="offset points", xytext=(0, 8), ha="center", fontsize=7,
        )
    arriba.set_ylabel("altura nariz [bu]")
    arriba.set_title(titulo)
    arriba.legend(fontsize=8, loc="upper right")

    abajo.plot(tiempo, v, color="#2ca02c", lw=1.0)
    abajo.axhline(brazo.umbral_v, color="#d62728", lw=0.9, ls="--")
    abajo.axhline(-brazo.umbral_v, color="#d62728", lw=0.9, ls="--")
    abajo.axhline(0, color="#999999", lw=0.6)
    abajo.set_ylabel("velocidad [bu/s]")
    abajo.set_xlabel("tiempo [s]")

    figura.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(destino)
    plt.close(figura)
    return True


# --- informe ---------------------------------------------------------------


class Informe:
    """Acumula el texto para escribirlo y enseñarlo a la vez."""

    def __init__(self) -> None:
        self.lineas: list[str] = []

    def __call__(self, texto: str = "") -> None:
        print(texto)
        self.lineas.append(texto)

    def guardar(self, destino: Path) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("\n".join(self.lineas) + "\n", encoding="utf-8")


def _fmt(valor: float, decimales: int = 3) -> str:
    return "-" if valor is None or not np.isfinite(valor) else f"{valor:.{decimales}f}"


def tabla(cabecera: list[str], filas: list[list[str]]) -> list[str]:
    anchos = [
        max(len(cabecera[c]), *(len(f[c]) for f in filas)) if filas else len(cabecera[c])
        for c in range(len(cabecera))
    ]
    sep = "  "
    lineas = [sep.join(t.ljust(anchos[c]) for c, t in enumerate(cabecera))]
    lineas.append(sep.join("-" * a for a in anchos))
    lineas += [sep.join(t.ljust(anchos[c]) for c, t in enumerate(fila)) for fila in filas]
    return lineas


# --- autotest con señal sintética ------------------------------------------


def senal_sintetica(
    ratio: float,
    n_reps: int,
    fps: float,
    t_subida: float = 0.7,
    pausa_abajo: float = 0.35,
    pausa_arriba: float = 0.10,
    amplitud: float = 1.0,
) -> np.ndarray:
    """Serie de dominadas de ratio conocido, muestreada a ``fps``.

    La señal se define como función CONTINUA del tiempo y luego se evalúa en la
    rejilla: si en vez de eso se generase muestra a muestra, redondear las
    duraciones a un número entero de muestras cambiaría la señal subyacente
    entre 30 y 15 Hz y el autotest mediría ese redondeo en vez del detector.

    Sirve para saber si el detector mide lo que dice medir ANTES de creerse
    ningún número sacado de un vídeo.
    """
    t_bajada = ratio * t_subida
    ciclo = pausa_abajo + t_subida + pausa_arriba + t_bajada
    t = np.arange(int(round(n_reps * ciclo * fps)) + 1) / fps
    fase = np.mod(t, ciclo)

    senal = np.zeros_like(fase)
    subiendo = (fase >= pausa_abajo) & (fase < pausa_abajo + t_subida)
    arriba = (fase >= pausa_abajo + t_subida) & (fase < pausa_abajo + t_subida + pausa_arriba)
    bajando = fase >= pausa_abajo + t_subida + pausa_arriba

    u = (fase[subiendo] - pausa_abajo) / t_subida
    senal[subiendo] = 0.5 * (1 - np.cos(np.pi * u))
    senal[arriba] = 1.0
    w = (fase[bajando] - pausa_abajo - t_subida - pausa_arriba) / t_bajada
    senal[bajando] = 0.5 * (1 + np.cos(np.pi * w))
    return amplitud * senal


def autotest(informe: Informe, definicion: str = "acumulada", ratios=(1.0, 1.5, 2.5)) -> None:
    """El detector contra señales de ratio conocido, a 30 y a 15 Hz."""
    from contador import Repeticion
    from scipy.signal import find_peaks

    def medir(ratio: float, fps_senal: float, paso: int) -> float:
        senal = senal_sintetica(ratio, 5, fps_senal)
        picos, _ = find_peaks(senal, prominence=0.4)
        reps = [
            Repeticion(numero=i + 1, instante_s=int(p) / fps_senal, margen_bu=0.1)
            for i, p in enumerate(picos)
        ]
        res = Resultado(
            repeticiones=reps,
            fps=fps_senal * paso,
            paso=paso,
            altura=senal,
            tiempo=np.arange(senal.size) / fps_senal,
            umbral_bu=0.0,
        )
        brazo = medir_fases(res, f"sintetico_p{paso}", definicion)
        if brazo is None:
            return float("nan")
        return _media(r.ratio for r in brazo.reps if not r.truncada)

    informe("AUTOTEST del detector de fases (señal sintética, ratio conocido)")
    informe("")
    filas: list[list[str]] = []
    for ratio in ratios:
        # 300 Hz = la misma definición sin cuantización: separa el sesgo de la
        # DEFINICIÓN del efecto del muestreo, que es lo que se quiere medir.
        ideal = medir(ratio, 300.0, 1)
        p1 = medir(ratio, 30.0, 1)
        p2 = medir(ratio, 15.0, 2)
        filas.append(
            [
                _fmt(ratio, 2),
                _fmt(ideal, 3),
                _fmt(p1, 3),
                _fmt(p2, 3),
                _fmt(p2 - p1, 4),
            ]
        )
    for linea in tabla(
        ["ratio real", "def. a 300 Hz", "medido p=1", "medido p=2", "p2 - p1"], filas
    ):
        informe(linea)
    informe("")
    informe(
        "Columna 2: el detector por umbral de velocidad recorta un poco cada fase,\n"
        "y recorta más la larga que la corta, así que el ratio medido se aplana\n"
        "respecto al real. Es un sesgo de la DEFINICIÓN, no del paso, y afecta\n"
        "igual a los dos brazos; se corregiría bajando FRAC_UMBRAL_V.\n"
        "Columna 5: eso es lo que aporta el muestreo, sobre una señal limpia y\n"
        "sin ruido de pose. Es el suelo del experimento: en vídeo real la\n"
        "diferencia entre pasos no puede salir más pequeña que esto."
    )


# --- experimento -----------------------------------------------------------


def videos_de(carpeta: Path) -> list[Path]:
    return sorted(
        p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES
    )


def procesar_video(
    video: Path,
    modelo: str,
    cache: Path | None,
    informe: Informe,
    decimado: bool,
    definicion: str,
    diagnosticos: Path | None,
) -> dict[str, Brazo]:
    """Los brazos del experimento para un vídeo: p=1, p=2 y (opcional) p=2 decimado."""
    brazos: dict[str, Brazo] = {}
    puntos_p1 = detectado_p1 = None
    fps = float("nan")

    for paso in (1, 2):
        puntos, detectado, fps, segundos = pose_de(video, modelo, paso, cache)
        if paso == 1:
            puntos_p1, detectado_p1 = puntos, detectado
        resultado = contar_puntos(puntos, detectado, fps, paso)
        brazo = medir_fases(resultado, f"p{paso}", definicion)
        if brazo is None:
            raise ValueError(f"ninguna repetición medible con paso={paso}")
        brazo.segundos_pose = segundos
        brazos[f"p{paso}"] = brazo
        if diagnosticos is not None:
            grafica_diagnostico(
                resultado,
                brazo,
                diagnosticos / f"diag_{video.stem}_p{paso}.png",
                f"{video.name}   paso={paso}   fases: {definicion}",
            )
        informe(
            f"    paso={paso}  {brazo.n_contadas} rep contadas, "
            f"{len(brazo.reps)} medibles, fs={brazo.fps_senal:.1f} Hz, "
            f"umbral_v={brazo.umbral_v:.3f} bu/s"
            + (f", pose {segundos:.1f} s" if segundos else ", pose en caché")
        )

    if decimado and puntos_p1 is not None:
        # Diagnóstico: mismos keypoints que p=1 pero a la mitad de muestras. Si
        # p2 real difiere de p1 y p2_dec no, la culpa es del seguimiento de
        # MediaPipe (ve otros frames), no del muestreo.
        resultado = contar_puntos(puntos_p1[::2], detectado_p1[::2], fps, 2)
        brazo = medir_fases(resultado, "p2_dec", definicion)
        if brazo is not None:
            brazos["p2_dec"] = brazo
            informe(
                f"    p2_dec (diagnóstico)  {brazo.n_contadas} rep contadas, "
                f"{len(brazo.reps)} medibles"
            )
    return brazos


def main(argv: list[str] | None = None) -> int:
    # Antes de construir el parser: la consola de Windows va en cp1252 y se
    # come los acentos, y --help se imprime dentro de parse_args().
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="FASE 0: ¿paso=2 sirve para las métricas de fase?"
    )
    parser.add_argument("carpeta", nargs="?", type=Path, help="carpeta con los vídeos")
    parser.add_argument("--salida", type=Path, default=Path("resultados/fase0"))
    parser.add_argument("--cache", type=Path, default=Path("resultados/cache_pose"))
    parser.add_argument("--sin-cache", action="store_true")
    parser.add_argument("--modelo", default="lite", choices=("lite", "heavy"))
    parser.add_argument(
        "--sin-decimado",
        action="store_true",
        help="omite el brazo diagnóstico de p=1 decimado a la mitad",
    )
    parser.add_argument(
        "--incluir-truncadas",
        action="store_true",
        help="usa también las repeticiones cuya fase toca el borde del vídeo",
    )
    parser.add_argument("--tolerancia", type=float, default=TOLERANCIA_EMPAREJADO_S)
    parser.add_argument(
        "--definicion",
        default="acumulada",
        choices=("acumulada", "contigua"),
        help=(
            "acumulada: tiempo total en movimiento dentro de la fase, robusta a "
            "excéntricas no monótonas. contigua: solo el tramo contiguo alrededor "
            "del extremo de velocidad."
        ),
    )
    parser.add_argument(
        "--diagnostico",
        action="store_true",
        help="guarda una gráfica por vídeo y paso con la señal, la velocidad y "
        "las fases detectadas: es lo único que permite ver si un ratio raro es "
        "del atleta o del detector",
    )
    parser.add_argument("--autotest", action="store_true")
    args = parser.parse_args(argv)

    informe = Informe()

    if args.autotest:
        autotest(informe, args.definicion)
        if args.carpeta is None:
            informe.guardar(args.salida / "autotest.txt")
            return 0
        informe("")
        informe("=" * 78)
        informe("")

    if args.carpeta is None:
        parser.error("hace falta una carpeta de vídeos (o --autotest a secas)")

    if not args.carpeta.is_dir():
        parser.error(f"no es una carpeta: {args.carpeta}")
    videos = videos_de(args.carpeta)
    if not videos:
        parser.error(f"no hay vídeos en {args.carpeta}")

    cache = None if args.sin_cache else args.cache
    decimado = not args.sin_decimado

    informe(
        f"FASE 0 - experimento de paso   modelo={args.modelo}   "
        f"{len(videos)} vídeos   fases: {args.definicion}"
    )
    informe("")

    procesados: dict[str, dict[str, Brazo]] = {}
    for video in videos:
        informe(f"  {video.name}")
        try:
            procesados[video.name] = procesar_video(
                video,
                args.modelo,
                cache,
                informe,
                decimado,
                args.definicion,
                args.salida if args.diagnostico else None,
            )
        except ValueError as error:
            informe(f"    descartado: {error}")
        except Exception as error:  # noqa: BLE001 - un vídeo roto no tumba el lote
            informe(f"    error inesperado: {type(error).__name__}: {error}")
        informe("")

    if not procesados:
        informe("Ningún vídeo dio repeticiones medibles. No hay experimento.")
        informe.guardar(args.salida / "informe.txt")
        return 1

    return informar(procesados, args, informe)


def informar(
    procesados: dict[str, dict[str, Brazo]], args, informe: Informe
) -> int:
    """Tablas, Bland-Altman, CSV y veredicto."""
    usable = (lambda r: True) if args.incluir_truncadas else (lambda r: not r.truncada)

    # --- tabla por serie ---
    informe("-" * 78)
    informe("SERIES")
    informe("")
    filas_serie: list[list[str]] = []
    csv_series: list[dict] = []
    for nombre, brazos in procesados.items():
        for etiqueta, brazo in brazos.items():
            reps = [r for r in brazo.reps if usable(r)]
            fila = {
                "video": nombre,
                "brazo": etiqueta,
                "paso": brazo.paso,
                "fps_senal": round(brazo.fps_senal, 2),
                "n_contadas": brazo.n_contadas,
                "n_medibles": len(brazo.reps),
                "n_usadas": len(reps),
                "recorrido_bu": round(brazo.recorrido_bu, 3),
                "umbral_v_bu_s": round(brazo.umbral_v, 4),
                "t_subida_media_s": _media(r.t_subida_s for r in reps),
                "t_bajada_media_s": _media(r.t_bajada_s for r in reps),
                "ratio_medio": _media(r.ratio for r in reps),
                "ratio_sd_intra": _sd(r.ratio for r in reps),
                "segundos_pose": round(brazo.segundos_pose, 1),
            }
            csv_series.append(fila)
            filas_serie.append(
                [
                    nombre[:28],
                    etiqueta,
                    str(brazo.n_contadas),
                    str(len(reps)),
                    _fmt(fila["t_subida_media_s"]),
                    _fmt(fila["t_bajada_media_s"]),
                    _fmt(fila["ratio_medio"]),
                    _fmt(fila["ratio_sd_intra"]),
                ]
            )
    for linea in tabla(
        ["video", "brazo", "cont", "usadas", "t_sub", "t_baj", "ratio", "sd_intra"],
        filas_serie,
    ):
        informe(linea)
    informe("")

    # --- emparejado p1 vs p2 ---
    parejas_por_video: dict[str, list[tuple[Rep, Rep]]] = {}
    parejas_dec: list[tuple[Rep, Rep]] = []
    sueltas = 0
    for nombre, brazos in procesados.items():
        if "p1" not in brazos or "p2" not in brazos:
            continue
        a = [r for r in brazos["p1"].reps if usable(r)]
        b = [r for r in brazos["p2"].reps if usable(r)]
        parejas = emparejar(a, b, args.tolerancia)
        parejas_por_video[nombre] = parejas
        sueltas += len(a) + len(b) - 2 * len(parejas)
        if "p2_dec" in brazos:
            c = [r for r in brazos["p2_dec"].reps if usable(r)]
            parejas_dec += emparejar(a, c, args.tolerancia)

    todas = [p for parejas in parejas_por_video.values() for p in parejas]
    if len(todas) < 2:
        informe("Menos de dos repeticiones emparejadas: no hay nada que comparar.")
        informe.guardar(args.salida / "informe.txt")
        return 1

    # --- conteo: lo primero que tiene que coincidir ---
    informe("-" * 78)
    informe("CONTEO (antes que las fases: si el número no coincide, lo demás sobra)")
    informe("")
    filas_conteo = []
    conteo_ok = True
    for nombre, brazos in procesados.items():
        n1 = brazos["p1"].n_contadas if "p1" in brazos else 0
        n2 = brazos["p2"].n_contadas if "p2" in brazos else 0
        v1 = sum(r.valida for r in brazos["p1"].reps) if "p1" in brazos else 0
        v2 = sum(r.valida for r in brazos["p2"].reps) if "p2" in brazos else 0
        conteo_ok &= n1 == n2
        filas_conteo.append(
            [nombre[:34], str(n1), str(n2), "=" if n1 == n2 else "DISTINTO",
             f"{v1}/{v2}"]
        )
    for linea in tabla(
        ["video", "rep p=1", "rep p=2", "", "válidas p1/p2"], filas_conteo
    ):
        informe(linea)
    informe("")

    # --- acuerdo entre pasos ---
    acuerdos = {
        "ratio_ecc_con": bland_altman([(x.ratio, y.ratio) for x, y in todas], "ratio ecc/con"),
        "t_subida_s": bland_altman(
            [(x.t_subida_s, y.t_subida_s) for x, y in todas], "t_subida (s)"
        ),
        "t_bajada_s": bland_altman(
            [(x.t_bajada_s, y.t_bajada_s) for x, y in todas], "t_bajada (s)"
        ),
        "rom_bu": bland_altman([(x.rom_bu, y.rom_bu) for x, y in todas], "ROM (bu)"),
        "v_pico_con": bland_altman(
            [(x.v_pico_con, y.v_pico_con) for x, y in todas], "v pico concéntrica (bu/s)"
        ),
    }

    sd_intra, grados = sd_intra_agrupada(
        [
            [r.ratio for r in brazos["p1"].reps if usable(r)]
            for brazos in procesados.values()
            if "p1" in brazos
        ]
    )

    informe("-" * 78)
    informe("ACUERDO ENTRE PASOS  (Bland-Altman, diferencia = paso2 - paso1)")
    informe("")
    filas_ba = []
    for a in acuerdos.values():
        # El error es proporcional -en el Bland-Altman la nube se abre a la
        # derecha-, así que el número en absoluto engaña: un ±0,17 sobre un
        # ratio de 0,7 y sobre uno de 2,6 no son el mismo error.
        rel = (
            100 * a.diferencias[a.medias != 0] / a.medias[a.medias != 0]
            if a.n
            else np.empty(0)
        )
        filas_ba.append(
            [
                a.magnitud,
                str(a.n),
                _fmt(a.sesgo, 4),
                _fmt(a.sd_dif, 4),
                f"[{_fmt(a.loa_bajo, 3)}, {_fmt(a.loa_alto, 3)}]",
                f"{_fmt(_media(rel), 1)} %",
                f"{_fmt(1.96 * _sd(rel), 1)} %",
            ]
        )
    for linea in tabla(
        [
            "magnitud", "n", "sesgo", "sd dif", "límites de acuerdo 95 %",
            "sesgo rel", "1,96·sd rel",
        ],
        filas_ba,
    ):
        informe(linea)
    informe("")

    # El número agrupado lo domina la serie más sucia. Sin desglose por vídeo no
    # se ve si el criterio pasa porque el muestreo da igual o porque hay una
    # serie con tanto ruido de medida que hace pasar cualquier cosa.
    informe("  Por vídeo (la SD agrupada la manda la serie más sucia):")
    informe("")
    filas_video = []
    for nombre, parejas in parejas_por_video.items():
        if len(parejas) < 2:
            continue
        ba_v = bland_altman([(x.ratio, y.ratio) for x, y in parejas], "ratio")
        sd_v = _sd(x.ratio for x, _ in parejas)
        veredicto = (
            "paso=2 ok"
            if np.isfinite(sd_v) and 1.96 * ba_v.sd_dif < sd_v
            else "mirar" if np.isfinite(sd_v) and abs(ba_v.sesgo) < sd_v else "NO"
        )
        filas_video.append(
            [
                nombre[:30], str(ba_v.n), _fmt(sd_v, 3), _fmt(ba_v.sesgo, 4),
                _fmt(1.96 * ba_v.sd_dif, 4), veredicto,
            ]
        )
    for linea in tabla(
        ["video", "n", "sd_intra", "sesgo", "1,96·sd_dif", "veredicto"], filas_video
    ):
        informe("  " + linea)
    informe("")
    informe(f"  repeticiones emparejadas: {len(todas)}   sin pareja: {sueltas}")

    # v_pico es un extremo instantáneo, lo más sensible que hay al muestreo, y
    # encima es sobre lo que FASE 1 monta la caída de velocidad. Va en relativo
    # porque en bu/s absolutos no se sabe si 0,2 es mucho o poco.
    ba_v = acuerdos["v_pico_con"]
    v_medio = _media(x.v_pico_con for x, _ in todas)
    if np.isfinite(v_medio) and v_medio > 0:
        informe(
            f"  v pico concéntrica: media {v_medio:.2f} bu/s, "
            f"sesgo {100 * ba_v.sesgo / v_medio:+.1f} %, "
            f"dispersión 1,96·sd = {100 * 1.96 * ba_v.sd_dif / v_medio:.1f} % "
            "(es un extremo instantáneo: lo más sensible al muestreo)"
        )
    if parejas_dec:
        ba_dec = bland_altman([(x.ratio, y.ratio) for x, y in parejas_dec], "ratio")
        informe(
            f"  diagnóstico p1 decimado (mismos keypoints, mitad de muestras): "
            f"sesgo {_fmt(ba_dec.sesgo, 4)}, sd {_fmt(ba_dec.sd_dif, 4)}, n={ba_dec.n}"
        )
    informe("")

    # --- caída de velocidad ---
    # La v_pico de UNA repetición es lo más sensible al muestreo de todo lo que
    # se mide aquí, pero el producto no enseña esa v_pico: enseña su pendiente a
    # lo largo de la serie. Una pendiente promedia el ruido de cada punto, así
    # que hay que comprobarla aparte antes de dar por buena la decisión.
    informe("-" * 78)
    informe("CAÍDA DE VELOCIDAD CONCÉNTRICA (pendiente por regresión, bu/s por rep)")
    informe("")
    filas_caida = []
    for nombre, parejas in parejas_por_video.items():
        if len(parejas) < 3:
            filas_caida.append([nombre[:30], str(len(parejas)), "-", "-", "-"])
            continue
        orden = np.arange(len(parejas), dtype=float)
        m1 = float(np.polyfit(orden, [x.v_pico_con for x, _ in parejas], 1)[0])
        m2 = float(np.polyfit(orden, [y.v_pico_con for _, y in parejas], 1)[0])
        filas_caida.append(
            [nombre[:30], str(len(parejas)), _fmt(m1, 4), _fmt(m2, 4), _fmt(m2 - m1, 4)]
        )
    for linea in tabla(
        ["video", "n", "pendiente p=1", "pendiente p=2", "p2 - p1"], filas_caida
    ):
        informe("  " + linea)
    informe("")

    # --- veredicto ---
    ba = acuerdos["ratio_ecc_con"]
    dif_media_abs = float(np.mean(np.abs(ba.diferencias))) if ba.n else float("nan")
    repetibilidad = 1.96 * ba.sd_dif if np.isfinite(ba.sd_dif) else float("nan")

    informe("-" * 78)
    informe("VEREDICTO")
    informe("")
    informe(f"  variabilidad del ratio DENTRO de la serie (SD agrupada) : {_fmt(sd_intra, 4)}"
            f"   (gl={grados})")
    informe(f"  |diferencia media| entre pasos                          : {_fmt(abs(ba.sesgo), 4)}")
    informe(f"  diferencia absoluta media por repetición                : {_fmt(dif_media_abs, 4)}")
    informe(f"  repetibilidad entre pasos (1,96 x sd_dif)               : {_fmt(repetibilidad, 4)}")
    informe("")

    criterio_spec = np.isfinite(sd_intra) and abs(ba.sesgo) < sd_intra
    criterio_duro = np.isfinite(sd_intra) and np.isfinite(repetibilidad) and repetibilidad < sd_intra

    if criterio_spec:
        informe("  [OK] Criterio del spec: la diferencia entre pasos es MENOR que la")
        informe("       variabilidad intra-serie. paso=2 vale para las métricas de fase.")
    else:
        informe("  [NO] Criterio del spec: la diferencia entre pasos NO es menor que la")
        informe("       variabilidad intra-serie. Hace falta paso=1 para las fases.")
    informe("")
    if criterio_duro:
        informe("  [OK] Criterio estricto (rep a rep): los límites de acuerdo también")
        informe("       caben dentro de la variabilidad intra-serie.")
    else:
        informe("  [!]  Criterio estricto (rep a rep): los límites de acuerdo NO caben")
        informe("       dentro de la variabilidad intra-serie. El promedio de la serie")
        informe("       aguanta paso=2, pero el ratio de UNA repetición concreta no es")
        informe("       intercambiable entre pasos. Si el producto enseña ratio rep a")
        informe("       rep, usa paso=1; si enseña la media de la serie, paso=2 basta.")
    if not conteo_ok:
        informe("")
        informe("  [!]  Hay vídeos donde el CONTEO difiere entre pasos. Eso pesa más que")
        informe("       cualquier métrica de fase: mira esos vídeos antes de decidir.")
    if len(procesados) < 3:
        informe("")
        informe(f"  [!]  Solo {len(procesados)} vídeo(s). Esto es una comprobación, no un")
        informe("       estudio: la SD intra-serie de una sola serie no representa a nadie.")
    informe("")

    # --- ficheros ---
    args.salida.mkdir(parents=True, exist_ok=True)
    escribir_csv_series(args.salida / "series.csv", csv_series)
    escribir_csv_reps(args.salida / "repeticiones.csv", parejas_por_video)

    graficas = []
    for clave in ("ratio_ecc_con", "t_subida_s", "t_bajada_s"):
        destino = args.salida / f"ba_{clave}.png"
        if grafica_bland_altman(acuerdos[clave], sd_intra if clave == "ratio_ecc_con" else float("nan"), destino):
            graficas.append(destino.name)
    if not graficas:
        informe("  (sin gráficas: falta matplotlib o no hay datos suficientes)")

    informe(f"  escrito en {args.salida}: series.csv, repeticiones.csv"
            + (", " + ", ".join(graficas) if graficas else ""))
    informe.guardar(args.salida / "informe.txt")
    return 0


def escribir_csv_series(destino: Path, filas: list[dict]) -> None:
    if not filas:
        return
    with destino.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def escribir_csv_reps(
    destino: Path, parejas_por_video: dict[str, list[tuple[Rep, Rep]]]
) -> None:
    columnas = [
        "video", "numero_p1", "numero_p2", "t_pico_p1_s", "t_pico_p2_s",
        "t_subida_p1_s", "t_subida_p2_s", "dif_t_subida_s",
        "t_bajada_p1_s", "t_bajada_p2_s", "dif_t_bajada_s",
        "ratio_p1", "ratio_p2", "dif_ratio",
        "rom_p1_bu", "rom_p2_bu", "v_pico_p1", "v_pico_p2",
        "valida_p1", "valida_p2", "truncada_p1", "truncada_p2",
    ]
    with destino.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        for nombre, parejas in parejas_por_video.items():
            for a, b in parejas:
                escritor.writerow(
                    [
                        nombre, a.numero, b.numero,
                        round(a.t_pico_s, 4), round(b.t_pico_s, 4),
                        round(a.t_subida_s, 4), round(b.t_subida_s, 4),
                        round(b.t_subida_s - a.t_subida_s, 4),
                        round(a.t_bajada_s, 4), round(b.t_bajada_s, 4),
                        round(b.t_bajada_s - a.t_bajada_s, 4),
                        round(a.ratio, 4), round(b.ratio, 4),
                        round(b.ratio - a.ratio, 4),
                        round(a.rom_bu, 4), round(b.rom_bu, 4),
                        round(a.v_pico_con, 4), round(b.v_pico_con, 4),
                        int(a.valida), int(b.valida),
                        int(a.truncada), int(b.truncada),
                    ]
                )


if __name__ == "__main__":
    raise SystemExit(main())
