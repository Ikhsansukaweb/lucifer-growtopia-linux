"""
Lucifer Linux — runtime skrip Lua untuk Growtopia.

Paket ini mengimplementasikan API Lua Lucifer V1.8 (fungsi, struct, enum) di
atas klien Growtopia asli: ENet yang dipatch Ubisoft, codec Tank/Variant,
pembaca items.dat, dan parser dunia.

Contoh cepat:
    from lucifer import LuaEngine, Account

    engine = LuaEngine(accounts=[Account(username="Nama", password="...", method="legacy")])
    engine.load_scripts("scripts")
    engine.bots["Nama"].connect()
    engine._listen_events(60)
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "Account",
    "Bot",
    "BotStatus",
    "ENetHost",
    "ItemDatabase",
    "LuaEngine",
    "Player",
    "Tank",
    "World",
    "fetch_server_data",
    "load_items",
    "parse_world",
    "protocol",
    "enet",
    "hash",
    "items",
    "world",
    "bot",
    "account",
    "__version__",
]

from . import account, enet, hash, items, protocol, world  # noqa: E402
from .account import Account, fetch_server_data  # noqa: E402
from .bot import Bot, BotStatus, Player  # noqa: E402
from .enet import ENetHost  # noqa: E402
from .items import ItemDatabase, load_items  # noqa: E402
from .protocol import Tank  # noqa: E402
from .world import World, parse_world  # noqa: E402


def __getattr__(name: str):
    # LuaEngine diimpor malas supaya `import lucifer` tetap jalan walau lupa
    # belum terpasang (mis. saat hanya memakai transport ENet).
    if name == "LuaEngine":
        from .lua_api import LuaEngine  # noqa: PLC0415

        return LuaEngine
    raise AttributeError(f"module 'lucifer' tidak punya atribut {name!r}")
