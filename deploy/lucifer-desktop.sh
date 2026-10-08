#!/usr/bin/env bash
# lucifer-desktop — buka Lucifer Linux sebagai APLIKASI DESKTOP.
#
# Cara kerja:
#   1. Pastikan server dashboard jalan (kalau belum, jalankan di latar).
#   2. Buka Chrome/Chromium dalam mode --app: jendela sendiri, tanpa
#      address bar & tanpa tab, jadi terlihat seperti aplikasi native.
#   3. Punya ikon sendiri di dock/taskbar (StartupWMClass=LuciferLinux).
#
# Pemakaian:
#   lucifer-desktop              # buka jendela aplikasi
#   lucifer-desktop --stop       # matikan server dashboard
#   lucifer-desktop --status     # cek server & tampilkan URL
#
# Variabel opsional:
#   LUCIFER_PORT=8787            # ganti port
#   LUCIFER_BROWSER=firefox      # ganti browser

set -uo pipefail

PORT="${LUCIFER_PORT:-8787}"
HOST="127.0.0.1"
URL="http://${HOST}:${PORT}/"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${DIR}/.venv/bin/lucifer"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/lucifer-web.pid"
LOG="${XDG_RUNTIME_DIR:-/tmp}/lucifer-web.log"

# -- deteksi sesi grafis ------------------------------------------------------ #
# Skrip ini sering dijalankan dari shell tanpa DISPLAY/XAUTHORITY (mis. dari
# agen/SSH). Padahal pengguna punya sesi GNOME. Kita cari sendiri kombinasinya.
siapkan_display() {
  [[ -n "${DISPLAY:-}" && -n "${XAUTHORITY:-}" ]] && \
    DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" xdpyinfo >/dev/null 2>&1 && return 0

  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

  local d a
  for d in ":0" ":1" ":2"; do
    # kandidat XAUTHORITY: auth Xwayland milik mutter, lalu ~/.Xauthority
    for a in "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* "$HOME/.Xauthority"; do
      [[ -f "$a" ]] || continue
      if DISPLAY="$d" XAUTHORITY="$a" xdpyinfo >/dev/null 2>&1; then
        export DISPLAY="$d" XAUTHORITY="$a"
        return 0
      fi
    done
  done
  return 1
}

# -- deteksi browser --------------------------------------------------------- #
cari_browser() {
  if [[ -n "${LUCIFER_BROWSER:-}" ]]; then echo "$LUCIFER_BROWSER"; return; fi
  for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
    command -v "$b" >/dev/null 2>&1 && { echo "$b"; return; }
  done
  echo ""
}

server_hidup() {
  curl -s -m 3 -o /dev/null "http://${HOST}:${PORT}/health" 2>/dev/null
}

# -- --stop ------------------------------------------------------------------ #
if [[ "${1:-}" == "--stop" ]]; then
  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "server dashboard dihentikan (pid $pid)"
    fi
    rm -f "$PIDFILE"
  else
    echo "tidak ada server yang dicatat di $PIDFILE"
  fi
  exit 0
fi

# -- --status ---------------------------------------------------------------- #
if [[ "${1:-}" == "--status" ]]; then
  if server_hidup; then
    echo "server HIDUP  -> $URL"
    curl -s -m 3 "http://${HOST}:${PORT}/api/status" | head -c 300; echo
  else
    echo "server MATI   (jalankan: lucifer-desktop)"
  fi
  exit 0
fi

# -- 1. pastikan server jalan ------------------------------------------------ #
if ! server_hidup; then
  echo "menjalankan server dashboard Lucifer di port ${PORT}..."
  if [[ ! -x "$PY" ]]; then
    echo "error: $PY tidak ada. Jalankan 'make' dulu di $DIR" >&2
    exit 1
  fi
  cd "$DIR"
  setsid "$PY" web --host "$HOST" --port "$PORT" >>"$LOG" 2>&1 &
  echo $! > "$PIDFILE"

  # tunggu siap (maks 15 detik) — tanpa sleep buta
  for _ in $(seq 1 30); do
    server_hidup && break
    sleep 0.5
  done
  if ! server_hidup; then
    echo "error: server gagal start. Log: $LOG" >&2
    tail -20 "$LOG" >&2 2>/dev/null
    exit 1
  fi
  echo "server siap: $URL"
else
  echo "server sudah jalan: $URL"
fi

# -- 2. buka jendela aplikasi ------------------------------------------------ #
if ! siapkan_display; then
  echo "peringatan: tidak menemukan sesi grafis (DISPLAY/XAUTHORITY)." >&2
  echo "           Server tetap jalan di $URL — buka manual di browser." >&2
  exit 0
fi
echo "sesi grafis: DISPLAY=$DISPLAY  ($(DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY xdpyinfo 2>/dev/null | grep -m1 dimensions | tr -s ' '))"

BROWSER="$(cari_browser)"
if [[ -z "$BROWSER" ]]; then
  echo "tidak ada Chrome/Chromium — membuka di browser default"
  xdg-open "$URL"
  exit 0
fi

PROFILE="${XDG_DATA_HOME:-$HOME/.local/share}/lucifer-linux/browser-profile"
mkdir -p "$PROFILE"

# --app  = jendela sendiri (tanpa address bar/tab) -> terasa seperti app native
# --class=LuciferLinux = agar ikon di dock memakai ikon Lucifer, bukan Chrome
nohup "$BROWSER" \
  --app="$URL" \
  --class=LuciferLinux \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=TranslateUI \
  >/dev/null 2>&1 &

echo "membuka jendela Lucifer Linux..."
