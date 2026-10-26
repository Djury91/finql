from fastapi import FastAPI
from fastapi.testclient import TestClient

from finql.core.errors import PermissionDeniedError
from finql.main import create_app
from tests.helpers import make_settings

UNREACHABLE_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


def app_with_failing_routes() -> FastAPI:
    app = create_app(make_settings(UNREACHABLE_DB))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/denied")
    async def denied() -> None:
        raise PermissionDeniedError()

    return app


def test_unknown_route_uses_the_error_format() -> None:
    with TestClient(app_with_failing_routes()) as client:
        response = client.get("/nincs-ilyen")

    error = response.json()["error"]
    assert response.status_code == 404
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


def test_domain_error_maps_to_status_and_code() -> None:
    with TestClient(app_with_failing_routes()) as client:
        response = client.get("/denied")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.headers.get_list("x-request-id") == [response.json()["error"]["request_id"]]


def test_unhandled_error_hides_details_but_keeps_the_request_id() -> None:
    with TestClient(app_with_failing_routes(), raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Request-ID": "trace-42"})

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "Váratlan hiba történt.",
        "request_id": "trace-42",
        "details": None,
    }
    assert "secret internal detail" not in response.text
    assert response.headers["x-request-id"] == "trace-42"


def test_suspicious_incoming_request_id_is_replaced() -> None:
    with TestClient(app_with_failing_routes()) as client:
        response = client.get("/health", headers={"X-Request-ID": "x\nforged log line"})

    assert response.headers["x-request-id"] != "x\nforged log line"
    assert len(response.headers["x-request-id"]) == 32


def test_validation_error_does_not_echo_the_submitted_password() -> None:
    with TestClient(app_with_failing_routes()) as client:
        response = client.post("/auth/token", data={"password": "hunter2-secret"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "hunter2-secret" not in response.text
