"""The web UI: the page, its security headers, and the config it reads before login."""

import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finql.main import create_app
from finql.web.router import STATIC_DIR
from tests.helpers import make_settings

UNREACHABLE_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


def client(**overrides: object) -> TestClient:
    return TestClient(create_app(make_settings(UNREACHABLE_DB, **overrides)))


def test_the_page_is_served_with_a_strict_content_security_policy() -> None:
    with client() as c:
        response = c.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "'unsafe-inline'" not in policy
    assert "frame-ancestors 'none'" in policy
    assert response.headers["x-content-type-options"] == "nosniff"


def test_static_files_are_served() -> None:
    with client() as c:
        script = c.get("/static/app.js")
        style = c.get("/static/app.css")

    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert style.status_code == 200 and style.headers["content-type"].startswith("text/css")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inline_scripts = 0
        self.inline_styles = 0
        self.handlers: list[str] = []
        self.assets: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        self.handlers += [name for name in named if name.startswith("on")]
        if "style" in named or tag == "style":
            self.inline_styles += 1
        if tag == "script":
            self._in_script = True
            if named.get("src") is None:
                self.inline_scripts += 1
        for name in ("src", "href"):
            value = named.get(name)
            if value and value.startswith("/static/"):
                self.assets.append(value.removeprefix("/static/"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False


def test_the_page_needs_no_inline_code_and_its_assets_exist() -> None:
    # The policy forbids inline script and style: the page would break, not just warn.
    page = _Page()
    page.feed((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    assert page.inline_scripts == 0 and page.inline_styles == 0 and page.handlers == []
    assert sorted(page.assets) == ["app.css", "app.js"]
    assert all((STATIC_DIR / asset).is_file() for asset in page.assets)


def test_the_script_builds_the_page_from_text_only() -> None:
    # Model output and document text are shown: nothing may be parsed as HTML or run as code.
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    forbidden = re.findall(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", script)
    assert forbidden == []


def test_config_without_demo_users() -> None:
    with client(llm_provider="anthropic") as c:
        config = c.get("/web/config").json()

    assert config["demo_mode"] is False
    assert config["demo_users"] == []
    assert config["examples"]


def test_config_in_demo_mode_lists_the_demo_users_but_not_their_password() -> None:
    with client(llm_provider="fake", demo_password="Demo-jelszo-2026") as c:
        response = c.get("/web/config")

    config = response.json()
    assert config["demo_mode"] is True
    pecs = next(u for u in config["demo_users"] if u["email"].startswith("pecs@"))
    assert pecs == {
        "email": "pecs@minta-bank.example",
        "name": "Pécsi Péter",
        "role": "branch_manager",
        "branch": "PEC01",
    }
    assert "Demo-jelszo-2026" not in response.text


PUBLIC_DEMO = {
    "public_demo": True,
    "demo_password": "Demo-jelszo-2026",
    "llm_provider": "fake",
    "embedding_provider": "hashing",
}


def test_a_public_demo_shows_the_password_for_one_click_login() -> None:
    with client(**PUBLIC_DEMO) as c:
        config = c.get("/web/config").json()

    assert config["demo_password"] == "Demo-jelszo-2026"
    assert config["demo_users"]


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"llm_provider": "anthropic"}, "llm_provider=fake"),
        ({"embedding_provider": "voyage"}, "embedding_provider=hashing"),
        ({"demo_password": None}, "needs demo_password"),
    ],
)
def test_a_public_demo_refuses_to_start_with_paid_apis_or_without_a_password(
    override: dict[str, object], reason: str
) -> None:
    # A public password with a real API key: anyone could spend on it.
    with pytest.raises(ValidationError, match=reason):
        make_settings(UNREACHABLE_DB, **{**PUBLIC_DEMO, **override})


def test_the_ui_routes_are_not_in_the_api_schema() -> None:
    with client() as c:
        paths = c.get("/openapi.json").json()["paths"]

    assert "/" not in paths and "/web/config" not in paths
