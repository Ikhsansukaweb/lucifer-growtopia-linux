# Proxy SOCKS5 + aplikasi desktop native

Dua tambahan ini tidak menyentuh protokol game: proxy hanya mengalihkan jalur
UDP, dan aplikasi desktop hanya lapisan tampilan di atas dashboard yang sudah
ada.

## 1. Proxy SOCKS5 per bot

### Format yang diterima

```
host:port
user:pass@host:port
socks5://host:port
socks5h://user:pass@host:port
```

`p%40ss` (persen-encoding) diurai, jadi sandi yang mengandung `@` atau `:`
tetap aman. Skema selain `socks5`/`socks5h` ditolak — ENet hanya bisa
SOCKS5, bukan HTTP CONNECT.

### Di mana dipasang

| Lapisan | Berkas | Peran |
|---|---|---|
| Parsing + uji | `lucifer/proxy.py` | normalisasi string, handshake SOCKS5 sungguhan |
| Koneksi | `lucifer/bot.py` | `enet_host_use_proxy()` sebelum `connect()` |
| Penyimpanan | `lucifer/account.py` | `Account.proxy` ditulis ke `accounts.json` |
| API | `lucifer/web.py` | `POST /api/proxy` |
| GUI | `desktop/src/main.cpp` | tab **Proxy** |

Yang lewat proxy **seluruh trafik game**, bukan hanya login: ENet membungkus
semua paket UDP ke server Growtopia lewat `UDP ASSOCIATE`. Login GrowID/Google
(http via `requests`) tetap langsung — kalau ingin itu juga lewat proxy, set
variabel lingkungan `HTTPS_PROXY`.

### API

```bash
# uji saja (tanpa simpan)
curl -s -X POST localhost:8787/api/proxy -d '{"proxy":"user:pass@1.2.3.4:1080"}'
# {"ok":true,"pesan":"ok — 1.2.3.4:1080 meneruskan ke 1.1.1.1:80","proxy":"socks5://user:***@1.2.3.4:1080"}

# pasang ke satu bot
curl -s -X POST localhost:8787/api/proxy -d '{"label":"main","proxy":"1.2.3.4:1080"}'

# hapus
curl -s -X POST localhost:8787/api/proxy -d '{"label":"main","proxy":""}'
```

Login juga bisa langsung membawa proxy:

```bash
curl -s -X POST localhost:8787/api/login \
  -d '{"label":"farm1","ltoken":"...","proxy":"1.2.3.4:1080","connect":true}'
```

### Perilaku saat gagal

- Format salah → ditolak sebelum disimpan (`proxy harus berformat host:port`).
- Proxy mati → bot tetap connect **tanpa** proxy dan menulis peringatan ke log
  (`proxy tidak valid (...) — connect tanpa proxy`). Tidak menggantung.
- Proxy menuntut user/pass tapi kredensial kosong → `uji()` melaporkan
  `proxy menuntut user/pass, tapi kredensial kosong`.

Ganti proxy berlaku saat **connect berikutnya**; bot yang sedang online tidak
dipindah jalur (memindahkan sesi ENet di tengah jalan akan memutus koneksi).

## 2. Aplikasi desktop native (GTK3, C++)

```
desktop/
├── CMakeLists.txt
└── src/main.cpp        # ~600 baris, GTK3 + json-glib
```

### Bangun & jalankan

```bash
sudo apt install libgtk-3-dev libjson-glib-dev
cmake -B desktop/build -S desktop -DCMAKE_BUILD_TYPE=Release
cmake --build desktop/build -j
./desktop/build/lucifer-desktop --repo "$PWD"
```

Opsi:

```
--repo DIR    folder repo (cari .venv/bin/python & modul lucifer)
--port N      port dashboard lokal (default 8787)
--url URL     pakai server yang sudah jalan, jangan spawn backend
--no-spawn    jangan nyalakan backend
```

### Arsitektur

Aplikasi **tidak** memuat ulang logika bot. Ia menyalakan
`python -m lucifer.cli web` sebagai proses anak, lalu bicara JSON lewat HTTP
loopback. Konsekuensinya:

- satu sumber kebenaran — bug protokol cukup diperbaiki sekali;
- GUI tidak butuh binding Python (tidak ada pybind11/ctypes);
- kalau backend mati, GUI tetap hidup dan menampilkan `● server mati`.

Klien HTTP-nya ditulis tangan (~90 baris: socket + `getaddrinfo`), termasuk
pembongkar `Transfer-Encoding: chunked` karena `http.server` Python memakainya.

### Tab

| Tab | Isi |
|---|---|
| **Bots** | tabel label/nama/status/level/ping/proxy/dunia/gems, tombol Tambah/Hapus/Connect/Disconnect |
| **Proxy** | pilih bot, isi proxy, tombol Uji/Simpan/Hapus |
| **Executor** | editor skrip Lua + Simpan + Jalankan |
| **Log** | log server (auto-scroll, disegarkan 2 detik) |

Dialog **Tambah Bot** memuat label, ltoken, GrowID, sandi, dan proxy sekaligus.

## Uji

```bash
.venv/bin/python tests/test_proxy.py        # 17 cek, termasuk SOCKS5 palsu
xvfb-run -a ./desktop/build/lucifer-desktop --no-spawn --repo "$PWD"
```

`tests/test_proxy.py` menjalankan server SOCKS5 palsu di localhost, jadi tidak
butuh internet maupun proxy sungguhan.
