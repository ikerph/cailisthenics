"""Deja el proyecto Flutter listo para correr en un Android.

`flutter create` genera las carpetas de plataforma pero NO pone los permisos de
cámara ni el permiso de tráfico sin cifrar, y sin ellos la app compila, arranca y
falla al abrir la cámara con un error genérico que no dice qué falta.

Este script es idempotente: se puede ejecutar las veces que haga falta, después
de cada `flutter create`, y no duplica nada.

    python cliente/preparar_android.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLIENTE = Path(__file__).resolve().parent
MANIFIESTO = CLIENTE / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
PLIST = CLIENTE / "ios" / "Runner" / "Info.plist"

PERMISOS = (
    ("android.permission.CAMERA", "grabar la serie"),
    ("android.permission.INTERNET", "subir el vídeo al servidor"),
)


def parchear_manifiesto() -> list[str]:
    """Permisos de cámara e internet, y tráfico sin cifrar para el backend local."""
    if not MANIFIESTO.exists():
        raise SystemExit(
            f"no existe {MANIFIESTO}\n"
            "Ejecuta antes:  cd cliente && flutter create --platforms=android,ios ."
        )

    texto = MANIFIESTO.read_text(encoding="utf-8")
    cambios: list[str] = []

    # Los permisos van DENTRO de <manifest>, justo detrás de su etiqueta de
    # apertura, que trae atributos y puede ocupar varias líneas.
    apertura = re.search(r"<manifest\b[^>]*>", texto)
    if apertura is None:
        raise SystemExit(f"{MANIFIESTO} no parece un AndroidManifest válido")

    faltan = [(p, m) for p, m in PERMISOS if p not in texto]
    if faltan:
        bloque = "".join(
            f'\n    <!-- {motivo} -->\n'
            f'    <uses-permission android:name="{permiso}" />'
            for permiso, motivo in faltan
        )
        corte = apertura.end()
        texto = texto[:corte] + bloque + texto[corte:]
        cambios += [f"permiso {permiso}" for permiso, _ in faltan]

    # Android 9+ bloquea HTTP sin cifrar. Mientras el backend sea local y sin
    # HTTPS hace falta permitirlo; hay que quitarlo antes de publicar nada.
    if "usesCleartextTraffic" not in texto:
        texto = re.sub(
            r"(<application\b)",
            r'\1\n        android:usesCleartextTraffic="true"',
            texto,
            count=1,
        )
        cambios.append("usesCleartextTraffic (backend local sin HTTPS)")

    if cambios:
        MANIFIESTO.write_text(texto, encoding="utf-8")
    return cambios


def parchear_plist() -> list[str]:
    """El texto que iOS enseña al pedir la cámara. Sin él, la app se cierra."""
    if not PLIST.exists():
        return []
    texto = PLIST.read_text(encoding="utf-8")
    if "NSCameraUsageDescription" in texto:
        return []
    texto = texto.replace(
        "</dict>",
        "\t<key>NSCameraUsageDescription</key>\n"
        "\t<string>Para grabar la serie de dominadas que se va a analizar.</string>\n"
        "</dict>",
        1,
    )
    PLIST.write_text(texto, encoding="utf-8")
    return ["NSCameraUsageDescription"]


def main() -> int:
    cambios = parchear_manifiesto() + parchear_plist()
    if cambios:
        print("Aplicado:")
        for cambio in cambios:
            print(f"  + {cambio}")
    else:
        print("Ya estaba todo puesto.")

    print()
    print("Comprueba el manifiesto:")
    print(f"  {MANIFIESTO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
