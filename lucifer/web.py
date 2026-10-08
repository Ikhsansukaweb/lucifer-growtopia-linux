"""
lucifer.web — Dashboard web untuk memantau dan mengendalikan bot.

Server HTTP kecil (tanpa dependensi tambahan) dengan:
    GET  /                halaman dashboard
    GET  /api/status      snapshot JSON (bot, dunia, log)
    POST /api/command     jalankan perintah teks (say/warp/run/reload/stop)
    GET  /api/scripts     daftar skrip + isinya

Dibuat dengan http.server supaya bisa langsung jalan di VPS tanpa npm.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .runner import Runner, RunnerConfig

log = logging.getLogger("lucifer.web")

PAGE = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lucifer Linux — Dashboard</title>
<style>
  :root{
    --bg:#1b1d20; --card:#232629; --line:#32373c; --txt:#f2f1ec; --dim:#6e6e6e;
    --acc:#5196fe; --ok:#3fb950; --warn:#f9754e; --bad:#e5534b;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;
         align-items:center;gap:12px;flex-wrap:wrap}
  h1{font-size:16px;margin:0;font-weight:600}
  .tag{font-size:11px;padding:2px 8px;border:1px solid var(--line);border-radius:99px;color:var(--dim)}
  main{padding:20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
           margin:0 0 10px;font-weight:600}
  .row{display:flex;justify-content:space-between;gap:10px;padding:3px 0}
  .row span:last-child{color:var(--acc)}
  .online{color:var(--ok)} .offline{color:var(--bad)} .warn{color:var(--warn)}
  pre{margin:0;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto;
      font-size:12px;color:#c9c9c4}
  input,button,select{font:inherit;background:#1b1d20;color:var(--txt);
      border:1px solid var(--line);border-radius:8px;padding:7px 10px}
  button{cursor:pointer;background:var(--acc);color:#0b1220;border:none;font-weight:600}
  button.ghost{background:transparent;color:var(--txt);border:1px solid var(--line);font-weight:400}
  .cmd{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
  .cmd input{flex:1;min-width:200px}
  .badge{display:inline-block;width:8px;height:8px;border-radius:99px;background:var(--ok);margin-right:6px}
  .badge.off{background:var(--bad)}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
  .kpi{background:#1b1d20;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
  .kpi b{display:block;font-size:18px;color:var(--acc)}
  .kpi small{color:var(--dim);font-size:11px}
  .field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
  .field label{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
  .field input{width:100%}
  .btnrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  button.mini{padding:4px 10px;font-size:12px}
  button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
  .hint{font-size:11px;color:var(--dim);line-height:1.6}
  .hint code{background:#1b1d20;border:1px solid var(--line);border-radius:4px;padding:1px 5px}
  .tabs{display:flex;gap:6px;margin-bottom:12px}
  .tabs button{background:transparent;color:var(--dim);border:1px solid var(--line);font-weight:400;font-size:12px;padding:5px 12px}
  .tabs button.active{background:var(--acc);color:#0b1220;border-color:var(--acc);font-weight:600}
  .akun{border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin-bottom:8px;background:#1b1d20}
  .akun .row:first-child{margin-bottom:4px}
  footer{padding:14px 20px;color:var(--dim);font-size:11px;border-top:1px solid var(--line)}
</style>
</head>
<body>
<header>
  <h1>Lucifer Linux</h1>
  <span class="tag">API Lua Lucifer V1.8</span>
  <span class="tag" id="uptime">—</span>
  <span style="margin-left:auto">
    <button class="ghost" onclick="load()">Muat ulang</button>
    <button class="ghost" onclick="send('reload')">Reload skrip</button>
  </span>
</header>

<main>
  <section class="card" style="grid-column:1/-1">
    <h2>Ringkasan</h2>
    <div class="grid" id="kpi"></div>
  </section>

  <section class="card" id="card-login">
    <h2>Login Akun</h2>

    <div class="tabs">
      <button id="tab-ltoken" class="active" onclick="pilihTab('ltoken')">Pakai ltoken</button>
      <button id="tab-hp" onclick="pilihTab('hp')">Dari HP (Android)</button>
      <button id="tab-growid" onclick="pilihTab('growid')">GrowID (nama + sandi)</button>
    </div>

    <!-- cara 0: langsung dari HP -->
    <div id="pane-hp" style="display:none">
      <div class="field">
        <label for="hp-label">Label bot</label>
        <input id="hp-label" placeholder="main">
      </div>
      <div class="btnrow">
        <button onclick="loginDariHP()">Ambil Token dari HP</button>
        <label class="hint" style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="hp-connect" checked style="width:auto"> langsung connect
        </label>
      </div>
      <p class="hint" style="margin:10px 0 0">
        Sambungkan HP dengan kabel USB (mode <b>USB debugging</b>), lalu tekan tombol.
        Token diambil otomatis dari <code>save.dat</code> Growtopia —
        <b>tanpa root</b>, <b>tanpa login ulang</b>. Paling praktis untuk akun Google/Apple.
      </p>
      <p class="hint" style="margin:6px 0 0;color:var(--dim)">
        Butuh <code>adb</code> terpasang dan <code>adb devices</code> menampilkan HP-mu.
      </p>
    </div>

    <!-- cara 1: ltoken -->
    <div id="pane-ltoken">
      <div class="field">
        <label for="lt-label">Label bot</label>
        <input id="lt-label" placeholder="main">
      </div>
      <div class="field">
        <label for="lt-token">ltoken</label>
        <input id="lt-token" placeholder="tempel ltoken di sini (boleh juga tempel blok client_data)" autocomplete="off">
      </div>
      <div class="btnrow">
        <button onclick="loginLtoken()">Simpan &amp; Login</button>
        <label class="hint" style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="lt-connect" checked style="width:auto"> langsung connect
        </label>
      </div>
      <p class="hint" style="margin:10px 0 0">
        Belum punya ltoken? Tempel saja <b>seluruh blok</b> <code>client_data</code> dari
        proxy debug — akan diambil otomatis. Atau pakai tab GrowID.
      </p>
    </div>

    <!-- cara 2: growid -->
    <div id="pane-growid" style="display:none">
      <div class="field">
        <label for="gd-label">Label bot</label>
        <input id="gd-label" placeholder="main">
      </div>
      <div class="field">
        <label for="gd-user">Nama GrowID</label>
        <input id="gd-user" placeholder="NamaKamu" autocomplete="username">
      </div>
      <div class="field">
        <label for="gd-pass">Sandi</label>
        <input id="gd-pass" type="password" placeholder="••••••••" autocomplete="current-password">
      </div>
      <div class="btnrow">
        <button onclick="loginGrowid()">Simpan &amp; Login</button>
        <label class="hint" style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="gd-connect" checked style="width:auto"> langsung connect
        </label>
      </div>
      <p class="hint" style="margin:10px 0 0">
        Sandi disimpan di <code>data/accounts.json</code> dengan izin <code>600</code>
        (hanya kamu yang bisa baca). Kalau akunmu pakai Google, pakai tab <b>ltoken</b>.
      </p>
    </div>

    <pre id="loginout" style="margin-top:12px;color:var(--dim)">—</pre>
  </section>

  <section class="card">
    <h2>Akun Tersimpan</h2>
    <div id="akunlist"><span style="color:var(--dim)">memuat…</span></div>
    <div class="btnrow" style="margin-top:10px">
      <button class="ghost mini" onclick="connectAll()">Connect semua</button>
      <button class="ghost mini" onclick="disconnectAll()">Putus semua</button>
    </div>
  </section>

  <section class="card">
    <h2>Bot</h2>
    <div id="bots"><span style="color:var(--dim)">memuat…</span></div>
  </section>

  <section class="card">
    <h2>Dunia &amp; Inventaris</h2>
    <div id="world"><span style="color:var(--dim)">memuat…</span></div>
  </section>

  <section class="card">
    <h2>Perintah &amp; Kontrol</h2>
    <div style="display:flex;gap:6px;margin-bottom:8px">
      <input id="warp-world" placeholder="Nama World (misal: START, FARM)" style="flex:1">
      <button onclick="warpWorld()">Warp</button>
    </div>
    <div style="display:flex;gap:6px;margin-bottom:12px">
      <input id="chat-text" placeholder="Pesan chat / say..." style="flex:1">
      <button onclick="sayChat()">Kirim Pesan</button>
    </div>
    <div style="margin-bottom:12px">
      <span style="font-size:11px;color:var(--dim);text-transform:uppercase;display:block;margin-bottom:4px">Navigasi Bot</span>
      <div style="display:grid;grid-template-columns:repeat(3,40px);gap:4px;justify-content:center;margin-bottom:6px">
        <div></div><button class="ghost" onclick="sendCmd('move main up')">▲</button><div></div>
        <button class="ghost" onclick="sendCmd('move main left')">◀</button>
        <button class="ghost" onclick="sendCmd('enter main')">OK</button>
        <button class="ghost" onclick="sendCmd('move main right')">▶</button>
        <div></div><button class="ghost" onclick="sendCmd('move main down')">▼</button><div></div>
      </div>
      <div class="btnrow" style="justify-content:center">
        <button class="ghost mini" onclick="sendCmd('respawn main')">Respawn</button>
        <button class="ghost mini" onclick="sendCmd('collect main')">Collect</button>
      </div>
    </div>
    <div class="cmd">
      <input id="cmd" placeholder="say main halo  |  warp main FARM  |  run 03_auto_farm.lua"
             onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()">Kirim</button>
    </div>
    <pre id="cmdout" style="color:var(--dim)">contoh: status · bots · reload · run 03_auto_farm.lua · warp main START</pre>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2>Log</h2>
    <pre id="logs">memuat…</pre>
  </section>
</main>

<footer>Lucifer Linux — ENet patch Ubisoft · Tank/Variant codec · items.dat · Lua 5.4 (lupa)</footer>

<script>
const $ = (id) => document.getElementById(id);

function cls(status){
  if(status === 'online') return 'online';
  if(status === 'offline') return 'offline';
  return 'warn';
}

/* `no_captcha` artinya server TIDAK meminta captcha — ini kondisi normal,
   bukan "tidak terbaca". Diberi label yang jelas supaya tidak membingungkan. */
function capTeks(s){
  if(!s) return '—';
  const peta = {
    no_captcha: 'tidak diminta (normal)',
    not_found:  'DIMINTA — perlu diselesaikan',
    solving:    'sedang diselesaikan',
    solved:     'selesai',
    failed:     'gagal',
    wrong:      'jawaban salah',
    no_access:  'tanpa akses',
    invalid_key:'kunci tidak valid',
    invalid_token: 'token tidak valid',
  };
  return peta[s] || s;
}

async function load(){
  try{
    const r = await fetch('/api/status');
    const d = await r.json();
    $('uptime').textContent = 'uptime ' + d.uptime + 's';
    $('kpi').innerHTML = `
      <div class="kpi"><b>${d.bots.length}</b><small>bot</small></div>
      <div class="kpi"><b>${d.bots.filter(b=>b.status==='online').length}</b><small>online</small></div>
      <div class="kpi"><b>${d.items_loaded}</b><small>item di database</small></div>
      <div class="kpi"><b>${d.scripts.length}</b><small>skrip</small></div>`;

    $('bots').innerHTML = d.bots.length ? d.bots.map(b => `
      <div class="row"><span><span class="badge ${b.status==='online'?'':'off'}"></span>${b.label}</span>
      <span class="${cls(b.status)}">${b.status}${b.ping?` · ${b.ping}ms`:''}</span></div>
      <div class="row"><span style="color:var(--dim)">dunia</span><span>${b.world||'—'}</span></div>
      <div class="row"><span style="color:var(--dim)">server</span><span>${b.server||'—'}</span></div>
    `).join('') : '<span style="color:var(--dim)">tidak ada bot</span>';

    const b0 = d.bots[0] || {};
    // Kalau bot belum tersambung, angka 0 itu BUKAN data asli — hanya nilai
    // awal. Tampilkan "—" supaya tidak disalahartikan sebagai dunia kosong.
    const hidup = b0.status === 'online' || b0.status === 'connecting';
    const n = v => hidup ? (v ?? 0) : '—';
    const ukuran = (b0.world_size && b0.world_size !== '0x0') ? b0.world_size
                   : (hidup ? 'belum masuk dunia' : '—');
    $('world').innerHTML = `
      <div class="row"><span>dunia</span><span>${b0.world||'—'}</span></div>
      <div class="row"><span>ukuran</span><span>${ukuran}</span></div>
      <div class="row"><span>tile</span><span>${n(b0.tiles)}</span></div>
      <div class="row"><span>objek jatuh</span><span>${n(b0.dropped)}</span></div>
      <div class="row"><span>pemain</span><span>${n(b0.players)}</span></div>
      <div class="row"><span>item inventaris</span><span>${n(b0.inventory_items)}</span></div>
      <div class="row"><span>level / gems</span><span>${n(b0.level)} / ${n(b0.gems)}</span></div>
      <div class="row"><span>captcha</span><span>${capTeks(b0.captcha)}</span></div>`;
    if(!hidup && b0.status){
      $('world').innerHTML = `<div class="row" style="color:var(--dim)">
        <span>bot belum tersambung (${b0.status}) — data dunia belum ada</span></div>`
        + $('world').innerHTML;
    }

    $('logs').textContent = (d.log_tail||[]).join('\n');
  }catch(e){
    $('logs').textContent = 'gagal memuat status: ' + e;
  }
}

async function send(cmd){
  const input = $('cmd');
  const text = cmd || input.value.trim();
  if(!text) return;
  try{
    const r = await fetch('/api/command', {method:'POST', headers:{'Content-Type':'application/json'},
                                           body: JSON.stringify({command: text})});
    const d = await r.json();
    $('cmdout').textContent = JSON.stringify(d, null, 2);
    if(!cmd) input.value = '';
    load();
  }catch(e){
    $('cmdout').textContent = 'error: ' + e;
  }
}

function sendCmd(c){
  send(c);
}

function warpWorld(){
  const w = $('warp-world').value.trim();
  if(!w) return;
  send('warp main ' + w);
}

function sayChat(){
  const msg = $('chat-text').value.trim();
  if(!msg) return;
  send('say main ' + msg);
  $('chat-text').value = '';
}

/* ---------- login ---------- */

function pilihTab(nama){
  const tab = ['ltoken','hp','growid'];
  for(const t of tab){
    $('tab-'+t).className = (t === nama) ? 'active' : '';
    $('pane-'+t).style.display = (t === nama) ? '' : 'none';
  }
  $('loginout').textContent = '—';
}

async function loginDariHP(){
  const label = $('hp-label').value.trim();
  $('loginout').textContent = 'membaca token dari HP… (pastikan kabel tersambung)';
  try{
    const d = await postJSON('/api/login/hp', {
      label, connect: $('hp-connect').checked
    });
    tampilLogin(d, d.ok);
    if(d.ok){ $('hp-label').value = ''; load(); loadAkun(); }
  }catch(e){ tampilLogin('error: ' + e, false); }
}

function tampilLogin(obj, ok){
  $('loginout').style.color = ok ? 'var(--ok)' : 'var(--warn)';
  $('loginout').textContent = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
}

/* Urai blok client_data -> {ltoken, tankIDName, rid, mac}
   Meniru tools/ltoken.py, supaya pengguna bisa langsung tempel blok mentah. */
function uraiClientData(teks){
  const hasil = {};
  const telanPerBaris = (s) => {
    for(const baris of String(s).split(/[\r\n]+/)){
      const b = baris.trim();
      if(!b || !b.includes('|')) continue;
      const i = b.indexOf('|');
      const k = b.slice(0, i).trim();
      if(k && !(k in hasil)) hasil[k] = b.slice(i + 1).trim();
    }
  };
  const telanPasangan = (s) => {
    const p = String(s).trim().split('|').map(x => x.trim());
    for(let i = 0; i + 1 < p.length; i += 2){
      if(p[i] && !(p[i] in hasil)) hasil[p[i]] = p[i + 1];
    }
  };
  const kandidat = [teks];
  try{
    const bersih = String(teks).replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
    const pad = bersih + '='.repeat((4 - bersih.length % 4) % 4);
    const d = atob(pad);
    if(d && d !== teks) kandidat.push(d);
  }catch(e){ /* bukan base64 — abaikan */ }

  for(const isi of kandidat){
    const satuBaris = !/[\r\n]/.test(isi.trim());
    if(satuBaris && (isi.match(/\|/g) || []).length >= 4){
      telanPasangan(isi);
      if(hasil.ltoken) return hasil;
    }
    telanPerBaris(isi);
    if(hasil.ltoken) return hasil;
  }
  return hasil;
}

async function postJSON(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify(body)});
  return await r.json();
}

async function loginLtoken(){
  const mentah = $('lt-token').value.trim();
  if(!mentah){ tampilLogin('isi ltoken dulu', false); return; }

  // Kalau yang ditempel ternyata blok client_data, ambil ltoken-nya otomatis
  let ltoken = mentah;
  let label = $('lt-label').value.trim();
  if(!/^[A-Za-z0-9_-]{16,}$/.test(mentah) || mentah.includes('|') || mentah.includes('=')){
    const u = uraiClientData(mentah);
    if(u.ltoken){
      ltoken = u.ltoken;
      if(!label && u.tankIDName) label = u.tankIDName;
    }
  }

  $('loginout').textContent = 'memproses…';
  try{
    const d = await postJSON('/api/login', {
      label, ltoken, connect: $('lt-connect').checked
    });
    tampilLogin(d, d.ok);
    if(d.ok){
      $('lt-token').value = ''; $('lt-label').value = '';
      load(); loadAkun();
    }
  }catch(e){ tampilLogin('error: ' + e, false); }
}

async function loginGrowid(){
  const username = $('gd-user').value.trim();
  const password = $('gd-pass').value;
  const label = $('gd-label').value.trim();
  if(!username || !password){ tampilLogin('isi nama GrowID dan sandi', false); return; }

  $('loginout').textContent = 'memproses…';
  try{
    const d = await postJSON('/api/login', {
      label, username, password, method: 'growid', connect: $('gd-connect').checked
    });
    tampilLogin(d, d.ok);
    if(d.ok){
      $('gd-pass').value = ''; $('gd-user').value = ''; $('gd-label').value = '';
      load(); loadAkun();
    }
  }catch(e){ tampilLogin('error: ' + e, false); }
}

async function loadAkun(){
  try{
    const r = await fetch('/api/accounts');
    const d = await r.json();
    const akun = d.accounts || [];
    if(!akun.length){
      $('akunlist').innerHTML = '<span style="color:var(--dim)">belum ada akun — tambahkan lewat form di atas</span>';
      return;
    }
    $('akunlist').innerHTML = akun.map(a => `
      <div class="akun">
        <div class="row"><span><span class="badge ${a.punya_ltoken || a.punya_sandi ? '' : 'off'}"></span>${a.label}</span>
          <span style="color:var(--dim)">${a.method || '—'}</span></div>
        <div class="row"><span style="color:var(--dim)">akun</span><span>${a.username || a.mail || '—'}</span></div>
        <div class="row"><span style="color:var(--dim)">kredensial</span>
          <span>${[a.punya_ltoken ? 'ltoken' : '', a.punya_sandi ? 'sandi' : ''].filter(Boolean).join(' + ') || '—'}</span></div>
        <div class="btnrow" style="margin-top:6px">
          <button class="ghost mini" onclick="connectSatu('${a.label}')">Connect</button>
          <button class="ghost mini" onclick="putusSatu('${a.label}')">Putus</button>
          <button class="danger mini" onclick="hapusAkun('${a.label}')">Hapus</button>
        </div>
      </div>`).join('');
  }catch(e){
    $('akunlist').innerHTML = '<span style="color:var(--warn)">gagal memuat akun: ' + e + '</span>';
  }
}

async function connectSatu(label){
  tampilLogin(await postJSON('/api/connect', {label}), true); load();
}
async function putusSatu(label){
  tampilLogin(await postJSON('/api/disconnect', {label}), true); load();
}
async function connectAll(){ tampilLogin(await postJSON('/api/connect', {}), true); load(); }
async function disconnectAll(){ tampilLogin(await postJSON('/api/disconnect', {}), true); load(); }

async function hapusAkun(label){
  if(!confirm('Hapus akun "' + label + '" beserta bot-nya?')) return;
  tampilLogin(await postJSON('/api/account/delete', {label}), true);
  load(); loadAkun();
}

load();
loadAkun();
setInterval(load, 3000);
setInterval(loadAkun, 10000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    runner: Optional[Runner] = None
    server_version = "LuciferLinux"

    def log_message(self, fmt, *args):  # noqa: A003
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- util -------------------------------------------------------------- #
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode())

    # -- routes ------------------------------------------------------------ #
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html")
        elif path == "/api/status":
            self._json(self.runner.snapshot() if self.runner else {})
        elif path == "/api/accounts":
            self._json({"accounts": self.runner.daftar_akun() if self.runner else []})
        elif path == "/api/scripts":
            scripts = []
            if self.runner:
                for folder in (self.runner.config.scripts_dir, self.runner.config.examples_dir):
                    d = Path(folder)
                    if not d.exists():
                        continue
                    for f in sorted(d.glob("*.lua")):
                        if f.name.startswith("_"):
                            continue
                        isi = f.read_text(encoding="utf-8", errors="replace")
                        scripts.append({
                            "name": f.name,
                            "folder": folder,
                            "lines": len(isi.splitlines()),
                            "bytes": len(isi.encode("utf-8")),
                            "content": isi[:8000],
                        })
            self._json({"scripts": scripts})
        elif path == "/api/logs":
            self._json({"logs": self.runner.logs() if self.runner else []})
        elif path == "/health":
            self._json({"ok": True, "running": bool(self.runner and not self.runner._stop.is_set())})
        else:
            self._json({"error": "tidak ditemukan"}, 404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path not in ("/api/command", "/api/login", "/api/login/hp",
                        "/api/account/delete",
                        "/api/connect", "/api/disconnect"):
            self._json({"error": "tidak ditemukan"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"payload tidak valid: {e}"}, 400)
            return

        if not self.runner:
            self._json({"ok": False, "error": "runner belum siap"}, 503)
            return

        try:
            if path == "/api/command":
                self._json(self.runner.command(str(payload.get("command", ""))))

            elif path == "/api/login":
                # Login dari dashboard: ltoken ATAU username+sandi (GrowID)
                self._json(self.runner.tambah_akun(
                    label=str(payload.get("label") or payload.get("username") or ""),
                    username=str(payload.get("username") or ""),
                    password=str(payload.get("password") or ""),
                    ltoken=str(payload.get("ltoken") or ""),
                    method=str(payload.get("method") or ""),
                    connect=bool(payload.get("connect", False)),
                ))

            elif path == "/api/login/hp":
                # Ambil refreshToken langsung dari save.dat HP (tanpa root),
                # segarkan lewat /player/growid/checktoken, lalu simpan.
                from .ltoken import token_dari_hp  # noqa: PLC0415

                cap = token_dari_hp()
                if not cap.ok:
                    self._json({"ok": False, "error": cap.pesan})
                    return
                self._json(self.runner.tambah_akun(
                    label=str(payload.get("label") or "main"),
                    ltoken=cap.ltoken,
                    method="hp/save.dat",
                    connect=bool(payload.get("connect", False)),
                ))

            elif path == "/api/account/delete":
                self._json(self.runner.hapus_akun(str(payload.get("label") or "")))

            elif path == "/api/connect":
                self._json(self.runner.connect_bot(str(payload.get("label") or "")))

            elif path == "/api/disconnect":
                self._json(self.runner.disconnect_bot(str(payload.get("label") or "")))

        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def create_server(
    runner: Optional[Runner] = None,
    host: str = "127.0.0.1",
    port: int = 8787,
    config: Optional[RunnerConfig] = None,
) -> tuple[ThreadingHTTPServer, Runner]:
    """Bangun server HTTP + Runner TANPA menjalankannya (dipakai uji & serve).

    Mengembalikan (httpd, runner) sehingga pemanggil bisa memakai
    `httpd.serve_forever()` atau `httpd.handle_request()`.
    """
    r = runner or Runner(config or RunnerConfig())
    if runner is None:
        try:
            r.setup()
        except Exception as e:  # noqa: BLE001
            print(f"peringatan: setup runner: {e}")

    # Handler per-server: subkelas supaya dua server di satu proses tidak
    # saling menimpa runner (class attribute pada Handler akan bentrok).
    class _Handler(Handler):
        pass

    _Handler.runner = r
    httpd = ThreadingHTTPServer((host, port), _Handler)
    return httpd, r


def serve(config: Optional[RunnerConfig] = None, host: str = "127.0.0.1", port: int = 8787) -> int:
    """Jalankan dashboard web (blocking)."""
    httpd, runner = create_server(config=config, host=host, port=port)

    threading.Thread(target=runner.start, kwargs={"block": False}, daemon=True).start()

    print(f"dashboard: http://{host}:{port}  (Ctrl+C untuk berhenti)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nberhenti")
    finally:
        httpd.server_close()
        runner.stop()
    return 0
