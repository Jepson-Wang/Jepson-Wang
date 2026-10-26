#!/usr/bin/env python3
"""Assemble the tech-stack icon rows from the tiles in assets/icons/.

Edit ROWS, then run `python scripts/build_stack.py` and commit assets/stack/.
A tile is looked up as <Name>-Dark.svg / <Name>-Light.svg, falling back to <Name>.svg.

Tiles: skill-icons (MIT, github.com/tandpfun/skill-icons) and
simple-icons (CC0, simpleicons.org) logos drawn in the same style.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"
OUT = ROOT / "assets" / "stack"

ROWS = {
    "languages": ["GoLang", "Python", "Java"],
    "backend": ["FastAPI", "Gin", "gRPC", "LangChain"],
    "data": ["PostgreSQL", "MySQL", "Redis", "SQLite"],
    "tools": ["Docker", "Linux", "Git", "GithubActions", "Pytest"],
    "learning": ["Hadoop", "Hive", "Celery"],
}

TILE, GAP = 256, 44     # source tile size and spacing, in tile units
DISPLAY = 52            # rendered height of one icon, in px


def tile(name: str, theme: str) -> str:
    for candidate in (ICONS / f"{name}-{theme}.svg", ICONS / f"{name}.svg"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"no tile for {name!r} in {ICONS}")


def namespaced(svg: str, prefix: str) -> str:
    """Prefix ids so gradients from different tiles can't collide in one file."""
    ids = set(re.findall(r'id="([^"]+)"', svg))
    for old in ids:
        new = f"{prefix}{old}"
        svg = svg.replace(f'id="{old}"', f'id="{new}"')
        svg = svg.replace(f"url(#{old})", f"url(#{new})")
        svg = svg.replace(f'href="#{old}"', f'href="#{new}"')
    return svg


def inner(svg: str) -> str:
    body = re.sub(r"^.*?<svg[^>]*>", "", svg, count=1, flags=re.S)
    return body.rsplit("</svg>", 1)[0]


def build_row(names: list[str], theme: str) -> str:
    width = len(names) * (TILE + GAP) - GAP
    parts = []
    for i, name in enumerate(names):
        body = inner(namespaced(tile(name, theme), f"t{i}_"))
        parts.append(f'<svg x="{i * (TILE + GAP)}" y="0" width="{TILE}" height="{TILE}" '
                     f'viewBox="0 0 {TILE} {TILE}"><title>{name}</title>{body}</svg>')
    px_w = round(width * DISPLAY / TILE)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{px_w}" height="{DISPLAY}" viewBox="0 0 {width} {TILE}" fill="none">'
            + "".join(parts) + "</svg>")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for row, names in ROWS.items():
        for theme in ("Dark", "Light"):
            (OUT / f"{row}-{theme.lower()}.svg").write_text(build_row(names, theme), encoding="utf-8")
    print(f"built {len(ROWS)} rows")


if __name__ == "__main__":
    main()
