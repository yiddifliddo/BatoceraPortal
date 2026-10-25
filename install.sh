#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Batocera Portal — installer (v1.0.0)
#  Author: Dan Lee · MIT
#
#  Run on the Batocera machine itself, over SSH:
#     ssh root@BATOCERA
#     git clone https://github.com/yiddifliddo/BatoceraPortal /userdata/system/batocera_portal
#     cd /userdata/system/batocera_portal && ./install.sh
#
#  Environment overrides (unattended installs and tests):
#     BP_BASE_DIR    Batocera base folder        (default /userdata/system)
#     BP_CUSTOM_SH   custom.sh to edit            (default $BP_BASE_DIR/custom.sh)
#     BP_PYTHON      python interpreter          (default python3)
#     BP_PORT        web port                    (default 5000)
#     BP_AUTOSTART   y / n: answer without asking
#     BP_NO_START    1: do not launch the server after installing
#     NO_COLOR       disable colours
# ──────────────────────────────────────────────────────────────
set -e

BASE_DIR="${BP_BASE_DIR:-/userdata/system}"
INSTALL_DIR="$BASE_DIR/batocera_portal"
CUSTOM_SH="${BP_CUSTOM_SH:-$BASE_DIR/custom.sh}"
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
kv()   { printf '  %s◆%s %-22s %s\n' "$CC" "$C0" "$1" "$2"; }

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

# 3. Autostart
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
    TMP="$(mktemp)"
    if [ -f "$CUSTOM_SH" ]; then
      # drop any previous block, keep the rest
      awk -v s="$MARKER" -v e="$TAG_END" '
        index($0,s)==1 {skip=1; next}
        index($0,e)==1 {skip=0; next}
        !skip {print}
      ' "$CUSTOM_SH" > "$TMP"
    else
      printf '#!/bin/bash\n' > "$TMP"
    fi
    grep -q '^#!' "$TMP" || sed -i '1i #!/bin/bash' "$TMP"
    printf '%s\n%s &\n%s\n' "$MARKER" "$CMD" "$TAG_END" >> "$TMP"
    mkdir -p "$(dirname "$CUSTOM_SH")"
    cat "$TMP" > "$CUSTOM_SH"; rm -f "$TMP"
    chmod +x "$CUSTOM_SH"
    ok "Autostart block written to $CUSTOM_SH"
    ;;
  n|N|no|NO|No)
    warn "Autostart not enabled. Start manually with: $CMD"
    ;;
  *)
    ;;
esac

# 4. Start now
if [ "${BP_NO_START:-0}" != "1" ]; then
  pkill -f "batocera_portal/app.py" 2>/dev/null || true
  sleep 1
  nohup $CMD >/dev/null 2>&1 &
  sleep 1
  if pgrep -f "batocera_portal/app.py" >/dev/null 2>&1; then
    ok "Running on port $PORT"
  else
    warn "Server did not stay up. Run it by hand to see errors: $CMD"
  fi
fi

HOST="$(hostname 2>/dev/null || echo BATOCERA)"
printf '\n  %sDone.%s Open http://%s:%s\n\n' "$CB" "$C0" "$HOST" "$PORT"
