from fastapi.testclient import TestClient

from finql.core.config import Settings
from finql.main import create_app

# Nothing listens on port 1, so the connection is refused immediately.
UNREACHABLE_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


def test_health_does_not_need_database() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DB))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable_database() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DB))
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}
