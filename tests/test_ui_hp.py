#!/usr/bin/env python3
"""
tests/test_ui_hp.py — Uji UI dashboard: tab "Dari HP" benar-benar berfungsi.

Bukan sekadar memeriksa HTML mengandung string — JS dashboard dijalankan
di Node dengan DOM tiruan, lalu dibuktikan bahwa:
  * pilihTab('hp') menampilkan panel HP & menyembunyikan panel lain
  * tombol "Ambil Token dari HP" memanggil POST /api/login/hp
  * body yang dikirim memuat label & connect

Jalankan:  .venv/bin/python tests/test_ui_hp.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

lulus = 0
gagal = 0


def cek(nama: str, syarat: bool, info: str = "") -> None:
    global lulus, gagal
    if syarat:
        lulus += 1
        print(f"  {GREEN}✓{RESET} {nama}")
    else:
        gagal += 1
        print(f"  {RED}✗{RESET} {nama}  {DIM}{info}{RESET}")


NODE_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.log(JSON.stringify({error: 'tanpa <script>'})); process.exit(0); }

const dibuat = {};
function el(id) {
  if (!dibuat[id]) {
    dibuat[id] = {
      id, style: {}, textContent: '', value: '', checked: true,
      innerHTML: '', className: '', onclick: null,
      getAttribute: () => null, querySelectorAll: () => [],
      addEventListener: () => {}, closest: () => null,
    };
  }
  return dibuat[id];
}
const dipanggil = [];
const sandbox = {
  console,
  document: {
    getElementById: el, querySelector: () => null, querySelectorAll: () => [],
    addEventListener: () => {}, readyState: 'complete',
  },
  window: {},
  fetch: async (url, opt) => {
    dipanggil.push({url, opt});
    return {ok: true, status: 200, json: async () => ({ok: true}), text: async () => '{}'};
  },
  localStorage: {getItem: () => null, setItem: () => {}},
  setInterval: () => 0, clearInterval: () => {},
  setTimeout: (f) => { try { f(); } catch (e) {} return 0; },
  JSON, Math, Date, Object, Array, String, Number, RegExp, Error, Promise,
};
sandbox.globalThis = sandbox;

const hasil = {};

try {
  vm.createContext(sandbox);
  vm.runInContext(m[1], sandbox);
  hasil.js_ok = true;
} catch (e) {
  console.log(JSON.stringify({js_ok: false, error: e.message}));
  process.exit(0);
}

// pilihTab('hp')
el('pane-ltoken').style.display = '';
el('pane-growid').style.display = 'none';
el('pane-hp').style.display = 'none';
sandbox.pilihTab('hp');
hasil.pane_hp_tampil = el('pane-hp').style.display === '';
hasil.pane_ltoken_tersembunyi = el('pane-ltoken').style.display === 'none';
hasil.pane_growid_tersembunyi = el('pane-growid').style.display === 'none';
hasil.tab_hp_aktif = el('tab-hp').className === 'active';

// klik tombol
el('hp-label').value = 'main';
el('hp-connect').checked = false;
hasil.fungsi_ada = typeof sandbox.loginDariHP === 'function';

(async () => {
  if (hasil.fungsi_ada) {
    await sandbox.loginDariHP();
    const f = dipanggil.find(x => x.url && x.url.includes('/api/login/hp'));
    hasil.endpoint_dipanggil = !!f;
    if (f) {
      try {
        const b = JSON.parse(f.opt.body);
        hasil.body = b;
        hasil.label_benar = b.label === 'main';
        hasil.connect_benar = b.connect === false;
      } catch (e) { hasil.body_error = String(e); }
    }
    hasil.status_terisi = (el('loginout').textContent || '').length > 0;
  }
  console.log(JSON.stringify(hasil));
})();
"""


def main() -> int:
    print(f"{BOLD}Uji UI dashboard — tab 'Dari HP'{RESET}")

    node = shutil.which("node")
    if not node:
        print(f"  {DIM}(node tidak ada — uji dilewati){RESET}")
        return 0

    from lucifer.runner import RunnerConfig
    from lucifer.web import create_server

    tmp = Path(tempfile.mkdtemp(prefix="lucifer-uihp-"))
    data = tmp / "data"
    data.mkdir(parents=True)
    (tmp / "scripts").mkdir(exist_ok=True)

    cfg = RunnerConfig(
        scripts_dir=str(ROOT / "scripts"),
        examples_dir=str(ROOT / "examples"),
        data_dir=str(data),
        items_path=str(ROOT / "data" / "items.dat"),
        auto_connect=False,
        hot_reload=False,
    )
    httpd, runner = create_server(config=cfg, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            html = r.read().decode("utf-8", "replace")

        print(f"\n{BOLD}1. Halaman & JS{RESET}")
        cek("halaman terkirim", len(html) > 2000, f"{len(html)} byte")
        cek("ada tab 'Dari HP'", "tab-hp" in html)
        cek("ada panel 'Dari HP'", "pane-hp" in html)
        cek("ada tombol ambil token", "loginDariHP" in html)

        # tulis skrip node ke berkas sementara
        jsfile = tmp / "uji.js"
        jsfile.write_text(NODE_SCRIPT)
        htmlfile = tmp / "page.html"
        htmlfile.write_text(html)

        out = subprocess.run([node, str(jsfile), str(htmlfile)],
                             capture_output=True, text=True, timeout=60)
        teks = (out.stdout or "").strip().splitlines()
        hasil = json.loads(teks[-1]) if teks else {}

        print(f"\n{BOLD}2. JS dashboard dijalankan (Node + DOM tiruan){RESET}")
        cek("JS jalan tanpa error", hasil.get("js_ok") is True,
            str(hasil.get("error", ""))[:80])
        cek("fungsi loginDariHP ada", hasil.get("fungsi_ada") is True)

        print(f"\n{BOLD}3. Tab 'Dari HP' berfungsi{RESET}")
        cek("pilihTab('hp') menampilkan panel HP", hasil.get("pane_hp_tampil") is True)
        cek("panel ltoken disembunyikan", hasil.get("pane_ltoken_tersembunyi") is True)
        cek("panel growid disembunyikan", hasil.get("pane_growid_tersembunyi") is True)
        cek("tab hp jadi aktif", hasil.get("tab_hp_aktif") is True)

        print(f"\n{BOLD}4. Tombol memanggil endpoint yang benar{RESET}")
        cek("memanggil POST /api/login/hp", hasil.get("endpoint_dipanggil") is True,
            str(hasil.get("body_error", ""))[:80])
        cek("label ikut terkirim", hasil.get("label_benar") is True,
            json.dumps(hasil.get("body", {}))[:80])
        cek("connect ikut terkirim", hasil.get("connect_benar") is True)
        cek("status ditampilkan ke pengguna", hasil.get("status_terisi") is True)

        print(f"\n{BOLD}5. Endpoint /api/login/hp nyata{RESET}")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/login/hp",
            data=json.dumps({"label": "uji", "connect": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read())
            # Tanpa HP tersambung -> ok=False dengan pesan jelas (bukan 500)
            cek("endpoint menjawab JSON (bukan crash)",
                isinstance(j, dict) and ("ok" in j or "error" in j), str(j)[:80])
            cek("pesan error jelas bila HP tak ada",
                j.get("ok") is True or bool(j.get("error")), str(j)[:90])
        except Exception as e:  # noqa: BLE001
            cek("endpoint menjawab JSON (bukan crash)", False,
                f"{type(e).__name__}: {e}"[:90])

    finally:
        httpd.shutdown()

    print("\n" + "=" * 62)
    warna = GREEN if gagal == 0 else RED
    print(f"{warna}{BOLD} HASIL: {lulus} lulus, {gagal} gagal{RESET}")
    print("=" * 62)
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
