from fastapi.testclient import TestClient

from finql.main import create_app
from tests.helpers import make_settings

# Nothing listens on port 1, so the connection is refused immediately.
UNREACHABLE_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


def test_health_does_not_need_database() -> None:
    app = create_app(make_settings(UNREACHABLE_DB))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable_database() -> None:
    app = create_app(make_settings(UNREACHABLE_DB))
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}
