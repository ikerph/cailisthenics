"""Clave compartida: sin ella, ninguna petición pasa.

El spec descartó el login para la beta, y mientras el backend vivía en un túnel
con URL aleatoria eso era inofensivo. Con una IP pública fija y un puerto
abierto deja de serlo: un escáner encuentra el servicio en horas y puede gastar
la CPU subiendo vídeos.

Esto no es autenticación de usuarios -sigue sin haber cuentas-. Es una única
clave que el servidor conoce y la app manda en cada petición. Suficiente para
que solo entre quien tú dejes entrar, y nada más.

Lo que NO resuelve, y conviene tener claro:

- **Va en claro si el transporte va en claro.** Sobre HTTP la clave viaja
  legible, así que quien pueda leer tu tráfico la ve. Detiene a los escáneres,
  no a alguien sentado en tu misma red. La solución de verdad es HTTPS.
- **No hay caducidad ni revocación por dispositivo.** Cambiar la clave echa a
  todos los móviles a la vez.
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .errores import CLAVE_INVALIDA
from .esquemas import a_json, payload_fallo

CABECERA = "X-Cai-Clave"
"""Cabecera propia en vez de `Authorization`.

`Authorization` la reescriben o la borran algunos proxies y CDN por su cuenta, y
el fallo resultante -401 sin motivo aparente, solo a través del proxy- es de los
que cuestan una tarde. Una cabecera propia pasa intacta.
"""

VARIABLE = "CAI_CLAVE"

LONGITUD_MINIMA = 16
"""La clave viaja en claro sobre HTTP y no hay límite de intentos: corta es
adivinable. Con 16 caracteres aleatorios ya no lo es por fuerza bruta remota."""


class ClaveNoConfigurada(RuntimeError):
    """El servidor no arranca sin clave: es la única forma de no dejarlo abierto
    por olvido. Fallar cerrado, nunca abierto."""


def clave_requerida() -> str:
    """La clave del entorno, o revienta con una explicación de qué hacer."""
    clave = os.environ.get(VARIABLE, "").strip()
    if not clave:
        raise ClaveNoConfigurada(
            f"falta la variable de entorno {VARIABLE}. El servidor no arranca sin "
            "clave para no quedarse abierto a internet por descuido.\n"
            "Genera una con:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(24))"\n'
            f"y arranca con {VARIABLE}=esa_clave"
        )
    if len(clave) < LONGITUD_MINIMA:
        raise ClaveNoConfigurada(
            f"la clave de {VARIABLE} tiene {len(clave)} caracteres y hacen falta "
            f"al menos {LONGITUD_MINIMA}: viaja en claro sobre HTTP y no hay "
            "límite de intentos."
        )
    return clave


def coincide(recibida: str | None, esperada: str) -> bool:
    """Compara en tiempo constante.

    Con `==` el tiempo de comparación depende de cuántos caracteres iniciales
    acierten, y eso deja adivinar la clave carácter a carácter midiendo la
    respuesta. `compare_digest` tarda lo mismo acierte o falle.
    """
    if not recibida:
        return False
    return hmac.compare_digest(recibida, esperada)


class ExigirClave(BaseHTTPMiddleware):
    """Rechaza toda petición sin la clave correcta.

    Middleware y no dependencia de FastAPI a propósito: una dependencia hay que
    acordarse de poner en cada endpoint, y el día que alguien añada uno nuevo se
    le olvidará. Esto cubre todo lo que responda la aplicación, incluidos
    `/docs` y los 404.
    """

    async def dispatch(self, peticion: Request, siguiente):
        # Las comprobaciones previas del navegador no llevan cabeceras propias;
        # bloquearlas rompería cualquier cliente web sin aportar nada, porque la
        # petición real sí pasa por aquí.
        if peticion.method == "OPTIONS":
            return await siguiente(peticion)

        esperada = getattr(peticion.app.state, "clave", None)
        if esperada is None or not coincide(peticion.headers.get(CABECERA), esperada):
            return Response(
                content=a_json(payload_fallo(CLAVE_INVALIDA)),
                media_type="application/json",
                status_code=401,
            )
        return await siguiente(peticion)
