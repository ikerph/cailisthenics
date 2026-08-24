"""Señales y keypoints sintéticos de parámetros conocidos.

Todo lo de aquí se define como función CONTINUA del tiempo y se evalúa en la
rejilla de muestreo. Generar muestra a muestra obligaría a redondear las
duraciones a un número entero de muestras, y entonces la señal a 15 Hz no sería
la misma que a 30: los tests medirían ese redondeo en vez del detector.
"""

from __future__ import annotations

import numpy as np

from contador import (
    HOMBRO_DER,
    HOMBRO_IZQ,
    MUNECA_DER,
    MUNECA_IZQ,
    NARIZ,
    Repeticion,
    Resultado,
)

ESCALA_PX = 100.0
"""Anchura de hombros en píxeles. Con 100, 1 bu = 100 px y las cuentas de los
tests se leen a ojo."""


def senal(
    ratio: float,
    n_reps: int,
    fps: float,
    t_subida: float = 0.7,
    pausa_abajo: float = 0.35,
    pausa_arriba: float = 0.10,
    amplitud: float = 1.0,
    decaimiento: float = 0.0,
) -> np.ndarray:
    """Serie de dominadas con ratio ecc/con conocido.

    Cada repetición sube con media onda de coseno en `t_subida` segundos, se
    mantiene arriba `pausa_arriba`, baja en `ratio * t_subida` y espera abajo
    `pausa_abajo`.

    `decaimiento` alarga la concéntrica un tanto por uno por repetición: sirve
    para fabricar fatiga con pendiente conocida sin tocar nada más.
    """
    t_bajada = ratio * t_subida
    trozos: list[np.ndarray] = []
    for i in range(n_reps):
        lento = 1.0 + decaimiento * i
        sube, baja = t_subida * lento, t_bajada * lento
        ciclo = pausa_abajo + sube + pausa_arriba + baja
        # El eje de cada repetición se construye aparte porque su duración
        # cambia con el decaimiento; concatenar rejillas de paso constante
        # mantiene el muestreo uniforme.
        n = int(round(ciclo * fps))
        fase = np.arange(n) / fps
        trozo = np.zeros(n)

        subiendo = (fase >= pausa_abajo) & (fase < pausa_abajo + sube)
        arriba = (fase >= pausa_abajo + sube) & (fase < pausa_abajo + sube + pausa_arriba)
        bajando = fase >= pausa_abajo + sube + pausa_arriba

        trozo[subiendo] = 0.5 * (1 - np.cos(np.pi * (fase[subiendo] - pausa_abajo) / sube))
        trozo[arriba] = 1.0
        avance = fase[bajando] - pausa_abajo - sube - pausa_arriba
        trozo[bajando] = 0.5 * (1 + np.cos(np.pi * np.clip(avance / baja, 0, 1)))
        trozos.append(trozo)
    return amplitud * np.concatenate(trozos)


def senal_excentrica_partida(
    n_reps: int, fps: float, amplitud: float = 1.0
) -> np.ndarray:
    """Excéntrica NO monótona: caída rápida, freno a media altura, deriva lenta.

    Es la forma real que tiene la bajada de una dominada en `fp.mp4`, y la que
    rompía la definición de fase por tramo contiguo (FASE 0). Este generador
    existe para que esa regresión no vuelva.
    """
    tramos = [
        (0.35, 0.0, 0.0),  # colgado abajo
        (0.70, 0.0, 1.0),  # concéntrica
        (0.10, 1.0, 1.0),  # pausa arriba
        (0.35, 1.0, 0.45),  # caída rápida
        (0.30, 0.45, 0.40),  # freno: casi parado, cruza el umbral por debajo
        (0.80, 0.40, 0.0),  # deriva lenta hasta el dead hang
    ]
    ciclo = sum(d for d, _, _ in tramos)
    n = int(round(ciclo * fps))
    fase = np.arange(n) / fps

    trozo = np.zeros(n)
    t0 = 0.0
    for duracion, desde, hasta in tramos:
        dentro = (fase >= t0) & (fase < t0 + duracion)
        u = (fase[dentro] - t0) / duracion
        # Media onda de coseno: empieza y acaba con velocidad nula, como el
        # movimiento real, en vez de con las esquinas de una rampa lineal.
        trozo[dentro] = desde + (hasta - desde) * 0.5 * (1 - np.cos(np.pi * u))
        t0 += duracion
    return amplitud * np.tile(trozo, n_reps)


def puntos_de(
    altura: np.ndarray,
    escala: float = ESCALA_PX,
    desnivel_bu: float = 0.0,
    desviacion_bu: float = 0.0,
) -> np.ndarray:
    """Keypoints `(n, 33, 2)` coherentes con una señal de altura.

    Solo se rellenan los cinco puntos que el contador usa; el resto queda a
    `NaN`, que es lo que devuelve MediaPipe cuando no ve algo.

    Origen arriba a la izquierda, "y" crece hacia abajo: por eso la altura se
    resta. El desnivel es hombro derecho menos izquierdo, en bu, con el mismo
    signo que `metricas._asimetria`.
    """
    n = altura.size
    puntos = np.full((n, 33, 2), np.nan)

    suelo_y = 600.0
    nariz_y = suelo_y - altura * escala
    centro_x = 320.0

    puntos[:, NARIZ] = np.column_stack([np.full(n, centro_x + desviacion_bu * escala), nariz_y])

    hombros_y = nariz_y + 0.5 * escala
    puntos[:, HOMBRO_IZQ] = np.column_stack(
        [np.full(n, centro_x - escala / 2), hombros_y]
    )
    puntos[:, HOMBRO_DER] = np.column_stack(
        [np.full(n, centro_x + escala / 2), hombros_y + desnivel_bu * escala]
    )

    # Las manos están agarradas a la barra: quietas, y por encima de los hombros
    # todo el rato, que es como `_tramo_colgado` decide que hay ejercicio.
    manos_y = suelo_y - 2.6 * escala
    puntos[:, MUNECA_IZQ] = np.column_stack(
        [np.full(n, centro_x - 0.8 * escala), np.full(n, manos_y)]
    )
    puntos[:, MUNECA_DER] = np.column_stack(
        [np.full(n, centro_x + 0.8 * escala), np.full(n, manos_y)]
    )
    return puntos


def resultado_de(
    altura: np.ndarray,
    fps: float = 30.0,
    paso: int = 1,
    puntos: np.ndarray | None = None,
    margen_bu: float = 0.10,
) -> Resultado:
    """Un `Resultado` a partir de una señal, saltándose la pose y el vídeo.

    Los picos se buscan con la misma prominencia relativa que usa el contador,
    para que la lista de repeticiones sea la que saldría de verdad.
    """
    from scipy.signal import find_peaks

    fps_senal = fps / max(paso, 1)
    recorrido = float(np.percentile(altura, 95) - np.percentile(altura, 5))
    picos, _ = find_peaks(altura, prominence=0.4 * recorrido)

    return Resultado(
        repeticiones=[
            Repeticion(
                numero=i + 1, instante_s=int(p) / fps_senal, margen_bu=margen_bu
            )
            for i, p in enumerate(picos)
        ],
        puntos=puntos if puntos is not None else puntos_de(altura),
        fps=fps,
        paso=paso,
        altura=altura,
        tiempo=np.arange(altura.size) / fps_senal,
        barra_bu=1.0,
        umbral_bu=1.0,
    )
