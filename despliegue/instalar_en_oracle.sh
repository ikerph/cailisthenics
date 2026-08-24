#!/usr/bin/env bash
#
# Instala el backend de cAI-listhenics en una instancia Ubuntu de Oracle Cloud.
# Pensado para el Ampere A1 del plan Always Free (ARM64), pero vale igual en x86.
#
# Se ejecuta EN EL SERVIDOR, por SSH:
#
#     curl -fsSL https://raw.githubusercontent.com/ikerph/cailisthenics/main/despliegue/instalar_en_oracle.sh | bash
#
# o, si aún no está en GitHub, copiando este fichero y ejecutándolo:
#
#     bash instalar_en_oracle.sh
#
# Deja el servidor arrancado como servicio de systemd, así que sobrevive a
# reinicios y a que se cierre la sesión de SSH.

set -euo pipefail

REPO="${REPO:-https://github.com/ikerph/cailisthenics.git}"
RAMA="${RAMA:-main}"
DESTINO="${DESTINO:-$HOME/cailisthenics}"
PUERTO="${PUERTO:-8000}"

echo "==> cAI-listhenics: instalación en $(uname -m)"

# --- 1. Paquetes del sistema ------------------------------------------------
# libgl1 y libglib2.0-0 los pide OpenCV aunque sea la versión headless.
echo "==> Paquetes del sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq \
  python3-venv python3-pip git \
  libgl1 libglib2.0-0

# --- 2. Código --------------------------------------------------------------
echo "==> Código en $DESTINO"
if [ -d "$DESTINO/.git" ]; then
  git -C "$DESTINO" fetch --quiet origin "$RAMA"
  git -C "$DESTINO" reset --hard --quiet "origin/$RAMA"
else
  git clone --quiet --branch "$RAMA" "$REPO" "$DESTINO"
fi

# --- 3. Entorno de Python ---------------------------------------------------
echo "==> Dependencias de Python (tarda unos minutos en ARM)"
python3 -m venv "$DESTINO/.venv"
"$DESTINO/.venv/bin/pip" install --quiet --upgrade pip
"$DESTINO/.venv/bin/pip" install --quiet -r "$DESTINO/requirements-servidor.txt"

# --- 4. El modelo de pose ---------------------------------------------------
# `models/` está en el .gitignore, así que no viene con el clon. Se baja con la
# propia función del contador, para que descargue exactamente el modelo que
# nombra la constante y no una copia que se quede desfasada.
echo "==> Modelo de pose"
cd "$DESTINO"
"$DESTINO/.venv/bin/python" -c "import contador; print('  ', contador.descargar_modelo())"

# --- 5. Cortafuegos DEL SISTEMA ---------------------------------------------
# Esto es lo que se salta todo el mundo. Las imágenes Ubuntu de Oracle traen
# reglas de iptables que DESCARTAN todo lo que no sea SSH, además de la Security
# List de la consola de OCI. Hay que abrir el puerto en LOS DOS SITIOS o el
# móvil se queda esperando sin recibir ni un rechazo.
echo "==> Cortafuegos del sistema (puerto $PUERTO)"
if command -v iptables >/dev/null 2>&1; then
  if ! sudo iptables -C INPUT -p tcp --dport "$PUERTO" -j ACCEPT 2>/dev/null; then
    # Antes de la regla REJECT final, no después: iptables evalúa en orden.
    sudo iptables -I INPUT 6 -p tcp --dport "$PUERTO" -m state --state NEW,ESTABLISHED -j ACCEPT
  fi
  sudo apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
  sudo netfilter-persistent save >/dev/null 2>&1 || true
fi
# Oracle Linux usa firewalld en vez de iptables a pelo.
if command -v firewall-cmd >/dev/null 2>&1; then
  sudo firewall-cmd --permanent --add-port="$PUERTO"/tcp || true
  sudo firewall-cmd --reload || true
fi

# --- 6. Clave de acceso -----------------------------------------------------
# El servidor no arranca sin ella: es lo que impide que quede abierto a
# internet. Se genera una vez y se conserva entre reinstalaciones, para no tener
# que reescribirla en el móvil cada vez que se actualiza.
SECRETOS=/etc/cailisthenics.env
echo "==> Clave de acceso"
if sudo test -f "$SECRETOS"; then
  echo "   ya existia, se conserva"
else
  CLAVE=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  # 600 y de root: los ficheros de unidad de systemd son 644, asi que meter la
  # clave ahi la dejaria legible para cualquier usuario de la maquina.
  echo "CAI_CLAVE=$CLAVE" | sudo tee "$SECRETOS" >/dev/null
  sudo chmod 600 "$SECRETOS"
  sudo chown root:root "$SECRETOS"
  echo "   generada"
fi

# --- 7. Servicio ------------------------------------------------------------
echo "==> Servicio de systemd"
sudo tee /etc/systemd/system/cailisthenics.service >/dev/null <<SERVICIO
[Unit]
Description=cAI-listhenics backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DESTINO
EnvironmentFile=$SECRETOS
ExecStart=$DESTINO/.venv/bin/uvicorn servidor.api:app --host 0.0.0.0 --port $PUERTO
Restart=always
RestartSec=5
# El análisis es CPU pura y los vídeos son temporales: nada que persistir.
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
SERVICIO

sudo systemctl daemon-reload
sudo systemctl enable --now cailisthenics
sleep 3

# --- 8. Comprobación --------------------------------------------------------
echo
CLAVE_ACTUAL=$(sudo sed -n 's/^CAI_CLAVE=//p' "$SECRETOS")
if curl -fsS --max-time 10 -H "X-Cai-Clave: $CLAVE_ACTUAL" "http://127.0.0.1:$PUERTO/salud" >/dev/null; then
  IP_PUBLICA=$(curl -fsS --max-time 10 https://api.ipify.org || echo "TU_IP")
  echo "LISTO. El backend responde en el propio servidor."
  echo
  echo "  Direccion para la app:  http://$IP_PUBLICA:$PUERTO"
  echo "  Contrasena:             $CLAVE_ACTUAL"
  echo
  echo "  APUNTA LA CONTRASENA: sin ella el servidor rechaza todo con un 401."
  echo "  Se puede volver a ver con:  sudo cat $SECRETOS"
  echo
  echo "FALTA UN PASO QUE NO SE PUEDE HACER DESDE AQUÍ:"
  echo "  abrir el puerto $PUERTO en la Security List de la consola de OCI."
  echo "  Redes > VCN > Subred > Security List > Add Ingress Rule"
  echo "    Source: 0.0.0.0/0   Protocolo: TCP   Destination Port: $PUERTO"
  echo
  echo "Comprueba desde el móvil:  http://$IP_PUBLICA:$PUERTO/salud"
else
  echo "El servicio no responde. Mira el log con:"
  echo "  sudo journalctl -u cailisthenics -n 50 --no-pager"
  exit 1
fi
