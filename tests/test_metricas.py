"""FASE 1: métricas de fase contra señales sintéticas de parámetros conocidos.

El orden importa: si el detector no recupera un ratio que sabemos de antemano,
cualquier número que saque de un vídeo real es indistinguible de un adorno.
"""

from __future__ import annotations

import numpy as np
import pytest

import metricas
from metricas import CONCENTRICA, EXCENTRICA, PAUSA
from tests import sintetico


# --- ratio ecc/con ---------------------------------------------------------


@pytest.mark.parametrize("ratio", [1.0, 1.5, 2.0, 2.5])
def test_ratio_se_ordena_como_el_real(ratio: float) -> None:
    """El ratio medido crece con el real y lo sigue de cerca.

    No se exige igualdad: el umbral de velocidad recorta cada fase por los dos
    extremos y recorta proporcionalmente más la larga que la corta, así que el
    ratio medido sale aplanado. Es un sesgo conocido de la definición (FASE 0),
    no un fallo; lo que no puede pasar es que se desordene.
    """
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(ratio, 5, 30.0)))
    medido = serie.ratio_medio

    assert np.isfinite(medido)
    assert 0.85 * ratio <= medido <= 1.05 * ratio


def test_ratio_simetrico_es_uno_exacto() -> None:
    """Subida y bajada iguales: el recorte del umbral afecta igual a las dos y
    se cancela. Aquí sí se exige el número clavado."""
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.0, 5, 30.0)))
    assert serie.ratio_medio == pytest.approx(1.0, abs=0.02)
    assert serie.t_subida_media_s == pytest.approx(serie.t_bajada_media_s, abs=0.02)


def test_ratio_creciente_es_monotono() -> None:
    ratios = [1.0, 1.5, 2.0, 2.5]
    medidos = [
        metricas.analizar(sintetico.resultado_de(sintetico.senal(r, 5, 30.0))).ratio_medio
        for r in ratios
    ]
    assert medidos == sorted(medidos)


# --- lo que FASE 0 dejó decidido ------------------------------------------


def test_paso_2_da_el_mismo_ratio_que_paso_1() -> None:
    """La decisión de FASE 0, como test: a 15 Hz sale lo mismo que a 30.

    Si alguien toca la ventana del Savitzky-Golay y la deja en muestras en vez
    de en segundos, este test es el que se cae.
    """
    a = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.5, 6, 30.0), fps=30.0))
    b = metricas.analizar(
        sintetico.resultado_de(sintetico.senal(1.5, 6, 15.0), fps=30.0, paso=2)
    )
    assert b.ratio_medio == pytest.approx(a.ratio_medio, rel=0.10)
    assert b.t_subida_media_s == pytest.approx(a.t_subida_media_s, rel=0.10)


def test_excentrica_partida_se_mide_entera() -> None:
    """Regresión de FASE 0: la bajada real no es monótona.

    Cae rápido, frena a media altura -la velocidad cruza el umbral por debajo- y
    sigue en deriva lenta. Quedarse con el tramo contiguo alrededor del pico de
    velocidad daría una bajada mucho más corta que la subida. Sumando todo el
    tiempo en movimiento, la bajada tiene que salir MÁS larga que la subida,
    porque en la señal dura 1,45 s contra 0,70.
    """
    altura = sintetico.senal_excentrica_partida(5, 30.0)
    serie = metricas.analizar(sintetico.resultado_de(altura))

    assert serie.n_usadas >= 3
    assert serie.t_bajada_media_s > serie.t_subida_media_s
    assert serie.ratio_medio > 1.3


def test_las_pausas_no_cuentan_como_fase() -> None:
    """Alargar la pausa de arriba no alarga ninguna fase: las duraciones son
    tiempo EN MOVIMIENTO."""
    corta = metricas.analizar(
        sintetico.resultado_de(sintetico.senal(1.0, 5, 30.0, pausa_arriba=0.10))
    )
    larga = metricas.analizar(
        sintetico.resultado_de(sintetico.senal(1.0, 5, 30.0, pausa_arriba=1.20))
    )
    assert larga.t_subida_media_s == pytest.approx(corta.t_subida_media_s, abs=0.05)
    assert larga.t_bajada_media_s == pytest.approx(corta.t_bajada_media_s, abs=0.05)


# --- umbral relativo -------------------------------------------------------


def test_el_umbral_es_relativo_a_la_serie() -> None:
    """Doblar la amplitud no cambia el ratio: el umbral escala con el atleta.

    Con un umbral absoluto en bu/s, el que sube el doble de recorrido cruzaría
    el umbral antes y sus fases saldrían más largas.
    """
    normal = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.5, 5, 30.0)))
    grande = metricas.analizar(
        sintetico.resultado_de(sintetico.senal(1.5, 5, 30.0, amplitud=2.0))
    )
    assert grande.ratio_medio == pytest.approx(normal.ratio_medio, rel=0.05)
    assert grande.umbral_v_bu_s > normal.umbral_v_bu_s


# --- valles y delimitación -------------------------------------------------


def test_cada_repeticion_es_valle_pico_valle() -> None:
    altura = sintetico.senal(1.2, 6, 30.0)
    resultado = sintetico.resultado_de(altura)
    picos = np.array(
        [round(r.instante_s * resultado.fps) for r in resultado.repeticiones], dtype=int
    )
    limites = metricas.valles_de(altura, picos)

    assert len(limites) == len(picos)
    for pico, (izq, der) in zip(picos, limites):
        assert izq < pico < der
        assert altura[izq] < altura[pico] > altura[der]


def test_hay_una_repeticion_por_dominada() -> None:
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 7, 30.0)))
    assert serie.n_total == 7


# --- fases por muestra -----------------------------------------------------


def test_las_fases_etiquetan_las_tres_situaciones() -> None:
    altura = sintetico.senal(1.5, 5, 30.0, pausa_abajo=0.6)
    serie = metricas.analizar(sintetico.resultado_de(altura))

    assert set(np.unique(serie.fases)) == {CONCENTRICA, PAUSA, EXCENTRICA}
    assert serie.fases.size == altura.size
    # Con ratio 1,5 se baja más despacio pero durante más tiempo: hay más
    # muestras de excéntrica que de concéntrica.
    assert (serie.fases == EXCENTRICA).sum() > (serie.fases == CONCENTRICA).sum()


# --- caída de velocidad ----------------------------------------------------


def test_serie_sin_fatiga_no_inventa_caida() -> None:
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 8, 30.0)))
    assert abs(serie.caida_velocidad) < 0.05
    assert abs(serie.caida_velocidad_pct) < 5.0


def test_serie_que_se_frena_da_pendiente_negativa() -> None:
    """Cada repetición tarda un 8 % más que la anterior en subir el mismo
    recorrido: la velocidad pico baja y la pendiente tiene que verlo."""
    altura = sintetico.senal(1.2, 8, 30.0, decaimiento=0.08)
    serie = metricas.analizar(sintetico.resultado_de(altura))

    assert serie.caida_velocidad < 0
    assert serie.caida_velocidad_pct < -15.0
    assert serie.caida_velocidad_r2 > 0.9


def test_sin_repeticiones_suficientes_no_hay_pendiente() -> None:
    """Dos puntos siempre dan una recta perfecta; llamar a eso fatiga es
    inventarse el dato."""
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 2, 30.0)))
    assert np.isnan(serie.caida_velocidad)


# --- asimetría bilateral ---------------------------------------------------


def test_desnivel_de_hombros_se_recupera() -> None:
    altura = sintetico.senal(1.2, 5, 30.0)
    puntos = sintetico.puntos_de(altura, desnivel_bu=0.12)
    serie = metricas.analizar(sintetico.resultado_de(altura, puntos=puntos))
    assert serie.desnivel_hombros_medio_bu == pytest.approx(0.12, abs=0.01)


def test_desviacion_lateral_de_la_nariz_se_recupera() -> None:
    altura = sintetico.senal(1.2, 5, 30.0)
    puntos = sintetico.puntos_de(altura, desviacion_bu=-0.20)
    serie = metricas.analizar(sintetico.resultado_de(altura, puntos=puntos))
    assert serie.desviacion_nariz_media_bu == pytest.approx(-0.20, abs=0.01)


def test_serie_simetrica_no_da_asimetria() -> None:
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 5, 30.0)))
    assert serie.desnivel_hombros_medio_bu == pytest.approx(0.0, abs=0.01)
    assert serie.desviacion_nariz_media_bu == pytest.approx(0.0, abs=0.01)


# --- escala y versión ------------------------------------------------------


def test_la_escala_es_la_anchura_biacromial() -> None:
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 4, 30.0)))
    assert serie.escala_px_bu == pytest.approx(sintetico.ESCALA_PX, rel=1e-6)


def test_la_version_distingue_muestreos() -> None:
    """Dos series con distinto `paso` no son la misma magnitud y el histórico
    tiene que poder separarlas."""
    a = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 4, 30.0), paso=1))
    b = metricas.analizar(
        sintetico.resultado_de(sintetico.senal(1.2, 4, 15.0), fps=30.0, paso=2)
    )
    assert a.version_pipeline != b.version_pipeline
    assert "nariz" in a.version_pipeline


# --- repeticiones truncadas ------------------------------------------------


def test_las_truncadas_no_entran_en_las_medias() -> None:
    """La primera y la última repetición tocan el borde de la señal: su fase
    está cortada y meterla en una media la falsea."""
    serie = metricas.analizar(sintetico.resultado_de(sintetico.senal(1.2, 6, 30.0)))
    assert serie.n_usadas < serie.n_total
    assert any(r.truncada for r in serie.repeticiones)


# --- entradas degeneradas --------------------------------------------------


def test_señal_vacia_da_error_claro() -> None:
    from contador import Resultado

    with pytest.raises(ValueError, match="señal de altura"):
        metricas.analizar(Resultado(repeticiones=[]))


def test_sin_hombros_da_error_claro() -> None:
    altura = sintetico.senal(1.2, 4, 30.0)
    puntos = sintetico.puntos_de(altura)
    puntos[:, [11, 12], :] = np.nan
    with pytest.raises(ValueError, match="hombros"):
        metricas.analizar(sintetico.resultado_de(altura, puntos=puntos))
