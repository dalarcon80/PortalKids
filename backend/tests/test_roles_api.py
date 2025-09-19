import os
from pathlib import Path

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


def test_admin_roles_crud_flow(sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    create_payload = {
        "slug": "qa-tester",
        "name": "QA Tester",
        "metadata": {"aliases": ["qa"], "description": "Quality team"},
    }
    create_response = client.post("/api/admin/roles", json=create_payload, headers=headers)
    assert create_response.status_code == 201
    created = create_response.get_json()["role"]
    assert created["slug"] == "qa-tester"
    assert created["name"] == "QA Tester"
    assert created["metadata"]["aliases"] == ["qa"]

    list_response = client.get("/api/admin/roles", headers=headers)
    assert list_response.status_code == 200
    roles = list_response.get_json()["roles"]
    assert any(role["slug"] == "qa-tester" for role in roles)

    detail_response = client.get("/api/admin/roles/qa-tester", headers=headers)
    assert detail_response.status_code == 200
    detail_role = detail_response.get_json()["role"]
    assert detail_role["name"] == "QA Tester"

    update_payload = {
        "name": "Quality Analyst",
        "metadata": {"aliases": ["qa", "quality"], "is_admin": False},
    }
    update_response = client.put(
        "/api/admin/roles/qa-tester",
        json=update_payload,
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()["role"]
    assert updated["name"] == "Quality Analyst"
    assert set(updated["metadata"]["aliases"]) == {"qa", "quality"}

    delete_response = client.delete("/api/admin/roles/qa-tester", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.get_json() == {"deleted": True}

    missing_response = client.get("/api/admin/roles/qa-tester", headers=headers)
    assert missing_response.status_code == 404


def test_admin_roles_validations(sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    invalid_slug_response = client.post(
        "/api/admin/roles",
        json={"slug": "Invalid Slug", "name": "Invalid"},
        headers=headers,
    )
    assert invalid_slug_response.status_code == 400

    client.post(
        "/api/admin/roles",
        json={"slug": "mentor", "name": "Mentor"},
        headers=headers,
    )
    duplicate_response = client.post(
        "/api/admin/roles",
        json={"slug": "mentor", "name": "Mentor"},
        headers=headers,
    )
    assert duplicate_response.status_code == 409

    update_response = client.put(
        "/api/admin/roles/mentor",
        json={"metadata": "invalid"},
        headers=headers,
    )
    assert update_response.status_code == 400

    in_use_response = client.delete("/api/admin/roles/admin", headers=headers)
    assert in_use_response.status_code == 409


def test_public_roles_endpoint(sqlite_backend):
    client = backend_app.app.test_client()
    response = client.get("/api/roles")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    roles = payload.get("roles")
    assert isinstance(roles, list)
    assert any(role.get("slug") == "admin" for role in roles)
