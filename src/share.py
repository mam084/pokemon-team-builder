"""
share.py

Teams in the page URL, so a team survives a refresh, can be bookmarked, and
can be sent to someone as a link. Nothing is stored on a server.

The team is written as its Showdown paste (the format every tool already
understands), compressed with zlib and encoded as URL-safe base64:

    ?f=gen9championsvgc2026regmc&team=eJx1kM1OwzAQhO...

A full six-Pokemon team comes out at roughly 500 characters, well within URL
limits. Decoding goes back through the paste parser, so a hand-edited or
stale link is checked against the current regulation like any import.
"""

from __future__ import annotations

import base64
import binascii
import re
import zlib

from src.dex import Dex
from src.paste import export_paste, parse_paste
from src.team import PokemonSet

MAX_TOKEN_LENGTH = 4000  # refuse anything absurd before decompressing it
MAX_PASTE_BYTES = 20_000
_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_DAMAGED = "That team link is damaged or incomplete, so it couldn't be loaded."


def encode_team(team: list[PokemonSet]) -> str:
    """Team -> URL-safe token ('' for an empty team)."""
    if not team:
        return ""
    raw = export_paste(team).replace("Level: 50\n", "")  # implied in Champions; keeps links shorter
    packed = zlib.compress(raw.encode("utf-8"), level=9)
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def decode_team(token: str, dex: Dex) -> tuple[list[PokemonSet], list[str]]:
    """URL token -> (team, warnings). A broken token gives ([], [reason]) instead of raising."""
    token = (token or "").strip()
    if not token:
        return [], []
    if len(token) > MAX_TOKEN_LENGTH:
        return [], ["The shared team link is too long to be a team."]
    if not _TOKEN.match(token):
        return [], [_DAMAGED]
    try:
        packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(packed, MAX_PASTE_BYTES)
        if decompressor.unconsumed_tail:
            return [], ["The shared team link is too large to load."]
        if not decompressor.eof:  # a cut-off link decompresses partway; don't load half a team
            return [], [_DAMAGED]
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError, zlib.error, UnicodeDecodeError):
        return [], [_DAMAGED]
    if not text.strip():
        return [], [_DAMAGED]
    return parse_paste(text, dex)
