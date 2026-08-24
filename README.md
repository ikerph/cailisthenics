# Contador de dominadas

Subes un vídeo de móvil y te dice cuántas dominadas has hecho y cuántas son
válidas. Sin sensores, sin marcadores y sin entrenar nada.

```bash
pip install -r requirements.txt
python app.py            # abre http://127.0.0.1:7860
```

La primera ejecución descarga el modelo de pose a `models/`. Un vídeo de un
minuto tarda unos veinte segundos en un portátil sin GPU, casi todo en la
estimación de pose.

Devuelve tres cosas: el número, la gráfica del recorrido de la nariz a lo largo
del tiempo —cada pico numerado es una repetición, verde si vale y rojo si se
quedó corta— y una copia del vídeo, descargable, con el esqueleto dibujado
encima, la línea de la barra y el marcador *realizadas | válidas* en una banda
arriba. La línea naranja es la comprobación más útil de todas: tiene que caer
sobre la barra que se ve en la imagen, y si no cae, la medida está mal y el
número no vale. Sirve para
comprobar de un vistazo que el modelo sigue al sujeto y no a alguien que pasa por
el fondo: el esqueleto entero va apagado y encendidos los cinco puntos que el
contador usa de verdad. Se escribe en H.264 dentro de un MP4, mandando los frames por
una tubería al ffmpeg que trae `imageio-ffmpeg` en el propio entorno de Python:
no hay que instalar nada en el sistema y sale un vídeo que se reproduce dentro
de la página, no solo descargable. Lo que OpenCV sabe escribir por su cuenta
depende de con qué códecs venga compilado, y en Windows normalmente no trae
H.264; además acepta el fourcc `avc1` y devuelve `isOpened() == True` aunque el
codificador no haya cargado, así que el fallo no se ve hasta que el navegador
se niega a reproducir. Si no hubiera ffmpeg se recurre a VP8 en WebM, que OpenCV
sí escribe bien.

## Precisión

Se analiza con el modelo de pose **ligero** y **uno de cada dos frames**. Las dos
decisiones van juntas en el código, en `MODELO` y `PASO`, y no cuestan lo mismo.

Saltar frames sale gratis: una dominada son 0,25-0,7 Hz y a 15 Hz de muestreo la
señal sigue dos órdenes de magnitud por debajo del límite de Nyquist, así que con
el mismo modelo el veredicto es idéntico en los tres vídeos —los márgenes se
mueven menos de 0,05 anchuras de hombros— al doble de velocidad.

El modelo ligero no sale gratis. Cuenta las mismas repeticiones que el pesado en
los tres vídeos, 3, 7 y 18, y tarda una quinta parte, pero sitúa la nariz
sistemáticamente entre 0,06 y 0,17 anchuras de hombros más abajo respecto a la
recta de las manos. No es ruido que el filtro quite: es un sesgo, y se lleva por
delante las repeticiones que pasaban la barra por poco.

**El número de repeticiones es firme; el de válidas es conservador.** En
`fp.mp4`, el vídeo con repeticiones al límite, el modelo pesado da las 5 válidas
etiquetadas a mano y el ligero da 3. Para recuperar ese veredicto se cambia
`MODELO` a `"heavy"` en `contador.py`; cuesta unos cinco veces más de tiempo.

Medido en este portátil, sin GPU:

| vídeo | `heavy` | `lite` (actual) | repeticiones | válidas |
|---|---|---|---|---|
| bandicam (12 s) | 19 s | 3 s | 3 = 3 | 3 = 3 |
| fp (45 s) | 83 s | 15 s | 7 = 7 | 5 → 3 |
| opo (60 s) | 106 s | 20 s | 18 = 18 | 18 = 18 |

## Cómo funciona

```
vídeo ──► pose ──► tramo colgado ──► señal ──► picos ──► número
```

**1. Pose.** MediaPipe devuelve 33 puntos por frame. Solo hacen falta cinco: la
nariz, los dos hombros y las dos muñecas.

**2. El tramo se detecta solo.** Mientras las dos muñecas estén por encima de los
hombros, el sujeto está agarrado a la barra. Eso se cumple durante toda la
dominada —por muy alto que suba, los hombros nunca pasan de las manos— y no se
cumple andando hacia la barra ni recogiendo el móvil.

**3. La nariz, no la barbilla.** El estándar es "barbilla por encima de la
barra", pero arriba la barra tapa la cara justo cuando haría falta verla. La
nariz está un poco más arriba y se ve durante todo el recorrido.

**4. Anchuras de hombros como unidad.** La altura de la nariz se divide por la
separación entre los hombros del propio sujeto, así el mismo umbral vale para un
vídeo en 4K y para uno en 480p, de cerca o desde el fondo del gimnasio.

**5. Filtro de fase cero.** Butterworth paso bajo hacia delante y hacia atrás
(`filtfilt`): un filtro normal retrasaría la señal y movería los picos.

**6. Contar picos por prominencia.** Una dominada es un pico cuya *prominencia*
—lo que hay que bajar desde él antes de subir a otro más alto— supera el 40% del
recorrido típico del sujeto en ese vídeo.

Contar cruces de una altura fija parece lo obvio y falla de dos maneras
opuestas: quien se queda temblando a media altura suma un cruce por temblor, y
quien no extiende los brazos entre repeticiones nunca baja del umbral de rearme y
deja de sumar a partir de la segunda. La prominencia mira cuánto destaca cada
pico de sus propios valles y resuelve los dos casos con un solo número.

**7. Válida = la barbilla pasó la barra.** La barra es la recta que une las dos
muñecas: las manos están agarradas a ella, no hace falta buscarla en la imagen.
La nariz tiene que superarla por 0,40 anchuras de hombros: 0,20 porque el
keypoint de muñeca cae por debajo de la barra y otros 0,20 porque la barbilla va
por detrás de la nariz.

## Estructura

```
contador.py                 vídeo -> repeticiones. La base de todo.
metricas.py                 FASE 1: fases por velocidad y métricas de serie
servidor/                   FASE 2: backend FastAPI
  api.py                    POST /analizar, GET /estado/{job}, GET /video/{job}
  trabajos.py               cola con hilos; borra el vídeo tras procesar
  errores.py                ValueError -> código + instrucción para el usuario
  anotado.py                vídeo anotado a 720p
  esquemas.py               el JSON, con el saneado de NaN
esquema/001_inicial.sql     FASE 3: histórico SQLite (vive en el dispositivo)
cliente/                    FASE 4: app Flutter (SIN COMPILAR, ver su README)
experimentos/fase0_paso.py  FASE 0: el experimento que decidió PASO=2
tests/                      55 tests
app.py                      la demo de Gradio original
```

### Arrancar el backend

```bash
pip install -r requirements-servidor.txt
uvicorn servidor.api:app --host 0.0.0.0 --port 8000
```

El vídeo se borra del servidor en cuanto termina el análisis, salga bien o mal.
Lo que vuelve —keypoints y métricas— se guarda en el móvil. Eso quita de en
medio la mayor parte del problema de datos personales: lo que no está guardado
no hay que protegerlo ni explicarlo en una política de privacidad.

### Los tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Tres de ellos hacen más trabajo del que parece:

- `test_todos_los_valueerror_estan_clasificados` lee los `raise ValueError` del
  AST de `contador.py` y comprueba que ninguno llega al usuario como "algo
  falló". Si alguien reescribe un mensaje, se cae aquí y no en un móvil.
- `test_sin_el_pragma_el_cascade_no_hace_nada` demuestra que `PRAGMA
  foreign_keys = ON` es lo que sostiene la integridad del histórico. Sin él, el
  `ON DELETE CASCADE` no falla: deja repeticiones huérfanas.
- `test_el_esquema_del_cliente_no_ha_divergido` compara byte a byte el SQL de
  `esquema/` con su copia en los assets de Flutter.

Para analizar con otro modelo o otro paso sin tocar las constantes se salta
`contar` y se llaman las dos piezas por separado:

```python
puntos, detectado, fps = extraer_pose(video, modelo="heavy", paso=1)
resultado = contar_puntos(puntos, detectado, fps, paso=1)
```

Comprobado contra tres vídeos anotados a mano: 3/3, 7/5 y 18/18 válidas, y los
tres tramos de serie encontrados solos.

## Métricas de fase

Sobre el conteo, `metricas.py` mide cada repetición: recorrido, tiempo de
subida, tiempo de bajada, ratio excéntrica/concéntrica y velocidad pico. Y por
serie, la **caída de velocidad concéntrica** —la pendiente de la regresión de la
velocidad pico contra el número de repetición—, que es lo que un contador de
repeticiones no da: mide cuánto se frena la serie, no cuántas salieron.

Las fases se detectan por **velocidad**, no por umbral de altura, y una fase es
el **tiempo en movimiento** entre sus dos extremos: las pausas no cuentan en
ninguna de las dos. Esa segunda decisión no es cosmética y salió de FASE 0: la
excéntrica real de una dominada no es monótona —caída rápida, freno a media
altura, deriva lenta hasta el dead hang— y quedarse con el tramo contiguo
alrededor del pico de velocidad triplicaba la dispersión de la medida. El
detalle está en [`experimentos/FASE0_RESULTADOS.md`](experimentos/FASE0_RESULTADOS.md).

También sale la **asimetría bilateral**: desnivel de hombros en el pico y
desviación lateral de la nariz respecto al centro de las manos. Es lo único que
la vista frontal mide mejor que la lateral, porque de perfil un hombro tapa al
otro.

## Qué NO hace

No comprueba la extensión de los brazos abajo, no detecta kipping y no separa dos
series distintas en el mismo vídeo: se queda con el tramo colgado más largo.

Los tiempos de fase no son el tempo real. El umbral de velocidad recorta cada
fase por los dos extremos, y recorta proporcionalmente más la larga que la
corta, así que el ratio medido sale aplanado: un ratio real de 2,50 se mide
2,16. Es sistemático y afecta igual a todas las series, así que comparar
sesiones entre sí es válido; el número absoluto no es el tempo.

El instante de cada repetición no está bien definido cuando hay pausa arriba: la
cresta de la señal es plana y el máximo salta hasta medio segundo entre
muestreos. Sirve para localizar la repetición en el vídeo, no como medida.

Nada de esto está validado contra un patrón externo. Se ha comprobado que dos
muestreos dan lo mismo y que el conteo cuadra con tres vídeos etiquetados a
mano; eso no es un estudio.

Las versiones anteriores quedan archivadas en carpetas aparte, cada una
ejecutable desde dentro de la suya: [`v2/`](v2/) es esta misma medición con
gráfica, vídeo anotado, veredicto *al límite* y 25 tests; [`v1/`](v1/) es el
primer prototipo, con detección de barra por bordes y criterio de codos.
