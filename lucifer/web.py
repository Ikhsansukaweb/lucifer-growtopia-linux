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
from urllib.parse import unquote

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
    <h2>Peta Dunia</h2>
    <div class="btnrow" style="margin-bottom:8px">
      <button class="ghost mini" onclick="muatPeta()">Muat peta</button>
      <span class="hint" id="peta-info">—</span>
    </div>
    <canvas id="peta" width="640" height="640"
            style="width:100%;max-width:640px;image-rendering:pixelated;background:#111;border-radius:8px;border:1px solid var(--line)"></canvas>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2>Fitur Otomasi (deltaX)</h2>
    <div class="grid" id="fitur-grid"><span style="color:var(--dim)">memuat…</span></div>
    <div class="btnrow" style="margin-top:10px">
      <button class="ghost mini" onclick="fitur('replay','record')">Rekam</button>
      <button class="ghost mini" onclick="fitur('replay','stop')">Stop rekam</button>
      <button class="ghost mini" onclick="fitur('replay','play')">Putar</button>
      <button class="ghost mini" onclick="fitur('replay','save')">Simpan</button>
      <button class="ghost mini" onclick="growscan()">Growscan</button>
      <button class="danger mini" onclick="fitur('stop_all','stop')">Stop semua</button>
    </div>
    <pre id="scanout" style="margin-top:8px;color:var(--dim)">—</pre>
    <div class="hint" style="margin-top:8px">
      Fitur berbasis paket saja. ESP/noclip/ghost/visual inventory tidak mungkin di klien bot.
    </div>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2>Skrip Lua</h2>
    <div class="btnrow" style="margin-bottom:8px">
      <input id="skrip-nama" placeholder="nama.lua" style="flex:0 0 200px">
      <button class="ghost mini" onclick="simpanSkrip()">Simpan</button>
      <button class="ghost mini" onclick="jalankanSkrip()">Jalankan</button>
      <span class="hint" id="skrip-out">—</span>
    </div>
    <textarea id="skrip-isi" spellcheck="false"
      style="width:100%;min-height:180px;font-family:ui-monospace,monospace;font-size:12px;background:#1b1d20;color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:10px"
      placeholder="-- tulis skrip Lucifer di sini"></textarea>
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
  return send(c);
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

/* ---------- Fitur otomasi (deltaX) ---------- */
let fiturTerakhir = null;

function warnaItem(id){
  // hash warna stabil per id supaya peta kebaca tanpa perlu sprite items.dat
  let h = (id * 2654435761) % 360;
  return `hsl(${h} 55% ${id===0?14:42}%)`;
}

async function muatFitur(){
  const r = await fetch('/api/features');
  const d = await r.json();
  fiturTerakhir = d;
  if(!d.ok){
    $('fitur-grid').innerHTML = `<span class="hint">${d.error||'tidak tersedia'}</span>`;
    return;
  }
  const s = d.status;
  const baris = [['autofarm','AutoFarm', s.autofarm.aktif, `${s.autofarm.siap_panen} siap panen · ${s.autofarm.kosong} kosong`],
    ['autocollect','AutoCollect', s.autocollect.aktif, `${s.autocollect.objek_dunia} objek · ${s.autocollect.diambil} diambil`],
    ['spammer','Spammer', s.spammer.aktif, `${s.spammer.jumlah_teks} teks · ${s.spammer.terkirim} terkirim`],
    ['autodrop','AutoDrop', s.autodrop.aktif, `mode ${s.autodrop.mode} · min ${s.autodrop.minimum}`],
    ['replay','Replay', s.replay.memutar, s.replay.merekam ? 'sedang merekam' : `${s.replay.aksi} aksi · ${s.replay.berkas.length} berkas`]];
  $('fitur-grid').innerHTML = baris.map(([k,nama,aktif,ket])=>`
    <div class="kpi">
      <b style="color:${aktif?'var(--ok)':'var(--dim)'}">${nama}</b>
      <small>${ket}</small>
      <div style="margin-top:6px">
        <button class="ghost mini" onclick="fitur('${k}','${aktif?'stop':'start'}')">${aktif?'Stop':'Start'}</button>
      </div>
    </div>`).join('');
}

async function fitur(feature, action){
  const body = {feature, action, label: (fiturTerakhir&&fiturTerakhir.label)||''};
  if(feature==='autofarm' && action==='start'){
    const seed = prompt('ID bibit untuk ditanam (kosongkan = hanya panen):','');
    if(seed) body.opts = {seed_id: parseInt(seed,10)||0};
  }
  if(feature==='spammer' && action==='start'){
    const teks = prompt('Teks spam (pisahkan dengan | ):','halo');
    if(!teks) return;
    body.opts = {texts: teks.split('|').map(t=>t.trim()).filter(Boolean)};
  }
  const r = await fetch('/api/feature', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const d = await r.json();
  if(d.scan) $('scanout').textContent = JSON.stringify(d.scan, null, 1);
  if(!d.ok && !d.scan) alert(d.error||'gagal');
  muatFitur();
}

async function growscan(){
  const r = await fetch('/api/feature', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({feature:'growscan', action:'scan', label:(fiturTerakhir&&fiturTerakhir.label)||''})});
  const d = await r.json();
  $('scanout').textContent = d.scan ? JSON.stringify(d.scan, null, 1) : (d.error||'gagal');
}

/* ---------- Peta dunia ---------- */
async function muatPeta(){
  const r = await fetch('/api/map');
  const d = await r.json();
  const cv = $('peta'), cx = cv.getContext('2d');
  if(!d.ok){ $('peta-info').textContent = d.error||'tidak tersedia'; cx.clearRect(0,0,cv.width,cv.height); return; }
  const n = Math.max(d.w, d.h) || 1;
  const skala = Math.floor(Math.min(cv.width, cv.height) / n) || 1;
  cv.width = cv.height = skala * n;
  cx.fillStyle = '#0d0f11'; cx.fillRect(0,0,cv.width,cv.height);
  for(const t of d.tiles){
    cx.fillStyle = warnaItem(t.bg || t.fg);
    cx.fillRect(t.x*skala, t.y*skala, skala, skala);
    if(t.fg){
      cx.fillStyle = warnaItem(t.fg);
      cx.fillRect(t.x*skala+1, t.y*skala+1, skala-2, skala-2);
    }
    if(t.ready){ cx.fillStyle='#ffd166'; cx.fillRect(t.x*skala+skala-3, t.y*skala, 3, 3); }
  }
  for(const p of d.players){
    cx.fillStyle = p.local ? '#00e676' : '#ff5252';
    cx.fillRect(p.x*skala, p.y*skala, Math.max(3,skala), Math.max(3,skala));
  }
  $('peta-info').textContent = `${d.world||'(tanpa nama)'} ${d.w}×${d.h} · ${d.tiles.length} tile · ${d.players.length} pemain · ${d.dropped} objek`;
}

/* ---------- Skrip ---------- */
async function simpanSkrip(){
  const name = $('skrip-nama').value.trim();
  const content = $('skrip-isi').value;
  if(!name){ alert('isi nama file dulu, misal farm.lua'); return; }
  const r = await fetch('/api/script/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, content})});
  const d = await r.json();
  $('skrip-out').textContent = d.ok ? `tersimpan: ${d.name} (${d.bytes} byte)` : (d.error||'gagal');
}

async function jalankanSkrip(){
  const name = $('skrip-nama').value.trim();
  if(!name){ alert('isi nama file dulu'); return; }
  await sendCmd('run ' + name);
  $('skrip-out').textContent = 'dijalankan: ' + name;
}

muatFitur();
muatPeta();
setInterval(muatFitur, 5000);
setInterval(muatPeta, 8000);
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
    def _query(self) -> dict[str, str]:
        q = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    q[unquote(k)] = unquote(v)
                elif part:
                    q[part] = ""
        return q

    def _bot(self, label: str = ""):
        """Ambil bot dari engine; tanpa label pakai bot pertama (atau parent)."""
        if not self.runner or self.runner.engine is None:
            return None
        bots = self.runner.engine.bots
        if label:
            return bots.get(label)
        return self.runner.engine.parent or (next(iter(bots.values())) if bots else None)

    def _fitur_snapshot(self, label: str = "") -> dict:
        """Snapshot fitur untuk SATU bot, plus daftar semua bot (multi-akun).

        `bots` dipakai panel kiri mod menu: tiap akun punya baris sendiri dan
        bisa dinyalakan/dimatikan terpisah. `label` kosong = bot aktif.
        """
        from .features import TILE_MENU  # noqa: PLC0415

        bot = self._bot(label)
        if bot is None:
            return {"ok": False, "error": "belum ada bot — tambah akun dulu"}

        daftar = []
        if self.runner and self.runner.engine:
            for b in self.runner.engine.bots.values():
                st = b.stats()
                daftar.append({
                    "label": b.label,
                    "status": st.get("status"),
                    "world": st.get("world") or "",
                    "ping": st.get("ping"),
                    "parent": b is self.runner.engine.parent,
                    "autofarm": b.fitur.autofarm.berjalan,
                })

        return {"ok": True, "label": bot.label, "status": bot.fitur.status(),
                "menu": TILE_MENU, "bot": bot.stats(), "bots": daftar}

    def _peta(self, label: str) -> dict:
        """Peta dunia siap-render: hanya tile tak-kosong supaya payload kecil."""
        bot = self._bot(label)
        if bot is None:
            return {"ok": False, "error": "belum ada bot — tambah akun dulu"}
        w = bot.world
        db = bot.items_db
        tiles = []
        for t in w.tiles:
            if t.fg == 0 and t.bg == 0:
                continue
            tiles.append({
                "x": t.x, "y": t.y, "fg": t.fg, "bg": t.bg,
                "flags": t.flags, "seed": t.is_seed, "ready": t.ready,
                "name": db.name_of(t.fg) if db else str(t.fg),
            })
        pemain = [{"x": p.tile_x, "y": p.tile_y, "name": p.name, "local": p is bot.local}
                  for p in bot.players.values()]
        return {"ok": True, "label": bot.label, "world": w.name,
                "w": w.width, "h": w.height, "tiles": tiles,
                "players": pemain, "dropped": len(w.dropped)}

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

    def _terapkan_fitur(self, payload: dict) -> dict:
        """Nyalakan/matikan satu fitur otomasi dari dashboard.

        Body: {"label":"main","feature":"autofarm","action":"start"|"stop",
               "opts":{...}}
        """
        bot = self._bot(str(payload.get("label") or ""))
        if bot is None:
            return {"ok": False, "error": "belum ada bot — tambah akun dulu"}
        nama = str(payload.get("feature") or "").strip()
        aksi = str(payload.get("action") or "start").strip()
        opts = payload.get("opts") or {}
        if not isinstance(opts, dict):
            opts = {}

        fb = bot.fitur
        peta = {
            "autofarm": fb.autofarm,
            "autocollect": fb.autocollect,
            "spammer": fb.spammer,
            "autodrop": fb.autodrop,
            "replay": fb.replay,
        }
        if nama == "stop_all":
            fb.stop_semua()
            return {"ok": True, "status": fb.status()}
        if nama in ("start_all", "stop_all_bots"):
            """Nyalakan/matikan satu fitur di SEMUA bot sekaligus."""
            hasil = {}
            for label_bot, b in (self.runner.engine.bots.items()
                                 if self.runner and self.runner.engine else []):
                f = getattr(b.fitur, "autofarm", None)
                if f is None:
                    continue
                try:
                    if nama == "start_all":
                        if opts:
                            f.atur(**opts)
                        f.start()
                    else:
                        f.stop()
                    hasil[label_bot] = f.berjalan
                except Exception as e:  # noqa: BLE001
                    hasil[label_bot] = f"gagal: {e}"
            return {"ok": True, "bots": hasil}
        if nama == "growscan":
            return {"ok": True, "scan": fb.growscan.scan()}
        if nama == "command":
            teks = str(payload.get("text") or "")
            ditangani = fb.commands.handle(teks)
            return {"ok": ditangani, "text": teks,
                    "console": bot.console.contents[-5:]}

        obj = peta.get(nama)
        if obj is None:
            return {"ok": False, "error": f"fitur '{nama}' tidak dikenal"}

        # Autofarm punya banyak tombol di deltaX: pakai `atur()` yang memetakan
        # alias (punch_count, autopunch_delay, overclock, autodrop_*, ...).
        if nama == "autofarm" and opts:
            fb.autofarm.atur(**opts)

        # terapkan opsi (nama field deltaX dipakai apa adanya)
        for k, v in opts.items():
            if k in ("seed_id", "tiles") or nama == "autofarm":
                continue
            if k == "texts":
                for t in (v if isinstance(v, list) else [v]):
                    fb.spammer.tambah(t)
            elif k == "radius":
                obj.radius = int(v or 3)
            elif k == "delay":
                if hasattr(obj, "delay"):
                    obj.delay = int(v or 1000)
            elif k == "minimum":
                fb.autodrop.minimum = int(v or 0)
            elif k == "mode":
                fb.autodrop.mode = str(v)
            elif k == "file":
                pass  # ditangani khusus per fitur di bawah
            elif hasattr(obj, k):
                setattr(obj, k, v)

        if nama == "replay":
            try:
                if aksi == "stop":
                    fb.replay.stop()
                elif aksi == "save":
                    fb.replay.simpan(str(opts.get("file") or "rekaman.json"))
                elif aksi == "load":
                    fb.replay.muat(str(opts.get("file") or "rekaman.json"))
                elif aksi == "play":
                    fb.replay.putar(bool(opts.get("loop", False)))
                elif aksi == "clear":
                    fb.replay.bersihkan()
                else:
                    fb.replay.mulai_rekam()
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e), "status": fb.status()}
            return {"ok": True, "label": bot.label, "status": fb.status()}

        if aksi == "stop":
            obj.stop()
        else:
            try:
                obj.start()
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e), "status": fb.status()}
        return {"ok": True, "label": bot.label, "status": fb.status()}

    def _pool(self):
        """ProxyPool per-runner (dibuat sekali, disimpan di runner)."""
        from .proxypool import ProxyPool  # noqa: PLC0415

        pool = getattr(self.runner, "_proxy_pool", None)
        if pool is None:
            pool = ProxyPool(Path(self.runner.config.data_dir or "data") / "proxies.json")
            self.runner._proxy_pool = pool
        return pool

    def _cari_item(self, q: dict[str, str]) -> dict:
        """Cari item berdasarkan id atau nama (untuk item picker GUI)."""
        db = self.runner.items_db if self.runner else None
        if db is None:
            return {"ok": False, "error": "items.dat belum dimuat"}

        teks = (q.get("q") or "").strip()
        batas = max(1, min(int(q.get("limit") or 40), 200))
        hasil: list[dict] = []

        if teks.isdigit():
            it = db.get(int(teks))
            if it:
                hasil.append(_ringkas_item(it))
        elif teks:
            for it in db.find(teks)[:batas]:
                hasil.append(_ringkas_item(it))
        else:
            for i in range(1, min(batas, len(db.items))):
                it = db.get(i)
                if it:
                    hasil.append(_ringkas_item(it))

        return {"ok": True, "total": len(db), "items": hasil}

    def _inventori(self, label: str = "") -> dict:
        """Isi inventaris satu bot, sudah dilengkapi nama item."""
        bot = self._bot(label)
        if bot is None:
            return {"ok": False, "error": "belum ada bot"}
        db = getattr(bot, "items_db", None) or (self.runner.items_db if self.runner else None)
        isi = []
        for it in bot.inventory.items.values():
            nama = db.name_of(it.id) if db else ""
            isi.append({
                "id": it.id,
                "name": nama,
                "count": it.count,
                "active": bool(it.isActive),
            })
        isi.sort(key=lambda x: (-x["count"], x["id"]))
        return {"ok": True, "label": bot.label,
                "slots": len(isi), "items": isi[:400]}

    def _switch_snapshot(self) -> dict:
        """Ringkasan untuk tab Switch: fitur apa saja yang bisa dinyalakan."""
        bot = self._bot()
        if bot is None:
            return {"ok": False, "error": "belum ada bot"}
        fb = bot.fitur
        saklar = {
            "autofarm": getattr(fb.autofarm, "aktif", False),
            "autocollect": getattr(fb.autocollect, "aktif", False),
            "spammer": getattr(fb.spammer, "aktif", False),
            "autodrop": getattr(fb.autodrop, "aktif", False),
            "pathfinder": getattr(fb.path, "aktif", False),
            "replay": getattr(fb.replay, "aktif", False),
        }
        return {"ok": True, "label": bot.label, "switch": saklar,
                "status": fb.status()}

    def _baca_skrip(self, nama: str) -> dict:
        nama = (nama or "").strip()
        if not nama.endswith(".lua") or "/" in nama or "\\" in nama:
            return {"ok": False, "error": "nama skrip harus *.lua tanpa path"}
        for folder in (self.runner.config.scripts_dir, self.runner.config.examples_dir):
            f = Path(folder) / nama
            if f.exists():
                return {"ok": True, "name": nama, "folder": folder,
                        "content": f.read_text(encoding="utf-8", errors="replace"),
                        "lines": len(f.read_text(encoding="utf-8", errors="replace").splitlines())}
        return {"ok": False, "error": f"skrip '{nama}' tidak ditemukan"}

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
        elif path == "/api/features":
            self._json(self._fitur_snapshot(self._query().get("label", "")))
        elif path == "/api/map":
            self._json(self._peta(self._query().get("label", "")))
        elif path == "/api/logs":
            self._json({"logs": self.runner.logs() if self.runner else []})
        elif path == "/api/items":
            self._json(self._cari_item(self._query()))
        elif path == "/api/script":
            self._json(self._baca_skrip(self._query().get("name", "")))
        elif path == "/api/proxies":
            if not self.runner:
                self._json({"ok": False, "error": "runner belum siap"})
                return
            self._json({"ok": True, "proxies": self._pool().daftar()})
        elif path == "/api/inventory":
            self._json(self._inventori(self._query().get("label", "")))
        elif path == "/api/switch":
            self._json(self._switch_snapshot())
        elif path == "/api/features/schema":
            from .features import TILE_MENU  # noqa: PLC0415

            self._json({"ok": True, "menu": TILE_MENU})
        elif path == "/health":
            self._json({"ok": True, "running": bool(self.runner and not self.runner._stop.is_set())})
        else:
            self._json({"error": "tidak ditemukan"}, 404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path not in ("/api/command", "/api/login", "/api/login/hp",
                        "/api/account/delete", "/api/feature",
                        "/api/script/save", "/api/script/delete",
                        "/api/bot/switch", "/api/proxy", "/api/proxies",
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
                    proxy=str(payload.get("proxy") or ""),
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

            elif path == "/api/proxies":
                aksi = str(payload.get("action") or "tambah").strip()
                pool = self._pool()
                if aksi == "tambah":
                    hasil = pool.tambah(str(payload.get("text") or ""))
                elif aksi == "hapus":
                    hasil = pool.hapus(str(payload.get("host") or ""),
                                       payload.get("port") or 0)
                elif aksi == "hapus_gagal":
                    hasil = pool.hapus_gagal()
                elif aksi == "cek":
                    hasil = pool.cek(int(payload.get("batas") or 0))
                elif aksi == "pakai":
                    url = pool.pilih(str(payload.get("host") or ""),
                                     payload.get("port") or 0)
                    if not url:
                        hasil = {"ok": False, "error": "proxy tidak ada di pool"}
                    else:
                        hasil = self.runner.atur_proxy(
                            str(payload.get("label") or ""), url)
                        hasil["proxy"] = url
                else:
                    hasil = {"ok": False, "error": f"aksi '{aksi}' tidak dikenal"}
                hasil["proxies"] = pool.daftar()
                self._json(hasil)

            elif path == "/api/proxy":
                # {label, proxy} -> set/hapus; {proxy} tanpa label -> uji saja
                label = str(payload.get("label") or "").strip()
                if not label:
                    from .proxy import parse as _parse_proxy, uji as _uji  # noqa: PLC0415
                    try:
                        pxy = _parse_proxy(str(payload.get("proxy") or ""))
                    except ValueError as e:
                        self._json({"ok": False, "error": str(e)})
                        return
                    if pxy is None:
                        self._json({"ok": False, "error": "isi proxy dulu"})
                        return
                    ok, pesan = _uji(pxy)
                    self._json({"ok": ok, "pesan": pesan, "proxy": pxy.url(sandi=False)})
                    return
                self._json(self.runner.atur_proxy(label, str(payload.get("proxy") or "")))

            elif path == "/api/feature":
                self._json(self._terapkan_fitur(payload))

            elif path == "/api/script/delete":
                nama = str(payload.get("name") or "").strip()
                if not nama.endswith(".lua") or "/" in nama or "\\" in nama:
                    self._json({"ok": False, "error": "nama skrip harus *.lua tanpa path"})
                    return
                hapus = 0
                for folder in (self.runner.config.scripts_dir,
                               self.runner.config.examples_dir):
                    f = Path(folder) / nama
                    if f.exists():
                        f.unlink()
                        hapus += 1
                self._json({"ok": hapus > 0, "dihapus": hapus, "name": nama})

            elif path == "/api/bot/switch":
                # Pilih bot aktif untuk dashboard (multi-akun).
                label = str(payload.get("label") or "").strip()
                if self.runner.engine and label in self.runner.engine.bots:
                    self.runner.engine.parent = self.runner.engine.bots[label]
                    self._json({"ok": True, "aktif": label})
                else:
                    self._json({"ok": False, "error": f"bot '{label}' tidak ada"})

            elif path == "/api/script/save":
                nama = str(payload.get("name") or "").strip()
                isi = str(payload.get("content") or "")
                if not nama.endswith(".lua") or "/" in nama or "\\" in nama:
                    self._json({"ok": False, "error": "nama skrip harus *.lua tanpa path"})
                    return
                d = Path(self.runner.config.scripts_dir)
                d.mkdir(parents=True, exist_ok=True)
                (d / nama).write_text(isi, encoding="utf-8")
                self._json({"ok": True, "name": nama, "bytes": len(isi.encode())})

            elif path == "/api/connect":
                self._json(self.runner.connect_bot(str(payload.get("label") or "")))

            elif path == "/api/disconnect":
                self._json(self.runner.disconnect_bot(str(payload.get("label") or "")))

        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def _ringkas_item(it) -> dict:
    """Bentuk ringkas item untuk GUI (tidak membawa seluruh field engine)."""
    return {
        "id": it.id,
        "name": it.name,
        "rarity": it.rarity,
        "type": it.action_type,
        "collision": it.collision_type,
        "grow_time": it.grow_time,
        "max_item": it.max_item,
        "desc": (it.description or "")[:160],
    }


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
