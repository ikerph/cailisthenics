"""Errores tipados: de un `ValueError` del contador a algo que el usuario pueda hacer.

Un stack trace no le sirve a nadie que esté en un parque con el móvil en la
mano. Cada fallo conocido del pipeline se traduce a un código estable -que el
cliente puede traducir- y a una instrucción concreta: qué hacer para que la
próxima vez salga.

El acoplamiento es feo a propósito y está a la vista: se reconoce el fallo por
un trozo del texto del mensaje. Lo correcto sería que `contador` lanzase
excepciones tipadas, pero eso es cirugía en el módulo que ya funciona. Lo que
sujeta esto es `tests/test_errores.py`, que provoca de verdad cada `ValueError`
del contador y comprueba que ninguno cae en `DESCONOCIDO`. Si alguien reescribe
un mensaje, el test se cae antes que el cliente.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fallo:
    """Un fallo que el cliente puede explicar y el usuario puede arreglar."""

    codigo: str
    titulo: str
    instruccion: str
    """Qué hacer distinto. Siempre una acción, nunca un diagnóstico."""

    reintentable: bool = True
    """False cuando volver a subir el mismo vídeo dará exactamente lo mismo."""


CATALOGO: tuple[tuple[str, Fallo], ...] = (
    (
        "no se ven las muñecas",
        Fallo(
            "MUNECAS_NO_VISIBLES",
            "No se ven las manos en la barra",
            "La barra es la recta que une las dos muñecas, y sin ellas no hay "
            "referencia. Graba de frente, con los brazos enteros dentro del "
            "encuadre desde el principio.",
        ),
    ),
    (
        "no se ve la nariz",
        Fallo(
            "NARIZ_NO_VISIBLE",
            "No se ve la cara",
            "Se sigue la nariz para medir la altura. Quita la gorra o la capucha "
            "si tapan la cara y comprueba que la cabeza no se sale por arriba.",
        ),
    ),
    (
        "no se ven los dos hombros",
        Fallo(
            "HOMBROS_NO_VISIBLES",
            "No se ven los dos hombros",
            "La anchura de hombros es la regla de medir. Graba de frente y sin "
            "ropa muy holgada que difumine la silueta.",
        ),
    ),
    (
        "en ningún frame se ven las dos manos por encima de los hombros",
        Fallo(
            "NO_SE_CUELGA",
            "No se te ve colgado de la barra",
            "Hace falta ver el cuerpo entero con las dos manos agarradas por "
            "encima de los hombros. Aléjate hasta que quepas entero y vuelve a "
            "grabar.",
        ),
    ),
    (
        "el tramo colgado más largo dura",
        Fallo(
            "TRAMO_CORTO",
            "La serie es demasiado corta",
            "Hacen falta al menos 3 segundos seguidos colgado. Empieza a grabar "
            "antes de subirte y para después de bajarte.",
        ),
    ),
    (
        "la nariz solo recorre",
        Fallo(
            "RECORRIDO_INSUFICIENTE",
            "El recorrido es demasiado corto",
            "El movimiento no llega a parecer una dominada: puede ser que no "
            "bajes a brazos estirados, o que la cámara esté tan lejos que el "
            "recorrido se pierda. Acércate y baja del todo entre repeticiones.",
        ),
    ),
    (
        "no se puede abrir el vídeo",
        Fallo(
            "VIDEO_ILEGIBLE",
            "No se puede leer el vídeo",
            "El fichero está corrupto o en un formato que no se reconoce. "
            "Vuelve a grabar y sube un MP4.",
            reintentable=False,
        ),
    ),
    (
        "fps inválido",
        Fallo(
            "FPS_INVALIDO",
            "El vídeo no declara su velocidad",
            "Sin fps no se pueden medir tiempos. Graba con la cámara del móvil "
            "en vez de exportar desde otra aplicación.",
            reintentable=False,
        ),
    ),
    (
        "no tiene ningún frame",
        Fallo(
            "VIDEO_VACIO",
            "El vídeo está vacío",
            "No llegó ninguna imagen. Comprueba que la grabación se guardó antes "
            "de subirla.",
            reintentable=False,
        ),
    ),
    (
        "no trae señal de altura",
        Fallo(
            "SIN_SENAL",
            "No se pudo construir la señal",
            "Se detectó a alguien colgado pero no hay suficiente movimiento que "
            "medir. Comprueba que se te ve entero durante toda la serie.",
        ),
    ),
    (
        "no trae keypoints",
        Fallo(
            "SIN_SENAL",
            "No se pudo construir la señal",
            "Se detectó a alguien colgado pero no hay suficiente movimiento que "
            "medir. Comprueba que se te ve entero durante toda la serie.",
        ),
    ),
)
"""Trozo de mensaje -> fallo. El orden importa: gana el primero que encaje."""


DESCONOCIDO = Fallo(
    "DESCONOCIDO",
    "No se pudo analizar el vídeo",
    "Algo falló al procesar. Prueba con otra grabación: cuerpo entero, de "
    "frente, buena luz y nadie más en el encuadre.",
)


VIDEO_DEMASIADO_GRANDE = Fallo(
    "VIDEO_DEMASIADO_GRANDE",
    "El vídeo pesa demasiado",
    "Graba series de menos de un minuto. Un vídeo más largo no mejora la "
    "medida y tarda mucho en subir.",
    reintentable=False,
)

FORMATO_NO_SOPORTADO = Fallo(
    "FORMATO_NO_SOPORTADO",
    "Formato de vídeo no soportado",
    "Sube un MP4 grabado con la cámara del móvil.",
    reintentable=False,
)

CLAVE_INVALIDA = Fallo(
    "CLAVE_INVALIDA",
    "Contraseña del servidor incorrecta",
    "El servidor solo acepta peticiones con la contraseña correcta. Revísala en "
    "los ajustes de servidor de la app: tiene que ser exactamente la misma que "
    "se configuró al instalar el backend.",
    reintentable=False,
)

TRABAJO_NO_ENCONTRADO = Fallo(
    "TRABAJO_NO_ENCONTRADO",
    "Ese análisis ya no existe",
    "Los resultados se borran del servidor al poco de entregarse. Vuelve a "
    "subir el vídeo.",
    reintentable=False,
)

SIN_VIDEO_ANOTADO = Fallo(
    "SIN_VIDEO_ANOTADO",
    "No hay vídeo anotado",
    "Este análisis se pidió sin vídeo anotado, o el vídeo ya se borró del "
    "servidor.",
    reintentable=False,
)


def clasificar(error: Exception) -> Fallo:
    """El `Fallo` que corresponde a una excepción del pipeline.

    Solo se traducen los `ValueError`: son los que el contador usa para decir
    "aquí no hay nadie haciendo dominadas". Cualquier otra excepción es un bug
    nuestro y no se le disfraza de consejo al usuario.
    """
    if isinstance(error, ValueError):
        texto = str(error).lower()
        for trozo, fallo in CATALOGO:
            if trozo.lower() in texto:
                return fallo
    return DESCONOCIDO
