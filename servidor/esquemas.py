"""El JSON que sale del backend.

Se construye a mano en vez de con pydantic porque el grueso del payload son los
keypoints -(n, 33, 2) floats, del orden de un megabyte- y validarlos campo a
campo cuesta más que generarlos.

Lo que sí es innegociable es el saneado de NaN. El pipeline produce NaN por
todas partes y con motivo: un punto que MediaPipe no ve, una desviación típica
de una sola repetición, un ratio de una fase sin medir. `json.dumps` los escribe
como `NaN` a pelo, que NO es JSON válido: Python lo relee sin rechistar, y el
cliente Dart revienta con un error de parseo a mitad de la respuesta. Aquí se
convierten a `null` y se serializa con `allow_nan=False`, para que si alguno se
escapa el fallo salga en el servidor y no en el móvil de un usuario.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any

import numpy as np

from metricas import MetricasSerie


def limpiar(valor: Any) -> Any:
    """Convierte a tipos JSON, con los no finitos a `None`."""
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, (np.floating, np.integer)):
        return limpiar(valor.item())
    if isinstance(valor, np.ndarray):
        return limpiar(valor.tolist())
    if isinstance(valor, (list, tuple)):
        return [limpiar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: limpiar(v) for k, v in valor.items()}
    if is_dataclass(valor) and not isinstance(valor, type):
        return limpiar(asdict(valor))
    return valor


def a_json(payload: dict) -> bytes:
    """Serializa rechazando no finitos: si queda un NaN, se entera el servidor."""
    return json.dumps(limpiar(payload), allow_nan=False, ensure_ascii=False).encode()


def payload_analisis(
    serie: MetricasSerie,
    resultado,
    *,
    job_id: str,
    video_anotado_url: str | None,
) -> dict:
    """Todo lo que el cliente necesita para pintar el resultado y guardarlo.

    Incluye los keypoints completos aunque el cliente no los pinte: son el
    dataset, y el vídeo se borra del servidor en cuanto termina el análisis. Si
    no viajan aquí, no existen en ninguna parte.
    """
    return {
        "job_id": job_id,
        "version_pipeline": serie.version_pipeline,
        "limitaciones": serie.limitaciones,
        "video_anotado_url": video_anotado_url,
        "captura": {
            "fps": serie.fps,
            "paso": serie.paso,
            "escala_px_bu": serie.escala_px_bu,
            "recorrido_bu": serie.recorrido_bu,
        },
        # Las tres referencias que hacen falta para que el gráfico sea una
        # prueba y no un adorno: sin la barra y el umbral, la señal no dice
        # por qué una repetición contó como válida.
        "referencias": {
            "barra_y_px": resultado.barra_y_px,
            "barra_bu": resultado.barra_bu,
            "umbral_bu": resultado.umbral_bu,
            "umbral_v_bu_s": serie.umbral_v_bu_s,
        },
        "conteo": {
            "n_total": serie.n_total,
            "n_validas": serie.n_validas,
            "n_usadas": serie.n_usadas,
        },
        "serie": {
            "rom_medio_bu": serie.rom_medio_bu,
            "rom_sd_bu": serie.rom_sd_bu,
            "t_subida_media_s": serie.t_subida_media_s,
            "t_subida_sd_s": serie.t_subida_sd_s,
            "t_bajada_media_s": serie.t_bajada_media_s,
            "t_bajada_sd_s": serie.t_bajada_sd_s,
            "ratio_medio": serie.ratio_medio,
            "ratio_sd": serie.ratio_sd,
            "v_pico_media": serie.v_pico_media,
            "v_pico_sd": serie.v_pico_sd,
            "caida_velocidad": serie.caida_velocidad,
            "caida_velocidad_pct": serie.caida_velocidad_pct,
            "caida_velocidad_r2": serie.caida_velocidad_r2,
            "desnivel_hombros_medio_bu": serie.desnivel_hombros_medio_bu,
            "desnivel_hombros_sd_bu": serie.desnivel_hombros_sd_bu,
            "desviacion_nariz_media_bu": serie.desviacion_nariz_media_bu,
            "desviacion_nariz_sd_bu": serie.desviacion_nariz_sd_bu,
        },
        "repeticiones": [
            {
                "numero": r.numero,
                "instante_s": r.instante_s,
                "rom_bu": r.rom_bu,
                "t_subida_s": r.t_subida_s,
                "t_bajada_s": r.t_bajada_s,
                "ratio_ecc_con": r.ratio_ecc_con,
                "v_pico_concentrica": r.v_pico_concentrica,
                "margen_bu": r.margen_bu,
                "valida": r.valida,
                "truncada": r.truncada,
                "desnivel_hombros_bu": r.desnivel_hombros_bu,
                "desviacion_nariz_bu": r.desviacion_nariz_bu,
            }
            for r in serie.repeticiones
        ],
        "senal": {
            "tiempo_s": resultado.tiempo,
            "altura_bu": resultado.altura,
            "fases": serie.fases,
        },
        "keypoints": resultado.puntos,
    }


def payload_fallo(fallo, *, job_id: str | None = None) -> dict:
    """El error, en la forma que el cliente sabe enseñar."""
    return {
        "job_id": job_id,
        "error": {
            "codigo": fallo.codigo,
            "titulo": fallo.titulo,
            "instruccion": fallo.instruccion,
            "reintentable": fallo.reintentable,
        },
    }
