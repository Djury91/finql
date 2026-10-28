"""The manual demo scenarios: the pages the login page links, and the links between the files."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finql.main import create_app
from finql.web.scenarios import PREFIX, SCENARIO_DIR, render
from tests.helpers import make_settings

UNREACHABLE_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"
MANUAL_DEMO = SCENARIO_DIR.parent
_MD_LINK = re.compile(r"\]\(([^)#]+\.md)\)")


def client() -> TestClient:
    return TestClient(create_app(make_settings(UNREACHABLE_DB)))


def test_the_index_lists_every_scenario_with_working_links() -> None:
    with client() as c:
        index = c.get(f"{PREFIX}/")
        assert index.status_code == 200
        assert "kézi demó-forgatókönyvek" in index.text
        assert index.headers["content-security-policy"].startswith("default-src 'self'")

        pages = sorted(set(re.findall(rf'href="({PREFIX}/[\w-]+)"', index.text)))
        assert len(pages) == len(list(SCENARIO_DIR.glob("*.md"))) - 1  # all but the index
        for page in pages:
            response = c.get(page)
            assert response.status_code == 200, page
            assert "<script" not in response.text and "style=" not in response.text


def test_the_address_placeholder_becomes_this_server() -> None:
    with client() as c:
        page = c.get(f"{PREFIX}/01-pecsi-fiokvezeto").text

    assert "demó-cím" not in page
    assert 'href="http://testserver/docs"' in page


def test_without_the_trailing_slash_it_redirects() -> None:
    with client() as c:
        response = c.get(PREFIX, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"{PREFIX}/"


@pytest.mark.parametrize("name", ["nincs-ilyen", "..%2F..%2Fpyproject", "%2E%2E"])
def test_only_the_scenario_files_are_served(name: str) -> None:
    with client() as c:
        assert c.get(f"{PREFIX}/{name}").status_code == 404


def test_html_in_the_markdown_is_escaped_and_links_out_go_to_github() -> None:
    page = render("<script>alert(1)</script>\n\n[English](../angol/README.md)", "http://x")

    assert "<script>" not in page and "&lt;script&gt;" in page
    assert 'href="https://github.com/Djury91/finql/blob/main/manual-demo/angol/README.md"' in page


@pytest.mark.parametrize("path", sorted(MANUAL_DEMO.rglob("*.md")), ids=lambda p: p.name)
def test_the_links_between_the_scenario_files_resolve(path: Path) -> None:
    for target in _MD_LINK.findall(path.read_text(encoding="utf-8")):
        assert (path.parent / target).resolve().is_file(), f"{path.name}: {target}"
