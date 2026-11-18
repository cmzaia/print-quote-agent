"""Imposition: how many finished-size pieces fit on one press sheet."""

from __future__ import annotations


def ups_per_sheet(
    piece_w: float,
    piece_h: float,
    sheet_w: float,
    sheet_h: float,
    margin: float,
    bleed: float,
) -> int:
    """Best of the two orientations, with bleed added on every edge.

    Returns 0 when the piece does not fit the printable area at all.
    """
    usable_w, usable_h = sheet_w - margin, sheet_h - margin
    pw, ph = piece_w + 2 * bleed, piece_h + 2 * bleed
    straight = int(usable_w // pw) * int(usable_h // ph)
    rotated = int(usable_w // ph) * int(usable_h // pw)
    return max(straight, rotated)
