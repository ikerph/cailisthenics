"""La clave compartida.

Lo que se prueba aquí no es "el 401 sale cuando toca", que eso es lo fácil. Es
que no haya ninguna rendija: ni un endpoint que se olvidara de pedirla, ni un
arranque sin clave que deje el servicio abierto, ni una comparación que permita
adivinarla midiendo tiempos.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from servidor import seguridad
from servidor.api import app
from servidor.seguridad import CABECERA, ClaveNoConfigurada, clave_requerida, coincide

CLAVE = "clave-de-pruebas-larga-y-aleatoria"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv(seguridad.VARIABLE, CLAVE)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cabecera():
    return {CABECERA: CLAVE}


# --- arranque --------------------------------------------------------------


def test_sin_clave_el_servidor_no_arranca(monkeypatch) -> None:
    """Fallar cerrado. Un servidor que arranca sin clave se queda abierto a
    internet y nadie se entera hasta que alguien lo encuentra."""
    monkeypatch.delenv(seguridad.VARIABLE, raising=False)
    with pytest.raises(ClaveNoConfigurada, match="falta la variable"):
        clave_requerida()


def test_una_clave_corta_se_rechaza(monkeypatch) -> None:
    """Viaja en claro sobre HTTP y no hay límite de intentos: corta es
    adivinable, así que no se acepta."""
    monkeypatch.setenv(seguridad.VARIABLE, "1234")
    with pytest.raises(ClaveNoConfigurada, match="al menos"):
        clave_requerida()


def test_el_error_de_arranque_dice_como_generar_una(monkeypatch) -> None:
    monkeypatch.delenv(seguridad.VARIABLE, raising=False)
    with pytest.raises(ClaveNoConfigurada) as fallo:
        clave_requerida()
    assert "secrets.token_urlsafe" in str(fallo.value)


# --- comparación -----------------------------------------------------------


def test_la_comparacion_es_en_tiempo_constante() -> None:
    """Con `==`, el tiempo depende de cuántos caracteres iniciales acierten y la
    clave se adivina carácter a carácter midiendo la respuesta.

    No se mide el tiempo aquí -sería un test inestable-: se comprueba que se usa
    `hmac.compare_digest`, que es lo que da la garantía.
    """
    import inspect

    fuente = inspect.getsource(coincide)
    assert "compare_digest" in fuente

    assert coincide(CLAVE, CLAVE)
    assert not coincide("otra", CLAVE)
    assert not coincide(None, CLAVE)
    assert not coincide("", CLAVE)
    # Un prefijo correcto no vale: sujeta el caso de comparar solo el principio.
    assert not coincide(CLAVE[:-1], CLAVE)
    assert not coincide(CLAVE + "x", CLAVE)


# --- ninguna rendija -------------------------------------------------------


RUTAS = [
    ("GET", "/salud"),
    ("GET", "/estado/loquesea"),
    ("GET", "/video/loquesea"),
    ("DELETE", "/estado/loquesea"),
    ("POST", "/analizar"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
    ("GET", "/ruta/que/no/existe"),
]


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_ninguna_ruta_responde_sin_clave(cliente, metodo: str, ruta: str) -> None:
    """Incluidos `/docs` y los 404.

    Un 404 sin clave ya filtra qué rutas existen y qué no. Por eso la
    comprobación es un middleware y no una dependencia por endpoint: una
    dependencia hay que acordarse de poner, y el día que alguien añada un
    endpoint nuevo se le olvidará.
    """
    respuesta = cliente.request(metodo, ruta)
    assert respuesta.status_code == 401, f"{metodo} {ruta} respondió sin clave"
    assert respuesta.json()["error"]["codigo"] == "CLAVE_INVALIDA"


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_ninguna_ruta_acepta_una_clave_equivocada(cliente, metodo: str, ruta: str) -> None:
    respuesta = cliente.request(metodo, ruta, headers={CABECERA: "clave-incorrecta-pero-larga"})
    assert respuesta.status_code == 401


def test_con_la_clave_correcta_pasa(cliente, cabecera) -> None:
    respuesta = cliente.get("/salud", headers=cabecera)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_el_401_explica_que_hacer(cliente) -> None:
    """Un código de error a pelo no le sirve a nadie con el móvil en la mano."""
    error = cliente.get("/salud").json()["error"]
    assert "contraseña" in error["instruccion"].lower()
    assert error["reintentable"] is False


def test_salud_sirve_para_validar_la_clave(cliente, cabecera) -> None:
    """La app usa `/salud` para comprobar la contraseña antes de subir nada:
    200 es correcta, 401 es incorrecta. Sin esto habría que gastarse una subida
    de vídeo entera para descubrir que la clave estaba mal."""
    assert cliente.get("/salud", headers=cabecera).status_code == 200
    assert cliente.get("/salud", headers={CABECERA: "mal"}).status_code == 401


def test_la_clave_no_aparece_en_las_respuestas(cliente, cabecera) -> None:
    """Ni en el error ni en el cuerpo correcto: nada de devolverla por error."""
    for respuesta in (cliente.get("/salud"), cliente.get("/salud", headers=cabecera)):
        assert CLAVE not in respuesta.text


def test_el_preflight_del_navegador_pasa(cliente) -> None:
    """OPTIONS no lleva cabeceras propias. Bloquearlo rompería cualquier cliente
    web sin aportar nada: la petición real sí pasa por el middleware."""
    assert cliente.request("OPTIONS", "/salud").status_code != 401
