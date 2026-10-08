#!/usr/bin/env bash
# deploy/install.sh — Pasang Lucifer Linux sebagai layanan (systemd atau pm2).
#
# Pemakaian:
#   sudo bash deploy/install.sh                 # systemd, /opt/lucifer-linux
#   sudo bash deploy/install.sh --pm2           # pm2 (tanpa systemd)
#   sudo bash deploy/install.sh --dir /srv/lucifer --user lucifer

set -euo pipefail

TARGET_DIR="/opt/lucifer-linux"
RUN_USER="lucifer"
MODE="systemd"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pm2)   MODE="pm2"; shift ;;
    --dir)   TARGET_DIR="$2"; shift 2 ;;
    --user)  RUN_USER="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "opsi tidak dikenal: $1" >&2; exit 1 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Lucifer Linux — pemasangan"
echo "    sumber : $SRC_DIR"
echo "    tujuan : $TARGET_DIR"
echo "    user   : $RUN_USER"
echo "    mode   : $MODE"
echo

# -- 1. prasyarat ----------------------------------------------------------- #
echo "==> Memeriksa prasyarat"
command -v python3 >/dev/null || { echo "python3 tidak ada"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "butuh Python >= 3.10"; exit 1; }
command -v g++ >/dev/null || command -v clang++ >/dev/null \
  || { echo "butuh g++ atau clang++ untuk ENet"; exit 1; }
echo "    ok"

# -- 2. user & folder ------------------------------------------------------- #
if [[ "$MODE" == "systemd" ]]; then
  if ! id -u "$RUN_USER" >/dev/null 2>&1; then
    echo "==> Membuat user sistem '$RUN_USER'"
    useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
  fi
fi

if [[ "$SRC_DIR" != "$TARGET_DIR" ]]; then
  echo "==> Menyalin berkas ke $TARGET_DIR"
  mkdir -p "$TARGET_DIR"
  for item in lucifer scripts tests enet deploy data Makefile requirements.txt pyproject.toml README.md; do
    [[ -e "$SRC_DIR/$item" ]] && cp -r "$SRC_DIR/$item" "$TARGET_DIR/"
  done
fi
cd "$TARGET_DIR"

# -- 3. build --------------------------------------------------------------- #
echo "==> Kompilasi ENet + menyiapkan venv"
make >/dev/null
.venv/bin/pip install -q -e .

# -- 4. izin ---------------------------------------------------------------- #
if [[ "$MODE" == "systemd" ]]; then
  chown -R "$RUN_USER:$RUN_USER" "$TARGET_DIR"
  chmod 700 "$TARGET_DIR/data"
  [[ -f "$TARGET_DIR/data/accounts.json" ]] && chmod 600 "$TARGET_DIR/data/accounts.json"
fi

# -- 5. layanan ------------------------------------------------------------- #
if [[ "$MODE" == "systemd" ]]; then
  echo "==> Memasang unit systemd"
  install -m 644 deploy/lucifer.service /etc/systemd/system/lucifer.service
  mkdir -p /etc/lucifer
  if [[ ! -f /etc/lucifer/credentials.env ]]; then
    cat > /etc/lucifer/credentials.env <<'ENV'
# Kredensial Lucifer Linux — JANGAN dibagikan.
# Isi salah satu cara di bawah, lalu: sudo systemctl restart lucifer
#
# 1) GrowID (nama + sandi)
# LUCIFER_USER=NamaGrowID
# LUCIFER_PASS=sandiGrowID
#
# 2) ltoken (paling andal — lihat README bagian "Login Google")
# LUCIFER_USER=NamaGrowID
# LUCIFER_PASS=
# (lalu jalankan: lucifer login --ltoken "<TOKEN>")
ENV
    chmod 600 /etc/lucifer/credentials.env
    chown root:root /etc/lucifer/credentials.env
    echo "    dibuat /etc/lucifer/credentials.env (isi kredensialnya!)"
  fi
  systemctl daemon-reload
  systemctl enable lucifer >/dev/null 2>&1 || true
  echo
  echo "==> Selesai. Langkah berikutnya:"
  echo "    1. sudo nano /etc/lucifer/credentials.env      # isi kredensial"
  echo "    2. sudo -u $RUN_USER $TARGET_DIR/.venv/bin/lucifer doctor"
  echo "    3. sudo systemctl start lucifer"
  echo "    4. sudo journalctl -u lucifer -f"
  echo "    5. buka http://127.0.0.1:8787"

elif [[ "$MODE" == "pm2" ]]; then
  command -v pm2 >/dev/null || { echo "pm2 tidak ada — npm install -g pm2"; exit 1; }
  mkdir -p /var/log/lucifer
  echo "==> Menjalankan lewat pm2"
  pm2 start deploy/ecosystem.config.json
  pm2 save
  echo
  echo "==> Selesai. Perintah berguna:"
  echo "    pm2 logs lucifer-web"
  echo "    pm2 logs lucifer-bot"
  echo "    pm2 restart lucifer-web lucifer-bot"
  echo "    pm2 startup            # agar otomatis jalan saat boot"
fi
