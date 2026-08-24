"""FASE 3: el esquema SQLite.

El esquema se ejecuta en el móvil de la gente, donde una migración cuesta una
release y un porcentaje de usuarios que no actualizan. Así que se prueba aquí,
contra el mismo SQLite que hay en Android, antes de que llegue a ningún sitio.

Lo que se comprueba no es "el CREATE TABLE no da error", que eso lo hace solo:
es que las garantías en las que se va a confiar existen de verdad. Sobre todo
el CASCADE, que sin `PRAGMA foreign_keys = ON` no falla -deja huérfanas y sigue
como si nada-.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

ESQUEMA = Path(__file__).resolve().parent.parent / "esquema" / "001_inicial.sql"


def abrir(ruta: str = ":memory:") -> sqlite3.Connection:
    """Una conexión con el esquema puesto, como la abre el cliente."""
    conexion = sqlite3.connect(ruta)
    conexion.executescript(ESQUEMA.read_text(encoding="utf-8"))
    # Por conexión, no por base: `executescript` ya lo trae, pero el cliente
    # abre conexiones nuevas y este es el recordatorio de que hay que repetirlo.
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def serie_de_prueba(conexion: sqlite3.Connection, n_reps: int = 5, **campos) -> int:
    valores = {
        "device_id": "dispositivo-1",
        "fecha_utc": "2026-08-22T10:00:00Z",
        "fps": 30.0,
        "paso": 2,
        "escala_px_bu": 50.1,
        "recorrido_bu": 2.14,
        "n_total": n_reps,
        "n_validas": n_reps,
        "caida_velocidad": -0.061,
        "notas": None,
        "keypoints_json_path": "series/1.json",
        "version_pipeline": "m1-nariz-lite-p2-margen0.40-corte3.0",
    }
    valores.update(campos)
    columnas = ", ".join(valores)
    marcas = ", ".join("?" * len(valores))
    cursor = conexion.execute(
        f"INSERT INTO serie ({columnas}) VALUES ({marcas})", tuple(valores.values())
    )
    serie_id = cursor.lastrowid
    conexion.executemany(
        "INSERT INTO repeticion (serie_id, numero, instante_s, rom_bu, t_subida_s,"
        " t_bajada_s, ratio_ecc_con, v_pico_concentrica, margen_bu, valida, truncada)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (serie_id, i + 1, 8.0 + 2.7 * i, 2.0, 0.9, 0.65, 0.72, 3.5 - 0.06 * i, 0.3, 1,
             1 if i in (0, n_reps - 1) else 0)
            for i in range(n_reps)
        ],
    )
    conexion.commit()
    return serie_id


# --- integridad ------------------------------------------------------------


def test_borrar_una_serie_se_lleva_sus_repeticiones() -> None:
    """El CASCADE del spec, comprobado.

    Sin `PRAGMA foreign_keys = ON` esto no falla: deja las repeticiones
    huérfanas, y el histórico empieza a sumar repeticiones de series que el
    usuario cree haber borrado.
    """
    conexion = abrir()
    serie_id = serie_de_prueba(conexion, 5)
    assert conexion.execute("SELECT COUNT(*) FROM repeticion").fetchone()[0] == 5

    conexion.execute("DELETE FROM serie WHERE id = ?", (serie_id,))
    conexion.commit()
    assert conexion.execute("SELECT COUNT(*) FROM repeticion").fetchone()[0] == 0


def test_sin_el_pragma_el_cascade_no_hace_nada() -> None:
    """Prueba de que el pragma es el que sostiene la integridad, no el DDL.

    Está aquí para que nadie lo quite del cliente pensando que es cosmético.
    """
    conexion = sqlite3.connect(":memory:")
    conexion.executescript(ESQUEMA.read_text(encoding="utf-8"))
    conexion.execute("PRAGMA foreign_keys = OFF")
    serie_id = serie_de_prueba(conexion, 3)

    conexion.execute("DELETE FROM serie WHERE id = ?", (serie_id,))
    conexion.commit()
    assert conexion.execute("SELECT COUNT(*) FROM repeticion").fetchone()[0] == 3


def test_no_se_puede_guardar_una_repeticion_sin_serie() -> None:
    conexion = abrir()
    with pytest.raises(sqlite3.IntegrityError):
        conexion.execute(
            "INSERT INTO repeticion (serie_id, numero, valida) VALUES (999, 1, 1)"
        )


def test_no_se_repite_el_numero_dentro_de_una_serie() -> None:
    """Sujeta el reintento del cliente: si guarda dos veces el mismo análisis,
    la segunda choca en vez de duplicar la serie."""
    conexion = abrir()
    serie_id = serie_de_prueba(conexion, 3)
    with pytest.raises(sqlite3.IntegrityError):
        conexion.execute(
            "INSERT INTO repeticion (serie_id, numero, valida) VALUES (?, 1, 1)",
            (serie_id,),
        )


def test_la_version_del_pipeline_es_obligatoria() -> None:
    """Es la columna que permite no mezclar dos reglas de medir. Si fuese
    opcional, el primer sitio donde se olvidaría sería el propio cliente."""
    conexion = abrir()
    with pytest.raises(sqlite3.IntegrityError):
        conexion.execute(
            "INSERT INTO serie (device_id, fecha_utc) VALUES ('d', '2026-01-01T00:00:00Z')"
        )


# --- lo que el esquema tiene que permitir preguntar -------------------------


def test_los_agregados_se_recalculan_desde_las_repeticiones() -> None:
    """La razón de guardar rep a rep: preguntas que no se previeron al diseñar.

    Aquí, el ratio medio de las TRES ÚLTIMAS repeticiones de cada serie. Con
    agregados por serie esa pregunta no tendría respuesta.
    """
    conexion = abrir()
    serie_de_prueba(conexion, 8)
    fila = conexion.execute(
        """
        SELECT AVG(ratio_ecc_con) FROM (
            SELECT ratio_ecc_con FROM repeticion
            WHERE serie_id = 1 ORDER BY numero DESC LIMIT 3
        )
        """
    ).fetchone()
    assert fila[0] == pytest.approx(0.72)


def test_el_historico_sale_ordenado_y_separado_por_version() -> None:
    """Dos pipelines distintos no se mezclan en el mismo gráfico."""
    conexion = abrir()
    serie_de_prueba(conexion, 3, fecha_utc="2026-08-01T10:00:00Z", version_pipeline="m1-nariz-lite-p2")
    serie_de_prueba(conexion, 3, fecha_utc="2026-08-15T10:00:00Z", version_pipeline="m1-nariz-lite-p2")
    serie_de_prueba(conexion, 3, fecha_utc="2026-08-20T10:00:00Z", version_pipeline="m2-barbilla-lite-p2")

    filas = conexion.execute(
        "SELECT fecha_utc, version_pipeline FROM serie"
        " WHERE device_id = ? ORDER BY fecha_utc DESC",
        ("dispositivo-1",),
    ).fetchall()
    assert [f[0] for f in filas] == [
        "2026-08-20T10:00:00Z",
        "2026-08-15T10:00:00Z",
        "2026-08-01T10:00:00Z",
    ]
    assert len({f[1] for f in filas}) == 2


def test_la_escala_biacromial_se_puede_comparar_entre_sesiones() -> None:
    """La advertencia de FASE 4: si la escala varía mucho, lo que cambió fue la
    distancia a la cámara, no el atleta."""
    conexion = abrir()
    serie_de_prueba(conexion, 3, fecha_utc="2026-08-01T10:00:00Z", escala_px_bu=50.0)
    serie_de_prueba(conexion, 3, fecha_utc="2026-08-15T10:00:00Z", escala_px_bu=91.0)

    escalas = [
        f[0]
        for f in conexion.execute(
            "SELECT escala_px_bu FROM serie ORDER BY fecha_utc"
        ).fetchall()
    ]
    variacion = abs(escalas[1] - escalas[0]) / escalas[0]
    assert variacion > 0.15


def test_las_truncadas_sobreviven_a_guardar_y_releer() -> None:
    """Sin esta columna, la media del histórico y la del resultado difieren.

    Una repetición pegada al borde del vídeo tiene la fase cortada y el análisis
    la deja fuera de las medias. Si al guardarla se perdiera esa marca, al
    releer la serie volvería a contar y el mismo día saldría con dos ratios
    distintos según la pantalla, sin que nada avisara.
    """
    conexion = abrir()
    serie_de_prueba(conexion, 6)

    marcadas = conexion.execute(
        "SELECT numero FROM repeticion WHERE truncada = 1 ORDER BY numero"
    ).fetchall()
    assert [f[0] for f in marcadas] == [1, 6]

    media_todas = conexion.execute(
        "SELECT AVG(ratio_ecc_con) FROM repeticion"
    ).fetchone()[0]
    media_usables = conexion.execute(
        "SELECT AVG(ratio_ecc_con) FROM repeticion WHERE truncada = 0"
    ).fetchone()[0]
    assert media_todas is not None and media_usables is not None


def test_truncada_tiene_valor_por_defecto() -> None:
    """Un insert que no la mencione no puede fallar: es NOT NULL con DEFAULT."""
    conexion = abrir()
    serie_de_prueba(conexion, 3)
    conexion.execute(
        "INSERT INTO repeticion (serie_id, numero, valida) VALUES (1, 99, 1)"
    )
    assert (
        conexion.execute(
            "SELECT truncada FROM repeticion WHERE numero = 99"
        ).fetchone()[0]
        == 0
    )


# --- índices y versión -----------------------------------------------------


def test_la_consulta_del_historico_usa_el_indice() -> None:
    """Sin índice esto es un recorrido completo en cada apertura de la app."""
    conexion = abrir()
    serie_de_prueba(conexion, 3)
    plan = conexion.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM serie WHERE device_id = ?"
        " ORDER BY fecha_utc DESC",
        ("dispositivo-1",),
    ).fetchall()
    assert any("idx_serie_device_fecha" in str(paso) for paso in plan), plan


def test_el_esquema_declara_su_version() -> None:
    conexion = abrir()
    assert conexion.execute("SELECT MAX(version) FROM version_esquema").fetchone()[0] == 1


def test_aplicar_el_esquema_dos_veces_no_rompe_nada() -> None:
    """El cliente lo ejecuta en cada arranque: tiene que ser idempotente."""
    ruta = ":memory:"
    conexion = abrir(ruta)
    serie_de_prueba(conexion, 3)
    conexion.executescript(ESQUEMA.read_text(encoding="utf-8"))
    assert conexion.execute("SELECT COUNT(*) FROM repeticion").fetchone()[0] == 3
    assert conexion.execute("SELECT COUNT(*) FROM version_esquema").fetchone()[0] == 1
