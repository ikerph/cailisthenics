# Desplegar el backend en Oracle Cloud Always Free

Al terminar esto tendrás el análisis corriendo 24/7 en un servidor gratuito, y
podrás irte al parque con el móvil solo: sin túneles, sin dejar el portátil
encendido.

Es ARM64 (Ampere A1). Ya está comprobado que MediaPipe, OpenCV, SciPy, NumPy e
imageio-ffmpeg tienen todos rueda `aarch64` para Linux, así que no hay que
compilar nada.

---

## 1. Sube el código a GitHub

El backend todavía no está en tu repositorio. Desde la carpeta del proyecto:

```powershell
git add metricas.py servidor esquema tests requirements-servidor.txt requirements-dev.txt despliegue Dockerfile
git commit -m "Backend de analisis, metricas de fase y esquema del historico"
git push
```

Tu repo es `github.com/ikerph/cailisthenics`. Si es **privado**, el servidor no
podrá clonarlo sin credenciales: o lo haces público, o usas una clave de
despliegue.

---

## 2. Crea la instancia

En la consola de Oracle: **Compute → Instances → Create Instance**.

| Campo | Valor |
|---|---|
| Image | Canonical Ubuntu 22.04 o 24.04 |
| Shape | **Ampere / VM.Standard.A1.Flex** |
| OCPUs | 4 |
| Memoria | 24 GB |
| SSH key | Genera una y **guarda la clave privada** |

Los 4 OCPU y 24 GB son el máximo del plan Always Free y no cuestan nada.

**Si sale "Out of capacity"** es lo normal con Ampere: prueba otro Availability
Domain del desplegable, o vuelve a intentarlo dentro de unas horas. No es un
error tuyo.

Apunta la **IP pública** cuando la instancia arranque.

---

## 3. Abre el puerto en la consola de OCI

Este paso y el siguiente son **dos cortafuegos distintos**, y saltarse
cualquiera de los dos deja el móvil esperando sin recibir siquiera un rechazo.
Es la causa número uno de que esto no funcione.

**Networking → Virtual Cloud Networks →** tu VCN **→ Subnets →** tu subred **→
Security Lists →** la lista por defecto **→ Add Ingress Rules**:

| Campo | Valor |
|---|---|
| Source Type | CIDR |
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `8000` |

---

## 4. Instala

Conéctate por SSH (`ubuntu` es el usuario en las imágenes Ubuntu):

```powershell
ssh -i C:\ruta\a\tu\clave.key ubuntu@TU_IP_PUBLICA
```

Y ejecuta:

```bash
curl -fsSL https://raw.githubusercontent.com/ikerph/cailisthenics/main/despliegue/instalar_en_oracle.sh | bash
```

El script instala las dependencias, se baja el modelo de pose, **abre el
cortafuegos del sistema** —el segundo de los dos— y deja el backend como
servicio de systemd, así que sobrevive a reinicios.

En ARM tarda unos minutos: SciPy y OpenCV son grandes.

---

## 5. Comprueba desde el móvil

Abre en el navegador del móvil, **con datos móviles, no con tu wifi**:

    http://TU_IP_PUBLICA:8000/salud

Tiene que salir un JSON de error diciendo **"Contraseña del servidor
incorrecta"**. Eso es exactamente lo que se busca: significa que llegaste al
servidor y que está rechazando lo que no lleva contraseña. El navegador no puede
mandarla; la app sí.

Si en cambio **no carga nada** y se queda esperando, el problema está en uno de
los dos cortafuegos, el del paso 3 o el del paso 4.

---

## 6. Apunta la app ahí

Al terminar, el script imprime **la dirección y la contraseña**. Apúntalas: sin
la contraseña el servidor rechaza todo con un 401.

En la app: pestaña **Histórico** → icono de servidor arriba a la derecha → rellena
los dos campos y pulsa **Comprobar y guardar**. La app valida contra el servidor
antes de guardar, así que si algo está mal te lo dice ahí mismo en vez de
después de subir un vídeo entero.

Si pierdes la contraseña, se vuelve a ver en el servidor con:

```bash
sudo cat /etc/cailisthenics.env
```

Ya no necesitas el portátil ni los túneles de Cloudflare. Puedes matar los
procesos `cloudflared.exe` y el `uvicorn` local.

---

## Mantenimiento

```bash
sudo cat /etc/cailisthenics.env          # ver la contraseña
sudo systemctl status cailisthenics      # cómo va
sudo journalctl -u cailisthenics -f      # log en vivo
sudo systemctl restart cailisthenics     # reiniciar
```

Para actualizar tras un `git push` desde el portátil, vuelve a lanzar el script
de instalación: hace `git reset --hard` a la rama y reinicia el servicio.

---

## Dos cosas que debes tener en cuenta

**El backend pide una contraseña, pero va por HTTP.** Toda petición sin la
cabecera `X-Cai-Clave` correcta se rechaza con un 401, incluidos `/docs` y las
rutas que no existen. Eso deja fuera a los escáneres, que es el problema real de
tener una IP pública fija.

Lo que NO resuelve: sobre HTTP la contraseña viaja legible. Detiene a quien
escanea internet, no a quien pueda leer tu tráfico. Y no hay límite de intentos
ni caducidad; cambiar la clave echa a todos los móviles a la vez.

Si quieres cerrarlo del todo, dos opciones que se suman bien: limitar el
`Source CIDR` de la regla de ingress al rango de tu operador móvil, y poner
HTTPS.

**Va por HTTP sin cifrar.** El manifiesto de Android ya lo permite
(`usesCleartextTraffic`). Significa que el vídeo viaja sin cifrar por la red. Si
quieres HTTPS, lo más simple es Caddy delante con un dominio gratuito de DuckDNS:
saca el certificado solo.

---

## Oracle y las cuentas gratuitas

Oracle reclama recursos Always Free que llevan mucho tiempo inactivos. Este
servicio recibiendo peticiones de vez en cuando cuenta como actividad, pero si
dejas de usar la app meses, no te extrañe encontrarte la instancia parada.
