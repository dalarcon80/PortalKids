from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend import app as backend_app


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


def _prepare_admin(slug: str = "admin-test") -> str:
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions")
            cur.execute("DELETE FROM completed_missions")
            cur.execute("DELETE FROM students")
            cur.execute(
                """
                INSERT INTO students (slug, name, role, email, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (slug, "Admin", "admin", "admin@example.com", ""),
            )
    return backend_app.create_session(slug)


def test_load_contracts_seeds_table(sqlite_backend):
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM missions")
    contracts = backend_app.load_contracts()
    assert "m1" in contracts
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM missions")
            row = cur.fetchone()
    assert row is not None
    assert int(row.get("count") or 0) > 0


def test_admin_mission_crud_flow(sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM missions")

    create_payload = {
        "mission_id": "test-mission",
        "title": "Prueba",
        "roles": ["learner"],
        "content": {"verification_type": "evidence", "deliverables": []},
    }
    create_response = client.post(
        "/api/admin/missions",
        json=create_payload,
        headers=headers,
    )
    assert create_response.status_code == 201
    created = create_response.get_json()["mission"]
    assert created["mission_id"] == create_payload["mission_id"]
    assert created["title"] == create_payload["title"]
    assert created["roles"] == ["learner"]
    assert created["content"]["verification_type"] == "evidence"

    list_response = client.get("/api/admin/missions", headers=headers)
    assert list_response.status_code == 200
    missions = list_response.get_json()["missions"]
    assert any(m["mission_id"] == create_payload["mission_id"] for m in missions)

    update_payload = {
        "title": "Actualizada",
        "roles": ["explorer"],
        "content": {
            "verification_type": "evidence",
            "deliverables": [{"type": "file_exists", "path": "README.md"}],
        },
    }
    update_response = client.put(
        f"/api/admin/missions/{create_payload['mission_id']}",
        json=update_payload,
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()["mission"]
    assert updated["title"] == "Actualizada"
    assert updated["roles"] == ["explorer"]
    assert updated["content"]["deliverables"][0]["path"] == "README.md"

    public_response = client.get("/api/missions?role=explorer")
    assert public_response.status_code == 200
    public_missions = public_response.get_json()["missions"]
    assert any(m["mission_id"] == create_payload["mission_id"] for m in public_missions)

    excluded_response = client.get("/api/missions?role=learner")
    assert excluded_response.status_code == 200
    excluded = excluded_response.get_json()["missions"]
    assert all(m["mission_id"] != create_payload["mission_id"] for m in excluded)


def test_admin_mission_requires_admin(sqlite_backend):
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM students")
            cur.execute(
                "INSERT INTO students (slug, role, email) VALUES (%s, %s, %s)",
                ("student", "learner", "student@example.com"),
            )
    token = backend_app.create_session("student")
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/api/admin/missions",
        json={
            "mission_id": "no-access",
            "content": {"verification_type": "evidence", "deliverables": []},
        },
        headers=headers,
    )
    assert response.status_code == 403
