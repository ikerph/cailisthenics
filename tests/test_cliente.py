"""FASE 4: lo del cliente que se puede comprobar desde Python.

No hay SDK de Flutter en esta máquina, así que el Dart no se compila aquí. Lo
que sí se puede sujetar es el CONTRATO entre las dos mitades, que es donde de
verdad se rompen las cosas: el esquema duplicado en los assets, los nombres de
los campos del JSON y las columnas de la base de datos del móvil.

Esto no sustituye a compilar el cliente. Sustituye a descubrir en un dispositivo
que el backend manda `caida_velocidad` y el cliente lee `caida_velicidad`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import metricas
from servidor.esquemas import a_json, payload_analisis
from tests import sintetico

RAIZ = Path(__file__).resolve().parent.parent
ESQUEMA = RAIZ / "esquema" / "001_inicial.sql"
ESQUEMA_CLIENTE = RAIZ / "cliente" / "assets" / "esquema" / "001_inicial.sql"
ALMACEN = RAIZ / "cliente" / "lib" / "datos" / "almacen.dart"
MODELO = RAIZ / "cliente" / "lib" / "modelo" / "analisis.dart"


def payload_de_ejemplo() -> dict:
    """Un payload real del backend, con todos sus campos."""
    altura = sintetico.senal(1.4, 6, 30.0)
    resultado = sintetico.resultado_de(altura)
    serie = metricas.analizar(resultado)
    return json.loads(
        a_json(
            payload_analisis(
                serie, resultado, job_id="x", video_anotado_url="http://x/video/x"
            )
        )
    )


def claves_de(valor, acumulador: set[str]) -> set[str]:
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            acumulador.add(clave)
            claves_de(contenido, acumulador)
    elif isinstance(valor, list) and valor:
        claves_de(valor[0], acumulador)
    return acumulador


# --- el esquema duplicado --------------------------------------------------


def test_el_esquema_del_cliente_no_ha_divergido() -> None:
    """El asset es copia del fichero de la raíz y tiene que serlo byte a byte.

    Es una copia porque Flutter solo empaqueta assets de dentro del paquete. El
    día que alguien toque uno y no el otro, el cliente creará una base de datos
    distinta de la que se ha probado, y eso se descubre en un dispositivo.
    """
    assert ESQUEMA_CLIENTE.exists(), (
        "falta cliente/assets/esquema/001_inicial.sql: cópialo de esquema/"
    )
    assert ESQUEMA_CLIENTE.read_bytes() == ESQUEMA.read_bytes(), (
        "el esquema del cliente y el de la raíz han divergido; copia el de la "
        "raíz a cliente/assets/esquema/"
    )


# --- contrato con la base de datos -----------------------------------------


def columnas_de(tabla: str) -> set[str]:
    conexion = sqlite3.connect(":memory:")
    conexion.executescript(ESQUEMA.read_text(encoding="utf-8"))
    filas = conexion.execute(f"PRAGMA table_info({tabla})").fetchall()
    conexion.close()
    return {f[1] for f in filas}


def campos_insertados(tabla: str) -> set[str]:
    """Las claves del mapa que el cliente pasa a `insert('<tabla>', {...})`."""
    fuente = ALMACEN.read_text(encoding="utf-8")
    inicio = fuente.find(f"insert('{tabla}', {{")
    assert inicio != -1, f"el cliente no inserta en {tabla}"
    fin = fuente.find("});", inicio)
    bloque = fuente[inicio:fin]
    return set(re.findall(r"'([a-z_]+)':", bloque))


def test_el_cliente_inserta_en_columnas_que_existen() -> None:
    for tabla in ("serie", "repeticion"):
        columnas = columnas_de(tabla)
        campos = campos_insertados(tabla)
        sobrantes = campos - columnas
        assert not sobrantes, (
            f"el cliente escribe en columnas que no existen en {tabla}: {sobrantes}"
        )


def test_el_cliente_guarda_la_version_del_pipeline() -> None:
    """La columna es NOT NULL y es la que impide mezclar dos reglas de medir.
    Si el cliente dejara de escribirla, el insert fallaría en el móvil."""
    assert "version_pipeline" in campos_insertados("serie")


def test_el_cliente_guarda_todas_las_metricas_por_repeticion() -> None:
    """Persistencia rep a rep: si el cliente se dejara un campo, el dato no se
    recupera después ni reprocesando, porque el vídeo ya no existe."""
    campos = campos_insertados("repeticion")
    for esperado in (
        "numero",
        "instante_s",
        "rom_bu",
        "t_subida_s",
        "t_bajada_s",
        "ratio_ecc_con",
        "v_pico_concentrica",
        "margen_bu",
        "valida",
        "truncada",
    ):
        assert esperado in campos, f"el cliente no guarda {esperado}"


# --- contrato con el JSON del backend --------------------------------------


def test_el_cliente_lee_claves_que_el_backend_manda() -> None:
    """Cada `json['...']` del modelo Dart tiene que existir en el payload."""
    fuente = MODELO.read_text(encoding="utf-8")
    leidas = set(re.findall(r"json\['([a-z_0-9]+)'\]", fuente))
    assert leidas, "no se encontró ninguna lectura de JSON en el modelo Dart"

    disponibles = claves_de(payload_de_ejemplo(), set())
    # `codigo`, `titulo`, `instruccion` y `reintentable` vienen del payload de
    # error, que es otro camino y no está en el de análisis.
    del_error = {"codigo", "titulo", "instruccion", "reintentable"}

    huerfanas = leidas - disponibles - del_error
    assert not huerfanas, (
        f"el cliente lee claves que el backend no manda: {sorted(huerfanas)}"
    )


def test_el_backend_manda_lo_que_la_base_de_datos_necesita() -> None:
    """Las columnas que el cliente rellena tienen que poder salir del payload."""
    payload = payload_de_ejemplo()
    assert payload["version_pipeline"]
    assert payload["captura"]["escala_px_bu"] is not None
    assert payload["conteo"]["n_total"] > 0
    assert payload["repeticiones"]
    assert payload["serie"]["caida_velocidad"] is not None


def test_las_limitaciones_viajan_con_el_analisis() -> None:
    """El banner que la app enseña siempre sale del backend, no de una cadena
    escrita en Dart: el día que cambie el método, cambia en un solo sitio."""
    payload = payload_de_ejemplo()
    assert payload["limitaciones"] == metricas.LIMITACIONES
    assert "nariz" in payload["limitaciones"]

    fuente = MODELO.read_text(encoding="utf-8")
    assert "json['limitaciones']" in fuente
