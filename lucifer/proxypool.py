"""lucifer.proxypool — daftar proxy SOCKS5 tersimpan (`data/proxies.json`).

Dipakai tab Proxy di GUI desktop: tambah/hapus/uji proxy secara massal, lalu
pasang salah satunya ke bot. Berkasnya JSON biasa supaya bisa diedit tangan.

Bentuk tiap entri:
    {"host":"1.2.3.4","port":1080,"user":"","passwd":"","ok":null,"ms":0,
     "error":"","checked":0}
`ok` = None (belum diuji) / True / False.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .proxy import Proxy, parse, uji, uji_enet, uji_udp

__all__ = ["ProxyPool"]


class ProxyPool:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._isi: list[dict[str, Any]] = []
        self.muat()

    # -- penyimpanan ------------------------------------------------------ #
    def muat(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._isi = [d for d in data if isinstance(d, dict) and d.get("host")]
            except Exception:  # noqa: BLE001
                self._isi = []
            return self.daftar()

    def _tulis(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._isi, indent=1, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    def daftar(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._isi]

    # -- operasi ---------------------------------------------------------- #
    def tambah(self, teks: str) -> dict[str, Any]:
        """Tambah satu atau banyak proxy (satu per baris)."""
        masuk = 0
        ditolak: list[str] = []
        with self._lock:
            # Kunci WAJIB termasuk user+passwd: proxy bergaya "rotating
            # gateway" memakai host:port sama untuk ribuan kredensial, dan
            # tiap kredensial keluar lewat IP berbeda. Dedupe host:port saja
            # membuang 57 dari 58 proxy yang sah.
            ada = {(e["host"], int(e["port"]), e.get("user", ""),
                    e.get("passwd", "")) for e in self._isi}
            for baris in str(teks).replace(",", "\n").splitlines():
                baris = baris.strip()
                if not baris:
                    continue
                try:
                    p = parse(baris)
                except ValueError as e:
                    ditolak.append(f"{baris}: {e}")
                    continue
                if p is None:
                    continue
                kunci = (p.host, p.port, p.user, p.passwd)
                if kunci in ada:
                    continue
                self._isi.append({
                    "host": p.host, "port": p.port,
                    "user": p.user, "passwd": p.passwd,
                    "ok": None, "ms": 0, "error": "", "checked": 0,
                })
                ada.add(kunci)
                masuk += 1
            if masuk:
                self._tulis()
        return {"ok": True, "ditambah": masuk, "total": len(self._isi),
                "ditolak": ditolak}

    def hapus(self, host: str, port: int | str = 0) -> dict[str, Any]:
        host = (host or "").strip()
        port = int(port or 0)
        with self._lock:
            awal = len(self._isi)
            self._isi = [
                e for e in self._isi
                if not (e["host"] == host and (not port or int(e["port"]) == port))
            ]
            n = awal - len(self._isi)
            if n:
                self._tulis()
        return {"ok": n > 0, "dihapus": n, "total": len(self._isi)}

    def hapus_gagal(self) -> dict[str, Any]:
        with self._lock:
            awal = len(self._isi)
            self._isi = [e for e in self._isi if e.get("ok") is not False]
            n = awal - len(self._isi)
            if n:
                self._tulis()
        return {"ok": True, "dihapus": n, "total": len(self._isi)}

    def cek(self, batas: int = 0, timeout: float = 6.0) -> dict[str, Any]:
        """Uji proxy: UDP dulu, lalu ENet ke server Growtopia. `batas`>0 = N teratas.

        Uji yang dipakai adalah ENet handshake ke SERVER GROWTOPIA sungguhan.
        Proxy yang lolos TCP tapi menolak UDP tetap ditandai gagal — itu satu-
        satunya uji yang berarti untuk game ini.
        """
        with self._lock:
            target = list(self._isi[: batas or len(self._isi)])

        server: Optional[tuple[str, int]] = None
        alasan_server = ""
        try:
            from .account import fetch_server_data  # noqa: PLC0415

            sd = fetch_server_data(225, "5.58", timeout=15)
            server = (sd["server"], int(sd["port"]))
        except Exception as e:  # noqa: BLE001
            alasan_server = f"server Growtopia tak diketahui: {e}"

        hasil: dict[int, tuple[bool, str, int]] = {}

        def satu(idx: int, e: dict[str, Any]) -> None:
            p = Proxy(str(e["host"]), int(e["port"]), str(e.get("user") or ""),
                      str(e.get("passwd") or ""))
            t0 = time.time()
            # Uji UDP dulu: murah (~1 dtk) dan langsung menyingkirkan proxy
            # TCP-only seperti webshare "direct" yang selalu menolak
            # UDP ASSOCIATE. Tanpa ini, uji ENet ke server yang sedang
            # tak terjangkau menghasilkan "gagal" yang menyesatkan.
            udp_ok, udp_pesan = uji_udp(p, timeout=timeout,
                                        target=server if server else None)
            if not udp_ok:
                hasil[idx] = (False, f"tidak bisa UDP: {udp_pesan}", 
                              int((time.time() - t0) * 1000))
                return
            if server is None:
                hasil[idx] = (True, f"UDP ok — {alasan_server}",
                              int((time.time() - t0) * 1000))
                return
            ok, pesan = uji_enet(p, server, timeout_ms=int(timeout * 1000))
            hasil[idx] = (ok, pesan, int((time.time() - t0) * 1000))

        utas = [threading.Thread(target=satu, args=(i, e), daemon=True)
                for i, e in enumerate(target)]
        for t in utas:
            t.start()
        for t in utas:
            t.join(timeout + 4)

        hidup = 0
        with self._lock:
            for i, e in enumerate(target):
                ok, pesan, ms = hasil.get(i, (False, "tidak diuji (timeout)", 0))
                e["ok"] = ok
                e["ms"] = ms
                e["error"] = "" if ok else pesan
                e["checked"] = int(time.time())
                if ok:
                    hidup += 1
            self._tulis()
        return {"ok": True, "diuji": len(target), "hidup": hidup,
                "mati": len(target) - hidup, "total": len(self._isi)}

    def pilih(self, host: str, port: int | str = 0) -> Optional[str]:
        """URL proxy untuk ditempel ke akun, atau None."""
        host = (host or "").strip()
        port = int(port or 0)
        with self._lock:
            for e in self._isi:
                if e["host"] == host and (not port or int(e["port"]) == port):
                    p = Proxy(str(e["host"]), int(e["port"]),
                              str(e.get("user") or ""), str(e.get("passwd") or ""))
                    return p.url()
        return None
