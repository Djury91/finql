"""Helpers for API tests: logging in as one of the demo users."""

from fastapi.testclient import TestClient

PASSWORD = "Demo-jelszo-2026"
PECS_MANAGER = "pecs@minta-bank.example"
ANALYST = "elemzo@minta-bank.example"
AUDITOR = "auditor@minta-bank.example"
ADMIN = "admin@minta-bank.example"


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = client.post("/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
