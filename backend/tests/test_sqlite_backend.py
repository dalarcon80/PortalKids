import os
import sqlite3
from pathlib import Path
import unittest

import werkzeug


os.environ.setdefault("SECRET_KEY", "testing-secret")
for key in [
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_INSTANCE_CONNECTION_NAME",
]:
    os.environ.pop(key, None)


if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "0"


from backend import app as backend_app


class SQLiteBackendFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(backend_app.BASE_DIR) / "database.db"
        for key in [
            "DB_NAME",
            "DB_USER",
            "DB_PASSWORD",
            "DB_HOST",
            "DB_INSTANCE_CONNECTION_NAME",
        ]:
            os.environ.pop(key, None)
        if self.db_path.exists():
            self.db_path.unlink()
        backend_app.init_db()
        self.client = backend_app.app.test_client()

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()

    def test_enroll_login_and_status_flow(self) -> None:
        payload = {
            "slug": "student-sqlite",
            "name": "Estudiante SQLite",
            "role": "learner",
            "workdir": "workspace",
            "email": "sqlite@example.com",
            "password": "Seguro123",
        }

        response = self.client.post("/api/enroll", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

        login_response = self.client.post(
            "/api/login",
            json={"slug": payload["slug"], "password": payload["password"]},
        )
        self.assertEqual(login_response.status_code, 200)
        login_data = login_response.get_json()
        self.assertTrue(login_data["authenticated"])
        self.assertTrue(login_data["token"])
        self.assertEqual(login_data["student"]["email"], payload["email"])
        self.assertFalse(login_data["student"]["is_admin"])
        self.assertEqual(login_data["completed"], [])

        status_response = self.client.get(
            f"/api/status?slug={payload['slug']}&token={login_data['token']}"
        )
        self.assertEqual(status_response.status_code, 200)
        status_data = status_response.get_json()
        self.assertEqual(status_data["student"]["slug"], payload["slug"])
        self.assertEqual(status_data["student"]["name"], payload["name"])
        self.assertFalse(status_data["student"]["is_admin"])
        self.assertEqual(status_data["completed"], [])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT slug, name, email, is_admin FROM students WHERE slug = ?",
                (payload["slug"],),
            )
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(dict(row)["email"], payload["email"])
            self.assertEqual(dict(row)["is_admin"], 0)
