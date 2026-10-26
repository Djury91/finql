import pytest
from fastapi.testclient import TestClient

from finql.main import create_app
from tests.helpers import make_settings

pytestmark = pytest.mark.integration


def test_ready_with_running_database(database_url: str) -> None:
    app = create_app(make_settings(database_url))
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
