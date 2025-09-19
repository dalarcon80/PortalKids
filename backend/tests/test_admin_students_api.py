import os
from datetime import datetime
from pathlib import Path
from typing import Any

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


def _reset_database() -> None:
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions")
            cur.execute("DELETE FROM completed_missions")
            cur.execute("DELETE FROM students")


def _add_student(
    slug: str,
    *,
    name: str = "Student",
    role: str = "learner",
    email: str | None = None,
    password: str = "secret",
    is_admin: bool = False,
    completed: list[str] | None = None,
) -> str:
    password_hash = backend_app.hash_password(password)
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO students (slug, name, role, email, workdir, password_hash, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    slug,
                    name,
                    role,
                    email or f"{slug}@example.com",
                    f"/home/{slug}",
                    password_hash,
                    1 if is_admin else 0,
                ),
            )
            for mission_id in completed or []:
                cur.execute(
                    "INSERT INTO completed_missions (student_slug, mission_id) VALUES (%s, %s)",
                    (slug, mission_id),
                )
    return password_hash


def test_admin_students_list_sqlite(sqlite_backend):
    _reset_database()
    _add_student("admin", name="Admin", role="admin", password="admin-pass", is_admin=True)
    _add_student("alice", name="Alice", completed=["m1"])
    _add_student("bob", name="Bob", role="explorer")
    token = backend_app.create_session("admin")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/admin/students", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    students = payload.get("students")
    assert isinstance(students, list)
    assert len(students) == 3
    alice = next(student for student in students if student["slug"] == "alice")
    assert alice["completed_missions"] == ["m1"]
    assert alice["role_name"] == "learner"
    admin_entry = next(student for student in students if student["slug"] == "admin")
    assert admin_entry["is_admin"] is True
    assert admin_entry["role_name"] == "admin"
    assert isinstance(admin_entry.get("role_metadata"), dict)
    assert admin_entry["role_metadata"].get("is_admin") is True


def test_admin_students_requires_admin(sqlite_backend):
    _reset_database()
    _add_student("learner", name="Learner", role="learner", password="pass")
    token = backend_app.create_session("learner")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/admin/students", headers=headers).status_code == 403
    assert (
        client.put(
            "/api/admin/students/learner",
            json={"name": "Nuevo"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.delete("/api/admin/students/learner", headers=headers).status_code == 403


def test_admin_update_student_sqlite(sqlite_backend):
    _reset_database()
    _add_student("admin", name="Admin", role="admin", password="admin-pass", is_admin=True)
    _add_student(
        "learner",
        name="Learner",
        role="learner",
        password="initial-pass",
        completed=["m1"],
    )
    token = backend_app.create_session("admin")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "name": "Learner Actualizada",
        "email": "learner@example.com",
        "role": "explorer",
        "is_admin": True,
        "password": "nueva-clave",
        "current_password": "initial-pass",
    }

    response = client.put(
        "/api/admin/students/learner",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 200
    student = response.get_json()["student"]
    assert student["name"] == payload["name"]
    assert student["email"] == payload["email"]
    assert student["role"] == payload["role"]
    assert student["role_name"] == "explorer"
    assert student["is_admin"] is True
    assert student["completed_missions"] == ["m1"]

    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM students WHERE slug = %s",
                ("learner",),
            )
            row = cur.fetchone()
    stored_hash = row.get("password_hash") if isinstance(row, dict) else row["password_hash"]
    assert backend_app.verify_password("nueva-clave", stored_hash)


def test_admin_update_student_rejects_wrong_current_password(sqlite_backend):
    _reset_database()
    _add_student("admin", name="Admin", role="admin", password="admin-pass", is_admin=True)
    _add_student("learner", name="Learner", role="learner", password="initial-pass")
    token = backend_app.create_session("admin")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.put(
        "/api/admin/students/learner",
        json={"password": "otra-clave", "current_password": "incorrecta"},
        headers=headers,
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert "error" in payload


def test_admin_delete_student_sqlite(sqlite_backend):
    _reset_database()
    _add_student("admin", name="Admin", role="admin", password="admin-pass", is_admin=True)
    _add_student(
        "learner",
        name="Learner",
        role="learner",
        password="initial-pass",
        completed=["m1", "m2"],
    )
    token = backend_app.create_session("admin")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.delete("/api/admin/students/learner", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"deleted": True}

    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count FROM students WHERE slug = %s",
                ("learner",),
            )
            student_row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS count FROM completed_missions WHERE student_slug = %s",
                ("learner",),
            )
            mission_row = cur.fetchone()
    student_count = (
        student_row.get("count") if isinstance(student_row, dict) else student_row["count"]
    )
    missions_count = (
        mission_row.get("count") if isinstance(mission_row, dict) else mission_row["count"]
    )
    assert int(student_count or 0) == 0
    assert int(missions_count or 0) == 0


def test_admin_update_student_rejects_unknown_role(sqlite_backend):
    _reset_database()
    _add_student("admin", name="Admin", role="admin", password="admin-pass", is_admin=True)
    _add_student("learner", name="Learner", role="learner", password="initial-pass")
    token = backend_app.create_session("admin")

    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.put(
        "/api/admin/students/learner",
        json={"role": "ghost"},
        headers=headers,
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert "error" in payload


def test_enroll_requires_valid_role(sqlite_backend):
    _reset_database()
    client = backend_app.app.test_client()
    payload = {
        "slug": "new-student",
        "name": "Nuevo Estudiante",
        "role": "ghost",
        "workdir": "/home/new-student",
        "email": "new-student@example.com",
        "password": "secret-pass",
    }

    response = client.post("/api/enroll", json=payload)

    assert response.status_code == 400
    data = response.get_json()
    assert isinstance(data, dict)
    assert "error" in data


def test_enroll_accepts_known_role_and_stores_slug(sqlite_backend):
    _reset_database()
    client = backend_app.app.test_client()
    payload = {
        "slug": "learner-two",
        "name": "Learner Two",
        "role": "Learner",
        "workdir": "/home/learner-two",
        "email": "learner-two@example.com",
        "password": "secret-pass",
    }

    response = client.post("/api/enroll", json=payload)

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}

    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slug, role FROM students WHERE slug = %s",
                ("learner-two",),
            )
            row = cur.fetchone()
    assert row is not None
    stored_role = row.get("role") if isinstance(row, dict) else row["role"]
    assert stored_role == "learner"


def _build_mysql_state() -> dict[str, Any]:
    now = backend_app._format_timestamp(datetime.utcnow())
    return {
        "students": {
            "admin": {
                "slug": "admin",
                "name": "Admin",
                "role": "admin",
                "workdir": "/home/admin",
                "email": "admin@example.com",
                "password_hash": "",
                "is_admin": 1,
                "created_at": now,
            },
            "learner": {
                "slug": "learner",
                "name": "Learner",
                "role": "learner",
                "workdir": "/home/learner",
                "email": "learner@example.com",
                "password_hash": "hashed-old",
                "is_admin": 0,
                "created_at": now,
            },
        },
        "completed_missions": {"learner": ["m1", "m2"]},
        "roles": {
            "admin": {
                "slug": "admin",
                "name": "admin",
                "metadata_json": '{"is_admin": true, "aliases": ["admin"]}',
                "created_at": now,
                "updated_at": now,
            },
            "learner": {
                "slug": "learner",
                "name": "learner",
                "metadata_json": "{}",
                "created_at": now,
                "updated_at": now,
            },
            "explorer": {
                "slug": "explorer",
                "name": "explorer",
                "metadata_json": "{}",
                "created_at": now,
                "updated_at": now,
            },
        },
    }


class FakeMySQLCursor:
    def __init__(self, state: dict[str, Any]):
        self._state = state
        self._results: list[dict[str, Any]] = []
        self.rowcount = 0
        self.last_query = ""
        self.last_params: tuple[Any, ...] = ()

    def __enter__(self) -> "FakeMySQLCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> None:
        self.last_query = query
        self.last_params = tuple(params or ())
        self.rowcount = 0
        stripped = query.strip()
        normalized = " ".join(stripped.split())
        if normalized.startswith(
            "SELECT slug, name, role, workdir, email, is_admin, created_at FROM students"
        ):
            self._results = [
                {
                    "slug": student["slug"],
                    "name": student.get("name"),
                    "role": student.get("role"),
                    "workdir": student.get("workdir"),
                    "email": student.get("email"),
                    "is_admin": student.get("is_admin"),
                    "created_at": student.get("created_at"),
                }
                for student in self._state["students"].values()
            ]
            self._results.sort(key=lambda item: (item.get("name") or ""))
        elif normalized.startswith(
            "SELECT slug, name, role, workdir, email, is_admin, password_hash, created_at FROM students WHERE slug"
        ):
            slug = self.last_params[0]
            student = self._state["students"].get(slug)
            self._results = [dict(student)] if student else []
        elif normalized.startswith(
            "SELECT slug, name, metadata_json, created_at, updated_at FROM roles ORDER BY name, slug"
        ):
            roles = [
                {
                    "slug": role.get("slug"),
                    "name": role.get("name"),
                    "metadata_json": role.get("metadata_json"),
                    "created_at": role.get("created_at"),
                    "updated_at": role.get("updated_at"),
                }
                for role in self._state["roles"].values()
            ]
            roles.sort(key=lambda item: ((item.get("name") or ""), item.get("slug") or ""))
            self._results = roles
        elif normalized.startswith(
            "SELECT slug, name, metadata_json, created_at, updated_at FROM roles WHERE slug"
        ):
            slug = self.last_params[0]
            role = self._state["roles"].get(slug)
            self._results = [dict(role)] if role else []
        elif normalized.startswith("SELECT slug FROM students WHERE slug = %s"):
            slug = self.last_params[0]
            student = self._state["students"].get(slug)
            self._results = [{"slug": slug}] if student else []
        elif normalized.startswith("DELETE FROM students WHERE slug = %s"):
            slug = self.last_params[0]
            existed = self._state["students"].pop(slug, None)
            self.rowcount = 1 if existed else 0
            self._results = []
        elif normalized.startswith("DELETE FROM completed_missions WHERE student_slug = %s"):
            slug = self.last_params[0]
            existed = self._state["completed_missions"].pop(slug, None)
            self.rowcount = 1 if existed else 0
            self._results = []
        elif normalized.startswith("UPDATE students SET"):
            slug = self.last_params[-1]
            student = self._state["students"].get(slug)
            if not student:
                self._results = []
                self.rowcount = 0
                return
            assignments = normalized.split("SET", 1)[1].split("WHERE", 1)[0].split(",")
            values = list(self.last_params[:-1])
            for assignment, value in zip(assignments, values):
                column = assignment.split("=")[0].strip(" `")
                student[column] = value
            self.rowcount = 1
            self._results = []
        elif normalized.startswith("SELECT student_slug, mission_id FROM completed_missions"):
            if "IN (" in normalized:
                slugs = list(self.last_params)
            else:
                slugs = [self.last_params[0]]
            results = []
            for slug in slugs:
                missions = self._state["completed_missions"].get(slug, [])
                for mission in missions:
                    results.append({"student_slug": slug, "mission_id": mission})
            self._results = results
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self) -> dict[str, Any] | None:
        if self._results:
            return self._results.pop(0)
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        results = list(self._results)
        self._results = []
        return results

    def close(self) -> None:
        self._results = []


class FakeMySQLConnection:
    is_sqlite = False

    def __init__(self, state: dict[str, Any]):
        self._state = state

    def __enter__(self) -> "FakeMySQLConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def cursor(self) -> FakeMySQLCursor:
        return FakeMySQLCursor(self._state)

    def commit(self) -> None:  # pragma: no cover - compatibility no-op
        pass

    def rollback(self) -> None:  # pragma: no cover - compatibility no-op
        pass

    def close(self) -> None:  # pragma: no cover - compatibility no-op
        pass


def test_admin_students_list_mysql(monkeypatch):
    state = _build_mysql_state()

    monkeypatch.setattr(backend_app, "get_db_connection", lambda: FakeMySQLConnection(state))
    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(
        backend_app,
        "_resolve_admin_request",
        lambda: ({"slug": "admin", "is_admin": True}, None),
    )

    client = backend_app.app.test_client()
    response = client.get("/api/admin/students")

    assert response.status_code == 200
    students = response.get_json()["students"]
    learner = next(student for student in students if student["slug"] == "learner")
    assert learner["completed_missions"] == ["m1", "m2"]
    assert learner["role_name"] == "learner"


def test_admin_update_student_mysql(monkeypatch):
    state = _build_mysql_state()

    monkeypatch.setattr(backend_app, "get_db_connection", lambda: FakeMySQLConnection(state))
    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(
        backend_app,
        "_resolve_admin_request",
        lambda: ({"slug": "admin", "is_admin": True}, None),
    )

    hash_calls: list[str] = []
    verify_calls: list[tuple[str, str]] = []

    def fake_hash(password: str) -> str:
        hash_calls.append(password)
        return f"hashed::{password}"

    def fake_verify(raw: str, stored: str) -> bool:
        verify_calls.append((raw, stored))
        return raw == "current-secret" and stored == "hashed-old"

    monkeypatch.setattr(backend_app, "hash_password", fake_hash)
    monkeypatch.setattr(backend_app, "verify_password", fake_verify)

    client = backend_app.app.test_client()
    payload = {
        "name": "Learner Updated",
        "email": "new@example.com",
        "role": "explorer",
        "is_admin": True,
        "password": "new-secret",
        "current_password": "current-secret",
    }
    response = client.put("/api/admin/students/learner", json=payload)

    assert response.status_code == 200
    student = response.get_json()["student"]
    assert student["name"] == payload["name"]
    assert student["email"] == payload["email"]
    assert student["role"] == payload["role"]
    assert student["role_name"] == "explorer"
    assert student["is_admin"] is True
    assert hash_calls == ["new-secret"]
    assert verify_calls == [("current-secret", "hashed-old")]
    assert state["students"]["learner"]["password_hash"] == "hashed::new-secret"


def test_admin_delete_student_mysql(monkeypatch):
    state = _build_mysql_state()

    monkeypatch.setattr(backend_app, "get_db_connection", lambda: FakeMySQLConnection(state))
    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(
        backend_app,
        "_resolve_admin_request",
        lambda: ({"slug": "admin", "is_admin": True}, None),
    )

    client = backend_app.app.test_client()
    response = client.delete("/api/admin/students/learner")

    assert response.status_code == 200
    assert response.get_json() == {"deleted": True}
    assert "learner" not in state["students"]
    assert "learner" not in state["completed_missions"]
