#!/usr/bin/env bash
# deploy/pasang-desktop.sh — pasang Lucifer Linux sebagai aplikasi GUI native
# (icon di daftar aplikasi, bisa dicari lewat Activities/launcher).
#
#   bash deploy/pasang-desktop.sh            # build + pasang
#   bash deploy/pasang-desktop.sh --hapus    # cabut entri menu + binary

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_SRC="$DIR/desktop/build/lucifer-desktop"
BIN_DST="$HOME/.local/bin/lucifer-desktop"
ICON_SRC="$DIR/deploy/icons/lucifer.png"
ICON_DST="$HOME/.local/share/icons/hicolor/256x256/apps/lucifer.png"
DESK_DIR="$HOME/.local/share/applications"
DESK="$DESK_DIR/lucifer.desktop"

if [[ "${1:-}" == "--hapus" ]]; then
  rm -f "$BIN_DST" "$ICON_DST" "$DESK"
  update-desktop-database "$DESK_DIR" 2>/dev/null || true
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "dicabut: entri menu, ikon, dan $BIN_DST"
  exit 0
fi

echo "==> build GUI native"
command -v cmake >/dev/null || { echo "butuh cmake" >&2; exit 1; }
cmake -S "$DIR/desktop" -B "$DIR/desktop/build" \
      -DCMAKE_MAKE_PROGRAM=/usr/bin/make >/dev/null
cmake --build "$DIR/desktop/build" -j"$(nproc)" >/dev/null
[[ -x "$BIN_SRC" ]] || { echo "build gagal: $BIN_SRC tidak ada" >&2; exit 1; }

echo "==> pasang binary + ikon + entri menu"
mkdir -p "$(dirname "$BIN_DST")" "$(dirname "$ICON_DST")" "$DESK_DIR"
install -m 755 "$BIN_SRC" "$BIN_DST"
install -m 644 "$ICON_SRC" "$ICON_DST"

sed "s|^Exec=.*|Exec=$BIN_DST|" "$DIR/deploy/lucifer.desktop" >"$DESK"
chmod 644 "$DESK"

update-desktop-database "$DESK_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "selesai. Cari \"Lucifer\" di daftar aplikasi, atau jalankan: lucifer-desktop"
echo "  (backend Python dinyalakan otomatis oleh GUI)"
