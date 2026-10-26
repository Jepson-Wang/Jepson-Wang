#!/usr/bin/env python3
"""Refresh the GitHub profile: render stats cards and the open-source activity block.

Runs in GitHub Actions (see .github/workflows/profile.yml). Standard library only.

    GH_TOKEN=... GH_LOGIN=Jepson-Wang python scripts/update_profile.py
    python scripts/update_profile.py --mock sample.json   # render from saved data, no network
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ASSETS = ROOT / "assets"

# Languages that describe tooling rather than what I write.
EXCLUDED_LANGS = {"HTML", "CSS", "Makefile", "Dockerfile", "Shell", "Batchfile", "Jupyter Notebook"}
MAX_PRS = 50
STAR_THRESHOLD = 50

QUERY = """
query($login: String!, $prQuery: String!) {
  user(login: $login) {
    name
    login
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount } }
      }
    }
  }
  search(query: $prQuery, type: ISSUE, first: 50) {
    nodes {
      ... on PullRequest {
        title url number state merged
        repository { nameWithOwner stargazerCount }
      }
    }
  }
}
"""


# --------------------------------------------------------------------------- data

def fetch(login: str, token: str) -> dict:
    variables = {
        "login": login,
        # PRs I opened against repositories I don't own.
        "prQuery": f"is:pr author:{login} -user:{login} sort:updated-desc",
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": f"{login}-profile-updater"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def summarize(data: dict) -> dict:
    user = data["user"]
    repos = user["repositories"]["nodes"]
    cc = user["contributionsCollection"]

    lang_size: dict[str, int] = {}
    lang_color: dict[str, str] = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in EXCLUDED_LANGS:
                continue
            lang_size[name] = lang_size.get(name, 0) + edge["size"]
            lang_color[name] = edge["node"]["color"] or "#8b949e"
    total = sum(lang_size.values()) or 1
    top = sorted(lang_size.items(), key=lambda kv: kv[1], reverse=True)[:5]
    languages = [{"name": n, "pct": s / total, "color": lang_color[n]} for n, s in top]

    weeks = [sum(d["contributionCount"] for d in w["contributionDays"])
             for w in cc["contributionCalendar"]["weeks"]]

    prs = []
    for node in data["search"]["nodes"]:
        if not node:  # non-PR search hits come back as empty objects
            continue
        if node["state"] == "CLOSED" and not node["merged"]:
            continue  # declined PRs aren't worth showcasing
        prs.append(node)

    return {
        "name": user["name"] or user["login"],
        "login": user["login"],
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "repos_contributed": cc["totalRepositoriesWithContributedCommits"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "repos": user["repositories"]["totalCount"],
        "languages": languages,
        "weeks": weeks[-52:],
        "external_prs": prs[:MAX_PRS],
    }


# --------------------------------------------------------------------------- svg

THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328", "muted": "#59636e",
              "accent": "#0969da", "track": "#eff2f5", "bar": "#2da44e", "bar_empty": "#ebedf0"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "text": "#e6edf3", "muted": "#9198a1",
             "accent": "#4493f8", "track": "#21262d", "bar": "#3fb950", "bar_empty": "#161b22"},
}

W, H = 600, 230
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def compact(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def render_card(s: dict, theme: str) -> str:
    t = THEMES[theme]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="GitHub stats for {escape(s["login"])}">',
        "<style>",
        f"text{{font-family:{FONT};fill:{t['text']}}}",
        f".muted{{fill:{t['muted']}}}",
        ".num{font-weight:600;font-size:22px;font-variant-numeric:tabular-nums}",
        ".label{font-size:11px;letter-spacing:.04em}",
        ".h{font-size:12px;font-weight:600;letter-spacing:.06em}",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<text x="24" y="34" class="h muted">LAST 12 MONTHS</text>',
    ]

    # Left: 2x2 stat grid.
    # A handful of stars reads as a weak signal, so only show them once they mean something.
    fourth = (("STARS EARNED", s["stars"]) if s["stars"] >= STAR_THRESHOLD
              else ("REPOS CONTRIBUTED", s["repos_contributed"]))
    stats = [("CONTRIBUTIONS", s["contributions"]), ("COMMITS", s["commits"]),
             ("PULL REQUESTS", s["prs"]), fourth]
    for i, (label, value) in enumerate(stats):
        x = 24 + (i % 2) * 140
        y = 72 + (i // 2) * 52
        out.append(f'<g>'
                   f'<text x="{x}" y="{y}" class="num">{compact(value)}</text>'
                   f'<text x="{x}" y="{y + 17}" class="label muted">{label}</text></g>')

    # Right: language bar + legend.
    lx, lw = 330, 246
    out.append(f'<text x="{lx}" y="34" class="h muted">TOP LANGUAGES</text>')
    out.append(f'<clipPath id="lb"><rect x="{lx}" y="50" width="{lw}" height="8" rx="4"/></clipPath>')
    out.append(f'<rect x="{lx}" y="50" width="{lw}" height="8" rx="4" fill="{t["track"]}"/>')
    cursor = lx
    langs = s["languages"]
    for j, lang in enumerate(langs):
        width = lw - (cursor - lx) if j == len(langs) - 1 else lang["pct"] * lw
        out.append(f'<rect x="{cursor:.2f}" y="50" width="{width:.2f}" height="8" '
                   f'fill="{lang["color"]}" clip-path="url(#lb)"/>')
        cursor += width
    for j, lang in enumerate(langs):
        x = lx + (j % 2) * 128
        y = 82 + (j // 2) * 22
        out.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{lang["color"]}"/>'
                   f'<text x="{x + 16}" y="{y}" font-size="12">{escape(lang["name"])} '
                   f'<tspan class="muted">{lang["pct"] * 100:.1f}%</tspan></text>')

    # Bottom: weekly contribution bars for the past year.
    weeks = s["weeks"] or [0]
    peak = max(weeks) or 1
    bx, by, bh = 24, 214, 34
    gap = 2
    bw = (W - 48 - gap * (len(weeks) - 1)) / len(weeks)
    out.append(f'<text x="24" y="{by - bh - 10}" class="h muted">WEEKLY ACTIVITY</text>')
    for k, count in enumerate(weeks):
        h = max(2.0, count / peak * bh)
        x = bx + k * (bw + gap)
        fill = t["bar"] if count else t["bar_empty"]
        opacity = 0.35 + 0.65 * (count / peak) if count else 1
        out.append(f'<rect x="{x:.2f}" y="{by - h:.2f}" '
                   f'width="{bw:.2f}" height="{h:.2f}" rx="1.5" fill="{fill}" fill-opacity="{opacity:.2f}">'
                   f'<title>{count} contributions</title></rect>')

    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------- readme

def render_oss(prs: list[dict]) -> str:
    """One line per repository: counts, then PR numbers with their titles as hover text."""
    groups: dict[str, dict] = {}
    for pr in prs:  # search order = most recently updated first
        repo = pr["repository"]
        g = groups.setdefault(repo["nameWithOwner"], {"stars": repo["stargazerCount"], "prs": []})
        g["prs"].append(pr)
    lines = []
    for name, g in groups.items():
        merged = sum(1 for pr in g["prs"] if pr["merged"])
        open_ = len(g["prs"]) - merged
        counts = " · ".join(part for part in (
            f"{merged} merged" if merged else "", f"{open_} in review" if open_ else "") if part)
        stars = f" ★ {compact(g['stars'])}" if g["stars"] >= 100 else ""
        links = " ".join(
            f'[#{pr["number"]}]({pr["url"]} "{pr["title"].replace(chr(34), chr(39))}")' for pr in g["prs"])
        lines.append(f"- **{name}**{stars} — {counts}: {links}")
    return "\n".join(lines)


def update_readme(oss_md: str) -> bool:
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(r"(<!-- OSS:START -->\n).*?(\n<!-- OSS:END -->)", re.S)
    if not pattern.search(text):
        print("OSS markers not found in README; skipping", file=sys.stderr)
        return False
    new = pattern.sub(lambda m: m.group(1) + oss_md + m.group(2), text)
    if new != text:
        README.write_text(new, encoding="utf-8")
        return True
    return False


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", type=Path, help="render from a saved GraphQL response")
    args = ap.parse_args()

    if args.mock:
        data = json.loads(args.mock.read_text(encoding="utf-8"))
    else:
        token = os.environ.get("GH_TOKEN")
        login = os.environ.get("GH_LOGIN")
        if not token or not login:
            sys.exit("GH_TOKEN and GH_LOGIN must be set")
        data = fetch(login, token)

    summary = summarize(data)
    ASSETS.mkdir(exist_ok=True)
    for theme in THEMES:
        (ASSETS / f"stats-{theme}.svg").write_text(render_card(summary, theme), encoding="utf-8")

    # Never wipe the hand-written block when the search comes back empty.
    if summary["external_prs"]:
        changed = update_readme(render_oss(summary["external_prs"]))
        print("README OSS block", "updated" if changed else "unchanged")
    print(f"cards rendered: {summary['contributions']} contributions, "
          f"{len(summary['languages'])} languages, {len(summary['external_prs'])} external PRs")


if __name__ == "__main__":
    main()
