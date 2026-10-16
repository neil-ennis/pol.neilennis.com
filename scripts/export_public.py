"""Build a public-only static snapshot of Political Musings.

The editable source remains the private local WordPress installation. This
initial snapshot uses the currently published site so a slow or updating local
container cannot produce a partial export. Only discovered public HTML and
referenced assets are written; PHP, database files, caches and backups are not.
"""

from __future__ import annotations

import concurrent.futures
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ORIGIN = "https://pol.neilennis.com"
HOST = "pol.neilennis.com"
COMENTARIO_DOMAIN_ID = "a5fd10e5-2636-42cc-9d9f-853e0f8b9a25"
SITE_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
USER_AGENT = "Political Musings public static archive export/1.0"
SOURCE_POSTMAP = Path(
    r"C:\Repos\neil\code\neilennis.com\pol.neilennis.com\postmap.json"
)
SOURCE_PAGE_LINKS = Path(__file__).with_name("page-links.json")
LOCAL_WORDPRESS = Path(
    r"C:\Repos\neil\code\neilennis.com\pol.neilennis.com\wordpress_data"
)
MAX_PAGES = 400
ASSET_PREFIXES = ("/wp-content/", "/wp-includes/")
ASSET_EXTENSIONS = {
    ".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".avif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".mp3", ".mp4", ".webm", ".ogg", ".ogv", ".txt",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


RAW = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
FOLLOW = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request_url(url: str, *, redirects: bool = True) -> tuple[int, str, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = FOLLOW if redirects else RAW
    try:
        with opener.open(request, timeout=45) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read(), response.headers.get("Location", ""),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code, error.headers.get("Content-Type", ""),
            error.read(), error.headers.get("Location", ""),
        )


def same_site_path(reference: str, base: str) -> str | None:
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(base, reference))
    if parsed.hostname not in {HOST, "www." + HOST}:
        return None
    path = urllib.parse.unquote(parsed.path or "/")
    if "\\" in path or any(segment == ".." for segment in path.split("/")):
        return None
    return path


def is_asset(path: str) -> bool:
    return path.startswith(ASSET_PREFIXES) and Path(path).suffix.lower() in ASSET_EXTENSIONS


def is_page(path: str) -> bool:
    if path.startswith(("/wp-", "/feed/", "/comments/", "/p/")):
        return False
    if path.endswith(("/feed", "/feed/")):
        return False
    return path == "/" or path.endswith("/") or not Path(path).suffix


class References(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.pages: set[str] = set()
        self.assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for key in ("src", "href", "poster", "data-src"):
            ref = attributes.get(key)
            if not ref:
                continue
            path = same_site_path(ref, self.base)
            if path is None:
                continue
            if is_asset(path):
                self.assets.add(path)
            elif tag == "a" and key == "href" and is_page(path):
                self.pages.add(path)
        for key in ("srcset", "data-srcset"):
            for item in (attributes.get(key) or "").split(","):
                ref = item.strip().split(" ", 1)[0]
                path = same_site_path(ref, self.base) if ref else None
                if path and is_asset(path):
                    self.assets.add(path)
        for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", attributes.get("style") or "", re.I):
            path = same_site_path(ref, self.base)
            if path and is_asset(path):
                self.assets.add(path)


def sitemap_paths() -> set[str]:
    status, _, body, _ = request_url(ORIGIN + "/wp-sitemap.xml")
    if status != 200:
        raise RuntimeError(f"Sitemap index returned {status}")
    root = ET.fromstring(body)
    urls = [urllib.parse.urljoin(ORIGIN, item.text or "") for item in root.findall(".//s:loc", SITE_NS)]
    paths: set[str] = {"/"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request_url, urls))
    for url, (status, _, body, _) in zip(urls, results):
        if status != 200:
            raise RuntimeError(f"Sitemap returned {status}: {url}")
        for item in ET.fromstring(body).findall(".//s:loc", SITE_NS):
            path = same_site_path(item.text or "", ORIGIN)
            if path and is_page(path):
                paths.add(path)
    if len(paths) < 80:
        raise RuntimeError(f"Sitemap appears incomplete: {len(paths)} paths")
    return paths


def prepare_html(markup: str, path: str) -> str:
    markup = markup.replace("\r\n", "\n").replace("\r", "\n")
    # The old Blogger migration linked a .jpg that is actually an HTML image
    # wrapper. Point that link at its already-present real image instead.
    markup = markup.replace(
        "/wp-content/uploads/2007/12/ThinkTV1.jpg",
        "/wp-content/uploads/2007/12/ThinkTV.jpg",
    )
    # Keep canonical and social URLs public while making links/assets work on
    # the preview host as well as the final custom domain.
    held: list[str] = []

    def hold(match: re.Match[str]) -> str:
        held.append(match.group())
        return f"__POL_CANONICAL_{len(held) - 1}__"

    markup = re.sub(
        r'<(?:link|meta)\b[^>]*(?:rel=["\']canonical["\']|property=["\']og:url["\'])[^>]*>',
        hold, markup, flags=re.I,
    )
    markup = re.sub(r"https?://(?:www\.)?pol\.neilennis\.com(?=/|[\"'\s<]|$)", "", markup, flags=re.I)
    for number, original in enumerate(held):
        markup = markup.replace(f"__POL_CANONICAL_{number}__", original)
    # The former WordPress contact URL is now the main blog's static contact
    # page. Keep this repair repeatable for future exports.
    markup = markup.replace(
        "https://blog.neilennis.com/index.php/contact/",
        "https://blog.neilennis.com/contact/",
    ).replace(
        "http://blog.neilennis.com/index.php/contact/",
        "https://blog.neilennis.com/contact/",
    )
    markup = markup.replace(
        '<h2 class="widget-title">Search</h2>',
        '<h2 class="widget-title" id="search">Search</h2>',
    )
    # WordPress advertises dynamic endpoints and comment feeds that a static
    # archive cannot serve. Keep the actual site RSS feed, served as feed.xml.
    markup = re.sub(r'<link\b[^>]*rel=["\']pingback["\'][^>]*>\s*', '', markup, flags=re.I)
    markup = re.sub(r'<link\b[^>]*rel=["\']EditURI["\'][^>]*>\s*', '', markup, flags=re.I)
    markup = re.sub(r'<link\b[^>]*rel=["\']https://api\.w\.org/["\'][^>]*>\s*', '', markup, flags=re.I)
    markup = re.sub(r'<link\b[^>]*rel=["\']alternate["\'][^>]*type=["\']application/json["\'][^>]*>\s*', '', markup, flags=re.I)
    markup = re.sub(r'<link\b[^>]*rel=["\']alternate["\'][^>]*type=["\']application/rss\+xml["\'][^>]*>\s*',
                    lambda m: m.group() if 'href="/feed/"' in m.group() else '', markup, flags=re.I)
    # Preserve each existing comment thread when a page is served from the
    # preview hostname. The domain ID is public configuration, not a secret.
    markup = markup.replace(
        '<comentario-comments theme="light"></comentario-comments>',
        f'<comentario-comments theme="light" domain-id="{COMENTARIO_DOMAIN_ID}" page-id="{path}"></comentario-comments>',
    )
    return markup


def target_for(path: str, destination: Path) -> Path:
    relative = path.lstrip("/")
    if path == "/":
        return destination / "index.html"
    if path.endswith("/") or not Path(path).suffix:
        return destination / relative / "index.html"
    return destination / relative


def fetch_page(path: str) -> tuple[str, int, str, bytes, str]:
    status, mime, body, location = request_url(ORIGIN + path, redirects=False)
    return path, status, mime, body, location


def crawl(destination: Path, seeds: set[str]) -> tuple[dict[str, str], set[str], set[str]]:
    pending = set(seeds)
    visited: set[str] = set()
    redirects: dict[str, str] = {}
    assets: set[str] = set()
    saved: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        while pending:
            batch = sorted(pending - visited)
            pending.clear()
            if not batch:
                break
            if len(visited) + len(batch) > MAX_PAGES:
                raise RuntimeError(f"Page crawl exceeds {MAX_PAGES} paths")
            for path, status, mime, body, location in pool.map(fetch_page, batch):
                visited.add(path)
                if status in {301, 302, 307, 308}:
                    if not location:
                        raise RuntimeError(f"Redirect without target: {path}")
                    redirects[path] = urllib.parse.urljoin(ORIGIN + path, location)
                    continue
                if status == 404:
                    print(f"Missing linked page: {path}", file=sys.stderr)
                    continue
                if status != 200 or "html" not in mime.lower():
                    print(f"Unexpected page response {status} {mime}: {path}", file=sys.stderr)
                    continue
                markup = body.decode("utf-8", "replace")
                if "<html" not in markup.lower():
                    raise RuntimeError(f"No HTML document: {path}")
                prepared = prepare_html(markup, path)
                refs = References(ORIGIN + path)
                refs.feed(prepared)
                assets.update(refs.assets)
                pending.update(refs.pages - visited)
                target = target_for(path, destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(prepared, encoding="utf-8", newline="\n")
                saved.add(path)
            print(f"Crawled {len(visited)} paths, saved {len(saved)}, found {len(assets)} assets", flush=True)
    return redirects, assets, saved


def css_refs(path: str, body: bytes) -> set[str]:
    text = body.decode("utf-8", "replace")
    base = ORIGIN + path
    result: set[str] = set()
    for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", text, re.I):
        candidate = same_site_path(ref, base)
        if candidate and is_asset(candidate):
            result.add(candidate)
    return result


def fetch_asset(path: str) -> tuple[str, bytes, str]:
    status, mime, body, _ = request_url(ORIGIN + urllib.parse.quote(path, safe="/%:@"))
    extension = Path(path).suffix.lower()
    signature = {
        ".jpg": bytes((255, 216)), ".jpeg": bytes((255, 216)),
        ".png": bytes((137, 80, 78, 71)), ".gif": b"GIF8", ".webp": b"RIFF",
    }.get(extension)
    if status == 200 and not mime.lower().startswith("text/html") and (not signature or body.startswith(signature)):
        return path, body, "public"
    local = LOCAL_WORDPRESS / path.lstrip("/")
    if local.is_file():
        body = local.read_bytes()
        if not signature or body.startswith(signature):
            return path, body, "local exact-path fallback"
    raise RuntimeError(f"Asset unavailable ({status}, {mime}): {path}")


def download_assets(destination: Path, initial: set[str]) -> tuple[int, int]:
    pending = set(initial)
    done: set[str] = set()
    local_count = 0
    total_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        while pending:
            batch = sorted(pending - done)
            pending.clear()
            if not batch:
                break
            for path, body, source in pool.map(fetch_asset, batch):
                target = target_for(path, destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                done.add(path)
                total_bytes += len(body)
                local_count += source != "public"
                if source != "public":
                    print(f"Local exact-path asset fallback: {path}", flush=True)
                if path.endswith(".css"):
                    pending.update(css_refs(path, body) - done)
            print(f"Downloaded {len(done)} assets, {total_bytes:,} bytes", flush=True)
    return len(done), local_count


def main(destination: Path) -> None:
    if destination.exists():
        raise SystemExit(f"Destination exists: {destination}")
    source_map = json.loads(SOURCE_POSTMAP.read_text(encoding="utf-8"))["map"]
    page_links = json.loads(SOURCE_PAGE_LINKS.read_text(encoding="utf-8"))
    for post_id, link in page_links.items():
        if source_map.get(post_id) != link["slug"]:
            raise RuntimeError(f"Page link does not match source postmap: {post_id}")
    seeds = sitemap_paths()
    seeds.update(
        "/" + slug.strip("/") + "/"
        for post_id, slug in source_map.items()
        if slug and post_id not in page_links
    )
    destination.mkdir(parents=True)
    redirects, assets, saved = crawl(destination, seeds)
    if len(saved) < 85:
        raise RuntimeError(f"Too few saved HTML paths: {len(saved)}")
    for link in page_links.values():
        redirects["/" + link["slug"].strip("/") + "/"] = link["target"]
    asset_count, local_count = download_assets(destination, assets)
    postmap: dict[str, str] = {}
    for post_id, slug in source_map.items():
        path = "/" + slug.strip("/") + "/"
        postmap[post_id] = redirects.get(path, path)
        target_path = urllib.parse.urlparse(urllib.parse.urljoin(ORIGIN, postmap[post_id])).path
        if target_path.startswith("/") and target_path not in saved and target_path not in redirects:
            if urllib.parse.urlparse(urllib.parse.urljoin(ORIGIN, postmap[post_id])).hostname == HOST:
                raise RuntimeError(f"Postmap {post_id} has no local destination: {postmap[post_id]}")
    (destination / "postmap.json").write_text(json.dumps(postmap, indent=2) + "\n", encoding="utf-8")
    (destination / "redirects.json").write_text(json.dumps(redirects, indent=2) + "\n", encoding="utf-8")
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap += "".join(f"  <url><loc>{ORIGIN}{path}</loc></url>\n" for path in sorted(saved))
    sitemap += "</urlset>\n"
    (destination / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (destination / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n", encoding="utf-8")
    status, mime, body, _ = request_url("http://localhost:8086/feed/")
    if status != 200 or "xml" not in mime:
        raise RuntimeError(f"Local WordPress RSS unavailable: {status} {mime}")
    body = body.replace(b"http://localhost:8086", ORIGIN.encode())
    (destination / "feed.xml").write_bytes(body)
    print(f"Exported {len(saved)} pages, {len(redirects)} redirects, {asset_count} assets ({local_count} local fallbacks)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python export_public.py FRESH_DESTINATION")
    main(Path(sys.argv[1]).resolve())
