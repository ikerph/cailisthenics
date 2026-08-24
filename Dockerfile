# Imagen del backend. Sirve para Hugging Face Spaces (puerto 7860) y para
# cualquier sitio donde se pueda correr un contenedor.
#
# Si vas a desplegar en Oracle Cloud Always Free NO necesitas esto: allí se
# instala directamente sobre el sistema con despliegue/instalar_en_oracle.sh.

FROM python:3.11-slim

# libgl1 y libglib2.0-0 los pide OpenCV aunque sea la versión headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces recomienda no correr como root: los directorios de
# escritura pertenecen al usuario 1000.
RUN useradd -m -u 1000 cai
USER cai
ENV PATH="/home/cai/.local/bin:$PATH"

WORKDIR /code

# Solo lo que el servidor usa de verdad. `requirements-servidor.txt` ya no
# hereda de requirements.txt: eso metía gradio, 200 MB que aquí no pintan nada.
COPY --chown=cai:cai requirements-servidor.txt /code/
RUN pip install --no-cache-dir --user -r requirements-servidor.txt

COPY --chown=cai:cai contador.py metricas.py /code/
COPY --chown=cai:cai servidor /code/servidor

# El modelo se baja en el build, no se copia: `models/` está en el .gitignore,
# así que no existe en un clon limpio. Se pide con la propia función del
# contador para que baje exactamente el modelo que nombra la constante y no una
# copia que se quede desfasada. Son 5,8 MB del modelo ligero, no los 45 MB de
# los tres.
RUN python -c "import contador; contador.descargar_modelo()"

EXPOSE 7860
CMD ["uvicorn", "servidor.api:app", "--host", "0.0.0.0", "--port", "7860"]
