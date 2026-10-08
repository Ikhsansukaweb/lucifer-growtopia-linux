#!/usr/bin/env bash
# Tanda-tangani base-patched.apk + semua split dengan kunci yang SAMA,
# lalu pasang ke HP. Dijalankan SETELAH patch selesai.
#
# PENTING: memasang APK ini mengharuskan Growtopia di-uninstall dulu
# (tanda tangan berbeda). save.dat sudah dibackup di ~/gt-apk/backup/.
set -uo pipefail

BT=/home/ikhsan/Android/Sdk/build-tools/34.0.0
KERJA=/home/ikhsan/gt-apk
KS=$KERJA/lucifer.keystore
ALIAS=lucifer
PASS=lucifer123
PKG=com.rtsoft.growtopia

cd "$KERJA" || exit 1

echo "=== 1. buat keystore (kalau belum ada) ==="
if [ ! -f "$KS" ]; then
  keytool -genkeypair -v -keystore "$KS" -alias "$ALIAS" \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$PASS" -keypass "$PASS" \
    -dname "CN=Lucifer, OU=Bot, O=Lucifer, L=Yogyakarta, C=ID" 2>&1 | tail -3
  echo "  keystore dibuat: $KS"
else
  echo "  keystore sudah ada"
fi

echo
echo "=== 2. siapkan APK yang akan dipasang ==="
# base hasil patch -> nama harus base.apk saat install
cp -f base-patched.apk base-terpasang.apk 2>/dev/null || cp -f gt-patched.apk base-terpasang.apk

for f in base-terpasang.apk split_config.arm64_v8a.apk split_config.in.apk split_config.xhdpi.apk; do
  [ -f "$f" ] || { echo "  LEWAT (tidak ada): $f"; continue; }
  echo "  tanda-tangan: $f"
  zipalign -f -p 4 "$f" "align-$f" 2>/dev/null && mv -f "align-$f" "$f"
  "$BT/apksigner" sign --ks "$KS" --ks-key-alias "$ALIAS" \
    --ks-pass "pass:$PASS" --key-pass "pass:$PASS" "$f" 2>&1 | tail -2
  "$BT/apksigner" verify "$f" 2>&1 | head -2
done

echo
echo "=== 3. uninstall versi lama (WAJIB, tanda tangan beda) ==="
echo "  backup save.dat ada di: $KERJA/backup/save.dat"
adb uninstall "$PKG" 2>&1 | tail -2

echo
echo "=== 4. pasang semua APK sekaligus (install-multiple) ==="
adb install-multiple -r \
  base-terpasang.apk \
  split_config.arm64_v8a.apk \
  split_config.in.apk \
  split_config.xhdpi.apk 2>&1 | tail -5

echo
echo "=== 5. kembalikan save.dat (biar tidak perlu login ulang) ==="
adb shell mkdir -p "/sdcard/Android/data/$PKG/files" 2>/dev/null
adb push "$KERJA/backup/save.dat" "/sdcard/Android/data/$PKG/files/save.dat" 2>&1 | tail -1

echo
echo "=== 6. verifikasi terpasang ==="
adb shell pm path "$PKG" 2>&1 | head -5
