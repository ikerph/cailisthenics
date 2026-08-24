"""Calibración: dónde está la barra y qué tramo del vídeo es la serie.

Las manos están agarradas a la barra, así que **la recta que une las dos muñecas
es la barra**. No hace falta buscarla en la imagen: sale de los mismos puntos que
ya se han estimado, y no se equivoca de línea. Buscarla por detección de bordes
sí se equivoca: en un vídeo de prueba se enganchó al rótulo de la grabadora y en
otro a un fluorescente del techo, los dos más largos y más contrastados que la
propia barra.

Esa recta da tres cosas:

- **la altura** contra la que se juzga si la barbilla pasó la barra;
- **la inclinación**, que es la del móvil: si sale torcida, la cámara estaba
  torcida;
- **el tramo a analizar**: mientras las muñecas estén por encima de los hombros,
  el sujeto está agarrado a la barra. Antes y después está andando, y ese vaivén
  no son dominadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pose import Pose

__all__ = [
    "Calibracion",
    "calibrar",
    "ErrorDeCalibracion",
    "DESFASE_MUNECA_BU",
    "DESFASE_BARBILLA_BU",
    "MARGEN_BARBILLA_BU",
    "INCERTIDUMBRE_BU",
]

#: Cuánto queda la barra **por encima** del punto de muñeca, en anchuras de
#: hombros. La mano envuelve la barra por arriba, así que el keypoint de muñeca
#: cae en el lado de abajo. Medido contra detección de barra por bordes en tres
#: vídeos: 0.17, 0.21 y 0.31.
DESFASE_MUNECA_BU = 0.20

#: Cuánto queda la barbilla **por debajo** de la nariz. Se sigue la nariz y no la
#: barbilla porque en el punto alto la barra tapa la cara justo cuando haría
#: falta verla, así que hay que descontar esta distancia.
DESFASE_BARBILLA_BU = 0.20

#: Lo que tiene que superar la nariz a la recta de las manos para que la barbilla
#: haya pasado la barra: los dos desfases apilados.
MARGEN_BARBILLA_BU = DESFASE_MUNECA_BU + DESFASE_BARBILLA_BU

#: Los dos desfases son estimaciones, así que el veredicto tiene esta
#: incertidumbre. Una repetición que caiga dentro de la banda se marca como *al
#: límite* en vez de darla por buena o por mala.
INCERTIDUMBRE_BU = 0.10


class ErrorDeCalibracion(ValueError):
    """En ese vídeo no se ve a nadie colgado de una barra."""


@dataclass(frozen=True)
class Calibracion:
    """La barra y el tramo de vídeo en que el sujeto está colgado.

    Attributes:
        inicio: primer frame del tramo, en la numeración del vídeo original.
        fin: último frame (exclusivo).
        hombros_px: anchura de hombros mediana; la regla de medir.
        manos_y_px: altura de la recta que une las dos muñecas, en ``x_ref_px``.
            Es lo único que se mide; la barra se deduce de ella.
        x_ref_px: abscisa en que se evalúa ``manos_y_px``.
        inclinacion_deg: inclinación aparente de la barra. Positivo = el extremo
            derecho de la imagen cae más bajo.
        avisos: lo que conviene saber antes de creerse el resultado.
    """

    inicio: int
    fin: int
    hombros_px: float
    manos_y_px: float
    x_ref_px: float
    inclinacion_deg: float
    fps: float
    avisos: list[str] = field(default_factory=list)

    @property
    def duracion_s(self) -> float:
        """Duración del tramo analizado, en segundos."""
        return (self.fin - self.inicio) / self.fps

    @property
    def barra_y_px(self) -> float:
        """Altura estimada de la barra: la de las manos menos el desfase de muñeca."""
        return self.manos_y_px - DESFASE_MUNECA_BU * self.hombros_px

    def altura_manos_en(self, x_px: np.ndarray | float) -> np.ndarray:
        """Altura de la recta de las manos en una abscisa dada.

        Con la barra inclinada 3° en una imagen de 500 px de ancho, sus extremos
        distan 26 px: comparar contra la altura del centro cuando el sujeto
        cuelga descentrado se equivocaría en media anchura de hombros.
        """
        pendiente = np.tan(np.radians(self.inclinacion_deg))
        return self.manos_y_px + pendiente * (np.asarray(x_px, dtype=np.float64) - self.x_ref_px)

    def altura_barra_en(self, x_px: np.ndarray | float) -> np.ndarray:
        """Altura estimada de la barra en una abscisa dada.

        ``y`` crece hacia abajo, así que estar por encima es restar.
        """
        return self.altura_manos_en(x_px) - DESFASE_MUNECA_BU * self.hombros_px


def calibrar(
    pose: Pose,
    hueco_max_s: float = 1.0,
    duracion_minima_s: float = 3.0,
) -> Calibracion:
    """Localiza el tramo colgado y la recta de la barra.

    Args:
        pose: los cinco puntos del vídeo entero.
        hueco_max_s: cuánto puede fallar el criterio de "colgado" sin cortar el
            tramo. Sirve para no partir la serie en cada repetición.
        duracion_minima_s: tramo mínimo para dar la calibración por buena.

    Returns:
        La :class:`Calibracion` del tramo más largo en que el sujeto está colgado.

    Raises:
        ErrorDeCalibracion: si no hay ningún tramo colgado utilizable.
    """
    colgado = _colgado(pose)
    if not colgado.any():
        raise ErrorDeCalibracion(
            "en ningún frame se ven las dos manos por encima de los hombros: "
            "el sujeto no llega a colgarse, o no se le ve entero en el encuadre"
        )

    inicio, fin = _tramo_mas_largo(colgado, pose.detectado, pose.fps, hueco_max_s)
    duracion = (fin - inicio) / pose.fps
    if duracion < duracion_minima_s:
        raise ErrorDeCalibracion(
            f"el tramo colgado más largo dura {duracion:.1f} s y hacen falta "
            f"{duracion_minima_s:.0f} s. ¿Se ve al sujeto entero durante la serie?"
        )

    tramo = pose.recortar(inicio, fin)
    anchuras = tramo.anchura_hombros
    anchuras = anchuras[np.isfinite(anchuras) & (anchuras > 0)]
    if anchuras.size < 5:
        raise ErrorDeCalibracion(
            "no se ven los hombros en casi ningún frame del tramo colgado: sin "
            "ellos no hay regla de medir"
        )
    # Una sola escala para todo el vídeo: la mediana. Recalcularla frame a frame
    # haría que la regla de medir cambiase de tamaño con el propio movimiento.
    hombros_px = float(np.median(anchuras))

    izq = np.nanmedian(tramo.muneca_izq, axis=0)
    der = np.nanmedian(tramo.muneca_der, axis=0)
    if not (np.isfinite(izq).all() and np.isfinite(der).all()):
        raise ErrorDeCalibracion("las muñecas no son visibles durante el tramo colgado")

    avisos: list[str] = []
    separacion = abs(izq[0] - der[0])
    if separacion < 0.5 * hombros_px:
        # Agarre muy estrecho o manos superpuestas: la recta no es fiable.
        inclinacion = 0.0
        avisos.append(
            f"las manos aparecen a solo {separacion / hombros_px:.2f} anchuras de "
            "hombros de distancia: no se puede medir la inclinación de la barra, "
            "se supone horizontal"
        )
    else:
        inclinacion = float(np.degrees(np.arctan2(der[1] - izq[1], der[0] - izq[0])))
        if abs(inclinacion) > 90:  # las manos vinieron en orden inverso
            inclinacion = float(np.degrees(np.arctan2(izq[1] - der[1], izq[0] - der[0])))
        if abs(inclinacion) > 2.0:
            avisos.append(
                f"la barra aparece inclinada {inclinacion:+.1f}° en la imagen: el "
                "móvil estaba torcido. El conteo no se resiente, pero nivélalo"
            )

    x_ref = float((izq[0] + der[0]) / 2)
    manos_y = float((izq[1] + der[1]) / 2)

    if inicio > 0 or fin < len(pose):
        avisos.append(
            f"se analiza de {inicio / pose.fps:.1f} s a {fin / pose.fps:.1f} s, que es "
            "cuando el sujeto está agarrado a la barra"
        )

    return Calibracion(
        inicio=pose.inicio + inicio,
        fin=pose.inicio + fin,
        hombros_px=hombros_px,
        manos_y_px=manos_y,
        x_ref_px=x_ref,
        inclinacion_deg=inclinacion,
        fps=pose.fps,
        avisos=avisos,
    )


def _colgado(pose: Pose) -> np.ndarray:
    """Frames en que las dos manos están por encima de los hombros.

    Se cumple durante toda la dominada, también arriba del todo: por muy alto que
    suba, los hombros nunca pasan de las manos. Y no se cumple andando con los
    brazos a los lados, que es justo lo que hay que descartar.
    """
    munecas = pose.altura_munecas
    hombros = pose.altura_hombros
    valido = np.isfinite(munecas) & np.isfinite(hombros)
    return valido & pose.detectado & (munecas < hombros)


def _tramo_mas_largo(
    colgado: np.ndarray, detectado: np.ndarray, fps: float, hueco_max_s: float
) -> tuple[int, int]:
    """Tramo colgado más largo, uniendo huecos cortos.

    Un hueco se une solo si en él se seguía viendo a la persona. Si se pierde el
    track, el tramo se corta ahí: después puede haber otro plano, otra toma u
    otra persona, y nada garantiza que siga siendo la misma serie.
    """
    hueco_max = max(int(round(hueco_max_s * fps)), 1)
    indices = np.flatnonzero(colgado)
    if indices.size == 0:
        return 0, 0

    tramos: list[tuple[int, int]] = []
    inicio = int(indices[0])
    anterior = int(indices[0])
    for i in indices[1:]:
        i = int(i)
        hueco = i - anterior - 1
        # `detectado[anterior + 1 : i]` es el hueco; si ahí se perdió a la
        # persona, no se une.
        if hueco > hueco_max or (hueco > 0 and not detectado[anterior + 1 : i].all()):
            tramos.append((inicio, anterior + 1))
            inicio = i
        anterior = i
    tramos.append((inicio, anterior + 1))
    return max(tramos, key=lambda t: t[1] - t[0])
