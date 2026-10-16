# Political Musings static site

This repository contains a public-only snapshot of `pol.neilennis.com` for
Cloudflare Workers Static Assets. The editable WordPress site is at
`C:\Repos\neil\code\neilennis.com\pol.neilennis.com`. Do not add that site's
database, PHP, backups, caches or credentials here.

## Contents and behaviour

- `site/` contains 102 HTML pages, 89 referenced assets, RSS, sitemap and maps
  for old WordPress IDs and redirected pages.
- `worker.mjs` serves the site and preserves `/?p=123`, `/?page_id=123` and
  `/p/123` links. It redirects the old feed and sitemap URLs, plus aliases
  recorded in `site/redirects.json`.
- Existing Comentario embeds and the Google Custom Search widget remain on
  the exported pages. The site's other externally hosted images remain with
  their original providers.
- `scripts/export_public.py` records the initial one-off public snapshot
  procedure. It also takes the RSS feed from local WordPress and uses a local
  exact-path file when the published copy is unavailable. It is not an
  unattended build; review its output and rerun the link audit before deploy.

## Deploy and maintain

Cloudflare builds this Worker from the GitHub repository. Changes pushed to
the connected production branch should start a new build. `wrangler.jsonc`
sets `site/` as the assets directory. The Worker must run before assets so its
shortlinks and redirects always work. Do not deploy `site/` alone as Pages.

Run `python scripts/check_site.py` after changing or replacing `site/`. The
checker verifies local page and asset references and all 81 old WordPress IDs.
A local HTTP server can preview pages and assets, but only a Cloudflare Worker
preview can test the redirect code.

## Migration notes

The initial snapshot was prepared on 16 October 2026 from the public website.
The local editable WordPress installation has the same sitemap shape: 63
posts, 8 pages, 21 categories and 1 author. The public site supplied the HTML
because the local installation was slow and briefly entered automatic update
maintenance mode. One linked image that was missing from the published site
was restored from its exact path in the local WordPress copy. A legacy `.jpg`
link that led to an HTML wrapper now points directly at the real image. The
RSS feed came from that local copy because the public `/feed/` returned HTML.

Only the final public site content belongs in Git. Retain the prior AWS site
for rollback until the live Cloudflare deployment has been accepted. If the
site is updated from WordPress in future, export again, audit links and media,
and review a preview before switching the production copy.
