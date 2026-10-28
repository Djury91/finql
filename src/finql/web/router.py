"""The web UI: one static page and a script that call the same API as any other client
(docs/03-architektura.md, 7.). No server-side rendering, no build step (ADR-010)."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from finql.auth.admin import DEMO_USERS
from finql.core.deps import AppSettings

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The page shows model output, SQL results and document text: none of it may run as code. The
# script builds the page from text nodes, and the policy forbids inline script and anything
# loaded from elsewhere, so an injected tag would not run even if one got through.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
PAGE_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}

# Shown as one-click questions. The first one is the phase 6 done criterion; the data questions
# are from the project plan, so the keyless demo knows them too.
EXAMPLE_QUESTIONS = (
    "Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?",
    "Hány aktív ügyfelünk van szegmensenként?",
    "Mennyi a késedelmi kamat a személyi kölcsönnél?",
    "Mi számít aktív ügyfélnek?",
)

router = APIRouter(include_in_schema=False)


class DemoUser(BaseModel):
    email: str
    name: str
    role: str
    branch: str | None


class WebConfig(BaseModel):
    demo_mode: bool  # no language model: the keyless stand-ins answer
    demo_users: list[DemoUser]  # login hints; only when the demo users exist (FINQL_DEMO_PASSWORD)
    # Public demo only (FINQL_PUBLIC_DEMO): one-click login. No secret there, nothing to spend.
    demo_password: str | None = None
    examples: list[str]


@router.api_route("/", methods=["GET", "HEAD"])  # HEAD: uptime checks
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=PAGE_HEADERS)


@router.get("/web/config")
async def config(settings: AppSettings) -> WebConfig:
    """What the login page and the chat need before login. Nothing secret: the demo password is
    here only in a public demo, which the settings allow without paid APIs only."""
    demo_users = (
        [
            DemoUser(email=u.email, name=u.full_name, role=u.role.value, branch=u.branch_code)
            for u in DEMO_USERS
        ]
        if settings.demo_password is not None
        else []
    )
    return WebConfig(
        demo_mode=settings.llm_provider == "fake",
        demo_users=demo_users,
        demo_password=(
            settings.demo_password.get_secret_value()
            if settings.public_demo and settings.demo_password is not None
            else None
        ),
        examples=list(EXAMPLE_QUESTIONS),
    )
