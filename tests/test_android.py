#!/usr/bin/env python3
"""
tests/test_android.py — Uji modul ADB (lucifer/android.py).

Uji ini TIDAK butuh HP tersambung: bagian adb dipalsukan, supaya uji
selalu bisa dijalankan di mesin mana pun.
"""
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0
GAGAL: list[str] = []


def cek(nama, syarat, detail=""):
    global PASS, FAIL
    if syarat:
        PASS += 1
        print(f"  \u2713 {nama}")
    else:
        FAIL += 1
        GAGAL.append(nama)
        print(f"  \u2717 {nama}" + (f"\n      {detail}" if detail else ""))


def bagian(t):
    print()
    print(f"--- {t} ---")


from lucifer import android  # noqa: E402

print("=" * 70)
print("UJI MODUL ANDROID (adb)")
print("=" * 70)

# ------------------------------------------------------------------ #
bagian("1. cari_adb: menemukan adb atau gagal dengan jelas")
adb = android.cari_adb()
cek("cari_adb mengembalikan str", isinstance(adb, str))
cek("cari_adb tidak kosong", bool(adb), repr(adb))
cek("path adb ada di disk", Path(adb).exists(), adb)

# ------------------------------------------------------------------ #
bagian("2. _adb: perintah dijalankan lewat subprocess")
dipanggil = []


def adb_palsu(cmd, **kw):
    dipanggil.append(cmd)
    return types.SimpleNamespace(returncode=0, stdout=b"ok\n", stderr=b"")


asli_run = subprocess.run
subprocess.run = adb_palsu
try:
    keluar = android._adb("devices", batas=5)
    cek("_adb mengembalikan stdout", keluar.strip() == "ok", repr(keluar))
    cek("_adb memanggil subprocess", len(dipanggil) == 1, str(dipanggil))
    cek("perintah berisi 'devices'", "devices" in dipanggil[0], str(dipanggil[0]))
    cek("perintah berisi path adb", dipanggil[0][0] == android.cari_adb(),
        str(dipanggil[0][:2]))

    # _adb sengaja TIDAK melempar saat adb balas error (biar pemanggil
    # bisa memeriksa keluaran). Yang penting: keluaran tetap dikembalikan.
    subprocess.run = lambda cmd, **kw: types.SimpleNamespace(
        returncode=1, stdout=b"device offline\n", stderr=b"device offline")
    keluar_gagal = android._adb("shell", "true")
    cek("_adb tetap mengembalikan keluaran saat adb error",
        "offline" in keluar_gagal, repr(keluar_gagal))

    # AdbError dilempar kalau adb TIDAK ADA sama sekali.
    asli_cari = android.cari_adb
    android.cari_adb = lambda: (_ for _ in ()).throw(
        android.AdbError("adb tidak ditemukan — pasang: sudo apt install adb"))
    try:
        android._adb("devices")
        cek("AdbError dilempar kalau adb tidak ada", False, "tidak melempar")
    except android.AdbError as e:
        cek("AdbError dilempar kalau adb tidak ada", True)
        cek("pesan AdbError menyebut cara pasang", "apt install" in str(e), str(e))
    finally:
        android.cari_adb = asli_cari
finally:
    subprocess.run = asli_run

# ------------------------------------------------------------------ #
bagian("3. deteksi: HP ada & terisi lengkap")
keluaran_palsu = {
    ("devices",): "List of devices attached\nABC123\tdevice\n",
    ("shell", "getprop", "ro.product.model"): "Infinix X655C\n",
    ("shell", "getprop", "ro.build.version.release"): "10\n",
    ("shell", "getprop", "ro.build.version.sdk"): "29\n",
    ("shell", "getprop", "ro.product.cpu.abi"): "arm64-v8a\n",
    ("shell", "pm", "list", "packages", android.PAKET_GT):
        f"package:{android.PAKET_GT}\n",
    ("shell", "dumpsys", "package", android.PAKET_GT):
        "    versionName=5.58\n    targetSdk=35\n",
    ("shell", "su", "-c", "id"): "uid=0(root)\n",
    ("shell", "settings", "get", "global", "http_proxy"): "null\n",
    ("shell", "ls", "-l",
     f"/sdcard/Android/data/{android.PAKET_GT}/files/save.dat"):
        "-rw-rw---- 1 u0_a369 sdcard_rw 2641 save.dat\n",
}


def adb_palsu2(cmd, **kw):
    for kunci, nilai in keluaran_palsu.items():
        if all(x in cmd for x in kunci):
            return types.SimpleNamespace(returncode=0, stdout=nilai.encode(), stderr=b"")
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


subprocess.run = adb_palsu2
try:
    info = android.deteksi()
finally:
    subprocess.run = asli_run

cek("info.ada True", info.ada is True)
cek("serial terisi", info.serial == "ABC123", info.serial)
cek("model terbaca", info.model == "Infinix X655C", info.model)
cek("android terbaca", info.android == "10", info.android)
cek("sdk jadi int", info.sdk == 29, repr(info.sdk))
cek("abi terbaca", info.abi == "arm64-v8a", info.abi)
cek("gt_terpasang True", info.gt_terpasang is True)
cek("versi Growtopia terbaca", info.gt_versi == "5.58", info.gt_versi)
cek("root terdeteksi", info.root is True)
cek("ca_sistem_bisa ikut root", info.ca_sistem_bisa is True)
cek("ringkas() bisa dipanggil", isinstance(info.ringkas(), str))

# ------------------------------------------------------------------ #
bagian("4. deteksi: tidak ada HP -> tidak crash, ada catatan")


def adb_kosong(cmd, **kw):
    if "devices" in cmd:
        return types.SimpleNamespace(returncode=0,
                                     stdout=b"List of devices attached\n", stderr=b"")
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


subprocess.run = adb_kosong
try:
    info2 = android.deteksi()
finally:
    subprocess.run = asli_run

cek("tanpa HP: ada=False", info2.ada is False)
cek("tanpa HP: ada catatan", len(info2.catatan) > 0, str(info2.catatan))

# ------------------------------------------------------------------ #
bagian("5. HP ada tapi belum 'device' (belum izinkan USB debugging)")


def adb_unauthorized(cmd, **kw):
    if "devices" in cmd:
        return types.SimpleNamespace(
            returncode=0, stdout=b"List of devices attached\nABC123\tunauthorized\n",
            stderr=b"")
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


subprocess.run = adb_unauthorized
try:
    info3 = android.deteksi()
finally:
    subprocess.run = asli_run

cek("unauthorized: ada=True tapi serial kosong",
    info3.ada is True and info3.serial == "", f"{info3.ada}/{info3.serial}")
cek("unauthorized: ada catatan jelas", len(info3.catatan) > 0, str(info3.catatan))

# ------------------------------------------------------------------ #
bagian("6. hash_nama_ca: penamaan file CA Android (harus cocok)")


def jalankan_openssl(pem: Path) -> str:
    r = subprocess.run(
        ["openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-in", str(pem)],
        capture_output=True, text=True)
    return r.stdout.strip().splitlines()[0] if r.returncode == 0 else ""


tmp = Path("/tmp/uji-android-ca")
tmp.mkdir(parents=True, exist_ok=True)
pem = tmp / "ca.pem"
subprocess.run(
    ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
     "-keyout", str(tmp / "ca.key"), "-out", str(pem), "-subj", "/CN=Lucifer Test"],
    capture_output=True)
if pem.exists():
    h = android.hash_nama_ca(pem)
    h_openssl = jalankan_openssl(pem)
    cek("hash_nama_ca mengembalikan hex 8 digit",
        bool(h) and all(c in "0123456789abcdef" for c in h) and len(h) == 8, h)
    cek("hash cocok dengan openssl -subject_hash_old", h == h_openssl,
        f"kita={h} openssl={h_openssl}")
else:
    cek("openssl tersedia untuk membuat CA uji", False, "pem tidak dibuat")

# ------------------------------------------------------------------ #
bagian("7. pasang_proxy / hapus_proxy: perintah adb benar")
perintah: list[list[str]] = []


def adb_catat(cmd, **kw):
    perintah.append(list(cmd))
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


subprocess.run = adb_catat
try:
    android.pasang_proxy("192.168.1.5", 8080)
    android.hapus_proxy()
finally:
    subprocess.run = asli_run

gab = [" ".join(p) for p in perintah]
cek("pasang_proxy memakai settings put",
    any("settings put global http_proxy 192.168.1.5:8080" in g for g in gab), str(gab))
cek("hapus_proxy memakai settings put global http_proxy :0",
    any("http_proxy :0" in g for g in gab), str(gab))

# ------------------------------------------------------------------ #
bagian("8. tarik_save_dat: gagal dengan rapi kalau adb error")
subprocess.run = lambda cmd, **kw: types.SimpleNamespace(
    returncode=1, stdout=b"", stderr=b"device offline")
try:
    hasil = android.tarik_save_dat(tujuan="/tmp/uji-android-ca/t.dat")
finally:
    subprocess.run = asli_run
cek("tarik_save_dat mengembalikan dict", isinstance(hasil, dict))
cek("tarik_save_dat ok=False saat gagal", hasil.get("ok") is False, str(hasil))
cek("tarik_save_dat ada pesan", bool(hasil.get("pesan")), str(hasil))

# ------------------------------------------------------------------ #
bagian("9. PAKET_GT benar")
cek("PAKET_GT = com.rtsoft.growtopia",
    android.PAKET_GT == "com.rtsoft.growtopia", android.PAKET_GT)

print()
print("=" * 70)
print(f"HASIL: {PASS} lulus, {FAIL} gagal")
print("=" * 70)
if GAGAL:
    print("GAGAL:")
    for g in GAGAL:
        print(f"  - {g}")
sys.exit(1 if FAIL else 0)
