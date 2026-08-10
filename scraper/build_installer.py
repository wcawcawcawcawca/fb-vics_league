"""
build_installer.py
====================
Reads scraper/poe_scraper.js (the canonical, readable bookmarklet source)
and generates a drag-to-bookmarks-bar HTML installer.

The installed bookmarklet is a tiny LOADER STUB, not the full scraper
source. Embedding the ~40K+ characters of poe_scraper.js directly into a
javascript: URI produces a bookmark URL so long that Firefox's bookmark
storage becomes unreliable -- the bookmark can silently fail to persist
("won't stay in the toolbar"), independent of how it's installed (drag,
right-click, or the HTML-installer workaround). Growing the script over
time only makes this worse.

Instead, the installed bookmarklet is a short stub (a few hundred chars)
that fetches the CURRENT poe_scraper.js from GitHub raw and evals it,
each time it's clicked. This has two benefits:
  1. The bookmark URL stays tiny and stable regardless of source size.
  2. Editing/fixing the scraper in the repo takes effect immediately on
     the next click -- no reinstall needed.

Usage:
    python3 build_installer.py

Reads:  scraper/poe_scraper.js  (only to extract GAME_SCRAPER_VERSION for
                                  display -- its contents are NOT embedded)
Writes: scraper/poe_scraper_installer.html

No dependencies beyond the standard library.
"""
import re
from pathlib import Path

SRC_PATH = Path(__file__).parent / "poe_scraper.js"
OUT_PATH = Path(__file__).parent / "poe_scraper_installer.html"

GITHUB_OWNER = "wcawcawcawcawca"
GITHUB_REPO = "fb-vics_league"
GITHUB_BRANCH = "main"
RAW_SCRIPT_PATH = "scraper/poe_scraper.js"


def extract_version(src: str) -> str:
    m = re.search(r"const GAME_SCRAPER_VERSION\s*=\s*(\d+)", src)
    return m.group(1) if m else "?"


def build_loader_href() -> str:
    raw_url = (f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
               f"{GITHUB_BRANCH}/{RAW_SCRIPT_PATH}")
    # Single-quoted, no literal newlines -- keep this a one-line stub so it
    # survives being pasted into a javascript: URI without escaping issues.
    loader_js = (
        "(function(){"
        f"fetch('{raw_url}?_cb='+Date.now())"
        ".then(function(r){return r.text();})"
        ".then(function(t){eval(t);})"
        ".catch(function(e){alert('POE scraper loader failed: '+e.message);});"
        "})();"
    )
    return "javascript:" + loader_js


def main():
    src = SRC_PATH.read_text()
    version = extract_version(src)
    href = build_loader_href()

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
<p><a class="bookmarklet" href="{href}">POE Scraper (loader, currently v{version})</a></p>
<p>This bookmarklet is a small loader -- it fetches and runs the current <code>scraper/poe_scraper.js</code> from GitHub every time you click it, so it always runs the latest version without needing to be reinstalled. Its own URL is short and stable, which avoids the too-long-URL issue Firefox has with bookmarking huge <code>javascript:</code> links.</p>
<p>Source of truth: <code>scraper/poe_scraper.js</code> in this repo. Regenerate this installer any time with <code>python3 scraper/build_installer.py</code> (only needed if the loader logic itself changes, e.g. repo owner/branch/path).</p>
</body>
</html>
"""
    OUT_PATH.write_text(html)
    print(f"Wrote {OUT_PATH} (GAME_SCRAPER_VERSION {version} at click-time, "
          f"loader href {len(href)} chars, {len(html)} chars total)")


if __name__ == "__main__":
    main()
