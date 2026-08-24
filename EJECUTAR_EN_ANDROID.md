# Ejecutar en tu móvil Android

Dos piezas: el **backend** corre en el portátil y el **cliente** en el móvil. Los
dos tienen que estar en la misma wifi.

Tu IP en la wifi es **192.168.1.148**. Si cambias de red, vuelve a mirarla con
`ipconfig` (la del "Adaptador de LAN inalámbrica Wi-Fi").

---

## El APK

    cAI-listhenics-beta.apk        (en la raíz del proyecto, 54 MB)

Firmado con la clave de la beta, no con la de depuración. Paquete
`com.cailisthenics.beta`, para arm64, armeabi-v7a y x86_64. Lleva
`http://192.168.1.148:8000` como servidor por defecto, y se puede cambiar desde
la propia app sin recompilar.

---

## Lo que ya está hecho

No hace falta que instales nada más:

- **Flutter 3.47.1** en `C:\src\flutter` (Dart 3.13.1).
- **Licencias del SDK de Android aceptadas.**
- **Flutter apuntando al JDK 21 de Android Studio**, no a tus JDK 18/23, con los
  que Gradle da errores raros.
- **`cliente/android/` generado**, manifiesto parcheado y clave de firma creada.
- `flutter analyze` limpio, 4 tests de widget y 57 tests de Python en verde.

Flutter solo necesita estar en el PATH de cada terminal nueva:

```powershell
$env:Path = "C:\src\flutter\bin;$env:Path"
```

Para dejarlo puesto de forma permanente:

```powershell
[Environment]::SetEnvironmentVariable(
  "Path", "C:\src\flutter\bin;" + [Environment]::GetEnvironmentVariable("Path","User"), "User")
```

(Abre una terminal nueva después.)

---

## 1. Levanta el backend

En una terminal del portátil, dentro de la carpeta del proyecto:

```powershell
python -m uvicorn servidor.api:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` no es opcional: por defecto uvicorn solo escucha en
`127.0.0.1` y el móvil no llegaría.

Comprueba desde el navegador **del móvil** que responde:

    http://192.168.1.148:8000/salud

Si eso no carga, no sigas: el problema es de red, no de la app. Casi siempre es
el firewall de Windows. Permítelo una vez, desde PowerShell **como
administrador**:

```powershell
New-NetFirewallRule -DisplayName "cAI-listhenics backend" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

Y comprueba que la wifi está marcada como red **privada**, no pública.

---

## 2. Instala el APK

**Lo más simple**: copia `cAI-listhenics-beta.apk` al móvil (cable, Telegram,
Drive), ábrelo desde el explorador de archivos del móvil y acepta "instalar de
orígenes desconocidos" cuando lo pida.

**Por cable con adb**, si prefieres:

1. Ajustes → Acerca del teléfono → toca 7 veces en **Número de compilación**.
2. Ajustes → Sistema → Opciones de desarrollador → activa **Depuración por USB**.
3. Conecta el cable y acepta "¿Permitir depuración USB?" en el móvil.

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb devices
& $adb install -r cAI-listhenics-beta.apk
```

En `adb devices` tiene que salir tu móvil con estado `device`. Si sale
`unauthorized`, no has aceptado el diálogo. Si no sale nada, prueba otro cable:
muchos cables son solo de carga y no llevan datos.

La primera vez que la abras, Android pedirá permiso de cámara. Hay que darlo o la
pantalla de grabar se queda en negro.

---

## 3. Graba una serie

1. Marca los cuatro puntos del checklist. Sin los cuatro, el botón no graba.
2. Encuadra: el cuerpo entero dentro de la silueta y **los pies por encima de la
   línea naranja**. Si los pies caen por debajo, estás demasiado cerca y te vas a
   salir del encuadre al subir.
3. Graba, para, y confirma en el diálogo de revisión.
4. Espera al análisis. Un vídeo de 30 s tarda entre 6 y 14 s.
5. Guarda la serie para que aparezca en el histórico.

Lo primero que hay que mirar del resultado **no es el número: es el gráfico**. La
línea naranja es la barra deducida de tus muñecas. Si no cae donde está la barra
de verdad, la medida está mal y el número no vale.

---

## Si tu IP cambia

No hace falta recompilar. En la pestaña **Histórico**, el icono de servidor
arriba a la derecha abre un campo para cambiar la dirección, y se recuerda entre
arranques. La pantalla de error de conexión trae el mismo botón.

---

## Desarrollo con recarga en caliente

Si prefieres verla desde el portátil mientras la tocas, con el móvil conectado
por cable:

```powershell
cd cliente
flutter run --dart-define=CAI_BASE_URL=http://192.168.1.148:8000
```

`r` recarga en caliente, `R` reinicia, `q` sale.

Para volver a generar el APK:

```powershell
cd cliente
flutter build apk --release --dart-define=CAI_BASE_URL=http://192.168.1.148:8000
```

---

## Si algo falla

**"No se pudo conectar"** — el móvil no llega al portátil. La pantalla de error
trae un botón para cambiar la dirección del servidor. Si la dirección es
correcta, vuelve al paso 1 y abre `/salud` desde el navegador del móvil.

**La pantalla de grabar sale en negro** — falta el permiso de cámara. Ajustes →
Aplicaciones → cAI-listhenics → Permisos → Cámara.

**"Aplicación no instalada"** al instalar el APK — ya tienes una versión firmada
con otra clave. Desinstala la anterior primero. Ojo: con la app se va el
histórico guardado en el móvil.

**Errores de Gradle sobre la versión de Java** — comprueba que Flutter sigue
apuntando al JDK de Android Studio:

```powershell
flutter config --jdk-dir "C:\Program Files\Android\Android Studio\jbr"
```

**El análisis falla con un mensaje concreto** — eso es el sistema funcionando.
Cada fallo del pipeline trae una instrucción de qué cambiar al grabar: cuerpo
entero, de frente, manos visibles, al menos 3 segundos colgado.

**Quieres probar sin móvil** — el backend se prueba solo:

```powershell
python -m pytest tests/ -q
```

---

## La clave de firma

`cliente/android/cai-beta.jks` y `cliente/android/key.properties` no están en el
repositorio. **Haz una copia de seguridad.** Si se pierden, las versiones nuevas
saldrán firmadas con otra clave y Android se negará a instalarlas encima de las
viejas: habrá que desinstalar, y con la app se va el histórico del móvil.

---

## Lo que pasa con tus vídeos

El vídeo se sube, se procesa y **se borra del servidor** en cuanto termina, salga
bien o mal. Lo que vuelve al móvil son los keypoints y las métricas, y eso se
guarda en el propio dispositivo, en SQLite. En el portátil no queda ninguna copia
del vídeo.
