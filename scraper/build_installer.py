"""
build_installer.py
====================
Reads scraper/poe_scraper.js (the canonical, readable bookmarklet source)
and generates a drag-to-bookmarks-bar HTML installer, since large
javascript: URIs are unreliable to drag-and-drop directly and some
browsers need the "download HTML, open it, drag the button" workflow.

Usage:
    python3 build_installer.py

Reads:  scraper/poe_scraper.js
Writes: scraper/poe_scraper_installer.html

No dependencies beyond the standard library.
"""
import re
import urllib.parse
from pathlib import Path

SRC_PATH = Path(__file__).parent / "poe_scraper.js"
OUT_PATH = Path(__file__).parent / "poe_scraper_installer.html"


def extract_version(src: str) -> str:
    m = re.search(r"const GAME_SCRAPER_VERSION\s*=\s*(\d+)", src)
    return m.group(1) if m else "?"


def main():
    src = SRC_PATH.read_text()
    version = extract_version(src)
    href = "javascript:" + urllib.parse.quote(src, safe="")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Pennants Over Easy scraper -- install (GAME_SCRAPER_VERSION {version})</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 20px; line-height: 1.5; color: #1a1a1a; }}
a.bookmarklet {{ display: inline-block; padding: 10px 18px; background: #2a78d6; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600; }}
</style>
</head>
<body>
<h1>Pennants Over Easy scraper</h1>
<p>Drag the button below to your bookmarks bar to install (or right-click it and choose "Bookmark this link").</p>
<p><a class="bookmarklet" href="{href}">POE Scraper (v{version})</a></p>
<p>Source of truth: <code>scraper/poe_scraper.js</code> in this repo. Regenerate this installer any time with <code>python3 scraper/build_installer.py</code> after editing the source.</p>
</body>
</html>
"""
    OUT_PATH.write_text(html)
    print(f"Wrote {OUT_PATH} (GAME_SCRAPER_VERSION {version}, {len(html)} chars)")


if __name__ == "__main__":
    main()
