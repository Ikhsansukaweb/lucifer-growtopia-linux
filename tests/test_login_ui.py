#!/usr/bin/env python3
"""
tests/test_login_ui.py — Uji fitur login dari dashboard (tanpa jaringan luar).

Yang diuji:
  * endpoint /api/login menyimpan akun ke accounts.json (izin 600)
  * validasi input (label kosong, kredensial kosong)
  * bot otomatis dibuat setelah akun ditambah
  * /api/accounts tidak membocorkan sandi/token penuh
  * /api/account/delete menghapus akun + bot
  * pengurai client_data (dipakai form ltoken) — diuji lewat Python
  * halaman dashboard memuat elemen form login

Tidak butuh kredensial asli: ltoken diverifikasi ke server, jadi kalau
jaringan mati tes tetap lulus (hanya catatan "tidak bisa cek token").
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0
GAGAL: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if kondisi:
        PASS += 1
        print(f"  \033[32m✓\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    else:
        FAIL += 1
        GAGAL.append(nama)
        print(f"  \033[31m✗\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    return kondisi


def bagian(judul: str) -> None:
    print(f"\n\033[1m== {judul} ==\033[0m")


def post(base: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.loads(r.read().decode())


def test_tangkap_code_e2e() -> None:
    """Uji penangkapan hasil login dari browser end-to-end (tanpa akun Google).

    Dua jalur diuji:

    A. Jalur `code` (CADANGAN) — server lokal meniru Google:
       redirect ke `.../google/callback?code=..&state=..`.
       Dipakai kalau halaman token tidak pernah muncul.

    B. Jalur TOKEN (UTAMA) — meniru perilaku GT yang sesungguhnya:
       callback -> redirect ke `/player/link/dashboard/validate/<payload>`
       yang isinya JSON `{"status":"success","token":"<ltoken>"}`.
       Ini yang benar, karena `code` OAuth hanya sekali pakai dan Chrome-lah
       yang memakainya (dulu kode menukar `code` lagi -> "Token is invalid").

    Kalau lingkungan tidak punya layar (DISPLAY kosong), uji dilewati.
    """
    import http.server
    import json as _json
    import socketserver
    import threading as _th

    from lucifer.google import POLA_VALIDATE, tangkap_code_dari_browser

    CODE = "4/0AX4XfWg_CODE-UJI-123"
    STATE = "STATE-UJI-abc"
    TOKEN = "eyJ0YW5rSUROYW1lIjoiVEVTVCJ9.TOKEN-E2E-UJI"

    # ---------------- A. jalur `code` (cadangan) ----------------
    # CATATAN: Chrome SELALU mengikuti redirect. Kalau diarahkan ke host GT
    # asli, ia akan benar-benar menembak server GT — jadi jalur cadangan ini
    # diuji dengan URL callback lokal (`/google/callback?code=..`) supaya
    # deterministik dan tidak menyentuh server GT.
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/go":
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_address[1]}"
                    f"/google/callback?code={CODE}&state={STATE}")
                self.end_headers()
            else:
                # halaman callback (isi tidak penting untuk jalur cadangan)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>callback</body></html>")

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        hasil = tangkap_code_dari_browser(
            f"http://127.0.0.1:{port}/go", batas=40, tampilkan=False)
    finally:
        srv.shutdown()

    if not hasil.ok and "tidak ada layar" in hasil.message:
        print("  \033[90m~ dilewati: tidak ada DISPLAY (lingkungan tanpa X)\033[0m")
        return
    cek("e2e (A): `code` cadangan tertangkap", hasil.ok, hasil.message)
    cek("e2e (A): nilai `code` benar", hasil.code == CODE, repr(hasil.code))

    # ---------------- B. jalur TOKEN (utama) ----------------
    # tiru GT: /go -> 302 ke halaman validate (dilayani server lokal ini juga)
    keluaran = {"port": 0}

    class H2(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/go":
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{keluaran['port']}{POLA_VALIDATE}p/q")
                self.end_headers()
            elif POLA_VALIDATE in self.path:
                body = _json.dumps({
                    "status": "success", "message": "Account Validated.",
                    "token": TOKEN, "url": "",
                    "accountType": "growtopia", "accountAge": 2})
                raw = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    srv2 = socketserver.TCPServer(("127.0.0.1", 0), H2)
    keluaran["port"] = srv2.server_address[1]
    _th.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        hasil2 = tangkap_code_dari_browser(
            f"http://127.0.0.1:{keluaran['port']}/go", batas=40,
            tampilkan=False)
    finally:
        srv2.shutdown()

    cek("e2e (B): token dibaca dari halaman hasil", hasil2.ok, hasil2.message)
    cek("e2e (B): nilai token benar", hasil2.token == TOKEN,
        repr(hasil2.token[:40]))
    cek("e2e (B): jalur = baca_halaman",
        (hasil2.details or {}).get("cara") == "baca_halaman",
        str(hasil2.details))


def test_bersihkan_lock_basi() -> None:
    """`SingletonLock` BASI harus dibersihkan, yang SAH jangan disentuh.

    Bug nyata: setelah Chrome di-kill, `SingletonLock -> <host>-<pid>` milik
    proses mati tertinggal. Chrome lalu menolak start dan gejalanya
    "DevTools tidak menjawab" (padahal Chrome tidak jalan sama sekali).
    """
    import os as _os
    import tempfile as _tf

    from lucifer.google import _bersihkan_lock_basi

    d = _tf.mkdtemp(prefix="lucifer-lock-")
    lock = _os.path.join(d, "SingletonLock")

    # lock BASI: PID yang pasti tidak ada
    for n in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = _os.path.join(d, n)
        if _os.path.lexists(p):
            _os.remove(p)
        _os.symlink("host-999999", p)
    dibersihkan = _bersihkan_lock_basi(d)
    cek("lock basi: dilaporkan dibersihkan", dibersihkan)
    cek("lock basi: SingletonLock hilang",
        not _os.path.lexists(lock))
    cek("lock basi: SingletonCookie hilang",
        not _os.path.lexists(_os.path.join(d, "SingletonCookie")))

    # lock SAH: PID proses yang benar-benar hidup (proses ini sendiri)
    _os.symlink(f"host-{_os.getpid()}", lock)
    cek("lock sah (proses hidup): TIDAK dihapus",
        _bersihkan_lock_basi(d) is False and _os.path.lexists(lock))

    # bukan symlink / tidak ada lock -> jangan error
    _os.remove(lock)
    cek("tanpa lock: aman (False)", _bersihkan_lock_basi(d) is False)

    import shutil as _sh
    _sh.rmtree(d, ignore_errors=True)


def test_pilih_tab() -> None:
    """Pemilihan tab CDP harus utamakan tab alur login, bukan tab lama.

    Bug nyata: profil persisten membuat Chrome me-restore tab lama; kalau CDP
    menempel ke tab itu, peristiwa `code` terlewat.
    """
    from lucifer.google import _pilih_tab

    pages = [
        {"url": "chrome://newtab/", "id": "a"},
        {"url": "https://www.google.com/", "id": "b"},
        {"url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=x", "id": "c"},
    ]
    cek("pilih_tab: lewati chrome://", _pilih_tab(pages)["id"] != "a")
    cek("pilih_tab: utamakan akun Google",
        _pilih_tab(pages)["id"] == "c")

    # `ingin` harus menang walau bukan tab pertama
    pages2 = [{"url": "about:blank", "id": "x"},
              {"url": "http://127.0.0.1:9/go", "id": "y"}]
    cek("pilih_tab: cocokkan `ingin`",
        _pilih_tab(pages2, ingin="http://127.0.0.1:9/go")["id"] == "y")
    cek("pilih_tab: kosong -> None", _pilih_tab([]) is None)


def main() -> int:
    print("\033[1m" + "=" * 62)
    print(" UJI LOGIN DARI DASHBOARD")
    print("=" * 62 + "\033[0m")

    tmp = Path(tempfile.mkdtemp(prefix="lucifer-login-"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (tmp / "scripts").mkdir(exist_ok=True)

    from lucifer.runner import Runner, RunnerConfig
    from lucifer.web import create_server

    cfg = RunnerConfig(
        accounts=[],
        scripts_dir=str(tmp / "scripts"),
        examples_dir=str(tmp / "contoh-tidak-ada"),
        data_dir=str(data_dir),
        items_path=str(ROOT / "data" / "items.dat"),
        auto_connect=False,
        hot_reload=False,
    )
    runner = Runner(cfg)
    runner.setup()

    httpd, _ = create_server(runner=runner, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    acc_file = data_dir / "accounts.json"

    try:
        # ------------------------------------------------------------------ #
        bagian("1. Halaman dashboard memuat form login")
        with urllib.request.urlopen(base + "/", timeout=20) as r:
            html = r.read().decode()
        cek("judul halaman", "Lucifer Linux" in html)
        cek("ada panel 'Login Akun'", "Login Akun" in html)
        cek("ada tab ltoken", 'id="tab-ltoken"' in html)
        cek("ada tab GrowID", 'id="tab-growid"' in html)
        cek("ada input ltoken", 'id="lt-token"' in html)
        cek("ada input nama GrowID", 'id="gd-user"' in html)
        cek("ada input sandi (type=password)", 'type="password"' in html)
        cek("ada tombol simpan+login", "loginLtoken()" in html and "loginGrowid()" in html)
        cek("ada panel 'Akun Tersimpan'", "Akun Tersimpan" in html)
        cek("ada tombol hapus akun", "hapusAkun" in html)
        cek("ada pengurai client_data di JS", "uraiClientData" in html)

        # ------------------------------------------------------------------ #
        bagian("2. Validasi input ditolak dengan pesan jelas")
        d = post(base, "/api/login", {})
        cek("label kosong ditolak", d.get("ok") is False, str(d.get("error", ""))[:60])

        d = post(base, "/api/login", {"label": "main"})
        cek("tanpa kredensial ditolak", d.get("ok") is False, str(d.get("error", ""))[:70])
        cek("pesan menyebut ltoken/sandi", "ltoken" in str(d.get("error", "")).lower())
        cek("tidak ada file akun dibuat", not acc_file.exists())

        # ------------------------------------------------------------------ #
        bagian("3. Tambah akun pakai ltoken")
        d = post(base, "/api/login", {"label": "utama", "ltoken": "DUMMY_TOKEN_1234567890"})
        cek("respons ok", d.get("ok") is True, json.dumps(d)[:120])
        cek("method otomatis 'token'", d.get("method") == "token")
        cek("ditandai akun baru", d.get("baru") is True)
        cek("bot dibuat", d.get("bot_dibuat") is True)
        cek("file accounts.json terbentuk", acc_file.exists())

        if acc_file.exists():
            isi = json.loads(acc_file.read_text())
            cek("berisi 1 akun", len(isi) == 1, f"{len(isi)} entri")
            cek("label tersimpan", isi[0].get("label") == "utama")
            cek("ltoken tersimpan", isi[0].get("ltoken") == "DUMMY_TOKEN_1234567890")
            mode = oct(acc_file.stat().st_mode)[-3:]
            cek("izin file 600 (rahasia aman)", mode == "600", f"mode={mode}")

        # ------------------------------------------------------------------ #
        bagian("4. Bot muncul di runner")
        cek("bot 'utama' ada di engine", "utama" in runner.engine.bots)
        cek("engine.parent diisi", runner.engine.parent is not None)

        # ------------------------------------------------------------------ #
        bagian("5. /api/accounts TIDAK membocorkan rahasia")
        d = get(base, "/api/accounts")
        akun = d.get("accounts", [])
        cek("1 akun terdaftar", len(akun) == 1)
        a = akun[0] if akun else {}
        cek("label tampil", a.get("label") == "utama")
        cek("flag punya_ltoken", a.get("punya_ltoken") is True)
        blob = json.dumps(akun)
        cek("token penuh TIDAK bocor", "DUMMY_TOKEN_1234567890" not in blob)
        cek("sandi tersamar", a.get("password") in ("", "***"))

        # ------------------------------------------------------------------ #
        bagian("6. Update akun yang sama (bukan duplikat)")
        d = post(base, "/api/login", {"label": "utama", "ltoken": "TOKEN_BARU_0987654321"})
        cek("respons ok", d.get("ok") is True)
        cek("ditandai BUKAN baru", d.get("baru") is False)
        isi = json.loads(acc_file.read_text())
        cek("tetap 1 akun (tidak duplikat)", len(isi) == 1, f"{len(isi)} entri")
        cek("token diperbarui", isi[0].get("ltoken") == "TOKEN_BARU_0987654321")

        # ------------------------------------------------------------------ #
        bagian("7. Tambah akun GrowID -> sandi DITUKAR jadi ltoken")
        # Server login ditiru supaya uji tidak bergantung jaringan/sandi nyata.
        import lucifer.runner as _rmod

        _asli_gl = _rmod.growid_login
        from lucifer.account import LoginResult as _LR

        _rmod.growid_login = lambda u, p, **k: _LR(
            True, "growid", token="LTOKEN_GROWID_7fQ2mZpL4vT8nB3wR6sY1d")
        try:
            d = post(base, "/api/login",
                     {"label": "alt", "username": "BudiGT", "password": "rahasia123"})
        finally:
            _rmod.growid_login = _asli_gl

        cek("respons ok", d.get("ok") is True, json.dumps(d)[:110])
        cek("method jadi 'token' (sandi sudah ditukar)",
            d.get("method") == "token", str(d.get("method")))
        isi = json.loads(acc_file.read_text())
        cek("sekarang 2 akun", len(isi) == 2, f"{len(isi)} entri")
        alt = next((x for x in isi if x.get("label") == "alt"), {})
        cek("ltoken hasil penukaran tersimpan",
            alt.get("ltoken") == "LTOKEN_GROWID_7fQ2mZpL4vT8nB3wR6sY1d",
            str(alt)[:130])
        cek("username tersimpan", alt.get("username") == "BudiGT")
        cek("sandi TIDAK ikut disimpan (sudah ditukar jadi ltoken)",
            not alt.get("password"), str(alt)[:130])
        cek("2 bot di engine", len(runner.engine.bots) == 2, f"{len(runner.engine.bots)} bot")

        # ------------------------------------------------------------------ #
        bagian("8. Connect/disconnect dari dashboard")
        d = post(base, "/api/connect", {"label": "tidak-ada"})
        cek("label salah ditolak", d.get("ok") is False, str(d.get("error", ""))[:50])

        d = post(base, "/api/disconnect", {"label": "utama"})
        cek("disconnect berhasil", d.get("ok") is True)
        cek("bot dilaporkan diputus", "utama" in d.get("diputus", []))

        # ------------------------------------------------------------------ #
        bagian("9. Hapus akun")
        d = post(base, "/api/account/delete", {"label": "alt"})
        cek("hapus berhasil", d.get("ok") is True)
        isi = json.loads(acc_file.read_text())
        cek("tinggal 1 akun", len(isi) == 1, f"{len(isi)} entri")
        cek("akun 'alt' hilang", all(x.get("label") != "alt" for x in isi))
        cek("bot 'alt' hilang dari engine", "alt" not in runner.engine.bots)
        cek("1 bot tersisa", len(runner.engine.bots) == 1)

        d = post(base, "/api/account/delete", {"label": "tidak-ada"})
        cek("hapus label salah ditolak", d.get("ok") is False)

        # ------------------------------------------------------------------ #
        bagian("10. Status & health tetap normal")
        d = get(base, "/api/status")
        cek("status punya accounts_list", isinstance(d.get("accounts_list"), list))
        cek("jumlah akun benar", d.get("accounts") == 1, f"accounts={d.get('accounts')}")
        d = get(base, "/health")
        cek("health ok", d.get("ok") is True)

    finally:
        httpd.shutdown()
        httpd.server_close()
        runner.stop()

    # ---------------------------------------------------------------------- #
    bagian("11. Pengurai client_data (dipakai form ltoken)")
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ltok", ROOT / "tools" / "ltoken.py")
        ltok = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(ltok)

        per_baris = "tankIDName|IkhsanGT\nltoken|AbCdEf1234567890XyZ\ntankIDPass|x\nrid|DEADBEEF\n"
        r = ltok.parse_client_data(per_baris)
        cek("bentuk per baris: ltoken", r.get("ltoken") == "AbCdEf1234567890XyZ")
        cek("bentuk per baris: nama", r.get("tankIDName") == "IkhsanGT")
        cek("bentuk per baris: rid", r.get("rid") == "DEADBEEF")

        import base64 as _b64
        r = ltok.parse_client_data(_b64.b64encode(per_baris.encode()).decode())
        cek("bentuk base64: ltoken", r.get("ltoken") == "AbCdEf1234567890XyZ")

        r = ltok.parse_client_data("tankIDName|BudiGT|ltoken|Zz11Yy22Xx33Ww44|rid|CAFE")
        cek("bentuk satu baris: ltoken", r.get("ltoken") == "Zz11Yy22Xx33Ww44")
        cek("bentuk satu baris: nama benar", r.get("tankIDName") == "BudiGT")

        r = ltok.parse_client_data("tankIDName|TanpaToken|tankIDPass|abc")
        cek("blok tanpa ltoken -> tidak ada ltoken", not r.get("ltoken"))
    except Exception as e:  # noqa: BLE001
        cek("pengurai client_data bisa dipanggil", False, f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------------------- #
    bagian("12. Tab GrowID menukar sandi jadi ltoken (perbaikan penting)")
    import tempfile as _tf

    from lucifer.account import LoginResult
    from lucifer.runner import Runner as _Runner
    from lucifer.runner import RunnerConfig as _Cfg

    with _tf.TemporaryDirectory() as _tmp:
        _cfg = _Cfg(data_dir=Path(_tmp), examples_dir=Path(_tmp))
        _r = _Runner(_cfg)

        # -- gagal: akun TIDAK boleh disimpan, pesan server diteruskan -- #
        import lucifer.runner as _mod

        _asli = _mod.growid_login
        _mod.growid_login = lambda u, p, **k: LoginResult(
            False, "growid",
            message="Please try login again.; CSRF token mismatch.")
        try:
            h = _r.tambah_akun(label="gagal", username="nama", password="sandi")
        finally:
            _mod.growid_login = _asli
        cek("GrowID gagal -> ok False", h.get("ok") is False, str(h)[:120])
        cek("pesan server diteruskan", "try login again" in (h.get("error") or ""),
            str(h.get("error"))[:120])
        cek("ada saran untuk pengguna", bool(h.get("saran")), str(h.get("saran"))[:80])
        cek("akun gagal TIDAK disimpan",
            not (Path(_tmp) / "accounts.json").exists(),
            "accounts.json seharusnya belum dibuat")

        # -- berhasil: sandi ditukar jadi ltoken, method jadi "token" -- #
        _mod.growid_login = lambda u, p, **k: LoginResult(
            True, "growid", token="LTOKEN_DARI_GROWID_9f2QmZ7Lx4Tb1Wn8Kd")
        try:
            h2 = _r.tambah_akun(label="berhasil", username="nama", password="sandi")
        finally:
            _mod.growid_login = _asli
        cek("GrowID berhasil -> ok True", h2.get("ok") is True, str(h2)[:120])
        cek("method jadi token (bukan growid)",
            h2.get("method") == "token", str(h2.get("method")))
        _akun = json.loads((Path(_tmp) / "accounts.json").read_text())
        cek("ltoken tersimpan", _akun[0].get("ltoken") ==
            "LTOKEN_DARI_GROWID_9f2QmZ7Lx4Tb1Wn8Kd", str(_akun[0])[:140])
        cek("sandi TIDAK disimpan (sudah ditukar)",
            not _akun[0].get("password"), str(_akun[0])[:140])

        # ------------------------------------------------------------------ #
        bagian("7. Penangkapan `code` dari browser (end-to-end, CDP)")
        test_tangkap_code_e2e()

        # ------------------------------------------------------------------ #
        bagian("8. Ketahanan browser (lock basi & pemilihan tab)")
        test_bersihkan_lock_basi()
        test_pilih_tab()

    print()
    print("=" * 62)
    if FAIL:
        print(f"  \033[31m{FAIL} GAGAL\033[0m / {PASS} lulus")
        for n in GAGAL:
            print(f"    - {n}")
    else:
        print(f"  \033[32mSEMUA {PASS} UJI LULUS\033[0m")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
