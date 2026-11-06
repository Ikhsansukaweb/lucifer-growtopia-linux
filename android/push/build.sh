#!/usr/bin/env bash
# Build APK Lucifer Token Push tanpa Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner.
set -euo pipefail

cd "$(dirname "$0")"
SDK="${ANDROID_SDK:-$HOME/Android/Sdk}"
BT="$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)"
JAR="$SDK/platforms/android-33/android.jar"
JAVAC="${JAVAC:-/opt/android-studio/jbr/bin/javac}"
KEYTOOL="${KEYTOOL:-/opt/android-studio/jbr/bin/keytool}"
OUT=build
APK="$OUT/lucifer-push.apk"

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "[1/6] aapt2 compile"
"$BT/aapt2" compile --dir res -o "$OUT/res.zip"

echo "[2/6] aapt2 link"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$JAR" \
  --manifest AndroidManifest.xml -R "$OUT/res.zip" \
  --java "$OUT/gen" --min-sdk-version 29 --target-sdk-version 29 \
  --auto-add-overlay

echo "[3/6] javac"
"$JAVAC" -source 8 -target 8 -nowarn \
  -bootclasspath "$JAR:$BT/core-lambda-stubs.jar" \
  -classpath "$JAR" -d "$OUT/classes" \
  $(find src "$OUT/gen" -name '*.java') 2>&1 | grep -v "bootstrap class path" || true

echo "[4/6] d8"
"$BT/d8" --release --min-api 29 --lib "$JAR" \
  --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')

echo "[5/6] gabung + zipalign"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q ../unsigned.apk classes.dex)
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "[6/6] tanda tangan"
KS="$OUT/lucifer.jks"
if [ ! -f "$KS" ]; then
  "$KEYTOOL" -genkeypair -keystore "$KS" -alias lucifer -keyalg RSA \
    -keysize 2048 -validity 10000 -storepass lucifer -keypass lucifer \
    -dname "CN=Lucifer Linux" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:lucifer \
  --key-pass pass:lucifer --out "$APK" "$OUT/aligned.apk"
"$BT/apksigner" verify "$APK" && echo "OK -> $APK"
