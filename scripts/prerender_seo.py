#!/usr/bin/env python3
"""Prerender crawlable semantic HTML into #root for LearnPokémon dist."""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/workspace/learnpokemon-deploy")
DIST = ROOT / "dist"
DATA = DIST / "data"
CACHE = ROOT / ".card-cache"
JS_PATH = DIST / "assets" / "index-C_5BRtms.js"
CSS_HREF = "/assets/index-C7yFYYVe.css"
JS_HREF = "/assets/index-C_5BRtms.js"
CANONICAL_HOST = "https://learnpokemon.fun"
CONTACT = "learnpokemonfun@outlook.com"
DISCLAIMER_EN = (
    "LearnPokémon is an unofficial fan project. It is not affiliated with Nintendo, "
    "Game Freak, Creatures, or The Pokémon Company."
)
DISCLAIMER_JA = (
    "LearnPokémonは非公式のファンプロジェクトです。任天堂、ゲームフリーク、クリーチャーズ、"
    "株式会社ポケモンとは一切関係ありません。"
)

CACHE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# JS object extraction
# ---------------------------------------------------------------------------

def extract_balanced(s: str, start: int) -> str:
    pairs = {"{": "}", "[": "]"}
    depth = 1
    stack = [pairs[s[start]]]
    in_str = None
    esc = False
    for j in range(start + 1, len(s)):
        c = s[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_str:
                in_str = None
            continue
        if c in "\"'`":
            in_str = c
            continue
        if c in "{[":
            stack.append(pairs[c])
            depth += 1
        elif c in "}]":
            if stack and c == stack[-1]:
                stack.pop()
                depth -= 1
                if depth == 0:
                    return s[start : j + 1]
            else:
                depth -= 1
                if depth == 0:
                    return s[start : j + 1]
    raise ValueError("unbalanced")


def extract_string(s: str, i: int):
    quote = s[i]
    i += 1
    buf = []
    esc = False
    while i < len(s):
        ch = s[i]
        if esc:
            if ch == "n":
                buf.append("\n")
            elif ch == "t":
                buf.append("\t")
            elif ch == "r":
                buf.append("\r")
            elif ch == "u" and i + 4 < len(s) and re.match(r"[0-9a-fA-F]{4}", s[i + 1 : i + 5]):
                buf.append(chr(int(s[i + 1 : i + 5], 16)))
                i += 4
            else:
                buf.append(ch)
            esc = False
            i += 1
            continue
        if ch == "\\":
            esc = True
            i += 1
            continue
        if ch == quote:
            return "".join(buf), i + 1
        buf.append(ch)
        i += 1
    return "".join(buf), i


def parse_js_value(s: str, i: int = 0):
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    c = s[i]
    if c in "\"'`":
        return extract_string(s, i)
    if c == "{":
        obj = {}
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if s[i] == "}":
                return obj, i + 1
            if s[i] in "\"'`":
                key, i = extract_string(s, i)
            else:
                m = re.match(r"[A-Za-z_$][\w$]*", s[i:])
                if not m:
                    raise ValueError(f"bad key {s[i:i+40]!r}")
                key = m.group(0)
                i += len(key)
            while i < len(s) and s[i] in " \t\n\r":
                i += 1
            if s[i] != ":":
                raise ValueError(f"no colon {s[i:i+20]!r}")
            i += 1
            val, i = parse_js_value(s, i)
            obj[key] = val
    if c == "[":
        arr = []
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if s[i] == "]":
                return arr, i + 1
            val, i = parse_js_value(s, i)
            arr.append(val)
    if s.startswith("true", i):
        return True, i + 4
    if s.startswith("false", i):
        return False, i + 5
    if s.startswith("null", i):
        return None, i + 4
    m = re.match(r"-?\d+\.?\d*([eE][+-]?\d+)?", s[i:])
    if m:
        num = m.group(0)
        i += len(num)
        return (float(num) if "." in num or "e" in num.lower() else int(num)), i
    raise ValueError(f"bad at {i}: {s[i:i+50]!r}")


def load_js_data():
    js = JS_PATH.read_text(encoding="utf-8")

    def grab(marker: str, expect: str):
        idx = js.find(marker)
        if idx < 0:
            raise RuntimeError(f"missing {marker}")
        start = js.find(expect, idx)
        return parse_js_value(extract_balanced(js, start), 0)[0]

    vr = grab("var vr=", "{")
    Ia = grab("var Ia=", "{")
    Va = grab(",Va=", "{")
    Vo = grab("var Vo=", "{")
    za = grab(",za=[", "[")
    # rarity scores
    # Prefer rarity-score table (second var Zr= in the bundle)
    idx = js.find("var Zr=[{label:`mega hyper rare`")
    if idx < 0:
        raise RuntimeError("missing Zr rarity table")
    start = js.find("[", idx)
    Zr = parse_js_value(extract_balanced(js, start), 0)[0]
    return {"vr": vr, "Ia": Ia, "Va": Va, "Vo": Vo, "za": za, "Zr": Zr, "js": js}


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

COMMON_HEAD = """    <meta charset="UTF-8" />
    <link rel="icon" href="/favicon.ico?v=5" sizes="any" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="index,follow" />
    <meta property="og:site_name" content="LearnPokémon" />
    <meta property="og:type" content="website" />
    <meta property="og:image" content="https://learnpokemon.fun/og.png?v=5" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="LearnPokémon, an unofficial Pokémon TCG compendium" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:image" content="https://learnpokemon.fun/og.png?v=5" />
    <meta name="twitter:image:alt" content="LearnPokémon, an unofficial Pokémon TCG compendium" />
    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png?v=5" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png?v=5" />
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4059575347806121"
     crossorigin="anonymous"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,700&family=Outfit:wght@400;500;600;700&display=swap"
      rel="stylesheet"
    />
    <link
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@500&amp;text=%E5%AD%90%E4%B8%91%E5%AF%85%E5%8D%AF%E8%BE%B0%E5%B7%B3%E5%8D%88%E6%9C%AA%E7%94%B3%E9%85%89%E6%88%8C%E4%BA%A5&amp;display=swap"
      rel="stylesheet"
    />
    <script type="module" crossorigin src="{js}"></script>
    <link rel="stylesheet" crossorigin href="{css}">""".format(
    js=JS_HREF, css=CSS_HREF
)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def esc_text(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def write_page(
    path: Path,
    *,
    lang: str,
    title: str,
    description: str,
    canonical_path: str,
    root_html: str,
):
    """Write a full index.html. canonical_path should start with / and have no trailing slash (except home /)."""
    if canonical_path != "/" and canonical_path.endswith("/"):
        canonical_path = canonical_path.rstrip("/")
    canon = CANONICAL_HOST + ("" if canonical_path == "/" else canonical_path)
    if canonical_path == "/":
        canon = CANONICAL_HOST + "/"
    og_url = canon
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = f"""<!doctype html>
<html lang="{esc(lang)}">
  <head>
{COMMON_HEAD}
    <title>{esc_text(title)}</title>
    <meta
      name="description"
      content="{esc(description)}"
    />
    <meta property="og:title" content="{esc(title)}" />
    <meta
      property="og:description"
      content="{esc(description)}"
    />
    <meta property="og:url" content="{esc(og_url)}" />
    <meta name="twitter:title" content="{esc(title)}" />
    <meta name="twitter:description" content="{esc(description)}" />
    <link rel="canonical" href="{esc(canon)}" />
  </head>
  <body>
    <div id="root">
{root_html}
    </div>
  </body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def disclaimer_block(ja: bool = False) -> str:
    text = DISCLAIMER_JA if ja else DISCLAIMER_EN
    contact_label = "連絡先" if ja else "Contact"
    return f"""      <aside class="disclaimer-banner" role="note">
        <p>{esc_text(text)}</p>
        <p>{esc_text(contact_label)}: <a href="mailto:{CONTACT}">{esc_text(CONTACT)}</a></p>
      </aside>"""


def nav_links(prefix: str = "", ja: bool = False) -> str:
    """prefix like '' or '/ja' or '/en-ja' or '/ja-en'."""
    def p(route: str) -> str:
        if route == "/":
            return prefix + "/" if prefix else "/"
        return f"{prefix}{route}"

    labels = (
        [("ホーム", "/"), ("図鑑", "/pokedex"), ("ランキング", "/rankings"), ("ものがたり", "/lore"), ("About", "/about/")]
        if ja
        else [("Home", "/"), ("Pokédex", "/pokedex"), ("Rankings", "/rankings"), ("Lore", "/lore"), ("About", "/about/")]
    )
    # Home for locale shells: prefix alone or /
    items = []
    for label, route in labels:
        href = p(route) if route != "/" else (prefix if prefix else "/")
        if href == "":
            href = "/"
        items.append(f'<a href="{esc(href)}">{esc_text(label)}</a>')
    return " · ".join(items)


# ---------------------------------------------------------------------------
# Card fetching
# ---------------------------------------------------------------------------

FAILED_FETCHES: list[str] = []


def fetch_en_cards(set_id: str) -> list[dict] | None:
    """Return card list, or None if fetch failed. Uses local JSON or cache first."""
    local = DATA / "cards" / f"{set_id}.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))

    cache_path = CACHE / f"{set_id}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "data" in data:
                return data["data"]
        except Exception:
            pass

    cards: list[dict] = []
    page = 1
    total_count = None
    while True:
        q = urllib.parse.urlencode(
            {"q": f"set.id:{set_id}", "pageSize": 250, "page": page}
        )
        url = f"https://api.pokemontcg.io/v2/cards?{q}"
        ok = False
        last_err = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "LearnPokemonPrerender/1.0 (+https://learnpokemon.fun)",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                batch = payload.get("data") or []
                if total_count is None:
                    total_count = payload.get("totalCount") or payload.get("count")
                cards.extend(batch)
                ok = True
                break
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        if not ok:
            FAILED_FETCHES.append(set_id)
            print(f"  FAIL fetch {set_id}: {last_err}")
            return None
        if not batch:
            break
        if total_count is not None and len(cards) >= int(total_count):
            break
        if len(batch) < 250:
            break
        page += 1
        time.sleep(0.35)

    cache_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    return cards


def load_ja_cards(set_id: str) -> list[dict] | None:
    p = DATA / "ja-cards" / f"{set_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def sort_en_cards(cards: list[dict]) -> list[dict]:
    def key(c):
        num = str(c.get("number") or "")
        return (0, int(num)) if num.isdigit() else (1, num)

    return sorted(cards, key=key)


def sort_ja_cards(cards: list[dict]) -> list[dict]:
    def key(c):
        num = str(c.get("localId") or c.get("number") or "")
        digits = re.sub(r"\D", "", num)
        return (0, int(digits)) if digits else (1, num)

    return sorted(cards, key=key)


def set_card_list_title(name: str, ja: bool = False) -> str:
    if ja:
        return f"{name} カードリスト | LearnPokémon"
    display = "Base Set" if name == "Base" else name
    return f"{display} Card List | LearnPokémon"


def set_meta_description(s: dict, ja: bool = False) -> str:
    name = s.get("name") or s.get("id")
    series = s.get("series") or ""
    total = s.get("printedTotal") or s.get("total") or ""
    release = s.get("releaseDate") or ""
    if ja:
        return (
            f"{name}は、シリーズ「{series}」の日本語ポケモンカードセットです。"
            f"収録カード数 {total}、発売日 {release}。"
            f"非公式ファン百科のカードリスト（価格保証はありません）。"
        )
    return (
        f"{name} is a Pokémon TCG set in the {series} series — "
        f"{total} cards, released {release}. "
        f"Unofficial fan encyclopedia card list (not live market prices)."
    )


def render_en_card_list(cards: list[dict]) -> str:
    lis = []
    for c in cards:
        num = esc_text(c.get("number") or "")
        name = esc_text(c.get("name") or "")
        rarity = c.get("rarity") or ""
        st = c.get("supertype") or ""
        extra = " · ".join(x for x in (st, rarity) if x)
        extra_html = f" — {esc_text(extra)}" if extra else ""
        lis.append(f"          <li><span class=\"card-num\">{num}</span> {name}{extra_html}</li>")
    return "        <ol class=\"card-grid\">\n" + "\n".join(lis) + "\n        </ol>"


def render_ja_card_list(cards: list[dict]) -> str:
    lis = []
    for c in cards:
        num = esc_text(c.get("localId") or c.get("number") or "")
        name = esc_text(c.get("name") or c.get("nameJa") or "")
        rarity = c.get("rarity") or ""
        cat = c.get("category") or ""
        extra = " · ".join(x for x in (cat, rarity) if x)
        extra_html = f" — {esc_text(extra)}" if extra else ""
        lis.append(f"          <li><span class=\"card-num\">{num}</span> {name}{extra_html}</li>")
    return "        <ol class=\"card-grid\">\n" + "\n".join(lis) + "\n        </ol>"


def render_set_root(
    s: dict,
    cards: list[dict] | None,
    *,
    ja_catalog: bool,
    path_prefix: str,
    fetch_failed: bool,
) -> str:
    name = s.get("name") or s["id"]
    series = s.get("series") or ""
    total = s.get("printedTotal") or s.get("total") or ""
    release = s.get("releaseDate") or ""
    is_ja_ui = path_prefix in ("/ja", "/ja-en")
    disc = disclaimer_block(ja=is_ja_ui)

    if ja_catalog:
        intro = (
            f"{esc_text(name)}（{esc_text(s['id'])}）は、シリーズ「{esc_text(series)}」の"
            f"日本語ポケモンカードセットです。発売日 {esc_text(release)}、収録 {esc_text(total)} 枚。"
            if is_ja_ui
            else f"{esc_text(name)} ({esc_text(s['id'])}) is a Japanese Pokémon TCG set in the "
            f"{esc_text(series)} series — {esc_text(total)} cards, released {esc_text(release)}."
        )
    else:
        intro = (
            f"{esc_text(name)}（{esc_text(s['id'])}）は、シリーズ「{esc_text(series)}」の"
            f"英語版ポケモンカードセットです。発売日 {esc_text(release)}、収録 {esc_text(total)} 枚。"
            if is_ja_ui
            else f"{esc_text(name)} ({esc_text(s['id'])}) is an English Pokémon TCG set in the "
            f"{esc_text(series)} series — {esc_text(total)} cards, released {esc_text(release)}."
        )

    parts = [
        f'      <article class="set-page">',
        f'        <header class="set-hero">',
        f"          <h1>{esc_text(name)}</h1>",
        f'          <p class="lede">{intro}</p>',
        f"          <p>Series: {esc_text(series)} · Cards: {esc_text(total)} · Released: {esc_text(release)}</p>",
        f"        </header>",
        disc,
    ]

    if cards:
        parts.append(
            "        <h2>Card list</h2>"
            if not is_ja_ui
            else "        <h2>カードリスト</h2>"
        )
        parts.append(
            render_ja_card_list(sort_ja_cards(cards))
            if ja_catalog
            else render_en_card_list(sort_en_cards(cards))
        )
    else:
        note = (
            "カードチェックリストはアプリ内で読み込まれます。このページではセット情報のみ表示しています。"
            if is_ja_ui
            else (
                "The interactive checklist loads in the app. "
                + (
                    "Card names could not be fetched for prerender; set facts above are from the catalog."
                    if fetch_failed
                    else "Card list data was not available for prerender; set facts above are from the catalog."
                )
            )
        )
        parts.append(f"        <p>{esc_text(note)}</p>")

    parts.append(
        f'        <p class="kicker"><a href="{esc(path_prefix + "/" if path_prefix else "/")}">← Home</a></p>'
    )
    parts.append("      </article>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Home / pokedex / rankings / lore
# ---------------------------------------------------------------------------

def home_root(locale: str, sets: list[dict], jsdata: dict) -> str:
    vr = jsdata["vr"]
    # en-ja and ja-en fall back to en/ja UI strings appropriately
    ui_key = "ja" if locale in ("ja", "ja-en") else "en"
    copy = vr[ui_key]
    headline = copy["headline"]
    sub = copy["sub"]
    meta = jsdata["Ia"][locale if locale in jsdata["Ia"] else "en"]
    if isinstance(meta, dict):
        # Ia values are plain strings in this bundle
        blurb = meta
    else:
        blurb = meta
    ja = locale in ("ja", "ja-en")
    prefix = {"en": "", "ja": "/ja", "en-ja": "/en-ja", "ja-en": "/ja-en"}[locale]
    encyclopedia = (
        "非公式のポケモンカードセット百科とポケモン図鑑です。"
        if ja
        else "This is an unofficial Pokémon TCG set encyclopedia and Pokédex."
    )
    set_links = []
    # Link sets according to catalog for this shell
    if locale in ("ja", "en-ja"):
        href_base = f"{prefix}/sets"
    else:
        href_base = f"{prefix}/sets" if prefix else "/sets"
    for s in sets:
        set_links.append(
            f'          <li><a href="{esc(href_base + "/" + s["id"])}">{esc_text(s["name"])}</a>'
            f' <span class="kicker">({esc_text(s.get("releaseDate") or "")})</span></li>'
        )
    sets_ol = "        <ul class=\"card-grid\">\n" + "\n".join(set_links) + "\n        </ul>"
    return f"""      <div class="home">
        <h1 class="home-headline">{esc_text(headline)}</h1>
        <p class="home-sub">{esc_text(sub)}</p>
        <p>{esc_text(encyclopedia)}</p>
        <p>{esc_text(blurb)}</p>
{disclaimer_block(ja=ja)}
        <nav aria-label="Site">
          <p>{nav_links(prefix, ja=ja)}</p>
        </nav>
        <h2>{esc_text(copy.get("expansions") or ("Sets" if not ja else "セット"))}</h2>
{sets_ol}
      </div>"""


def pokedex_root(species: list[dict]) -> str:
    lis = []
    for s in species:
        types = ", ".join(s.get("types") or [])
        num = f"#{s['id']:04d}"
        # No species detail URLs — plain text
        lis.append(
            f'          <li><strong>{esc_text(num)}</strong> {esc_text(s["name"])}'
            f' — {esc_text(types)}</li>'
        )
    return f"""      <div class="home">
        <h1>Pokédex</h1>
        <p class="lede">An unofficial educational index of {len(species)} Pokémon species — names, numbers, and types. Filters stay interactive in the app.</p>
{disclaimer_block(False)}
        <nav><p>{nav_links("")}</p></nav>
        <h2>Species ({len(species)})</h2>
        <ul class="card-grid">
{chr(10).join(lis)}
        </ul>
      </div>"""


def rankings_hub_root() -> str:
    return f"""      <div class="rank-page">
        <p class="kicker">Unofficial educational rankings</p>
        <h1>Top 100s</h1>
        <p class="lede">Browse educational Top 100 lists for raw market value among indexed sets, species base-stat power, and printed rarity labels. These are not live guaranteed prices.</p>
{disclaimer_block(False)}
        <nav><p>{nav_links("")}</p></nav>
        <ul class="rank-list">
          <li><a href="/rankings/value">Value</a> — top raw prices in indexed sets</li>
          <li><a href="/rankings/power">Power</a> — top species by base-stat total</li>
          <li><a href="/rankings/rarity">Rarity</a> — top chase cards by printed rarity label</li>
        </ul>
      </div>"""


def rankings_value_root(tv: dict) -> str:
    cards = tv.get("cards") or []
    source = tv.get("source") or "bundled set card JSON"
    generated = tv.get("generatedAt") or ""
    note = tv.get("coverageNote") or ""
    rows = []
    for c in cards:
        rows.append(
            "          <tr>"
            f"<td>{esc_text(c.get('rank'))}</td>"
            f"<td>{esc_text(c.get('name'))}</td>"
            f"<td>{esc_text(c.get('setName'))} #{esc_text(c.get('number'))}</td>"
            f"<td>{esc_text(c.get('rarity'))}</td>"
            f"<td>{esc_text(c.get('market'))} {esc_text(c.get('currency') or 'USD')}</td>"
            "</tr>"
        )
    return f"""      <div class="rank-page">
        <p class="kicker">Ungraded market, indexed sets</p>
        <h1>Top raw prices in indexed sets.</h1>
        <p class="lede">The highest ungraded TCGPlayer market price among cards in the set files LearnPokémon currently bundles. Not every card ever printed, and not a PSA grade or a one-of-a-kind trophy.</p>
        <p>Source: {esc_text(source)}. Generated at {esc_text(generated)}. {esc_text(note)} Not live guaranteed prices.</p>
{disclaimer_block(False)}
        <nav><p><a href="/rankings/value">Value</a> · <a href="/rankings/power">Power</a> · <a href="/rankings/rarity">Rarity</a></p></nav>
        <table class="rank-list">
          <thead><tr><th>#</th><th>Card</th><th>Set</th><th>Rarity</th><th>Market</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>"""


def rankings_power_root(species_top: list[dict]) -> str:
    rows = []
    for i, s in enumerate(species_top, 1):
        st = s["stats"]
        total = st["hp"] + st["attack"] + st["defense"] + st["specialAttack"] + st["specialDefense"] + st["speed"]
        rows.append(
            f'          <li><strong>#{i}</strong> {esc_text(s["name"])} '
            f'(#{s["id"]:04d}) — base-stat total {total}</li>'
        )
    return f"""      <div class="rank-page">
        <p class="kicker">Species base stats</p>
        <h1>Top 100 by power.</h1>
        <p class="lede">Power is the unweighted base-stat total of each species. It is not a card price.</p>
        <p>Source: local Pokédex species stats in data/pokedex.json. Educational reference only.</p>
{disclaimer_block(False)}
        <nav><p><a href="/rankings/value">Value</a> · <a href="/rankings/power">Power</a> · <a href="/rankings/rarity">Rarity</a></p></nav>
        <ol class="rank-list">
{chr(10).join(rows)}
        </ol>
      </div>"""


def rarity_score(label: str | None, Zr: list[dict]) -> int:
    if not label:
        return 0
    t = label.strip().lower()
    for e in Zr:
        if e["label"] == t:
            return e["score"]
    for e in Zr:
        if e["label"] in t:
            return e["score"]
    return 18


def rankings_rarity_root(chase: list[dict], Zr: list[dict]) -> str:
    # Deduplicate by id, sort like mi()/di()
    seen = set()
    uniq = []
    for c in chase:
        cid = c.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        uniq.append(c)

    def sort_key(c):
        return (
            -rarity_score(c.get("rarity"), Zr),
            -(1 if (c.get("set") or {}).get("releaseDate") else 0),
            (c.get("set") or {}).get("releaseDate") or "",
            # secret (number > printedTotal) first — mimic ci inverted via sort in di: Number(ci(t))-Number(ci(e)) so True>False
            # di: si(t)-si(e) || releaseDate localeCompare || Number(ci(t))-Number(ci(e)) || number || id
        )

    # Implement closer to di
    def is_secret(c):
        pt = (c.get("set") or {}).get("printedTotal")
        num = c.get("number") or ""
        if not pt or not re.match(r"^\d+$", str(num)):
            return False
        return int(num) > int(pt)

    def num_key(a, b):
        return 0  # use sorted with cmp via key tuple

    uniq.sort(
        key=lambda c: (
            -rarity_score(c.get("rarity"), Zr),
            (c.get("set") or {}).get("releaseDate") or "",
            -int(is_secret(c)),
            # numeric number string — approximate with zero-pad
            str(c.get("number") or "").zfill(8),
            c.get("id") or "",
        )
    )
    # releaseDate in di is localeCompare of t vs e with higher rarity first; for same rarity newer first? 
    # localeCompare(t, e) ascending means older first when rarity equal. Keep as above.
    top = uniq[:100]
    rows = []
    for i, c in enumerate(top, 1):
        set_name = (c.get("set") or {}).get("name") or ""
        rows.append(
            f'          <li><strong>#{i}</strong> {esc_text(c.get("name"))} — '
            f'{esc_text(set_name)} #{esc_text(c.get("number"))} · {esc_text(c.get("rarity") or "Unlisted")}</li>'
        )
    return f"""      <div class="rank-page">
        <p class="kicker">Printed chase labels</p>
        <h1>Top 100 by rarity.</h1>
        <p class="lede">Rarity ranks the printed label the Pokémon TCG API stored. It is not a pull rate or a price.</p>
        <p>Source: bundled data/chase.json snapshot of Hyper Rare / Special Illustration Rare and related chase cards. Not live guaranteed prices.</p>
{disclaimer_block(False)}
        <nav><p><a href="/rankings/value">Value</a> · <a href="/rankings/power">Power</a> · <a href="/rankings/rarity">Rarity</a></p></nav>
        <ol class="rank-list">
{chr(10).join(rows)}
        </ol>
      </div>"""


def lore_root(Va_loc: dict, za: list[dict], *, locale: str) -> str:
    ja = locale in ("ja", "ja-en")
    prefix = {"en": "", "ja": "/ja", "en-ja": "/en-ja", "ja-en": "/ja-en"}[locale]
    sections_html = []
    for sec in Va_loc.get("sections") or []:
        paras = "\n".join(f"          <p>{esc_text(p)}</p>" for p in (sec.get("p") or []))
        # creators section may have people
        people = sec.get("people") or []
        people_html = ""
        if people:
            items = []
            for pe in people:
                items.append(
                    f"            <li><strong>{esc_text(pe.get('name'))}</strong>"
                    f" — {esc_text(pe.get('role'))}. {esc_text(pe.get('bio'))}</li>"
                )
            people_html = "          <ul>\n" + "\n".join(items) + "\n          </ul>"
        sections_html.append(
            f'        <section id="{esc(sec.get("id") or "")}" class="prose">\n'
            f'          <h2>{esc_text(sec.get("h") or "")}</h2>\n'
            f"{paras}\n{people_html}\n"
            f"        </section>"
        )
    char_link = f"{prefix}/lore/characters"
    return f"""      <article class="lore">
        <p class="kicker">{esc_text(Va_loc.get("kicker") or "")}</p>
        <h1>{esc_text(Va_loc.get("title") or "Lore")}</h1>
        <p class="lede lore-intro">{esc_text(Va_loc.get("lede") or "")}</p>
{disclaimer_block(ja=ja)}
        <nav><p>{nav_links(prefix, ja=ja)} · <a href="{esc(char_link)}">{"人物" if ja else "Characters"}</a></p></nav>
{chr(10).join(sections_html)}
      </article>"""


def lore_characters_root(za: list[dict], *, locale: str) -> str:
    ja = locale in ("ja", "ja-en")
    prefix = {"en": "", "ja": "/ja", "en-ja": "/en-ja", "ja-en": "/ja-en"}[locale]
    title = "人物 — ポケモンのキャラクター" if ja else "Characters — faces of the Pokémon world"
    lede = (
        "アニメとゲームに登場する主な人物の非公式ガイドです。詳細ページのURLは用意していません。"
        if ja
        else "An unofficial guide to major characters from the anime and games. There are no separate species or character detail routes."
    )
    groups = {}
    for c in za:
        groups.setdefault(c.get("group") or "other", []).append(c)
    blocks = []
    for group, members in groups.items():
        items = []
        for c in members:
            name = c.get("nameJa") if ja else c.get("name")
            role = c.get("roleJa") if ja else c.get("role")
            who = c.get("whoJa") if ja else c.get("who")
            history = c.get("historyJa") if ja else c.get("history")
            items.append(
                f'          <li class="prose"><strong>{esc_text(name)}</strong> — {esc_text(role)}. '
                f"{esc_text(who)} {esc_text(history)}</li>"
            )
        blocks.append(
            f'        <h2>{esc_text(group)}</h2>\n        <ul class="rank-list">\n'
            + "\n".join(items)
            + "\n        </ul>"
        )
    return f"""      <article class="lore">
        <p class="kicker">{"人物ガイド" if ja else "Character guide"}</p>
        <h1>{esc_text(title)}</h1>
        <p class="lede lore-intro">{esc_text(lede)}</p>
{disclaimer_block(ja=ja)}
        <nav><p>{nav_links(prefix, ja=ja)} · <a href="{esc(prefix + "/lore")}">{"ものがたり" if ja else "Lore"}</a></p></nav>
{chr(10).join(blocks)}
      </article>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading data...")
    jsdata = load_js_data()
    sets_en = json.loads((DATA / "sets.json").read_text(encoding="utf-8"))
    sets_ja = json.loads((DATA / "sets-ja.json").read_text(encoding="utf-8"))
    pokedex = json.loads((DATA / "pokedex.json").read_text(encoding="utf-8"))
    top100 = json.loads((DATA / "top100-value.json").read_text(encoding="utf-8"))
    chase = json.loads((DATA / "chase.json").read_text(encoding="utf-8"))
    Zr = jsdata["Zr"]
    Va = jsdata["Va"]
    za = jsdata["za"]

    # Power top 100
    def bst(s):
        t = s["stats"]
        return t["hp"] + t["attack"] + t["defense"] + t["specialAttack"] + t["specialDefense"] + t["speed"]

    power_top = sorted(pokedex, key=lambda s: (-bst(s), s["id"]))[:100]

    # --- Homepages ---
    print("Writing home shells...")
    home_specs = [
        ("en", DIST / "index.html", "/", sets_en, jsdata["Ia"]["en"]),
        ("ja", DIST / "ja" / "index.html", "/ja", sets_ja, jsdata["Ia"]["ja"]),
        ("en-ja", DIST / "en-ja" / "index.html", "/en-ja", sets_ja, jsdata["Ia"]["en-ja"]),
        ("ja-en", DIST / "ja-en" / "index.html", "/ja-en", sets_en, jsdata["Ia"]["ja-en"]),
    ]
    titles = {
        "en": "LearnPokémon",
        "ja": "LearnPokémon — 日本語セット一覧",
        "en-ja": "LearnPokémon — Japanese sets (English UI)",
        "ja-en": "LearnPokémon — English sets (日本語 UI)",
    }
    langs = {"en": "en", "ja": "ja", "en-ja": "en", "ja-en": "ja"}
    for loc, path, canon, sets, desc in home_specs:
        write_page(
            path,
            lang=langs[loc],
            title=titles[loc],
            description=desc if isinstance(desc, str) else str(desc),
            canonical_path=canon,
            root_html=home_root(loc, sets, jsdata),
        )

    # --- Pokedex ---
    print("Writing Pokédex...")
    write_page(
        DIST / "pokedex" / "index.html",
        lang="en",
        title="Pokédex | LearnPokémon",
        description="Unofficial educational Pokédex of 1025 species — names, numbers, types, and base stats context for the TCG encyclopedia.",
        canonical_path="/pokedex",
        root_html=pokedex_root(pokedex),
    )

    # --- Rankings ---
    print("Writing rankings...")
    write_page(
        DIST / "rankings" / "index.html",
        lang="en",
        title="Top 100s | LearnPokémon",
        description="Unofficial educational Top 100 rankings for value, power, and rarity. Not live guaranteed prices.",
        canonical_path="/rankings",
        root_html=rankings_hub_root(),
    )
    write_page(
        DIST / "rankings" / "value" / "index.html",
        lang="en",
        title="Top raw prices in indexed sets | LearnPokémon",
        description=jsdata["Vo"]["value"]["lede"],
        canonical_path="/rankings/value",
        root_html=rankings_value_root(top100),
    )
    write_page(
        DIST / "rankings" / "power" / "index.html",
        lang="en",
        title="Top 100 Power | LearnPokémon",
        description=jsdata["Vo"]["power"]["lede"],
        canonical_path="/rankings/power",
        root_html=rankings_power_root(power_top),
    )
    write_page(
        DIST / "rankings" / "rarity" / "index.html",
        lang="en",
        title="Top 100 Rarity | LearnPokémon",
        description=jsdata["Vo"]["rarity"]["lede"],
        canonical_path="/rankings/rarity",
        root_html=rankings_rarity_root(chase, Zr),
    )

    # --- Lore ---
    print("Writing lore...")
    lore_locales = [
        ("en", "en", ""),
        ("ja", "ja", "/ja"),
        ("en", "en-ja", "/en-ja"),  # en-ja uses English lore copy
        ("ja", "ja-en", "/ja-en"),  # ja-en uses Japanese lore copy
    ]
    for va_key, loc, prefix in lore_locales:
        Va_loc = Va[va_key]
        write_page(
            DIST / prefix.lstrip("/") / "lore" / "index.html" if prefix else DIST / "lore" / "index.html",
            lang="ja" if va_key == "ja" else "en",
            title=f"{Va_loc['title']} | LearnPokémon",
            description=Va_loc["lede"][:160],
            canonical_path=f"{prefix}/lore" if prefix else "/lore",
            root_html=lore_root(Va_loc, za, locale=loc),
        )
        write_page(
            DIST / prefix.lstrip("/") / "lore" / "characters" / "index.html"
            if prefix
            else DIST / "lore" / "characters" / "index.html",
            lang="ja" if va_key == "ja" else "en",
            title=("人物 | LearnPokémon" if va_key == "ja" else "Characters | LearnPokémon"),
            description=(
                "非公式のポケモンキャラクターガイド。"
                if va_key == "ja"
                else "Unofficial guide to major Pokémon anime and game characters."
            ),
            canonical_path=f"{prefix}/lore/characters" if prefix else "/lore/characters",
            root_html=lore_characters_root(za, locale=loc),
        )

    # Fix lore path join for en (prefix="")
    # The write_page paths above for prefix="" use DIST/lore — good.
    # For prefix /ja etc, DIST / "ja" / "lore" — Path("ja") from lstrip works.

    # --- Fetch EN cards (sequential-ish with small pool) ---
    print("Fetching/caching English card lists...")
    en_cards_map: dict[str, list | None] = {}
    failed_local = []

    def job(sid: str):
        return sid, fetch_en_cards(sid)

    # Prefer sequential with polite delay for API misses; parallel only for cache hits is hard —
    # use small concurrency.
    ids = [s["id"] for s in sets_en]
    # Process: local/cache first quickly, then API
    need_api = []
    for sid in ids:
        local = DATA / "cards" / f"{sid}.json"
        cache = CACHE / f"{sid}.json"
        if local.exists() or cache.exists():
            en_cards_map[sid] = fetch_en_cards(sid)
        else:
            need_api.append(sid)

    print(f"  cached/local: {len(en_cards_map)}, need API: {len(need_api)}")
    # Small concurrency to stay polite with the public API
    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fetch_en_cards, sid): sid for sid in need_api}
        for fut in as_completed(futs):
            sid = futs[fut]
            en_cards_map[sid] = fut.result()
            done += 1
            if done % 10 == 0 or done == len(need_api):
                print(f"  API progress {done}/{len(need_api)} (fails={len(FAILED_FETCHES)})")

    # --- Set pages ---
    print("Writing English set pages (/sets and /ja-en/sets)...")
    for s in sets_en:
        sid = s["id"]
        cards = en_cards_map.get(sid)
        failed = sid in FAILED_FETCHES
        title = set_card_list_title(s["name"], ja=False)
        desc = set_meta_description(s, ja=False)
        for prefix in ("", "/ja-en"):
            root = render_set_root(
                s, cards, ja_catalog=False, path_prefix=prefix, fetch_failed=failed
            )
            out = DIST / prefix.lstrip("/") / "sets" / sid / "index.html" if prefix else DIST / "sets" / sid / "index.html"
            write_page(
                out,
                lang="ja" if prefix == "/ja-en" else "en",
                title=title,
                description=desc,
                canonical_path=f"{prefix}/sets/{sid}" if prefix else f"/sets/{sid}",
                root_html=root,
            )

    print("Writing Japanese set pages (/ja/sets and /en-ja/sets)...")
    for s in sets_ja:
        sid = s["id"]
        cards = load_ja_cards(sid)
        title = set_card_list_title(s["name"], ja=True)
        desc = set_meta_description(s, ja=True)
        for prefix in ("/ja", "/en-ja"):
            root = render_set_root(
                s, cards, ja_catalog=True, path_prefix=prefix, fetch_failed=cards is None
            )
            out = DIST / prefix.lstrip("/") / "sets" / sid / "index.html"
            write_page(
                out,
                lang="ja" if prefix == "/ja" else "en",
                title=title,
                description=desc,
                canonical_path=f"{prefix}/sets/{sid}",
                root_html=root,
            )

    # robots.txt exact
    (DIST / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nAllow: /ads.txt\nSitemap: https://learnpokemon.fun/sitemap.xml\n",
        encoding="utf-8",
    )

    # Ensure no species detail pages
    species_pages = list(DIST.glob("pokedex/**/index.html"))
    # only pokedex/index.html should exist under pokedex
    extra = [p for p in species_pages if p != DIST / "pokedex" / "index.html"]
    if extra:
        print("WARNING unexpected pokedex pages:", extra)

    print("DONE")
    print("FAILED_FETCHES", len(FAILED_FETCHES), FAILED_FETCHES[:20])
    # counts
    print("en sets", len(sets_en), "ja sets", len(sets_ja), "species", len(pokedex), "cast", len(za))
    Path("/tmp/prerender_report.json").write_text(
        json.dumps(
            {
                "failed_fetches": FAILED_FETCHES,
                "en_sets": len(sets_en),
                "ja_sets": len(sets_ja),
                "species": len(pokedex),
                "cast": len(za),
                "lore_sections_en": len(Va["en"]["sections"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
