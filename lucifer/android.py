"""
lucifer/android.py — Bantu ambil ltoken dari HP Android lewat ADB.

LATAR BELAKANG (dibuktikan di mesin ini)
----------------------------------------
* Client Growtopia PC **crash** di Wine (CPU i5-2400 tidak punya AVX2, client
  butuh itu → SIGILL tepat di layar "confirm age").
* HP Android justru bisa menjalankan Growtopia dengan normal.
* Growtopia Android **tidak** punya `network_security_config.xml` → tidak ada
  certificate pinning → proxy MITM BISA bekerja, asal CA dipercaya sistem.

Modul ini membantu:
  1. memeriksa HP lewat ADB (versi, root, proxy),
  2. memasang CA Lucifer sebagai CA **sistem** (butuh root) atau memberi tahu
     kalau harus pakai cara lain,
  3. memasang/mencabut proxy di HP supaya trafiknya lewat `lucifer capture`.

Semua perintah `adb` dijalankan lewat subprocess; tidak ada dependensi baru.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Nama paket Growtopia di Android.
PAKET_GT = "com.rtsoft.growtopia"

# Lokasi CA sistem Android (untuk pemasangan lewat root).
_DIR_CA_SISTEM = "/system/etc/security/cacerts"
_DIR_CA_SISTEM_ALT = "/apex/com.android.conscrypt/cacerts"


class AdbError(RuntimeError):
    """Perintah adb gagal."""


def cari_adb() -> str:
    p = shutil.which("adb")
    if not p:
        raise AdbError("adb tidak ditemukan — pasang: sudo apt install adb")
    return p


def _adb(*args: str, batas: int = 60, perangkat: str = "") -> str:
    """Jalankan adb dan kembalikan stdout (teks)."""
    argv = [cari_adb()]
    if perangkat:
        argv += ["-s", perangkat]
    argv += list(args)
    hasil = subprocess.run(argv, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=batas, check=False)
    return hasil.stdout.decode("utf-8", "replace")


def _adb_biner(*args: str, batas: int = 120, perangkat: str = "") -> bytes:
    argv = [cari_adb()]
    if perangkat:
        argv += ["-s", perangkat]
    argv += list(args)
    hasil = subprocess.run(argv, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=batas, check=False)
    return hasil.stdout


@dataclass
class InfoHp:
    """Ringkasan keadaan HP Android."""
    ada: bool = False
    serial: str = ""
    model: str = ""
    android: str = ""
    sdk: int = 0
    abi: str = ""
    gt_terpasang: bool = False
    gt_versi: str = ""
    root: bool = False
    proxy: str = ""
    ca_sistem_bisa: bool = False
    catatan: list[str] = field(default_factory=list)

    def ringkas(self) -> str:
        baris = [
            f"perangkat : {self.model} ({self.serial})",
            f"android   : {self.android} (SDK {self.sdk}, {self.abi})",
            f"growtopia : {'versi ' + self.gt_versi if self.gt_terpasang else 'TIDAK terpasang'}",
            f"root      : {'ya' if self.root else 'tidak'}",
            f"proxy     : {self.proxy or '(kosong)'}",
            f"pasang CA : {'bisa (root)' if self.ca_sistem_bisa else 'butuh cara lain'}",
        ]
        return "\n".join(baris)


def deteksi(perangkat: str = "") -> InfoHp:
    """Periksa HP yang terhubung lewat ADB."""
    info = InfoHp()

    keluaran = _adb("devices", batas=20)
    baris_dev = [b for b in keluaran.splitlines()[1:] if b.strip()]
    if not baris_dev:
        info.catatan.append("tidak ada perangkat terhubung (nyalakan USB debugging)")
        return info

    info.ada = True
    if not perangkat:
        for b in baris_dev:
            bagian = b.split()
            if len(bagian) >= 2 and bagian[1] == "device":
                perangkat = bagian[0]
                break
        else:
            info.catatan.append("perangkat ada tapi belum 'device' "
                                "(terima dialog USB debugging di HP)")
            return info
    info.serial = perangkat

    def ambil(prop: str) -> str:
        return _adb("shell", "getprop", prop, perangkat=perangkat).strip()

    info.model = ambil("ro.product.model")
    info.android = ambil("ro.build.version.release")
    try:
        info.sdk = int(ambil("ro.build.version.sdk") or 0)
    except ValueError:
        info.sdk = 0
    info.abi = ambil("ro.product.cpu.abi")

    paket = _adb("shell", "pm", "list", "packages", PAKET_GT, perangkat=perangkat)
    info.gt_terpasang = PAKET_GT in paket
    if info.gt_terpasang:
        dump = _adb("shell", "dumpsys", "package", PAKET_GT, perangkat=perangkat)
        m = re.search(r"versionName=(\S+)", dump)
        if m:
            info.gt_versi = m.group(1)

    # root?
    cek_root = _adb("shell", "su", "-c", "id", perangkat=perangkat, batas=15)
    info.root = "uid=0" in cek_root
    if not info.root:
        cek2 = _adb("shell", "which", "su", perangkat=perangkat, batas=15)
        info.root = "su" in cek2 and "not found" not in cek2

    proxy = _adb("shell", "settings", "get", "global", "http_proxy",
                 perangkat=perangkat).strip()
    info.proxy = "" if proxy in ("null", "None") else proxy

    info.ca_sistem_bisa = info.root
    if not info.root and info.sdk >= 24:
        info.catatan.append(
            "Android 7+ tanpa root: CA pengguna tidak dipercaya app biasa. "
            "Perlu root, atau patch APK (network_security_config), "
            "atau pakai HP/emulator yang bisa root."
        )
    if info.gt_terpasang and not info.root:
        info.catatan.append(
            "Growtopia TIDAK punya certificate pinning (sudah diperiksa), "
            "jadi kalau CA bisa masuk ke sistem, MITM akan bekerja."
        )
    return info


def pasang_proxy(host: str, port: int, perangkat: str = "") -> None:
    """Set proxy global di HP."""
    _adb("shell", "settings", "put", "global", "http_proxy",
         f"{host}:{port}", perangkat=perangkat)
    _adb("shell", "settings", "put", "global", "global_http_proxy_host",
         host, perangkat=perangkat)
    _adb("shell", "settings", "put", "global", "global_http_proxy_port",
         str(port), perangkat=perangkat)


def hapus_proxy(perangkat: str = "") -> None:
    """Hapus proxy global di HP."""
    _adb("shell", "settings", "put", "global", "http_proxy", ":0",
         perangkat=perangkat)
    _adb("shell", "settings", "delete", "global", "global_http_proxy_host",
         perangkat=perangkat)
    _adb("shell", "settings", "delete", "global", "global_http_proxy_port",
         perangkat=perangkat)


def hash_nama_ca(pem: Path) -> str:
    """Android menyimpan CA dengan nama <hash>.<n> — hitung hash-nya."""
    # Android memakai subject hash (openssl x509 -subject_hash_old).
    for opsi in ("-subject_hash_old", "-subject_hash"):
        hasil = subprocess.run(
            ["openssl", "x509", "-inform", "PEM", "-in", str(pem),
             opsi, "-noout"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        teks = hasil.stdout.decode().strip()
        if teks and not teks.startswith("Error"):
            return teks.splitlines()[0]
    raise AdbError("gagal menghitung hash sertifikat (openssl bermasalah)")


def pasang_ca_sistem(pem: Path, perangkat: str = "") -> dict[str, Any]:
    """Pasang CA Lucifer sebagai CA SISTEM di HP (butuh root).

    Mengembalikan dict berisi hasil + langkah yang dilakukan.
    """
    hasil: dict[str, Any] = {"ok": False, "langkah": []}

    info = deteksi(perangkat)
    if not info.ada:
        hasil["pesan"] = "HP tidak terdeteksi"
        return hasil
    if not info.root:
        hasil["pesan"] = ("butuh root untuk memasang CA ke sistem — "
                          "lihat catatan di `lucifer android --info`")
        return hasil

    dev = perangkat or info.serial
    nama = f"{hash_nama_ca(pem)}.0"
    jarak = f"/data/local/tmp/{nama}"
    hasil["langkah"].append(f"nama CA di Android: {nama}")

    # 1. unggah sertifikat
    _adb("push", str(pem), jarak, perangkat=dev, batas=60)
    hasil["langkah"].append(f"unggah ke {jarak}")

    # 2. lepas proteksi tulis /system (kalau perlu) lalu salin
    _adb("shell", "su", "-c", "mount -o rw,remount /system 2>/dev/null || "
         "mount -o rw,remount / 2>/dev/null", perangkat=dev, batas=40)
    for tujuan in (_DIR_CA_SISTEM, _DIR_CA_SISTEM_ALT):
        perintah = (
            f"mkdir -p {tujuan} && cp {jarak} {tujuan}/{nama} && "
            f"chmod 644 {tujuan}/{nama} && "
            f"chown root:root {tujuan}/{nama}"
        )
        keluaran = _adb("shell", "su", "-c", perintah, perangkat=dev, batas=60)
        if "denied" in keluaran.lower() or "not found" in keluaran.lower():
            hasil["langkah"].append(f"gagal salin ke {tujuan}")
            continue
        hasil["langkah"].append(f"pasang di {tujuan}/{nama}")

    # 3. selaraskan direktori CA APEX (Android 10+)
    _adb("shell", "su", "-c",
         "for d in /apex/com.android.conscrypt/cacerts /system/etc/security/cacerts; do "
         f"[ -d $d ] && cp -f {jarak} $d/{nama}; done",
         perangkat=dev, batas=60)
    hasil["langkah"].append("salin ke direktori CA conscrypt (kalau ada)")

    # 4. verifikasi
    cek = _adb("shell", "su", "-c",
               f"ls -l {_DIR_CA_SISTEM}/{nama} 2>/dev/null; "
               f"ls -l {_DIR_CA_SISTEM_ALT}/{nama} 2>/dev/null",
               perangkat=dev, batas=30)
    hasil["verifikasi"] = cek.strip()
    hasil["ok"] = nama in cek
    if hasil["ok"]:
        hasil["pesan"] = ("CA terpasang. Mulai ulang HP (atau restart app) "
                          "supaya dipercaya sistem.")
    else:
        hasil["pesan"] = ("CA belum terpasang — kemungkinan /system terkunci "
                          "(butuh Magisk/system rw).")
    return hasil


def hapus_ca_sistem(pem: Path, perangkat: str = "") -> dict[str, Any]:
    """Cabut CA Lucifer dari sistem (butuh root)."""
    info = deteksi(perangkat)
    dev = perangkat or info.serial
    if not info.root:
        return {"ok": False, "pesan": "butuh root"}
    nama = f"{hash_nama_ca(pem)}.0"
    _adb("shell", "su", "-c",
         f"rm -f {_DIR_CA_SISTEM}/{nama} {_DIR_CA_SISTEM_ALT}/{nama} "
         f"/apex/com.android.conscrypt/cacerts/{nama} "
         f"/system/etc/security/cacerts/{nama}",
         perangkat=dev, batas=60)
    return {"ok": True, "pesan": f"CA {nama} dicabut"}


def info_save_dat(perangkat: str = "") -> dict[str, Any]:
    """Lihat save.dat Growtopia di HP (tanpa root, lewat penyimpanan luar)."""
    hasil: dict[str, Any] = {"ada": False}
    jarak = f"/sdcard/Android/data/{PAKET_GT}/files/save.dat"
    keluaran = _adb("shell", "ls", "-l", jarak, perangkat=perangkat, batas=30)
    if "No such file" in keluaran or "not found" in keluaran.lower():
        return hasil
    hasil["ada"] = True
    hasil["info"] = keluaran.strip()
    return hasil


def tarik_save_dat(tujuan: Path | str = "", perangkat: str = "") -> dict[str, Any]:
    """Salin save.dat dari HP ke komputer (tanpa root).

    save.dat berisi GrowID, nama tank, dan Token (terenkripsi) — berguna untuk
    memastikan akun mana yang login, dan untuk cadangan.
    """
    jarak = f"/sdcard/Android/data/{PAKET_GT}/files/save.dat"
    if not tujuan:
        tujuan = Path(__file__).resolve().parent.parent / "data" / "save-hp.dat"
    tujuan = Path(tujuan)
    tujuan.parent.mkdir(parents=True, exist_ok=True)

    try:
        keluaran = _adb("pull", jarak, str(tujuan), perangkat=perangkat, batas=120)
    except AdbError as e:
        return {"ok": False, "pesan": str(e)}
    if not tujuan.exists() or tujuan.stat().st_size == 0:
        return {"ok": False, "pesan": f"gagal menyalin: {keluaran.strip()[:120]}"}
    return {"ok": True, "tujuan": str(tujuan), "ukuran": tujuan.stat().st_size}
