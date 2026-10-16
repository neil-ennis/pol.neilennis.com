"""Audit a Political Musings static snapshot before deployment."""

from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlparse


SITE = Path(__file__).resolve().parents[1] / "site"
HOST = "pol.neilennis.com"


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("href", "src", "poster", "data-src"):
            if attrs.get(key):
                self.refs.append((tag, key, attrs[key]))
        for key in ("srcset", "data-srcset"):
            for item in (attrs.get(key) or "").split(","):
                if item.strip():
                    self.refs.append((tag, key, item.strip().split()[0]))
        for value in re.findall(r"url\(\s*['\"]?([^'\")]+)", attrs.get("style") or "", re.I):
            self.refs.append((tag, "style", value))


def target(path):
    path = unquote(path)
    if "\\" in path or ".." in path.split("/"):
        return None
    relative = path.lstrip("/")
    result = SITE / relative
    if path == "/" or path.endswith("/") or not Path(path).suffix:
        result /= "index.html"
    return result


def main():
    pages = sorted(SITE.rglob("*.html"))
    postmap = json.loads((SITE / "postmap.json").read_text(encoding="utf-8"))
    redirects = json.loads((SITE / "redirects.json").read_text(encoding="utf-8"))
    missing = Counter()
    unusual = Counter()
    checked = 0
    for page in pages:
        source_path = "/" + page.relative_to(SITE).parent.as_posix().strip("./") + "/"
        if source_path == "//":
            source_path = "/"
        parser = References()
        parser.feed(page.read_text(encoding="utf-8"))
        for tag, key, ref in parser.refs:
            parsed = urlparse(urljoin(f"https://{HOST}{source_path}", ref))
            if parsed.hostname not in {HOST, "www." + HOST}:
                continue
            path = unquote(parsed.path)
            if path in redirects or path in {"/feed/", "/wp-sitemap.xml", "/p/"}:
                continue
            if path.startswith("/p/") and path.split("/")[2].isdecimal():
                continue
            if path == "/" and (parsed.query.startswith("p=") or parsed.query.startswith("page_id=")):
                continue
            if path.startswith(("/wp-json/", "/xmlrpc.php", "/wp-admin/")):
                unusual[(path, "service")]+=1
                continue
            if path.endswith("/feed/") or path == "/comments/feed/":
                unusual[(path, "feed")]+=1
                continue
            checked += 1
            resolved = target(path)
            if resolved is None or not resolved.exists():
                missing[(path, tag, key)] += 1
    for post_id, destination in postmap.items():
        if not post_id.isdecimal():
            missing[(post_id, "postmap", "bad ID")] += 1
            continue
        parsed = urlparse(urljoin(f"https://{HOST}/", destination))
        if parsed.hostname == HOST and parsed.path not in redirects and not target(parsed.path).exists():
            missing[(destination, "postmap", post_id)] += 1
    signatures = {
        ".jpg": bytes((255, 216)), ".jpeg": bytes((255, 216)),
        ".png": bytes((137, 80, 78, 71)), ".gif": b"GIF8", ".webp": b"RIFF",
    }
    for asset in SITE.rglob("*"):
        if asset.is_file() and asset.suffix.lower() in signatures:
            if not asset.read_bytes().startswith(signatures[asset.suffix.lower()]):
                missing[(asset.relative_to(SITE).as_posix(), "asset", "invalid image bytes")] += 1
    print(f"HTML pages: {len(pages)}; post IDs: {len(postmap)}; redirects: {len(redirects)}; checked local references: {checked}")
    print("Missing references:")
    for item, count in missing.most_common():
        print(count, item)
    print("Unusual service/feed references:")
    for item, count in unusual.most_common():
        print(count, item)
    if len(pages) < 90 or len(postmap) != 81 or missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
