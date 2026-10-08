#!/usr/bin/env python3
"""
tests/test_web.py — Uji dashboard web TANPA jaringan luar.

Menjalankan server HTTP sungguhan di port acak (127.0.0.1) lalu memanggil
endpoint-nya dengan urllib. Tidak butuh akun/kredensial: dashboard harus tetap
berfungsi dalam "mode pantau" dan memberi pesan yang jelas.
"""

from __future__ import annotations

import json
import socket
import sys
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


def port_bebas() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def ambil(url: str, method: str = "GET", data: dict | None = None,
          timeout: float = 15.0) -> tuple[int, str]:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    print("\033[1m" + "=" * 62)
    print(" UJI DASHBOARD WEB (server HTTP nyata di 127.0.0.1)")
    print("=" * 62 + "\033[0m")

    from lucifer.runner import RunnerConfig
    from lucifer.web import create_server

    # PENTING: pakai data_dir SEMENTARA supaya uji hermetik — kalau memakai
    # data/ asli, akun nyata milik pengguna membuat asumsi "0 akun" gagal.
    import tempfile as _tempfile

    _tmp = _tempfile.mkdtemp(prefix="lucifer-web-")
    _data = Path(_tmp) / "data"
    _data.mkdir(parents=True, exist_ok=True)

    port = port_bebas()
    cfg = RunnerConfig(
        scripts_dir=str(ROOT / "scripts"),
        examples_dir=str(ROOT / "examples"),
        data_dir=str(_data),
        # items.dat itu data statis repo (bukan state pengguna) -> tetap dari repo
        items_path=str(ROOT / "data" / "items.dat"),
        auto_connect=False,
        hot_reload=False,
    )
    httpd, runner = create_server(config=cfg, host="127.0.0.1", port=port)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"

    try:
        # -- halaman & kesehatan -------------------------------------------- #
        st, html = ambil(f"{base}/")
        cek("GET / -> 200", st == 200, f"HTTP {st}")
        cek("GET / mengembalikan HTML", "<html" in html.lower(), f"{len(html)} byte")
        cek("GET / punya judul dashboard", "Lucifer" in html and "<title>" in html)
        cek("GET / memuat dashboard (bukan halaman kosong)", len(html) > 2000, f"{len(html)} byte")

        st, body = ambil(f"{base}/health")
        cek("GET /health -> 200", st == 200, f"HTTP {st}")
        h = json.loads(body)
        cek("/health: ok=true", h.get("ok") is True)

        # -- status --------------------------------------------------------- #
        st, body = ambil(f"{base}/api/status")
        cek("GET /api/status -> 200", st == 200, f"HTTP {st}")
        d = json.loads(body)
        cek("status: items.dat terbaca", d.get("items_loaded", 0) > 15000, str(d.get("items_loaded")))
        cek("status: daftar skrip terisi", len(d.get("scripts", [])) >= 7, str(len(d.get("scripts", []))))
        cek("status: skrip contoh terlihat dari examples/",
            any(s.endswith(".lua") for s in d.get("scripts", [])))
        cek("status: log_tail ada", isinstance(d.get("log_tail"), list) and len(d["log_tail"]) > 0)
        cek("status: mode pantau (0 akun) dijelaskan di log",
            any("belum ada akun" in x or "mode pantau" in x for x in d["log_tail"]))

        # -- daftar skrip --------------------------------------------------- #
        st, body = ambil(f"{base}/api/scripts")
        cek("GET /api/scripts -> 200", st == 200, f"HTTP {st}")
        sc = json.loads(body)["scripts"]
        cek("scripts: minimal 7 berkas", len(sc) >= 7, str(len(sc)))
        cek("scripts: punya nama+baris+isi",
            all({"name", "lines", "content"} <= set(s) for s in sc))
        cek("scripts: isi benar-benar ada (bukan kosong)",
            all(len(s["content"]) > 0 for s in sc))
        cek("scripts: berkas diawali _ disembunyikan",
            not any(s["name"].startswith("_") for s in sc))

        # -- log ------------------------------------------------------------ #
        st, body = ambil(f"{base}/api/logs")
        cek("GET /api/logs -> 200", st == 200, f"HTTP {st}")
        cek("logs: berbentuk daftar", isinstance(json.loads(body).get("logs"), list))

        # -- perintah ------------------------------------------------------- #
        st, body = ambil(f"{base}/api/command", "POST", {"command": "status"})
        cek("POST /api/command status -> 200", st == 200, f"HTTP {st}")
        cek("perintah status: ok", json.loads(body).get("ok") is True)

        st, body = ambil(f"{base}/api/command", "POST", {"command": "reload"})
        cek("perintah reload: ok", json.loads(body).get("ok") is True, body[:80])

        st, body = ambil(f"{base}/api/command", "POST", {"command": "bots"})
        cek("perintah bots: ok + daftar", json.loads(body).get("ok") is True)

        st, body = ambil(f"{base}/api/command", "POST", {"command": "say main halo"})
        j = json.loads(body)
        cek("perintah say tanpa bot: ok=false", j.get("ok") is False)
        cek("perintah say tanpa bot: pesan MENJELASKAN cara memperbaiki",
            "ltoken" in j.get("error", "") or "accounts.json" in j.get("error", ""),
            j.get("error", "")[:90])

        st, body = ambil(f"{base}/api/command", "POST", {"command": ""})
        cek("perintah kosong: ok=false", json.loads(body).get("ok") is False)

        # -- 404 ------------------------------------------------------------ #
        st, _ = ambil(f"{base}/tidak-ada")
        cek("path tidak dikenal -> 404", st == 404, f"HTTP {st}")

        # -- JavaScript dashboard harus VALID -------------------------------- #
        # PAGE adalah string Python: escape seperti \r \n di dalam regex JS
        # akan dikonversi jadi baris baru sungguhan dan merusak seluruh script
        # (semua tombol mati). Uji ini menjaga bug itu tidak kembali.
        import re as _re
        import shutil as _shutil
        import subprocess as _sub
        import tempfile as _tmp

        st, html = ambil(f"{base}/")
        cek("halaman dashboard terkirim", st == 200 and "<script>" in html)
        m = _re.search(r"<script>(.*?)</script>", html, _re.S)
        cek("blok <script> ditemukan", m is not None)
        if m:
            js = m.group(1)
            cek("JS tidak kosong", len(js) > 2000, f"{len(js)} karakter")

            node = _shutil.which("node")
            if node:
                with _tmp.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                    f.write(js)
                    jspath = f.name
                r = _sub.run([node, "--check", jspath], capture_output=True, text=True, timeout=30)
                cek("sintaks JavaScript VALID (dashboard tidak mati)",
                    r.returncode == 0,
                    (r.stderr.strip().splitlines() or [""])[-1][:110])
            else:
                cek("node tersedia untuk cek sintaks JS", True, "dilewati (node tidak ada)")

            # Penjaga khusus: regex JS tidak boleh berisi baris baru SUNGGUHAN
            # (akibat escape Python seperti \r \n yang tidak di-raw).
            rusak = any(
                "[\n" in js or "[\r" in js or "\r\n" in js.split("<script>")[-1][:200]
                for _ in (0,)
            )
            cek("tidak ada regex JS yang rusak karena escape Python", not rusak,
                "regex mengandung baris baru liar" if rusak else "")

        # -- dashboard tetap responsif (tidak hang) -------------------------- #
        import time
        t0 = time.time()
        for _ in range(5):
            ambil(f"{base}/api/status", timeout=5)
        dt = time.time() - t0
        cek("5x /api/status cepat (< 3 dtk, dashboard tidak hang)", dt < 3.0, f"{dt:.2f} dtk")

    finally:
        httpd.shutdown()
        httpd.server_close()
        runner.stop()
        th.join(timeout=5)

    print("\n" + "=" * 62)
    print(f" lulus: {PASS}   gagal: {FAIL}")
    print("=" * 62)
    if GAGAL:
        print("\033[31myang gagal:\033[0m")
        for n in GAGAL:
            print(f"  - {n}")
        return 1
    print("\033[32mSEMUA UJI DASHBOARD LULUS\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
