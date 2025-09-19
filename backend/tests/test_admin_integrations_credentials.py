import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import werkzeug

from backend import app as backend_app

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "0"


@pytest.fixture()
def sqlite_backend():
    for key in [
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_INSTANCE_CONNECTION_NAME",
    ]:
        os.environ.pop(key, None)
    db_path = Path(backend_app.BASE_DIR) / "database.db"
    if db_path.exists():
        db_path.unlink()
    backend_app.init_db()
    yield db_path
    if db_path.exists():
        db_path.unlink()


def _prepare_admin(slug: str = "admin") -> str:
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions")
            cur.execute("DELETE FROM students")
            cur.execute(
                """
                INSERT INTO students (slug, name, role, email, password_hash, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (slug, "Admin", "admin", "admin@example.com", "", 1),
            )
    return backend_app.create_session(slug)


@patch("backend.app.OpenAI")
@patch("backend.app.requests.Session")
def test_update_integrations_validates_credentials_success(mock_session_cls, mock_openai_cls, sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    backend_app._REQUESTS_AVAILABLE = True

    mock_session = MagicMock()
    mock_session.headers = {}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_response.text = ""
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    mock_openai_client = MagicMock()
    mock_openai_client.models.list.return_value = {"data": []}
    mock_openai_cls.return_value = mock_openai_client

    payload = {
        "updates": [
            {"key": "github_token", "value": "ghp_validtoken"},
            {"key": "openai_api_key", "value": "sk-valid"},
        ]
    }
    response = client.put("/api/admin/integrations", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert set(body.get("updated_keys", [])) == {"github_token", "openai_api_key"}
    assert backend_app.get_service_setting("github_token") == "ghp_validtoken"
    assert backend_app.get_service_setting("openai_api_key") == "sk-valid"
    mock_session.get.assert_called_once()
    mock_openai_client.models.list.assert_called_once()


@patch("backend.app.OpenAI")
@patch("backend.app.requests.Session")
def test_update_integrations_reports_github_error(mock_session_cls, mock_openai_cls, sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    backend_app._REQUESTS_AVAILABLE = True

    mock_session = MagicMock()
    mock_session.headers = {}
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"message": "Bad credentials"}
    mock_response.text = "Bad credentials"
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    mock_openai_client = MagicMock()
    mock_openai_client.models.list.return_value = {"data": []}
    mock_openai_cls.return_value = mock_openai_client

    payload = {"updates": [{"key": "github_token", "value": "ghp_invalid"}]}
    response = client.put("/api/admin/integrations", json=payload, headers=headers)
    assert response.status_code == 400
    body = response.get_json()
    assert "GitHub rechazó el token" in body.get("error", "")
    assert backend_app.get_service_setting("github_token") in (None, "")
    mock_openai_client.models.list.assert_not_called()


@patch("backend.app.requests.Session")
def test_update_integrations_reports_openai_error(mock_session_cls, sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    backend_app._REQUESTS_AVAILABLE = True

    mock_session = MagicMock()
    mock_session.headers = {}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_response.text = ""
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    class DummyAPIError(Exception):
        def __init__(self, message="error"):
            super().__init__(message)
            self.message = message

    with patch("backend.app.APIError", DummyAPIError), patch("backend.app.OpenAI") as mock_openai_cls:
        mock_openai_client = MagicMock()
        mock_openai_client.models.list.side_effect = DummyAPIError("Clave inválida")
        mock_openai_cls.return_value = mock_openai_client

        payload = {
            "updates": [
                {"key": "github_token", "value": "ghp_valid"},
                {"key": "openai_api_key", "value": "sk-invalid"},
            ]
        }
        response = client.put("/api/admin/integrations", json=payload, headers=headers)
    assert response.status_code == 400
    body = response.get_json()
    assert "OpenAI rechazó la clave proporcionada" in body.get("error", "")
    assert backend_app.get_service_setting("openai_api_key") in (None, "")
    assert backend_app.get_service_setting("github_token") in (None, "")
    mock_session.get.assert_called_once()
