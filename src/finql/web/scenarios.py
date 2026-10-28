"""The manual demo scenarios (manual-demo/magyar/*.md) as pages. The login page links them, so a
visitor of the public demo can follow them step by step. Rendered from the same Markdown the
repository shows; raw HTML in the Markdown is escaped, not passed through."""

import html
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markdown_it import MarkdownIt

from finql.core.errors import NotFoundError
from finql.web.router import PAGE_HEADERS

SCENARIO_DIR = Path(__file__).resolve().parents[3] / "manual-demo" / "magyar"
PREFIX = "/forgatokonyvek"
REPOSITORY = "https://github.com/Djury91/finql/blob/main/manual-demo/"

# `<demó-cím>` and `<demó-cím>/docs` in the Markdown: a link to this server instead.
_PLACEHOLDER = re.compile(r"`<demó-cím>([^`\s]*)`")
_TITLE = re.compile(r"^# (.+)$", re.MULTILINE)
_HREF = re.compile(r'href="([^"]+)"')

_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")

router = APIRouter(prefix=PREFIX, include_in_schema=False)


def _href(target: str) -> str:
    """Links between the scenario files stay here; links out of the folder go to GitHub."""
    if target.startswith("../"):
        return REPOSITORY + target.removeprefix("../")
    if target == "README.md":
        return f"{PREFIX}/"
    if target.endswith(".md") and "/" not in target:
        return f"{PREFIX}/{target.removesuffix('.md')}"
    return target


def render(markdown: str, base_url: str) -> str:
    """The page for one scenario file. `base_url` is this server, without a trailing slash."""
    source = _PLACEHOLDER.sub(lambda m: f"[{base_url}{m[1]}]({base_url}{m[1]})", markdown)
    body = _HREF.sub(
        lambda m: f'href="{html.escape(_href(html.unescape(m[1])))}"', _markdown.render(source)
    )
    title = match[1] if (match := _TITLE.search(markdown)) else "Demó-forgatókönyvek"
    return f"""<!doctype html>
<html lang="hu">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)} – FinQL</title>
    <link rel="icon" href="data:," />
    <link rel="stylesheet" href="/static/app.css" />
  </head>
  <body>
    <header class="topbar">
      <div class="brand">FinQL <span class="brand-sub">demó-forgatókönyvek</span></div>
      <a href="/">Vissza a demóhoz</a>
    </header>
    <main class="doc">
{body}    </main>
  </body>
</html>
"""


def _page(name: str, request: Request) -> HTMLResponse:
    # Only the files that are there: the name never becomes a path on its own.
    files = {path.stem: path for path in SCENARIO_DIR.glob("*.md")}
    if name not in files:
        raise NotFoundError("Nincs ilyen forgatókönyv.")
    base_url = str(request.base_url).rstrip("/")
    content = render(files[name].read_text(encoding="utf-8"), base_url)
    return HTMLResponse(content, headers=PAGE_HEADERS)


@router.get("")
async def scenarios_redirect() -> RedirectResponse:
    # The relative links between the pages need the trailing slash.
    return RedirectResponse(f"{PREFIX}/")


@router.get("/")
async def scenarios_index(request: Request) -> HTMLResponse:
    return _page("README", request)


@router.get("/{name}")
async def scenario(name: str, request: Request) -> HTMLResponse:
    return _page(name, request)
