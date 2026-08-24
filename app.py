"""Interfaz web del contador:  python app.py

Se sube un vídeo y sale cuántas dominadas válidas hay, más una copia del vídeo
con el esqueleto y el marcador dibujados encima, lista para descargar.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr
import matplotlib

matplotlib.use("Agg")  # sin ventana: esto corre en un servidor

import matplotlib.pyplot as plt

from contador import Resultado, contar, dibujar
from servidor.api import app as fastapi_app

VERDE, ROJO, AZUL, NARANJA, GRIS = "#16a34a", "#dc2626", "#2563eb", "#ea580c", "#94a3b8"

EJEMPLOS = [[v] for v in ("opo.mp4", "fp.mp4") if Path(v).exists()]


def analizar(
    video: str | None, progreso: gr.Progress = gr.Progress()
) -> tuple[str, "plt.Figure | None", str | None]:
    """Cuenta las dominadas y devuelve ``(marcador, gráfica, vídeo anotado)``.

    La estimación de pose se lleva casi todo el tiempo y dibujar encima es
    barato, así que el vídeo anotado se genera siempre.
    """
    if not video:
        return "Sube un vídeo para empezar.", None, None
    try:
        resultado = contar(video, progreso=lambda f: progreso(0.85 * f, desc="Analizando"))
        destino = Path(tempfile.mkdtemp()) / f"{Path(video).stem}_analizado.mp4"
        anotado = str(
            dibujar(
                video,
                resultado,
                destino,
                progreso=lambda f: progreso(0.85 + 0.15 * f, desc="Dibujando"),
            )
        )
    except (ValueError, RuntimeError) as error:
        return f"### No se ha podido contar\n{error}", None, None

    marcador = "\n".join(
        [
            f"# {resultado.validas} válidas",
            f"### de {resultado.total} dominadas contadas",
            "",
            # El modelo ligero mide un poco por debajo, así que las
            # repeticiones justas caen del lado de "no válida": el número de
            # arriba se queda corto, y eso hay que decirlo donde se lee.
            "> El número de repeticiones es firme. El de válidas es conservador: "
            "las que pasan la barra por muy poco pueden contarse como cortas "
            "(margen entre paréntesis, en anchuras de hombros).",
            "",
            "| # | instante | barbilla sobre la barra |",
            "|---|---|---|",
            *(
                f"| {r.numero} | {r.instante_s:.1f} s | "
                f"{'✅ sí' if r.valida else '❌ no'} ({r.margen_bu:+.2f}) |"
                for r in resultado.repeticiones
            ),
        ]
    )
    return marcador, grafica(resultado), anotado


def grafica(resultado: Resultado) -> "plt.Figure":
    """El recorrido de la nariz a lo largo del tiempo, con lo que decide cada cosa.

    No es decoración: es la forma de comprobar el número con los ojos. Cada
    pico numerado es una repetición contada, y su color dice si la nariz llegó
    por encima de la línea de puntos, que es donde la barbilla pasa la barra.
    """
    figura, eje = plt.subplots(figsize=(9, 3.4), dpi=120)
    eje.plot(resultado.tiempo, resultado.altura, linewidth=1.5, color=AZUL, zorder=2)

    eje.axhline(
        resultado.barra_bu, color=NARANJA, linewidth=1.2,
        linestyle="--", alpha=0.5, zorder=1,
    )
    eje.axhline(resultado.umbral_bu, color=GRIS, linestyle="--", linewidth=1, zorder=1)
    # Rótulos cortos sobre las líneas, con fondo para que no los pise la señal;
    # la explicación larga va en el título, donde no tapa nada.
    fondo = {"facecolor": "white", "alpha": 0.75, "edgecolor": "none", "pad": 1}
    inicio = resultado.tiempo[0]
    eje.text(
        inicio, resultado.barra_bu, " barra", va="top", fontsize=7.5,
        color=NARANJA, bbox=fondo, zorder=4,
    )
    eje.text(
        inicio, resultado.umbral_bu, " umbral de barbilla", va="bottom", fontsize=7.5,
        color="#64748b", bbox=fondo, zorder=4,
    )

    for r in resultado.repeticiones:
        color = VERDE if r.valida else ROJO
        altura_pico = resultado.umbral_bu + r.margen_bu
        eje.plot(r.instante_s, altura_pico, "o", color=color, markersize=4, zorder=3)
        eje.annotate(
            str(r.numero),
            xy=(r.instante_s, altura_pico),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=color,
        )

    eje.set_xlabel("tiempo (s)")
    eje.set_ylabel("altura de la nariz\n(anchuras de hombros)")
    eje.set_title(
        f"{resultado.total} repeticiones, {resultado.validas} válidas — la nariz "
        "tiene que pasar la línea de puntos, porque la barbilla va por detrás",
        fontsize=9,
        color="#475569",
    )
    eje.margins(x=0.01, y=0.16)
    eje.spines[["top", "right"]].set_visible(False)
    figura.tight_layout()
    return figura


def construir() -> gr.Blocks:
    """Monta la interfaz."""
    with gr.Blocks(title="Contador de dominadas") as demo:
        gr.Markdown(
            "# Contador de dominadas\n"
            "Vídeo de frente, agarre prono, el sujeto entero en el encuadre. "
            "El tramo de la serie lo encuentra solo."
        )
        with gr.Row():
            with gr.Column():
                video = gr.Video(label="Vídeo", sources=["upload"])
                boton = gr.Button("Contar", variant="primary")
                if EJEMPLOS:
                    gr.Examples(EJEMPLOS, inputs=[video], label="Ejemplos")
            with gr.Column():
                salida = gr.Markdown("# —")
                trazo = gr.Plot(label="Recorrido de la nariz")
                anotado = gr.Video(label="Vídeo analizado (descargable)", interactive=False)
        boton.click(analizar, video, [salida, trazo, anotado])
    return demo


demo = construir()
app = gr.mount_gradio_app(fastapi_app, demo, path="/web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
