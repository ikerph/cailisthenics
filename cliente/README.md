# Cliente Flutter

`flutter analyze` sin avisos y 4 tests de widget en verde. La carpeta
`android/` está generada, el manifiesto parcheado y el APK release firmado se
compila. Lo que **no** se ha hecho todavía es ejecutarlo en un móvil de verdad:
para eso, [`EJECUTAR_EN_ANDROID.md`](../EJECUTAR_EN_ANDROID.md) en la raíz.

## Arrancar

Con el backend levantado (`uvicorn servidor.api:app --host 0.0.0.0 --port 8000`):

```bash
cd cliente
flutter run --dart-define=CAI_BASE_URL=http://TU_IP:8000
```

Para sacar el APK que se instala a mano:

```bash
flutter build apk --release --dart-define=CAI_BASE_URL=http://TU_IP:8000
```

El `--dart-define` solo fija el valor POR DEFECTO. La dirección se puede cambiar
desde la propia app (icono de servidor en el histórico) y se recuerda: el APK se
compila una vez y la IP del portátil cambia con el DHCP del router.

## Firma

`android/key.properties` y `android/cai-beta.jks` llevan la clave de firma de la
beta y **no están en el repositorio**. Si se pierden, las versiones nuevas
saldrán firmadas con otra clave y Android se negará a instalarlas encima de las
viejas: habrá que desinstalar, y con la app se va el histórico del móvil.

Si `key.properties` no está, Gradle compila con la clave de depuración en vez de
fallar, para que el proyecto siga siendo ejecutable por cualquiera.

## Si se regenera la carpeta de plataforma

`flutter create` no pone los permisos, y sin ellos la app compila, arranca y
falla al abrir la cámara con un `CameraException` genérico que no dice qué
falta. Después de cualquier `flutter create`:

```bash
python preparar_android.py
```

Es idempotente. Añade al manifiesto `CAMERA`, `INTERNET` y
`usesCleartextTraffic` -este último porque Android 9 en adelante bloquea el HTTP
sin cifrar, y hay que quitarlo en cuanto el backend tenga HTTPS-, y en iOS el
`NSCameraUsageDescription`.

## Cómo está montado

```
lib/
  config.dart              baseUrl y los límites de duración
  modelo/analisis.dart     el JSON del backend en tipos de Dart
  red/api.dart             subida y sondeo del análisis
  datos/almacen.dart       SQLite + keypoints + device_id
  pantallas/captura.dart   checklist, guía de encuadre y validación
  pantallas/resultado.dart contador, gráfico, tabla y banner
  pantallas/historico.dart progresiones y aviso de escala
  widgets/                 gráficos a mano y piezas comunes
```

Tres cosas que conviene no deshacer sin leer por qué están:

**Los números son `double?`, no `double`.** El servidor manda `null` donde el
pipeline dio NaN, y da NaN con motivo: la desviación típica de una serie de una
repetición no es cero, es "no hay". Poner un `?? 0` convierte huecos en datos
falsos y el gráfico enseña caídas que no ocurrieron.

**El esquema SQL se lee de `assets/esquema/001_inicial.sql`**, que es copia de
`esquema/001_inicial.sql` de la raíz. Si tocas uno, copia el otro:
`tests/test_cliente.py` comprueba que no han divergido.

**`PRAGMA foreign_keys = ON` va en `onConfigure`, por conexión.** SQLite ignora
las claves ajenas por defecto y el `ON DELETE CASCADE` del esquema no falla: no
borra nada y deja repeticiones huérfanas que el histórico sigue contando.

## Lo que no lleva, a propósito

Login, social, rutinas, otros ejercicios, compartir y pagos. Nada de eso ayuda a
averiguar si el análisis sirve, que es lo único que la beta tiene que descubrir.
