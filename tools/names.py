#!/usr/bin/env python3
"""Comparing participant names across sources that spell them differently.

Nike writes "Sorribes Tormo S." and "Zheng Qinwen"; Smarkets writes "Sara
Sorribes Tormo" and "Qinwen Zheng". Whole tokens are compared rather than a
guessed surname, because which part of a name is the surname varies by naming
convention and guessing it wrongly silently mismatches people.
"""
from __future__ import annotations

import unicodedata


def tokens(name: str) -> set[str]:
    """Comparable name parts: lowercased, unaccented, initials dropped."""
    flat = unicodedata.normalize("NFKD", name.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    for separator in (".", "-", "/"):
        flat = flat.replace(separator, " ")
    return {part for part in flat.split() if len(part) > 1}


def same_person(a: str, b: str) -> bool:
    """True when two spellings share at least one full name token."""
    return bool(tokens(a) & tokens(b))


def is_pair(name: str) -> bool:
    """Is this a doubles pair rather than one competitor?

    Both sources join a pair with a slash -- "Jasika O./Tomic B." and
    "Jasika O / Tomic B" -- so the separator identifies them.
    """
    return "/" in name
