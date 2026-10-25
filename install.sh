#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Batocera Portal — installer (v1.2.0)
#  Author: Dan Lee · MIT
#
#  Run on the Batocera machine itself, over SSH, from the folder
#  that holds this script:
#     cd /userdata/system/batocera_portal && ./install.sh
#
#  Environment overrides (unattended installs and tests):
#     BP_PORT        web port                    (default 5000)
#     BP_AUTOSTART   y / n: answer without asking
#     BP_NO_START    1: do not launch the server after installing
#     BP_BASE_DIR    Batocera system folder      (default /userdata/system)
#     BP_PYTHON      python interpreter          (default python3)
#     NO_COLOR       disable colours
# ──────────────────────────────────────────────────────────────
set -e

BASE_DIR="${BP_BASE_DIR:-/userdata/system}"
INSTALL_DIR="$BASE_DIR/batocera_portal"
SERVICES_DIR="$BASE_DIR/services"
SERVICE_NAME="batocera_portal"
SETTINGS_FILE="$BASE_DIR/batocera_portal_settings.json"
PYTHON="${BP_PYTHON:-python3}"
PORT="${BP_PORT:-5000}"
MARKER="# [batocera-portal]"
TAG_END="# [/batocera-portal]"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C0=$'\033[0m'; CB=$'\033[1m'; CG=$'\033[32m'; CY=$'\033[33m'; CR=$'\033[31m'; CC=$'\033[36m'
else
  C0=''; CB=''; CG=''; CY=''; CR=''; CC=''
fi
ok()   { printf '  %s✔%s %s\n' "$CG" "$C0" "$1"; }
warn() { printf '  %s◌%s %s\n' "$CY" "$C0" "$1"; }
bad()  { printf '  %s✖%s %s\n' "$CR" "$C0" "$1"; }
kv()   { printf '  %s◆%s %-24s %s\n' "$CC" "$C0" "$1" "$2"; }

printf '\n%s  Batocera Portal installer%s\n' "$CB" "$C0"
printf '  target: %s\n\n' "$INSTALL_DIR"

# 1. Python
if "$PYTHON" --version >/dev/null 2>&1; then
  kv "Python" "$("$PYTHON" --version 2>&1)"
else
  bad "Cannot find '$PYTHON'. Set BP_PYTHON=/path/to/python3 and retry."
  exit 1
fi
if "$PYTHON" -c "from PIL import Image" >/dev/null 2>&1; then
  kv "Pillow (placeholder logos)" "available"
else
  kv "Pillow (placeholder logos)" "not installed (optional)"
fi

# 2. Files
IN_PLACE=0
if [ "$SCRIPT_DIR" = "$INSTALL_DIR" ]; then
  IN_PLACE=1
elif [ -f "$SCRIPT_DIR/app.py" ] && [ -f "$INSTALL_DIR/app.py" ] && [ "$SCRIPT_DIR/app.py" -ef "$INSTALL_DIR/app.py" ]; then
  IN_PLACE=1
fi
if [ "$IN_PLACE" = 1 ]; then
  kv "Files" "already in place"
else
  mkdir -p "$INSTALL_DIR"
  for item in app.py portal static README.md CHANGELOG.md LICENSE; do
    if [ -e "$SCRIPT_DIR/$item" ]; then
      rm -rf "${INSTALL_DIR:?}/$item"
      cp -r "$SCRIPT_DIR/$item" "$INSTALL_DIR/$item"
    fi
  done
  find "$INSTALL_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  ok "Files copied to $INSTALL_DIR"
fi
chmod +x "$INSTALL_DIR/app.py" 2>/dev/null || true

# 3. Stop a previous copy of the portal, then check the port is free
PROC_PAT='python3? [^ ]*batocera_portal/app\.py'
pkill -f "$PROC_PAT" 2>/dev/null || true
sleep 1
# Try to bind the port ourselves; that works even where ss/netstat are missing.
PORT_BUSY=0
"$PYTHON" - "$PORT" <<'PY' || PORT_BUSY=1
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
if [ "$PORT_BUSY" = 1 ]; then
  PORT_USER=""
  if command -v ss >/dev/null 2>&1; then
    PORT_USER="$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $NF}' | head -1)"
  elif command -v netstat >/dev/null 2>&1; then
    PORT_USER="$(netstat -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p"$" {print $NF}' | head -1)"
  fi
  bad "Port $PORT is already in use${PORT_USER:+ by: $PORT_USER}"
  printf '     Either stop that program, or install on another port:\n'
  printf '       BP_PORT=5001 BP_AUTOSTART=y ./install.sh\n\n'
  exit 1
fi
kv "Port" "$PORT is free"

# Remember the port so the portal's own restart button uses it too
"$PYTHON" - "$SETTINGS_FILE" "$PORT" <<'PY' 2>/dev/null || true
import json, sys
path, port = sys.argv[1], int(sys.argv[2])
try:
    data = json.load(open(path))
except Exception:
    data = {}
data["server_port"] = port
json.dump(data, open(path, "w"), indent=2)
PY

# 4. Autostart
CMD="$PYTHON $INSTALL_DIR/app.py --port $PORT"
ANSWER="${BP_AUTOSTART:-}"
if [ -z "$ANSWER" ]; then
  if [ -t 0 ]; then
    printf '\n  %sStart Batocera Portal automatically at boot?%s [Y/n]: ' "$CY" "$C0"
    read -r ANSWER || ANSWER=''
  else
    warn "No interactive terminal: leaving autostart unchanged (set BP_AUTOSTART=y or n)."
    ANSWER="skip"
  fi
fi
ANSWER="${ANSWER//[$'\r\n\t ']/}"
case "$ANSWER" in
  ""|y|Y|yes|YES|Yes)
    if command -v batocera-services >/dev/null 2>&1; then
      # The supported way on Batocera >= 36: a service script + batocera-services enable
      mkdir -p "$SERVICES_DIR"
      cat > "$SERVICES_DIR/$SERVICE_NAME" <<SVC
#!/bin/bash
$MARKER
# Batocera Portal service. Managed from the portal's Settings page.
case "\$1" in
  start)
    $CMD >/dev/null 2>&1 &
    ;;
  stop)
    pkill -f '$PROC_PAT' 2>/dev/null
    ;;
  restart)
    "\$0" stop; sleep 1; "\$0" start
    ;;
  status)
    pgrep -f '$PROC_PAT' >/dev/null && echo running || echo stopped
    ;;
esac
$TAG_END
SVC
      chmod +x "$SERVICES_DIR/$SERVICE_NAME" 2>/dev/null || true
      if batocera-services enable "$SERVICE_NAME" >/dev/null 2>&1; then
        ok "Service '$SERVICE_NAME' enabled (batocera-services)"
      else
        warn "Service script written but 'batocera-services enable' failed; run it by hand:"
        printf '       batocera-services enable %s\n' "$SERVICE_NAME"
      fi
      # Drop any old custom.sh block from earlier versions
      CUSTOM_SH="$BASE_DIR/custom.sh"
      if [ -f "$CUSTOM_SH" ] && grep -qF "$MARKER" "$CUSTOM_SH"; then
        TMP="$(mktemp)"
        awk -v s="$MARKER" -v e="$TAG_END" 'index($0,s)==1{skip=1;next} index($0,e)==1{skip=0;next} !skip{print}' "$CUSTOM_SH" > "$TMP"
        cat "$TMP" > "$CUSTOM_SH"; rm -f "$TMP"
        ok "Removed the old custom.sh block"
      fi
    else
      # Fallback: custom.sh, inserted before its final 'exit' and guarded for 'start'
      CUSTOM_SH="${BP_CUSTOM_SH:-$BASE_DIR/custom.sh}"
      TMP="$(mktemp)"
      BLOCK="$(printf '%s\nif [ -z "$1" ] || [ "$1" = "start" ]; then\n  %s >/dev/null 2>&1 &\nfi\n%s' "$MARKER" "$CMD" "$TAG_END")"
      if [ -f "$CUSTOM_SH" ]; then
        awk -v s="$MARKER" -v e="$TAG_END" 'index($0,s)==1{skip=1;next} index($0,e)==1{skip=0;next} !skip{print}' "$CUSTOM_SH" > "$TMP"
      else
        printf '#!/bin/bash\n' > "$TMP"
      fi
      grep -q '^#!' "$TMP" || sed -i '1i #!/bin/bash' "$TMP"
      if grep -qE '^exit\b' "$TMP"; then
        awk -v b="$BLOCK" '/^exit[[:space:]]|^exit$/ && !done {print b; done=1} {print}' "$TMP" > "$TMP.2" && mv "$TMP.2" "$TMP"
      else
        printf '%s\n' "$BLOCK" >> "$TMP"
      fi
      mkdir -p "$(dirname "$CUSTOM_SH")"
      cat "$TMP" > "$CUSTOM_SH"; rm -f "$TMP"
      chmod +x "$CUSTOM_SH" 2>/dev/null || true
      ok "Autostart block written to $CUSTOM_SH"
    fi
    ;;
  n|N|no|NO|No)
    warn "Autostart not enabled. Start manually with: $CMD"
    ;;
  *)
    ;;
esac

# 5. Start now
if [ "${BP_NO_START:-0}" != "1" ]; then
  nohup $CMD >"$BASE_DIR/batocera_portal.log" 2>&1 &
  sleep 2
  if pgrep -f "$PROC_PAT" >/dev/null 2>&1; then
    ok "Running on port $PORT"
  else
    bad "Server did not stay up. Last log lines:"
    tail -5 "$BASE_DIR/batocera_portal.log" 2>/dev/null | sed 's/^/       /'
    exit 1
  fi
fi

IP="$(ip -4 route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)"
printf '\n  %sDone.%s Open http://%s:%s and sign in with the password linuxrox\n\n' "$CB" "$C0" "${IP:-$(hostname)}" "$PORT"
