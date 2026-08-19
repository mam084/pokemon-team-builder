"""
name_utils.py

PokeAPI and Smogon use different naming conventions:
    PokeAPI:  lowercase, hyphenated              e.g. "ogerpon-wellspring"
    Smogon:   title case, spaces, punctuation     e.g. "Ogerpon-Wellspring", "Tapu Koko", "Mr. Mime"

To join data from both sources (e.g. matching a Pokemon in our dex data to
its Smogon usage stats), we normalize both to a common key.

This is a best-effort normalization, not a guaranteed-perfect mapping - a
handful of Pokemon names have irregular PokeAPI slugs (regional forms,
Nidoran's gender symbols, etc.) that this won't catch. Any unmatched names
simply won't show usage data in the dashboard rather than crashing, so it's
safe to ship as-is and refine later if specific mismatches come up.
"""

import re


def normalize_name(name: str) -> str:
    """Convert a Pokemon name (from either source) into a common lookup key."""
    key = name.lower().strip()
    key = key.replace("'", "")      # Farfetch'd -> farfetchd
    key = key.replace(".", "")      # Mr. Mime -> mr mime
    key = key.replace(":", "")      # Type: Null -> type null
    key = re.sub(r"\s+", "-", key)  # Tapu Koko -> tapu-koko
    return key