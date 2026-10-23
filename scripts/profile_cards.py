#!/usr/bin/env python3
"""Gera os cards SVG do perfil do GitHub.

Saída (em --out):
  profile-header.svg     nome, bio, números e o avatar em LEDs
  profile-city.svg       contribuições do último ano como uma cidade 3D
  profile-languages.svg  linguagens ponderadas pelos bytes dos repositórios
  profile-projects.svg   repositórios fixados (ou os mais recentes)

Com GITHUB_TOKEN usa a API GraphQL. Sem token (para testar localmente) usa a
API REST pública e o calendário público de contribuições.
"""

import argparse
import datetime as dt
import html
import io
import json
import math
import os
import random
import re
import urllib.request

API = "https://api.github.com"

LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572A5",
    "HTML": "#e34c26", "CSS": "#663399", "Java": "#b07219", "C#": "#178600",
    "C": "#555555", "C++": "#f34b7d", "Go": "#00ADD8", "Rust": "#dea584",
    "Shell": "#89e051", "PHP": "#4F5D95", "Kotlin": "#A97BFF", "Dart": "#00B4AB",
    "Vue": "#41b883", "SCSS": "#c6538c", "Ruby": "#701516", "Jupyter Notebook": "#DA5B0B",
}

# paleta dos cards
BG_TOP, BG_BOTTOM = "#0f1630", "#0a0f1f"
BORDER = "#2f9e78"
ACCENT = "#5eead4"
TEXT = "#e6edf3"
MUTED = "#8b98b8"
TRACK = "#1c2747"
MONO = "'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "'Segoe UI',Inter,Helvetica,Arial,sans-serif"

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ---------------------------------------------------------------- dados

def request(url, token=None, data=None, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "profile-cards"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return raw if accept == "*/*" else json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()


GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    login name bio avatarUrl(size: 200)
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description isFork isPrivate stargazerCount pushedAt
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
      }
    }
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes { ... on Repository { name description stargazerCount pushedAt primaryLanguage { name color } } }
    }
    contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""


def fetch_graphql(login, token):
    res = request(f"{API}/graphql", token, {"query": GRAPHQL_QUERY, "variables": {"login": login}})
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    u = res["data"]["user"]
    repos = []
    for r in u["repositories"]["nodes"]:
        repos.append({
            "name": r["name"], "description": r["description"], "fork": r["isFork"],
            "private": r["isPrivate"], "stars": r["stargazerCount"], "pushed": r["pushedAt"],
            "language": (r["primaryLanguage"] or {}).get("name"),
            "languages": {e["node"]["name"]: e["size"] for e in r["languages"]["edges"]},
        })
    for e in (e for r in u["repositories"]["nodes"] for e in r["languages"]["edges"]):
        LANG_COLORS.setdefault(e["node"]["name"], e["node"]["color"] or MUTED)
    pinned = [{
        "name": p["name"], "description": p["description"], "stars": p["stargazerCount"],
        "pushed": p["pushedAt"], "language": (p["primaryLanguage"] or {}).get("name"),
    } for p in u["pinnedItems"]["nodes"] if p]
    days = [(d["date"], d["contributionCount"])
            for w in u["contributionsCollection"]["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    return {
        "login": u["login"], "name": u["name"] or u["login"], "bio": u["bio"] or "",
        "avatar": u["avatarUrl"], "followers": u["followers"]["totalCount"],
        "repo_count": u["repositories"]["totalCount"], "repos": repos, "pinned": pinned, "days": days,
    }


def fetch_public(login):
    u = request(f"{API}/users/{login}")
    repos = []
    for r in request(f"{API}/users/{login}/repos?per_page=100&sort=pushed"):
        langs = {} if r["fork"] else request(r["languages_url"])
        repos.append({
            "name": r["name"], "description": r["description"], "fork": r["fork"], "private": False,
            "stars": r["stargazers_count"], "pushed": r["pushed_at"], "language": r["language"],
            "languages": langs,
        })
    # calendário público: cada <td> tem a data e um <tool-tip> com a contagem
    page = request(f"https://github.com/users/{login}/contributions", accept="text/html")
    dates = dict(re.findall(r'data-date="([\d-]+)" id="(contribution-day-component-[\d-]+)"', page))
    counts = {}
    for target, label in re.findall(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)', page):
        m = re.match(r"(\d+) contribution", label)
        counts[target] = int(m.group(1)) if m else 0
    days = sorted((d, counts.get(cid, 0)) for d, cid in dates.items())
    return {
        "login": u["login"], "name": u["name"] or u["login"], "bio": u["bio"] or "",
        "avatar": u["avatar_url"], "followers": u["followers"], "repo_count": u["public_repos"],
        "repos": repos, "pinned": [], "days": days,
    }


# ---------------------------------------------------------------- utilidades SVG

def esc(text):
    return html.escape(str(text), quote=True)


STATIC = False


def card(width, height, body, title, extra_style=""):
    if STATIC:
        extra_style = ""
    stars = starfield(width, height, seed=width * height)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<title>{esc(title)}</title>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOTTOM}"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-50%" width="140%" height="200%">
    <feGaussianBlur stdDeviation="6" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>
<style>
  text {{ font-family: {MONO}; fill: {TEXT}; }}
  .muted {{ fill: {MUTED}; }}
  .accent {{ fill: {ACCENT}; }}
  .star {{ fill: #fff; animation: twinkle 4s ease-in-out infinite; }}
  .cursor {{ animation: blink 1.1s steps(1) infinite; }}
  @keyframes twinkle {{ 0%,100% {{ opacity: .15; }} 50% {{ opacity: .8; }} }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
  {extra_style}
</style>
<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="18" fill="url(#bg)" stroke="{BORDER}" stroke-opacity=".75" stroke-width="1.5"/>
{stars}
{body}
</svg>
"""


def starfield(width, height, seed, count=26):
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        x, y = rng.uniform(20, width - 20), rng.uniform(16, height - 16)
        out.append(f'<circle class="star" cx="{x:.1f}" cy="{y:.1f}" r="{rng.choice((0.6, 0.8, 1.1))}" '
                   f'style="animation-delay:{rng.uniform(0, 4):.2f}s"/>')
    return "\n".join(out)


ICONS = {
    "repo": '<path d="M3 1.5h9.5v13H3.8A1.8 1.8 0 0 1 2 12.7V3.3A1.8 1.8 0 0 1 3.8 1.5Zm0 11.2c0 .5.4.8.8.8h7.7M5.5 4.5h4M5.5 7h4" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>',
    "star": '<path d="M8 1.6l1.9 4 4.3.5-3.2 3 .9 4.3L8 11.2l-3.9 2.2.9-4.3-3.2-3 4.3-.5Z" fill="none" stroke="{c}" stroke-width="1.3" stroke-linejoin="round"/>',
    "chart": '<path d="M2 14.5h12M4 12V8.5M7 12V4M10 12V6.5M13 12V2.5" fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round"/>',
    "user": '<circle cx="8" cy="5" r="3" fill="none" stroke="{c}" stroke-width="1.3"/><path d="M2.5 14.5c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>',
}


def icon(name, x, y, color=ACCENT):
    return f'<g transform="translate({x},{y})">{ICONS[name].format(c=color)}</g>'


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def lang_color(name):
    return LANG_COLORS.get(name, MUTED)


def language_totals(repos):
    totals = {}
    for r in repos:
        if r["fork"]:
            continue
        for lang, size in r["languages"].items():
            totals[lang] = totals.get(lang, 0) + size
    return sorted(totals.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------- avatar em LEDs

def led_avatar(url, cx, cy, size=260, grid=44):
    """Avatar redesenhado como um painel de LEDs redondo. Precisa do Pillow."""
    try:
        from PIL import Image, ImageEnhance
        raw = request(url, accept="*/*")
        img = Image.open(io.BytesIO(raw)).convert("RGB").resize((grid, grid), Image.LANCZOS)
        img = ImageEnhance.Color(img).enhance(1.35)
    except Exception as exc:  # sem Pillow ou sem rede: o card sai sem o avatar
        print(f"avatar em LEDs ignorado: {exc}")
        return ""
    pitch = size / grid
    radius = grid / 2
    leds = []
    for gy in range(grid):
        for gx in range(grid):
            dist = math.hypot(gx + 0.5 - radius, gy + 0.5 - radius)
            if dist > radius:
                continue
            r, g, b = img.getpixel((gx, gy))
            fade = 1 if dist < radius - 3 else max(0.25, (radius - dist) / 3)
            x = cx - size / 2 + (gx + 0.5) * pitch
            y = cy - size / 2 + (gy + 0.5) * pitch
            leds.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{pitch * 0.42:.2f}" '
                        f'fill="#{r:02x}{g:02x}{b:02x}" opacity="{fade:.2f}"/>')
    return f"""<defs><clipPath id="ledclip"><circle cx="{cx}" cy="{cy}" r="{size / 2}"/></clipPath></defs>
<circle cx="{cx}" cy="{cy}" r="{size / 2 + 8}" fill="none" stroke="{ACCENT}" stroke-opacity=".25" stroke-dasharray="2 6"/>
<g>{''.join(leds)}</g>
<g clip-path="url(#ledclip)"><rect class="scan" x="{cx - size / 2}" y="{cy - size / 2}" width="{size}" height="26" fill="{ACCENT}" opacity=".12"/></g>"""


# ---------------------------------------------------------------- cards

def header_card(data, stats, langs):
    w, h = 900, 340
    top_langs = [name for name, _ in langs[:5]]
    chips, x = [], 70
    for name in top_langs:
        cw = 34 + len(name) * 8
        chips.append(f'<rect x="{x}" y="294" width="{cw}" height="26" rx="13" fill="#141d3a" stroke="#2a3866"/>'
                     f'<circle cx="{x + 13}" cy="307" r="4" fill="{lang_color(name)}"/>'
                     f'<text x="{x + 23}" y="311.5" font-size="12">{esc(name)}</text>')
        x += cw + 8
    rows = [
        ("repo", data["repo_count"], "Repositórios"),
        ("star", stats["stars"], "Estrelas"),
        ("chart", stats["total"], "Contribuições no ano"),
        ("user", data["followers"], "Seguidores"),
    ]
    lines = []
    for i, (ic, value, label) in enumerate(rows):
        y = 192 + i * 26
        lines.append(icon(ic, 70, y - 12) +
                     f'<text x="97" y="{y}" font-size="14"><tspan class="accent" font-weight="700">{value}</tspan> {label if value != 1 else label.rstrip("s")}</text>')
    body = f"""
<text x="68" y="62" font-size="15" class="accent">@{esc(data['login'])}</text>
<text x="66" y="118" font-family="{SANS}" font-size="46" font-weight="700" fill="#e9fffb" filter="url(#glow)">{esc(data['name'])}</text>
<text x="70" y="148" font-size="14" class="muted">{esc(data['bio'] or 'Desenvolvedor')}<tspan class="accent cursor"> _</tspan></text>
{''.join(lines)}
{''.join(chips)}
{led_avatar(data['avatar'], 745, 170)}"""
    style = ".scan { animation: scan 5s linear infinite; } @keyframes scan { from { transform: translateY(-30px); } to { transform: translateY(290px); } }"
    return card(w, h, body, f"{data['name']} (@{data['login']})", style)


def contribution_stats(days, repos):
    today = dt.date.today().isoformat()
    days = [(d, c) for d, c in days if d <= today]
    longest = current = 0
    for _, c in days:
        current = current + 1 if c else 0
        longest = max(longest, current)
    best_date, best = max(days, key=lambda dc: dc[1]) if days else ("", 0)
    return {
        "total": sum(c for _, c in days),
        "active": sum(1 for _, c in days if c),
        "best": best, "best_date": best_date,
        "longest": longest, "current": current,
        "today": days[-1][1] if days else 0,
        "stars": sum(r["stars"] for r in repos if not r["fork"]),
    }


def city_card(days, stats):
    w, h = 900, 320
    today = dt.date.today().isoformat()
    by_date = dict(days)
    first = dt.date.fromisoformat(days[0][0]) if days else dt.date.today()
    first -= dt.timedelta(days=(first.weekday() + 1) % 7)  # semanas começam no domingo
    weeks = 53
    peak = max([c for _, c in days] + [1])

    # semanas sobem para a direita, dias descem para a direita (frente = embaixo)
    wx, wy = 7.9, -2.55
    dx, dy_ = 4.8, 3.3
    ox, oy = 400, 262         # canto da semana 0, domingo
    max_h = 88

    def pt(wk, dy, z=0.0):
        return ox + wk * wx + dy * dx, oy + wk * wy + dy * dy_ - z

    def poly(points, fill, extra=""):
        return f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" fill="{fill}"{extra}/>'

    floor = poly([pt(0, 0), pt(weeks, 0), pt(weeks, 7), pt(0, 7)], "#0c2a2a", ' stroke="#1d5c52" stroke-width=".8"')
    grid = []
    for wk in range(weeks + 1):
        (x1, y1), (x2, y2) = pt(wk, 0), pt(wk, 7)
        grid.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")
    for dy in range(8):
        (x1, y1), (x2, y2) = pt(0, dy), pt(weeks, dy)
        grid.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")

    shades = [("#1f6f5c", "#14493d", "#0e3a31"), ("#2aa184", "#1b6b58", "#145545"),
              ("#3fd1ab", "#249073", "#1b6f59"), ("#7af0d2", "#3bb895", "#2c917a")]
    buildings = []
    m = 0.14  # espaço entre os prédios
    for wk in range(weeks):
        for dy in range(7):
            date = (first + dt.timedelta(days=wk * 7 + dy)).isoformat()
            count = by_date.get(date, 0)
            if date > today or not count:
                continue
            z = 6 + max_h * math.sqrt(count / peak)
            level = min(3, int(count / peak * 4))
            top, left, right = shades[level]
            a, b, c, d = pt(wk + m, dy + m), pt(wk + 1 - m, dy + m), pt(wk + 1 - m, dy + 1 - m), pt(wk + m, dy + 1 - m)
            up = lambda p: (p[0], p[1] - z)
            delay = f"{wk * 0.025:.2f}s"
            buildings.append((dy - wk, f'<g class="bld" style="animation-delay:{delay}">'
                              + poly([a, d, up(d), up(a)], left)
                              + poly([d, c, up(c), up(d)], right)
                              + poly([up(a), up(b), up(c), up(d)], top)
                              + f'<title>{date}: {count}</title></g>'))
    buildings.sort(key=lambda item: item[0])

    labels = []
    for wk in range(0, weeks, 9):
        month = first + dt.timedelta(days=wk * 7)
        x, y = pt(wk + 0.5, 7.6)
        labels.append(f'<text x="{x:.1f}" y="{y + 10:.1f}" font-size="10" class="muted">{MONTHS[month.month - 1]}</text>')

    best = ""
    if stats["best_date"]:
        bd = dt.date.fromisoformat(stats["best_date"])
        best = f" ({bd.day:02d}/{bd.month:02d})"
    dot = ACCENT if stats["today"] else "#3b4a6b"
    body = f"""
<text x="34" y="54" font-size="20" font-weight="700">A cidade que construí este ano</text>
<text x="866" y="40" font-size="12" class="accent" text-anchor="end">visão 3D<tspan class="cursor">_</tspan></text>
<text x="34" y="104" font-size="12" class="accent" letter-spacing="1.5">CONTRIBUIÇÕES</text>
<text x="32" y="150" font-size="42" font-weight="700">{stats['total']}</text>
<text x="34" y="188" font-size="13">{plural(stats['active'], 'dia ativo', 'dias ativos')}</text>
<text x="34" y="212" font-size="13">Recorde num dia: {stats['best']}{best}</text>
<text x="34" y="236" font-size="13">Maior sequência: {plural(stats['longest'], 'dia')}</text>
<text x="34" y="260" font-size="13">Sequência atual: {plural(stats['current'], 'dia')}</text>
<circle cx="39" cy="286" r="4" fill="{dot}"/>
<text x="50" y="290" font-size="13" class="accent">Hoje: {plural(stats['today'], 'contribuição', 'contribuições')}</text>
{floor}
<path d="{''.join(grid)}" stroke="#1d5c52" stroke-width=".5" opacity=".7"/>
{''.join(b for _, b in buildings)}
{''.join(labels)}"""
    style = ".bld { animation: rise .7s ease-out both; } @keyframes rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }"
    return card(w, h, body, "A cidade que construí este ano: contribuições em 3D", style)


def languages_card(langs):
    w, h = 445, 310
    total = sum(size for _, size in langs) or 1
    top = [(n, s) for n, s in langs[:6] if s / total >= 0.005]
    rows = []
    for i, (name, size) in enumerate(top):
        y = 108 + i * 33
        pct = size / total * 100
        bar = max(4, 180 * size / total)
        color = lang_color(name)
        rows.append(f'<circle cx="30" cy="{y - 4}" r="5" fill="{color}"/>'
                    f'<text x="44" y="{y}" font-size="13">{esc(name)}</text>'
                    f'<text x="230" y="{y}" font-size="12" fill="{color}" text-anchor="end">{pct:.0f}%</text>'
                    f'<rect x="242" y="{y - 9}" width="180" height="8" rx="4" fill="{TRACK}"/>'
                    f'<rect class="bar" x="242" y="{y - 9}" width="{bar:.1f}" height="8" rx="4" fill="{color}"/>')
    if not rows:
        rows.append(f'<text x="24" y="120" font-size="13" class="muted">Nenhuma linguagem encontrada ainda.</text>')
    body = f"""
<text x="24" y="44" font-size="17" font-weight="700">Stack de linguagens</text>
<text x="421" y="44" font-size="11" class="accent" text-anchor="end">&gt; stack.scan<tspan class="cursor">_</tspan></text>
<text x="24" y="64" font-size="11" class="accent">ponderado pelos repositórios</text>
{''.join(rows)}"""
    style = ".bar { transform-box: fill-box; animation: grow 1.2s ease-out both; } @keyframes grow { from { transform: scaleX(0); } }"
    return card(w, h, body, "Stack de linguagens", style)


def projects_card(data):
    w, h = 445, 310
    projects = data["pinned"] or [
        r for r in data["repos"] if not r["fork"] and not r["private"] and r["name"].lower() != data["login"].lower()
    ]
    rows = []
    for i, p in enumerate(projects[:4]):
        y = 86 + i * 57
        desc = p["description"] or "sem descrição"
        if len(desc) > 44:
            desc = desc[:43] + "…"
        pushed = dt.date.fromisoformat(p["pushed"][:10])
        lang = p["language"] or "—"
        rows.append(
            f'<text x="24" y="{y}" font-size="14" font-weight="700" class="accent">{esc(p["name"])}</text>'
            f'<text x="421" y="{y}" font-size="11" class="muted" text-anchor="end">★ {p["stars"]}</text>'
            f'<text x="24" y="{y + 18}" font-size="11" class="muted">{esc(desc)}</text>'
            f'<circle cx="28" cy="{y + 31}" r="4" fill="{lang_color(lang)}"/>'
            f'<text x="38" y="{y + 35}" font-size="11">{esc(lang)}'
            f'<tspan class="muted">  ·  atualizado {pushed.day:02d}/{pushed.month:02d}/{pushed.year}</tspan></text>')
    if not rows:
        rows.append('<text x="24" y="120" font-size="13" class="muted">Os primeiros projetos estão a caminho.</text>')
    flag = "--pinned" if data["pinned"] else "--recent"
    body = f"""
<text x="24" y="44" font-size="15" font-weight="700">Projects.list <tspan class="muted" font-weight="400">./projetos.sh {flag}</tspan><tspan class="accent cursor">_</tspan></text>
{''.join(rows)}"""
    return card(w, h, body, "Projetos em destaque")


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--out", default="dist")
    parser.add_argument("--static", action="store_true", help="sem animações")
    args = parser.parse_args()
    global STATIC
    STATIC = args.static

    token = os.environ.get("GITHUB_TOKEN")
    data = fetch_graphql(args.user, token) if token else fetch_public(args.user)
    langs = language_totals(data["repos"])
    stats = contribution_stats(data["days"], data["repos"])

    os.makedirs(args.out, exist_ok=True)
    cards = {
        "profile-header.svg": header_card(data, stats, langs),
        "profile-city.svg": city_card(data["days"], stats),
        "profile-languages.svg": languages_card(langs),
        "profile-projects.svg": projects_card(data),
    }
    for name, svg in cards.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"{name}: {len(svg) // 1024} KB")


if __name__ == "__main__":
    main()
