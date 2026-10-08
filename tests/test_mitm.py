#!/usr/bin/env python3
"""
UJI MITM: apakah proxy benar-benar menangkap token dari HTTPS?

Membuat server HTTPS TIRUAN yang meniru respons login Growtopia, lalu
mengarahkan proxy ke sana. Token harus tertangkap utuh.
"""
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/home/ikhsan/Documents/lucifer-linux")
from lucifer.mitm import PenangkapToken, ekstrak_token, ekstrak_client_data

TOKEN_ASLI = "X3Rva2VuPWV5SjBZVzVyU1VST1lXUzR2b1RPSG9Uc0l6VXlNek0xTmpjNE9UQXdNREV5TXpRME5UWTNPRGt3TVRBeE1qTTBORFUyTnpnNU1ERXlNelEwTlRZM09Ea3dNVE..." 
PESAN = {"status": "success", "message": "", "token": TOKEN_ASLI,
         "url": "", "accountType": "growtopia", "accountAge": "2"}

TMP = Path("/tmp/uji-mitm")
TMP.mkdir(parents=True, exist_ok=True)


class Tiruan(BaseHTTPRequestHandler):
    def do_GET(self):
        if "validate" in self.path or "checktoken" in self.path:
            b = json.dumps(PESAN).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            b = b'{"status":"failed","message":"nope"}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        if b"ltoken" in body or b"data=" in body:
            b = json.dumps(PESAN).encode()
        else:
            b = json.dumps(PESAN).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def buat_server_tiruan(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Tiruan)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Pakai sertifikat dari CA Lucifer (sama seperti yang dipakai proxy).
    ctx.load_cert_chain(TMP / "server.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


PASS = FAIL = 0


def cek(nama, syarat, info=""):
    global PASS, FAIL
    if syarat:
        PASS += 1
        print(f"  OK   {nama}")
    else:
        FAIL += 1
        print(f"  GAGAL {nama}  {info}")


print("=" * 70)
print("UJI MITM — penangkap ltoken")
print("=" * 70)
print()

# --- 1. unit: ekstraksi token ------------------------------------------- #
print("1. ekstraksi token dari badan respons")
tok = ekstrak_token(json.dumps(PESAN).encode())
cek("token JSON terbaca", tok is not None and tok["token"] == TOKEN_ASLI,
    str(tok)[:80])
cek("accountType ikut terbaca", tok and tok["accountType"] == "growtopia")
cek("accountAge ikut terbaca", tok and tok["accountAge"] == "2")

tok2 = ekstrak_token(b'{"status":"failed","message":"Please try login again.",'
                     b'"token":"","url":"","accountType":"growtopia",'
                     b'"accountAge":2}')
cek("respons gagal TIDAK dianggap token", tok2 is None, str(tok2)[:60])

tok3 = ekstrak_token(b'{"token":"abcdef1234567890"}')
cek("pola token sederhana terbaca", tok3 and tok3["token"] == "abcdef1234567890")

cd = ekstrak_client_data(b"protocol|225&data=SGVsbG8gV29ybGQ%3D&adc=1")
cek("client_data ikut ditangkap", "data" in cd, str(cd)[:60])

print()
print("2. sertifikat CA")
p = PenangkapToken(TMP / "ca")
cek("CA dibuat", Path(p.info_ca()["pem"]).exists())
cek("kunci CA ada", Path(p.info_ca()["key"]).exists())

print()
print("3. proxy sungguhan menangkap token dari HTTPS")
# Server tiruan di 127.0.0.1:9443, proxy mengarahkan host pantau ke sana.
sert = TMP / "server.pem"
# Buat sertifikat server dari CA Lucifer untuk host "login.growtopiaguma.com"
from lucifer.mitm import sertifikat_host
gabung = sertifikat_host(p.info_ca(), TMP / "ca", "login.growtopiaguma.com")
Path(sert).write_bytes(Path(gabung).read_bytes())

srv = buat_server_tiruan(9443)

p2 = PenangkapToken(
    TMP / "ca2",
    host_pantau=("growtopiaguma.com",),
    peta_upstream={"login.growtopiaguma.com": ("127.0.0.1", 9443)},
    log_fn=lambda m: print("     " + m),
)
port = p2.mulai(port=0, host="127.0.0.1")
cek("proxy mendengarkan", port > 0, f"port={port}")

# Klien memakai proxy kita, DAN mempercayai CA kita.
ctx = ssl.create_default_context(cafile=p2.info_ca()["pem"])
# Lewat proxy: kirim CONNECT dulu, lalu TLS di dalamnya.
import socket as sk
raw = sk.create_connection(("127.0.0.1", port), timeout=10)
raw.sendall(b"CONNECT login.growtopiaguma.com:443 HTTP/1.1\r\n\r\n")
jawab = raw.recv(4096)
cek("CONNECT diterima", b"200" in jawab, jawab[:60])

tls = ctx.wrap_socket(raw, server_hostname="login.growtopiaguma.com")
tls.sendall(b"POST /player/growid/login/validate HTTP/1.1\r\n"
            b"Host: login.growtopiaguma.com\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: 22\r\n\r\n"
            b"growId=abc&password=xy")
time.sleep(0.6)
balik = b""
try:
    while True:
        c = tls.recv(65536)
        if not c:
            break
        balik += c
except Exception:
    pass

cek("token TERTANGKAP oleh proxy", p2.token is not None and
    p2.token["token"] == TOKEN_ASLI,
    str(p2.token)[:70])
cek("respons diteruskan ke klien", TOKEN_ASLI.encode() in balik,
    str(balik)[:80])
cek("jumlah request tercatat", p2.jumlah_request >= 1)

p2.tutup()
srv.shutdown()
p.tutup()

print()
print("=" * 70)
print(f"HASIL: {PASS} lulus, {FAIL} gagal")
print("=" * 70)
sys.exit(1 if FAIL else 0)
