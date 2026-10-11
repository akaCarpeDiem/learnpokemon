#!/usr/bin/env python3
"""Add the redesign to a LearnPokemon build folder, or take it out again.

    python apply_redesign.py /path/to/dist           add the redesign
    python apply_redesign.py /path/to/dist --undo    go back to the previous build

What it does to the build folder:
  1. copies assets/lp-redesign.css, assets/lp-redesign.js and assets/lp-battle.js
     into <dist>/assets
  2. in every .html file that loads the old battle script, adds the stylesheet
     link, swaps lp-vs-battle.js for lp-battle.js, and adds lp-redesign.js

Nothing else is touched. The old lp-vs-battle.js file stays where it is, so
--undo only has to put the three tags back. Running it twice is harmless.
"""
import re
import shutil
import sys
from pathlib import Path

VERSION = "r1"  # bump when the redesign files change, so browsers fetch the new copy
HERE = Path(__file__).resolve().parent
NEW_FILES = ["lp-redesign.css", "lp-redesign.js", "lp-battle.js"]

CSS_TAG = '<link rel="stylesheet" href="/assets/lp-redesign.css?v=%s" />' % VERSION
OLD_BATTLE = re.compile(r'<script src="/assets/lp-vs-battle\.js(\?v=[^"]*)?" defer></script>')
NEW_BATTLE = '<script src="/assets/lp-battle.js?v=%s" defer></script>' % VERSION
NEW_REDESIGN = '<script src="/assets/lp-redesign.js?v=%s" defer></script>' % VERSION
ANY_REDESIGN_TAG = re.compile(
    r'[ \t]*<(?:link rel="stylesheet" href|script src)="/assets/lp-(?:redesign\.css|redesign\.js|battle\.js)[^>]*>(?:</script>)?\n?'
)


def add(html):
    if "lp-redesign.css" in html:
        return html, False
    if not OLD_BATTLE.search(html):
        return html, False
    # Stylesheet goes last, so it wins over the existing lp-*.css files.
    html = re.sub(r"[ \t]*</head>", "    " + CSS_TAG + "\n  </head>", html, count=1)
    html = OLD_BATTLE.sub(NEW_BATTLE + "\n    " + NEW_REDESIGN, html, count=1)
    return html, True


def remove(html):
    if "lp-redesign.css" not in html and "lp-battle.js" not in html:
        return html, False
    indent = "    "
    html = ANY_REDESIGN_TAG.sub("", html)
    if "lp-vs-battle.js" not in html:
        html = re.sub(r"[ \t]*</body>", indent + '<script src="/assets/lp-vs-battle.js?v=5" defer></script>\n  </body>', html, count=1)
    return html, True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    undo = "--undo" in sys.argv
    dist = Path(args[0] if args else "dist").resolve()
    if not (dist / "index.html").is_file():
        sys.exit("No index.html in %s. Pass the build folder as the first argument." % dist)

    if not undo:
        (dist / "assets").mkdir(exist_ok=True)
        for name in NEW_FILES:
            shutil.copyfile(HERE / "assets" / name, dist / "assets" / name)
        print("copied %d files into %s" % (len(NEW_FILES), dist / "assets"))

    changed = 0
    for page in sorted(dist.rglob("*.html")):
        text = page.read_text(encoding="utf-8")
        new_text, did = (remove if undo else add)(text)
        if did:
            page.write_text(new_text, encoding="utf-8")
            changed += 1
            print(("restored " if undo else "updated ") + str(page.relative_to(dist)))
    if not changed:
        print("no pages needed changing" + ("" if undo else " (already applied, or the old battle script tag was not found)"))
    elif not undo:
        print("done. To go back: python apply_redesign.py %s --undo" % dist)


if __name__ == "__main__":
    main()
