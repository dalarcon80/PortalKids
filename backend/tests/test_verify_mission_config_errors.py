from __future__ import annotations

import pytest

from backend import app as backend_app
from backend.github_client import GitHubConfigurationError


class _DummyCursor:
    def __init__(self, role: str = "") -> None:
        self._role = role

    def __enter__(self) -> "_DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        return None

    def fetchone(self) -> dict:
        return {"role": self._role}

    def fetchall(self) -> list:
        return []


class _DummyConnection:
    def __init__(self, role: str = "") -> None:
        self._role = role

    def __enter__(self) -> "_DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _DummyCursor:
        return _DummyCursor(self._role)


@pytest.fixture(autouse=True)
def _configure_app(monkeypatch):
    backend_app.app.config["TESTING"] = True
    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(backend_app, "get_db_connection", lambda: _DummyConnection())
    monkeypatch.setattr(backend_app, "_get_mission_by_id", lambda mission_id: None)
    monkeypatch.setattr(
        backend_app, "_fetch_missions_from_db", lambda mission_id=None: []
    )
    monkeypatch.setattr(backend_app, "validate_session", lambda token, slug=None: True)
    import werkzeug

    if not hasattr(werkzeug, "__version__"):
        monkeypatch.setattr(werkzeug, "__version__", "0", raising=False)


def _patch_contract(monkeypatch, verification_type: str) -> None:
    contract = {"verification_type": verification_type}
    monkeypatch.setattr(
        backend_app,
        "_get_mission_by_id",
        lambda mission_id: {"mission_id": mission_id, "content": contract},
    )


def _patch_client_failure(monkeypatch, message: str) -> None:
    def _raise(cls):
        raise GitHubConfigurationError(message)

    monkeypatch.setattr(backend_app.GitHubClient, "from_env", classmethod(_raise))


@pytest.mark.parametrize("verification_type", ["evidence", "script_output"])
def test_verify_mission_returns_configuration_error(monkeypatch, verification_type):
    _patch_contract(monkeypatch, verification_type)
    _patch_client_failure(monkeypatch, "sin requests")
    client = backend_app.app.test_client()
    response = client.post(
        "/api/verify_mission",
        json={"slug": "student", "mission_id": "mission"},
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"verified": False, "feedback": ["sin requests"]}


def test_verify_mission_handles_missing_contract():
    client = backend_app.app.test_client()
    response = client.post(
        "/api/verify_mission",
        json={"slug": "student", "mission_id": "mission"},
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "verified": False,
        "feedback": [
            "No hay contratos de misión disponibles. Contacta a la persona administradora.",
        ],
    }
