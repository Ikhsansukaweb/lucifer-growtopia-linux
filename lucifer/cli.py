"""
lucifer.cli — Antarmuka baris perintah.

Perintah:
    lucifer doctor            Cek lingkungan (ENet, lupa, jaringan, server GT)
    lucifer probe             Uji handshake ENet ke server Growtopia asli
    lucifer items [file]      Tampilkan isi items.dat (cari/nama)
    lucifer scripts           Daftar skrip Lua yang tersedia
    lucifer run [opsi]        Jalankan bot + skrip Lua
    lucifer web [opsi]        Jalankan dashboard web
    lucifer lua <file>        Jalankan satu file Lua (butuh akun)
    lucifer check <file>      Cek sintaks file Lua tanpa menjalankan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from . import __version__
from .account import (fetch_server_data, pesan_penolakan_login,
                      sedang_maintenance)
from .bot import BotStatus
from .items import ItemDatabase
from .runner import ROOT, Runner, RunnerConfig, load_config

BANNER = r"""
  _                       _  _
 | |   _   _  ___(_) __ _ | |(_)_ __
 | |  | | | |/ __| |/ _` || || | '__|     Lucifer Linux  v{ver}
 | |__| |_| | (__| | (_| || || | |        API Lua Lucifer V1.8 untuk Growtopia
 |_____\__,_|\___|_|\__,_|_|/ |_|
                          |__/
"""


def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(t: str) -> str:
    return _c("32", t)


def bad(t: str) -> str:
    return _c("31", t)


def warn(t: str) -> str:
    return _c("33", t)


def dim(t: str) -> str:
    return _c("90", t)


def head(t: str) -> str:
    return _c("1;36", t)


# Pesan yang dikirim server Growtopia secara GENERIK — artinya request-nya
# belum memenuhi bentuk yang diharapkan, BUKAN bahwa tokennya salah.
# Dibuktikan: token asli dari save.dat dan token ngawur dibalas persis sama.
_PESAN_GENERIK = (
    "token is invalid",
    "please try login again",
    "please try again",
)


def _respons_generik(res) -> bool:
    """True bila pesan server bersifat generik (tidak membedakan token benar/salah)."""
    msg = (getattr(res, "message", "") or "").lower()
    return any(p in msg for p in _PESAN_GENERIK)


def _pisah_code_state(teks: str) -> tuple[str, str]:
    """Terima `code` polos ATAU URL callback utuh, kembalikan (code, state).

    Pengguna sering menyalin SELURUH URL callback
    (`https://login.growtopiagame.com/google/callback?code=4/0A...&state=...`).
    Menempelkannya utuh dulu gagal karena `code`-nya jadi mengandung `?`/`&`.
    Fungsi ini menerima keduanya, dan mengembalikan `state` juga — karena
    server Growtopia mewajibkan `state` ikut dikirim (tanpa itu HTTP 500).
    """
    teks = (teks or "").strip().strip('"').strip("'")
    if "code=" in teks and ("://" in teks or "?" in teks):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(teks).query)
        code = (q.get("code") or [""])[0]
        state = (q.get("state") or [""])[0]
        if code:
            return code, state
    return teks, ""


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args) -> int:
    print(head("== Lucifer Linux — pemeriksaan lingkungan =="))
    problems = 0

    # Python
    print(f"\n{head('Python')}")
    print(f"  versi      : {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print(bad("  ✗ butuh Python >= 3.10"))
        problems += 1
    else:
        print(ok("  ✓ versi memadai"))

    # ENet
    print(f"\n{head('ENet (patch Growtopia)')}")
    try:
        from .enet import ENetHost, library_path, load_library

        load_library()  # muat lebih dulu supaya path-nya bisa dilaporkan
        lib = library_path()
        print(ok(f"  ✓ library dimuat: {lib}"))
        host = ENetHost()
        print(ok("  ✓ host dibuat, patch new-packet + crc32 + range-coder aktif"))
        host.close()
    except Exception as e:  # noqa: BLE001
        print(bad(f"  ✗ {e}"))
        problems += 1

    # lupa
    print(f"\n{head('Lua runtime (lupa)')}")
    try:
        import lupa  # noqa: PLC0415

        lua = lupa.LuaRuntime()
        print(ok(f"  ✓ lupa {lupa.__version__} — {lua.eval('_VERSION')}"))
    except Exception as e:  # noqa: BLE001
        print(bad(f"  ✗ {e}"))
        print(dim("     perbaiki: pip install lupa"))
        problems += 1

    # items.dat
    print(f"\n{head('items.dat')}")
    p = Path(args.items)
    if p.exists():
        try:
            db = ItemDatabase.from_file(p)
            print(ok(f"  ✓ {p} — {len(db)} item (versi {db.version})"))
            for name in ("World Lock", "Dirt", "Pepper"):
                f = db.find(name, exact=True)
                if f:
                    print(dim(f"     contoh: {f[0].id} = {f[0].name}"))
        except Exception as e:  # noqa: BLE001
            print(bad(f"  ✗ gagal membaca: {e}"))
            problems += 1
    else:
        print(warn(f"  ! {p} belum ada (bot akan memintanya dari server)"))

    # akun
    print(f"\n{head('Akun')}")
    acc_path = Path(ROOT / "data" / "accounts.json")
    if acc_path.exists():
        try:
            from .account import load_accounts  # noqa: PLC0415

            accs = load_accounts(acc_path)
            print(ok(f"  ✓ {acc_path} — {len(accs)} akun"))
            for a in accs:
                print(dim(f"     - {a.redacted()}"))
        except Exception as e:  # noqa: BLE001
            print(bad(f"  ✗ {e}"))
            problems += 1
    elif os.environ.get("LUCIFER_USER"):
        print(ok(f"  ✓ dari env: {os.environ['LUCIFER_USER']}"))
    else:
        print(warn("  ! belum ada akun (data/accounts.json atau env LUCIFER_USER/LUCIFER_PASS)"))

    # jaringan
    print(f"\n{head('Jaringan ke Growtopia')}")
    try:
        t0 = time.time()
        sd = fetch_server_data()
        dt = (time.time() - t0) * 1000
        print(ok(f"  ✓ server_data OK ({dt:.0f} ms)"))
        print(dim(f"     server: {sd.get('server')}:{sd.get('port')}"))
        print(dim(f"     meta  : {sd.get('meta', '')[:32]}..."))
        if sedang_maintenance(sd):
            # `maint` tanpa `#` bisa berarti maintenance ATAU rate-limit
            # ("wait N seconds before logging in again") — bedakan!
            penolak = pesan_penolakan_login(sd)
            print(warn(f"  ! {penolak}"))
            print(dim("     bot tidak akan bisa connect sampai ini selesai;"))
            print(dim("     ini bukan masalah jaringan/IP-mu."))
    except Exception as e:  # noqa: BLE001
        print(bad(f"  ✗ {e}"))
        problems += 1

    print()
    if problems:
        print(bad(f"== {problems} masalah ditemukan =="))
    else:
        print(ok("== semua siap — jalankan: lucifer run =="))
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #
def cmd_probe(args) -> int:
    import struct  # noqa: PLC0415

    from .enet import ENetHost  # noqa: PLC0415
    from .protocol import NetMessage, decode_text, parse_packet  # noqa: PLC0415

    print(head("== Uji handshake ENet ke server Growtopia =="))
    sd = fetch_server_data()
    host, port = sd["server"], int(sd["port"])
    print(f"  target : {host}:{port}")

    # Cek maintenance DULU. PENTING: hanya `maint` TANPA `#` yang berarti
    # maintenance aktif — baris `#maint` selalu ada dan BUKAN tanda apa pun.
    if sedang_maintenance(sd):
        penolak = pesan_penolakan_login(sd)
        print(warn(f"  ! {penolak}"))
        print(dim("     server tetap memberi host+port, tapi port itu tidak menjawab."))
        print(dim("     coba lagi setelah ini selesai."))
        return 2

    h = ENetHost()
    t0 = time.time()
    if not h.connect(host, port, args.timeout * 1000):
        print(bad("  ✗ ENet connect gagal"))
        h.close()
        return 1
    print(ok(f"  ✓ tersambung dalam {(time.time()-t0)*1000:.0f} ms (ping {h.ping} ms)"))

    print("  menunggu ServerHello...")
    deadline = time.time() + args.timeout
    got = False
    while time.time() < deadline:
        ev = h.service(1500)
        if ev.kind == "receive":
            mtype, payload = parse_packet(ev.data)
            try:
                name = NetMessage(mtype).name
            except ValueError:
                name = f"#{mtype}"
            print(ok(f"  ✓ paket masuk: type={mtype} ({name}) {len(ev.data)} byte"))
            got = True
            if mtype == NetMessage.ServerHello:
                print(ok("  ✓ SERVERHELLO — transport & codec terbukti bekerja"))
            break
        if ev.kind in ("disconnect", "timeout"):
            print(bad(f"  ✗ {ev.kind}"))
            break
    h.close()
    if not got:
        print(warn("  ! tidak ada paket dalam batas waktu"))
        return 1
    return 0


# --------------------------------------------------------------------------- #
# items
# --------------------------------------------------------------------------- #
def cmd_items(args) -> int:
    p = Path(args.file)
    if not p.exists():
        print(bad(f"file tidak ditemukan: {p}"))
        return 1
    db = ItemDatabase.from_file(p)
    print(head(f"== items.dat: {p} =="))
    print(f"  versi: {db.version}   jumlah item: {len(db)}")
    if args.search:
        found = db.find(args.search, exact=args.exact)
        print(f"\n  hasil pencarian '{args.search}': {len(found)}")
        for it in found[: args.limit]:
            print(f"   #{it.id:<7} {it.name:<38} rarity={it.rarity:<4} grow={it.grow_time:<8} material={it.material}")
    else:
        print("\n  contoh item pertama:")
        for it in list(db)[: args.limit]:
            print(f"   #{it.id:<7} {it.name}")
    return 0


# --------------------------------------------------------------------------- #
# scripts
# --------------------------------------------------------------------------- #
def cmd_scripts(args) -> int:
    folders = [args.dir]
    if args.dir == "scripts" and Path("examples").exists():
        folders.append("examples")
    total = 0
    for folder in folders:
        d = Path(folder)
        if not d.exists():
            if len(folders) == 1:
                print(bad(f"folder tidak ada: {d}"))
                return 1
            continue
        files = sorted(d.glob("*.lua"))
        print(head(f"== skrip di {d} =="))
        if not files:
            print(warn("  (kosong — taruh skrip .lua di sini)"))
            continue
        for f in files:
            n = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            mark = dim(" (contoh, diawali _)") if f.name.startswith("_") else ""
            print(f"  {f.name:<28} {n:>5} baris{mark}")
            total += 1
        print()
    print(dim(f"total {total} berkas .lua"))
    return 0


# --------------------------------------------------------------------------- #
# check (sintaks Lua)
# --------------------------------------------------------------------------- #
def cmd_check(args) -> int:
    try:
        from lupa import LuaRuntime  # noqa: PLC0415
    except ImportError:
        print(bad("butuh 'lupa': pip install lupa"))
        return 1
    lua = LuaRuntime()
    rc = 0
    for name in args.files:
        p = Path(name)
        if not p.exists():
            print(bad(f"  ✗ {name} tidak ada"))
            rc = 1
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            lua.execute(f"return function()\n{src}\nend")
            print(ok(f"  ✓ {p.name} sintaks OK"))
        except Exception as e:  # noqa: BLE001
            print(bad(f"  ✗ {p.name}: {e}"))
            rc = 1
    return rc


# --------------------------------------------------------------------------- #
# lua (jalankan file)
# --------------------------------------------------------------------------- #
def cmd_lua(args) -> int:
    from .account import Account, load_accounts  # noqa: PLC0415
    from .lua_api import LuaEngine  # noqa: PLC0415

    cfg = load_config(args.config)
    if not cfg.accounts:
        cfg.accounts = load_accounts(ROOT / "data" / "accounts.json")
    if not cfg.accounts and not args.dry_run:
        print(bad("butuh akun (data/accounts.json atau env LUCIFER_USER/LUCIFER_PASS)"))
        print(dim("  tip: pakai --dry-run untuk menguji skrip tanpa login"))
        return 1

    items_db = None
    if Path(cfg.items_path).exists():
        items_db = ItemDatabase.from_file(cfg.items_path)

    engine = LuaEngine(
        accounts=cfg.accounts or [],
        items_db=items_db,
        scripts_dir=cfg.scripts_dir,
        data_dir=cfg.data_dir,
    )

    p = Path(args.file)
    if not p.exists():
        print(bad(f"file Lua tidak ditemukan: {p}"))
        return 1

    if not args.dry_run:
        for acc in engine.accounts:
            engine._new_bot(acc, acc.label)
        if args.connect:
            for bot in engine.bots.values():
                bot.connect()
                time.sleep(1)
    else:
        # Mode dry-run: sediakan satu bot placeholder supaya getBot() tidak nil
        # (skrip tetap bisa diuji tanpa kredensial / tanpa koneksi).
        placeholder = engine.accounts[0] if engine.accounts else Account(
            username="dry_run", password="", method="legacy", label="dry_run"
        )
        engine._new_bot(placeholder, placeholder.label)

    print(head(f"== menjalankan {p.name} =="))
    okrun = engine.run_script_file(p)
    if not okrun:
        return 1
    try:
        engine._listen_events(args.listen)
    except KeyboardInterrupt:
        pass
    engine.stop()
    return 0


def cmd_login(args) -> int:
    """lucifer login — login ke Growtopia dan simpan ltoken.

    Tiga cara:
      --ltoken <token>   simpan ltoken yang sudah kamu punya (paling andal)
      --google <id_token> tukar id_token Google jadi ltoken
      --growid           login GrowID (username + password) -> ltoken
    """
    import json as _json  # noqa: PLC0415

    from .account import Account, check_token, growid_login, social_login  # noqa: PLC0415

    out_path = Path(args.out)
    print(head("== Lucifer Linux — login & simpan ltoken =="))

    token = ""
    how = ""
    info: dict[str, Any] = {}

    if args.ltoken:
        res = check_token(args.ltoken) if args.verify else None
        token, how = args.ltoken, "ltoken-langsung"
        if res is not None:
            if res.ok:
                token = res.token
                print(ok(f"  ✓ ltoken VALID ({res.message})"))
            else:
                print(bad(f"  ✗ ltoken ditolak server: {res.message}"))
                if not args.force:
                    print(dim("     pakai --force untuk menyimpan tetap"))
                    return 1

    elif getattr(args, "code", "") or getattr(args, "google_browser", False):
        # Login Google lewat OAuth web flow (cara Growlauncher).
        #
        # Growtopia punya OAuth client bertipe "Web" (client_id ada di base.apk
        # resmi). Karena bertipe Web, Google MENGIZINKAN redirect ke
        # https://login.growtopiagame.com/google/callback — jadi tidak perlu
        # SDK native. Alurnya:
        #   browser -> pilih akun Google -> callback?code=..
        #           -> server GT tukar code -> JSON {token: <ltoken>}
        from .google import (  # noqa: PLC0415
            buat_state,
            login_google,
            url_login_google,
        )

        if args.code:
            # Terima `code` polos ATAU seluruh URL callback yang disalin utuh.
            code, state = _pisah_code_state(args.code)
            print(dim("  memakai `code` yang kamu berikan..."))
            res = login_google(code=code, state=state, verifikasi=args.verify)
        else:
            # `state` dibuat SEKALI di sini, lalu dipakai untuk URL yang
            # ditampilkan DAN untuk browser. Server Growtopia mewajibkan
            # callback membawa `state` (tanpa itu -> HTTP 500), jadi nilainya
            # harus konsisten dari awal.
            st = buat_state()
            url = url_login_google(state=st)
            print(dim("  membuka browser — pilih akun Google, lalu setujui."))
            print(dim("  (sandi Google TIDAK diminta oleh Lucifer; kamu yang"))
            print(dim("   memilih akunnya sendiri di jendela browser)"))
            print(dim(f"  batas tunggu: {args.detik} detik"))
            print(dim(f"  kalau browser tidak terbuka, buka manual URL ini:\n     {url}"))
            res = login_google(batas=args.detik, state=st,
                               verifikasi=args.verify)

        if not res.ok:
            print(bad(f"  ✗ login Google gagal: {res.message}"))
            if res.raw:
                print(dim(f"     balasan server: {res.raw[:200]}"))
            m = (res.message or "").lower()
            if "please try login again" in m:
                print(dim("     artinya: server TIDAK mengenali sesi/`state` kita."))
                print(dim("     `state` harus diterbitkan server GT, bukan dibuat"))
                print(dim("     sendiri. Pakai tombol \"Login with Google\" di halaman"))
                print(dim("     resmi (atau Growlauncher), lalu tempel URL callback-nya:"))
                print(dim("       lucifer login --code \"<URL callback>\" --verify"))
            elif "token is invalid" in m:
                print(dim("     artinya: `code` OAuth sudah dipakai/kedaluwarsa."))
                print(dim("     `code` hanya berlaku SEKALI. Ulangi alur resmi dan"))
                print(dim("     tempel URL callback yang BARU:"))
                print(dim("       lucifer login --code \"<URL callback>\" --verify"))
            else:
                print(dim("     alternatif: buka URL login Google di atas, setelah"))
                print(dim("     disetujui browser mendarat di halaman `google/callback`."))
                print(dim("     Salin SELURUH URL itu (atau hanya nilai `code`-nya), lalu:"))
                print(dim("       lucifer login --code \"<URL atau code>\" --verify"))
            return 1
        token, how = res.token, "google-web"
        print(ok(f"  ✓ ltoken didapat ({len(token)} char)"))
        if res.details.get("accountType"):
            info["accountType"] = res.details["accountType"]
            print(dim(f"     tipe akun: {res.details['accountType']}"))
        if args.verify and res.details.get("verify"):
            tanda = ok if res.details.get("verify_ok") else bad
            print(tanda(f"     verifikasi: {res.details['verify']}"))

    elif args.google:
        res = social_login(args.google, "google")
        if not res.ok:
            print(bad(f"  ✗ login Google gagal: {res.message}"))
            for t in (res.details or {}).get("dicoba", []):
                print(dim(f"     {t}"))
            return 1
        token, how = res.token, "google"
        print(ok("  ✓ token Google ditukar jadi ltoken"))

    elif getattr(args, "dari_hp", False):
        # Jalur HP, tiga cara (otomatis, berurutan sampai berhasil).
        #
        #  D. save.dat  -> field `Token` (472 char). Ditukar lewat
        #     POST /player/growid/checktoken {refreshToken, clientData}.
        #
        #     JUJUR: per 2026-09-29 jalur ini BELUM menghasilkan token. Server
        #     menjawab status `redirect` / "Token is invalid." — pesan yang
        #     SAMA PERSIS untuk token asli maupun token ngawur (sudah diuji),
        #     jadi server menolak sebelum token diperiksa. Karena itu kalau
        #     gagal kita TIDAK berhenti, tapi lanjut ke jalur logcat.
        #
        #  A. logcat    -> id_token Google yang ditulis klien GT sendiri.
        #  B. proxy     -> `lucifer capture` (manual, lewat APK ter-patch).
        from .ltoken import (  # noqa: PLC0415
            tangkap_id_token,
            token_dari_hp,
            tukar_id_token,
        )

        print(head("  Mengambil token dari HP..."))
        cap = token_dari_hp()
        lanjut_ke_logcat = False

        if cap.ok:
            print(ok(f"  ✓ refreshToken dari save.dat ({len(cap.ltoken)} char)"))
            res = check_token(cap.ltoken)
            if res.ok:
                token, how = res.token, "hp/save.dat"
                info["accountType"] = (res.details or {}).get("accountType", "")
                print(ok(f"  ✓ token disegarkan — akun {info['accountType']} "
                         f"({len(token)} char)"))
            else:
                print(bad(f"  ✗ server menolak: {res.message}"))
                if _respons_generik(res):
                    print(dim("     pesan ini GENERIK (token asli & ngawur sama) —"))
                    print(dim("     server menolak sebelum token diperiksa."))
                    lanjut_ke_logcat = True
                else:
                    return 1
        else:
            print(dim(f"     {cap.pesan}"))
            lanjut_ke_logcat = True

        if lanjut_ke_logcat and token == "":
            print(dim("     → mencoba jalur logcat (login Google di HP)..."))
            cap = tangkap_id_token(durasi=args.detik)
            if not cap.ok:
                print(bad(f"  ✗ {cap.pesan}"))
                if cap.mentah:
                    print(dim("     log terakhir: " + cap.mentah[-300:].replace("\n", " | ")))
                print(dim("     alternatif: `lucifer capture` (proxy MITM) atau "
                          "tempel ltoken manual di dashboard."))
                return 1
            print(ok(f"  ✓ id_token Google tertangkap ({len(cap.id_token)} char)"))
            print(dim("     menukar ke token lewat login.growtopiagame.com..."))
            tukar = tukar_id_token(cap.id_token)
            if tukar.ok and tukar.ltoken:
                token, how = tukar.ltoken, "hp/google"
                print(ok("  ✓ id_token ditukar jadi token"))
            else:
                print(bad(f"  ⚠ penukaran otomatis gagal: {tukar.pesan}"))
                info["id_token"] = cap.id_token
                token, how = "", "hp/id_token-saja"
                if not args.force:
                    print(dim("     jalankan dengan --force untuk menyimpan id_token saja"))
                    return 1

    elif args.growid:
        pw = args.password or os.environ.get("LUCIFER_PASS", "")
        if not pw:
            import getpass  # noqa: PLC0415

            pw = getpass.getpass("  password GrowID: ")
        res = growid_login(args.growid, pw)
        if not res.ok:
            print(bad(f"  ✗ login GrowID gagal: {res.message}"))
            for t in (res.details or {}).get("dicoba", []):
                print(dim(f"     {t}"))
            return 1
        token, how = res.token, "growid"
        print(ok("  ✓ ltoken diperoleh"))
    else:
        print(bad("  pilih salah satu: --ltoken <t> | --google <id_token> | "
                  "--dari-hp | --growid <nama>"))
        return 1

    # simpan
    acc = Account(
        username=args.name or "main", method="token", ltoken=token,
        label=args.label or (args.name or "main"),
    )
    if args.redacted:
        # Mode redacted: hanya untuk ditampilkan/dibagikan, tulis apa adanya.
        data = {"accounts": [acc.redacted() | {"ltoken": "***"}]}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        print(ok(f"  ✓ disimpan (REDACTED) ke {out_path}"))
        return 0

    # PENTING: pakai upsert_account supaya label yang sama DIGANTI, bukan
    # ditambahkan lagi (dulu login berulang menghasilkan akun duplikat).
    from .account import upsert_account  # noqa: PLC0415

    path, baru = upsert_account(out_path, acc)
    print(ok(f"  ✓ disimpan ke {path} (izin 600)"))
    print(dim(f"     metode: {how} | ltoken: {token[:14]}..."))
    if not baru:
        print(dim("     (akun dengan label ini sudah ada — diperbarui)"))
    print(dim("     jalankan: lucifer run"))
    return 0


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def cmd_run(args) -> int:
    print(BANNER.format(ver=__version__))
    cfg = load_config(args.config) if args.config else RunnerConfig()
    if args.accounts:
        cfg.accounts = __import__("lucifer.account", fromlist=["load_accounts"]).load_accounts(args.accounts)
    if args.scripts:
        cfg.scripts_dir = args.scripts
    if args.data:
        cfg.data_dir = args.data
        cfg.items_path = str(Path(args.data) / "items.dat")
    if args.username:
        cfg.username = args.username
    if args.no_reload:
        cfg.hot_reload = False
    if args.no_connect:
        cfg.auto_connect = False
    if args.log:
        cfg.log_file = args.log

    try:
        runner = Runner(cfg)
        runner.setup()
    except Exception as e:  # noqa: BLE001
        print(bad(f"gagal menyiapkan runner: {e}"))
        return 1
    runner.start(block=True)
    return 0


# --------------------------------------------------------------------------- #
# web
# --------------------------------------------------------------------------- #
def cmd_ltoken(args) -> int:
    """lucifer ltoken — ambil ltoken dari blok client_data ATAU dari kredensial.

    Dua mode:
        lucifer ltoken --data "<blok client_data>"   (hasil proxy debug)
        lucifer ltoken --growid <nama> -p <sandi>    (hitung sendiri)
    """
    import subprocess  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415

    # --- Mode baru: hitung langsung dari kredensial (tanpa HP, tanpa proxy) ---
    if getattr(args, "growid", ""):
        import base64 as _b64  # noqa: PLC0415
        import re as _re  # noqa: PLC0415

        from .ltoken import ltoken_dari_kredensial  # noqa: PLC0415

        pw = args.password or os.environ.get("LUCIFER_PASS", "")
        if not pw:
            import getpass  # noqa: PLC0415

            pw = getpass.getpass("  password GrowID: ")
        lt = ltoken_dari_kredensial(args.growid, pw)
        if args.json:
            import json as _json  # noqa: PLC0415

            print(_json.dumps({
                "ok": True, "growid": args.growid, "ltoken": lt,
                "panjang": len(lt),
            }, indent=2))
        else:
            print(ok(f"  ✓ ltoken dihitung ({len(lt)} char) untuk {args.growid}"))
            print(dim("     " + _re.sub(r"password=[^&]*", "password=***",
                                         _b64.b64decode(lt).decode()[:110]) + "..."))
            print()
            print(head("  ltoken:"))
            print("  " + lt)
        if args.save:
            from .account import Account  # noqa: PLC0415

            Account(username=args.growid, method="token", ltoken=lt,
                    label=args.label or args.growid).save()
            print(ok("  ✓ disimpan ke data/accounts.json"))
        return 0

    kandidat = [
        _P(__file__).resolve().parent.parent / "tools" / "ltoken.py",
        _P.home() / ".local" / "share" / "lucifer-linux" / "ltoken.py",
    ]
    skrip = next((p for p in kandidat if p.exists()), None)
    if skrip is None:
        print(bad("tools/ltoken.py tidak ditemukan"))
        return 1

    argv = [sys.executable, str(skrip)]
    if args.data:
        argv += ["--data", args.data]
    if args.file:
        argv += ["--file", args.file]
    if args.clipboard:
        argv.append("--clipboard")
    if args.save:
        argv.append("--save")
    if args.label:
        argv += ["--label", args.label]
    if args.json:
        argv.append("--json")
    return subprocess.call(argv)


def cmd_desktop(args) -> int:
    """lucifer desktop — buka Lucifer sebagai aplikasi desktop.

    Menjalankan skrip deploy/lucifer-desktop.sh: server dashboard dinyalakan
    di latar, lalu dibuka di Chrome mode --app (jendela sendiri, tanpa UI
    browser) sehingga terasa seperti aplikasi native.
    """
    import subprocess  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415

    # GUI native (GTK3) diutamakan kalau sudah dibangun.
    repo = _P(__file__).resolve().parent.parent
    native = [
        repo / "desktop" / "build" / "lucifer-desktop",
        _P.home() / ".local" / "bin" / "lucifer-desktop",
    ]
    biner = next((p for p in native if p.exists() and os.access(p, os.X_OK)), None)
    if biner is not None:
        argv = [str(biner), "--repo", str(repo), "--port", str(args.port)]
        if args.stop:
            argv = ["pkill", "-f", "lucifer.cli web"]
        return subprocess.call(argv)

    # fallback: bungkus Chrome mode --app
    kandidat = [
        repo / "deploy" / "lucifer-desktop.sh",
        _P.home() / ".local" / "bin" / "lucifer-desktop",
    ]
    skrip = next((p for p in kandidat if p.exists()), None)
    if skrip is None:
        print(bad("GUI native belum dibangun. Jalankan:\n"
                  "  cmake -B desktop/build -S desktop && cmake --build desktop/build -j"))
        return 1

    argv = ["bash", str(skrip)]
    if args.stop:
        argv.append("--stop")
    elif args.status:
        argv.append("--status")

    env = dict(os.environ)
    env.setdefault("LUCIFER_PORT", str(args.port))
    return subprocess.call(argv, env=env)


def cmd_capture(args) -> int:
    """Tangkap ltoken lewat proxy MITM."""
    from .mitm import PenangkapToken, ip_lokal, tunggu_token

    root = Path(__file__).resolve().parent.parent
    folder_ca = Path(args.ca) if args.ca else (root / "data" / "ca")
    tersimpan: dict[str, object] = {}

    def saat_token(tok):
        tersimpan.update(tok)

    def catat(pesan: str) -> None:
        print(dim("  " + pesan), flush=True)

    try:
        p = PenangkapToken(folder_ca, on_token=saat_token, log_fn=catat)
    except Exception as e:  # noqa: BLE001
        print(bad(f"gagal siapkan proxy: {e}"))
        return 1

    try:
        port = p.mulai(port=args.port, host=args.host)
    except OSError as e:
        print(bad(f"gagal buka port {args.port}: {e}"))
        print(dim("  coba port lain: lucifer capture --port 8081"))
        return 1

    ip = ip_lokal()
    print()
    print(head("  Penangkap ltoken Growtopia siap"))
    print("  " + "─" * 56)
    print(f"  1. Di perangkat yang menjalankan Growtopia, atur proxy:")
    print(f"       host : {head(ip)}")
    print(f"       port : {head(str(port))}")
    print()
    print(f"  2. Pasang sertifikat CA ini di perangkat tersebut:")
    print(f"       {head(p.info_ca()['pem'])}")
    print(f"     {dim('(Android: Settings > Security > Install certificate > CA)')}")
    print()
    print(f"  3. Login Growtopia seperti biasa — pilih akun Google.")
    print(f"     Lucifer akan menangkap ltoken-nya otomatis.")
    print()
    print(dim(f"  menunggu sampai {args.batas} detik… (Ctrl+C untuk berhenti)"))
    print()

    try:
        hasil = tunggu_token(p, batas_detik=args.batas)
    except KeyboardInterrupt:
        p.tutup()
        print(dim("\n  dihentikan"))
        return 130

    p.tutup()

    if not hasil:
        print(bad("  tidak ada token tertangkap."))
        print(dim("  pastikan proxy & sertifikat CA sudah dipasang, "
                  "lalu login Growtopia."))
        return 1

    print()
    print(ok("  ltoken tertangkap!"))
    print(f"  tipe akun : {hasil.get('accountType') or '?'}")
    print(f"  umur akun : {hasil.get('accountAge') or '?'}")
    print(f"  ltoken    : {hasil['token'][:28]}… "
          f"({len(hasil['token'])} karakter)")

    if args.save:
        from .account import Account, upsert_account, load_accounts
        label = args.label or (hasil.get("accountType") or "google")
        daftar = load_accounts()
        if any(a.label == label for a in daftar):
            label = f"{label}-2"
        acc = Account(label=label, username=label, ltoken=str(hasil["token"]),
                      method="token")
        upsert_account(acc)
        print(ok(f"  disimpan sebagai akun '{label}'"))
        print(dim(f"  jalankan: lucifer run --akun {label}"))

    if args.json:
        print(json.dumps(hasil, indent=2))
    return 0


def cmd_android(args) -> int:
    """Periksa Growtopia di HP Android lewat ADB."""
    import json as _json

    from . import android

    info = android.deteksi()
    if args.json:
        print(_json.dumps({
            "ada": info.ada, "serial": info.serial, "model": info.model,
            "android": info.android, "sdk": info.sdk, "abi": info.abi,
            "gt_terpasang": info.gt_terpasang, "gt_versi": info.gt_versi,
            "root": info.root, "proxy": info.proxy,
            "ca_sistem_bisa": info.ca_sistem_bisa, "catatan": info.catatan,
        }, indent=2, ensure_ascii=False))
        return 0 if info.ada else 1

    print()
    print(head("  Growtopia di HP Android"))
    print("  " + "─" * 56)

    if not info.ada:
        print(bad("  HP tidak terdeteksi lewat ADB"))
        for s in info.catatan:
            print(dim(f"  • {s}"))
        print(dim("  • sambungkan HP dengan kabel USB + aktifkan USB debugging"))
        print()
        return 1

    print(f"  HP        : {info.model} ({info.serial})")
    print(f"  Android   : {info.android} (SDK {info.sdk}, {info.abi})")
    if info.gt_terpasang:
        print(f"  Growtopia : versi {info.gt_versi}")
    else:
        print(dim("  Growtopia : tidak terdeteksi"))
    print(f"  Root      : {'ya' if info.root else 'tidak'}")
    print(f"  Proxy HP  : {info.proxy or dim('(kosong)')}")

    sd = android.info_save_dat()
    if sd.get("ada"):
        print(f"  save.dat  : ada  {dim(sd.get('info', '')[:60])}")
    else:
        print(dim("  save.dat  : tidak ada (belum pernah login di HP)"))

    for s in info.catatan:
        print(dim(f"  • {s}"))

    if args.pull:
        print()
        hasil = android.tarik_save_dat()
        if hasil.get("ok"):
            print(ok(f"  save.dat disalin ke {hasil.get('tujuan')}"))
        else:
            print(bad(f"  gagal menarik save.dat: {hasil.get('pesan')}"))

    print()
    return 0


def cmd_web(args) -> int:
    from .web import serve  # noqa: PLC0415

    print(BANNER.format(ver=__version__))
    cfg = load_config(args.config) if args.config else RunnerConfig()
    if args.scripts:
        cfg.scripts_dir = args.scripts
    if args.data:
        cfg.data_dir = args.data
        cfg.items_path = str(Path(args.data) / "items.dat")
    if args.no_connect:
        cfg.auto_connect = False
    return serve(cfg, host=args.host, port=args.port)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lucifer",
        description="Lucifer Linux — bot Growtopia dengan API Lua Lucifer V1.8",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Contoh:\n"
               "  lucifer doctor\n"
               "  lucifer probe\n"
               "  lucifer run --scripts scripts\n"
               "  lucifer web --port 8080\n",
    )
    p.add_argument("-V", "--version", action="version", version=f"lucifer {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="cek lingkungan")
    d.add_argument("--items", default=str(ROOT / "data" / "items.dat"))
    d.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("probe", help="uji handshake ENet ke server Growtopia")
    pr.add_argument("--timeout", type=int, default=12)
    pr.set_defaults(func=cmd_probe)

    it = sub.add_parser("items", help="periksa items.dat")
    it.add_argument("file", nargs="?", default=str(ROOT / "data" / "items.dat"))
    it.add_argument("-s", "--search", default="")
    it.add_argument("-e", "--exact", action="store_true")
    it.add_argument("-n", "--limit", type=int, default=15)
    it.set_defaults(func=cmd_items)

    sc = sub.add_parser("scripts", help="daftar skrip Lua")
    sc.add_argument("-d", "--dir", default="scripts")
    sc.set_defaults(func=cmd_scripts)

    ck = sub.add_parser("check", help="cek sintaks file Lua")
    ck.add_argument("files", nargs="+")
    ck.set_defaults(func=cmd_check)

    lu = sub.add_parser("lua", help="jalankan satu file Lua")
    lu.add_argument("file")
    lu.add_argument("-c", "--config", default=str(ROOT / "data" / "config.json"))
    lu.add_argument("--dry-run", action="store_true", help="tanpa login/koneksi")
    lu.add_argument("--connect", action="store_true", help="connect bot sebelum skrip")
    lu.add_argument("--listen", type=float, default=30.0)
    lu.set_defaults(func=cmd_lua)

    lg = sub.add_parser("login", help="login Growtopia & simpan ltoken (Google/GrowID/ltoken)")
    lg.add_argument("--ltoken", default="", help="pakai ltoken yang sudah ada")
    lg.add_argument("--code", default="",
                    help="authorization code Google (dari URL callback) — "
                         "langsung ditukar jadi ltoken")
    lg.add_argument("--google-browser", dest="google_browser",
                    action="store_true",
                    help="login Google lewat browser (pilih akun manual) — "
                         "cara Growlauncher")
    lg.add_argument("--google", default="", help="id_token Google untuk ditukar jadi ltoken")
    lg.add_argument("--growid", default="", help="nama GrowID (butuh password)")
    lg.add_argument("-p", "--password", default="", help="password GrowID (kosong = tanya)")
    lg.add_argument("-n", "--name", default="", help="nama bot")
    lg.add_argument("-l", "--label", default="", help="label bot")
    lg.add_argument("-o", "--out", default=str(ROOT / "data" / "accounts.json"))
    lg.add_argument("--verify", action="store_true", help="cek ltoken ke server dulu")
    lg.add_argument("--force", action="store_true", help="timpa/tetap simpan")
    lg.add_argument("--dari-hp", dest="dari_hp", action="store_true",
                    help="tangkap id_token dari log Growtopia di HP (butuh adb)")
    lg.add_argument("--detik", type=int, default=90,
                    help="lama menunggu login Google di HP (detik, default 90)")
    lg.add_argument("--redacted", action="store_true", help="tulis versi tersamarkan")
    lg.set_defaults(func=cmd_login)

    r = sub.add_parser("run", help="jalankan bot + skrip")
    r.add_argument("-c", "--config", default=str(ROOT / "data" / "config.json"))
    r.add_argument("-a", "--accounts", default=str(ROOT / "data" / "accounts.json"))
    r.add_argument("-s", "--scripts", default="")
    r.add_argument("-d", "--data", default="")
    r.add_argument("-u", "--username", default="")
    r.add_argument("--no-reload", action="store_true")
    r.add_argument("--no-connect", action="store_true")
    r.add_argument("--log", default="")
    r.set_defaults(func=cmd_run)

    w = sub.add_parser("web", help="jalankan dashboard web")
    w.add_argument("-c", "--config", default=str(ROOT / "data" / "config.json"))
    w.add_argument("-s", "--scripts", default="")
    w.add_argument("-d", "--data", default="")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8787)
    w.add_argument("--no-connect", action="store_true")
    w.set_defaults(func=cmd_web)

    dk = sub.add_parser("desktop", help="buka Lucifer sebagai aplikasi desktop (jendela sendiri)")
    dk.add_argument("--port", type=int, default=8787)
    dk.add_argument("--stop", action="store_true", help="matikan server dashboard")
    dk.add_argument("--status", action="store_true", help="cek server dashboard")
    dk.set_defaults(func=cmd_desktop)

    lt = sub.add_parser("ltoken",
                        help="ambil ltoken dari blok client_data, atau hitung dari kredensial")
    lt.add_argument("--data", default="", help="blok client_data (base64 atau teks key|value)")
    lt.add_argument("--file", default="", help="file berisi blok client_data")
    lt.add_argument("--growid", default="", help="hitung ltoken dari nama GrowID")
    lt.add_argument("-p", "--password", default="", help="sandi GrowID (atau env LUCIFER_PASS)")
    lt.add_argument("--clipboard", action="store_true", help="ambil dari clipboard")
    lt.add_argument("--save", action="store_true", help="simpan ke data/accounts.json")
    lt.add_argument("--label", default="", help="label akun saat disimpan")
    lt.add_argument("--json", action="store_true", help="cetak hasil sebagai JSON")
    lt.set_defaults(func=cmd_ltoken)

    cp = sub.add_parser("capture",
                        help="tangkap ltoken lewat proxy MITM (akun Google/Apple)")
    cp.add_argument("--port", type=int, default=8080, help="port proxy (bawaan 8080)")
    cp.add_argument("--host", default="0.0.0.0", help="alamat dengar (bawaan semua antarmuka)")
    cp.add_argument("--batas", type=int, default=300, help="batas tunggu detik (bawaan 300)")
    cp.add_argument("--save", action="store_true", help="simpan otomatis sebagai akun")
    cp.add_argument("--label", default="", help="label akun saat disimpan")
    cp.add_argument("--ca", default="", help="folder CA (bawaan data/ca)")
    cp.add_argument("--json", action="store_true", help="cetak hasil sebagai JSON")
    cp.set_defaults(func=cmd_capture)

    ad = sub.add_parser("android",
                        help="periksa Growtopia di HP Android lewat ADB (bantu ambil ltoken)")
    ad.add_argument("--pull", action="store_true",
                    help="tarik save.dat dari HP ke folder data/")
    ad.add_argument("--json", action="store_true", help="cetak hasil sebagai JSON")
    ad.set_defaults(func=cmd_android)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n" + dim("dihentikan"))
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
