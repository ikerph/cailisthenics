"""Vídeo anotado a 720p.

`contador.dibujar` escribe a la resolución del original. Un vídeo de móvil a
1080p anotado pesa tres veces más y no se ve mejor: el esqueleto y la línea de
la barra se leen igual a 720p, y lo que se descarga por una red móvil importa.

Aquí se reescala el frame Y los keypoints por el mismo factor. Escalar solo uno
de los dos deja el esqueleto flotando al lado del cuerpo, que es el fallo obvio;
el silencioso es el otro, el del `paso`, y está comentado abajo.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from contador import (
    Resultado,
    _abrir_escritor,
    _dibujar_barra,
    _dibujar_esqueleto,
    _dibujar_marcador,
)

ALTO_MAXIMO = 720


def _par(valor: float) -> int:
    """Redondea a entero par.

    H.264 con submuestreo de croma 4:2:0 necesita anchura y altura pares. Con un
    número impar, ffmpeg falla al arrancar y el error sale por stderr de un
    proceso hijo, donde nadie lo mira.
    """
    return max(2, int(round(valor / 2)) * 2)


def anotar(
    video: str | Path,
    resultado: Resultado,
    destino: str | Path,
    alto_maximo: int = ALTO_MAXIMO,
    progreso=None,
) -> Path:
    """Copia del vídeo con esqueleto, barra y marcador, reescalada a 720p.

    Args:
        video: el vídeo original.
        resultado: lo devuelto por `contador.contar`.
        destino: ruta de salida; la extensión la decide el códec disponible.
        alto_maximo: altura de salida. Nunca se amplía un vídeo más pequeño.
        progreso: se llama con la fracción escrita, de 0 a 1.

    Returns:
        La ruta escrita.
    """
    captura = cv2.VideoCapture(str(video))
    if not captura.isOpened():
        raise ValueError(f"no se puede abrir el vídeo: {video}")

    ancho0 = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto0 = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if alto0 <= 0 or ancho0 <= 0:
        captura.release()
        raise ValueError(f"no se puede abrir el vídeo: {video}")

    factor = min(1.0, alto_maximo / alto0)
    ancho, alto = _par(ancho0 * factor), _par(alto0 * factor)
    # El factor real es el que sale de las dimensiones pares, no el pedido: si
    # se usara el pedido, los puntos quedarían desplazados hasta un píxel.
    factor_x, factor_y = ancho / ancho0, alto / alto0

    puntos = resultado.puntos * np.array([factor_x, factor_y])
    barra_y = resultado.barra_y_px * factor_y

    filas = len(puntos)
    total = filas * resultado.paso
    escritor, ruta = _abrir_escritor(Path(destino), resultado.fps, ancho, alto)

    picos = [
        (int(round(r.instante_s * resultado.fps)), r.esValida)
        for r in resultado.repeticiones
    ]

    try:
        indice = 0
        while True:
            ok, imagen = captura.read()
            if not ok:
                break
            if (ancho, alto) != (ancho0, alto0):
                imagen = cv2.resize(imagen, (ancho, alto), interpolation=cv2.INTER_AREA)

            # NO tocar sin leer esto: se escriben TODOS los frames del original,
            # pero solo hay una fila de puntos cada `paso` frames. Si aquí se
            # saltasen frames, o se usara `indice` en vez de `indice // paso`,
            # el esqueleto seguiría dibujándose sin fallar y sin avisar, pero
            # desplazado en el tiempo respecto al cuerpo: el error más caro de
            # detectar de todo el proyecto, porque el vídeo "sale bien".
            fila = indice // resultado.paso
            if fila < filas:
                _dibujar_esqueleto(imagen, puntos[fila])
            _dibujar_barra(imagen, barra_y)

            hechas = sum(1 for pico, _ in picos if pico <= indice)
            validas = sum(1 for pico, valida in picos if valida and pico <= indice)
            # Sin tildes: las fuentes Hershey de OpenCV no traen glifos acentuados.
            _dibujar_marcador(imagen, f"{hechas} realizadas  |  {validas} validas")

            escritor.write(imagen)
            indice += 1
            if progreso and total and indice % 15 == 0:
                progreso(min(indice / total, 1.0))
    finally:
        captura.release()
        escritor.release()
    return ruta
