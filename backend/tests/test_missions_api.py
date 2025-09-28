from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
import werkzeug

from backend import app as backend_app
from backend.github_client import GitHubFileNotFoundError, RepositoryInfo

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


def _prepare_admin(slug: str = "admin-test") -> str:
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions")
            cur.execute("DELETE FROM completed_missions")
            cur.execute("DELETE FROM students")
            cur.execute(
                """
                INSERT INTO students (slug, name, role, email, password_hash, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (slug, "Admin", "admin", "admin@example.com", "", 1),
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
    mission_rows = backend_app._fetch_missions_from_db("m1")
    assert mission_rows, "Esperábamos encontrar la misión m1 reseedeada"
    mission = mission_rows[0]
    assert mission.get("title") == "M1 — La Puerta de la Base"
    assert mission.get("roles") == ["Ventas", "Operaciones"]


def test_blank_titles_are_reseeded(sqlite_backend):
    backend_app.init_db()
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM missions WHERE mission_id = %s", ("m1",))
            cur.execute(
                """
                INSERT INTO missions (mission_id, title, roles, content_json, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    "m1",
                    "   ",
                    "[]",
                    "",
                    backend_app._format_timestamp(datetime.utcnow()),
                ),
            )

    client = backend_app.app.test_client()
    response = client.get("/api/missions")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    missions = payload.get("missions")
    assert isinstance(missions, list)
    mission = next((m for m in missions if m.get("mission_id") == "m1"), None)
    assert mission is not None
    assert mission.get("title") == "M1 — La Puerta de la Base"
    assert mission.get("roles") == ["Ventas", "Operaciones"]
    content = mission.get("content")
    assert isinstance(content, dict)
    assert content.get("verification_type") == "evidence"
    display_html = content.get("display_html")
    assert isinstance(display_html, str) and display_html.strip()


def test_m3_contract_includes_orders_seed_guidance(sqlite_backend):
    contracts = backend_app.load_contracts()
    m3 = contracts.get("m3")
    assert isinstance(m3, dict)
    workspace_paths = m3.get("workspace_paths")
    assert isinstance(workspace_paths, list), "La misión m3 debe exponer rutas de workspace"
    assert "sources/" in workspace_paths, "Se espera que m3 incluya sources/ en workspace_paths"
    feedback_message = m3.get("feedback_required_file_missing", "")
    assert "students/{{slug}}/sources/orders_seed.csv" in feedback_message
    assert "docs/orders_seed_instructions.md" in feedback_message
    display_html = m3.get("display_html", "")
    assert "Checklist antes de subir cambios" in display_html
    assert "students/{slug}/sources/orders_seed.csv" in display_html
    assert "docs/orders_seed_instructions.md" in display_html


def test_blank_display_html_is_replaced_from_contract(sqlite_backend):
    backend_app.init_db()
    contracts_payload = backend_app._load_contract_payload()
    mission_id = None
    expected_html = None
    for candidate_id, contract in contracts_payload.items():
        html_value = contract.get("display_html") if isinstance(contract, dict) else None
        if isinstance(html_value, str) and html_value.strip():
            mission_id = candidate_id
            expected_html = html_value
            break
    assert mission_id is not None, "Se esperaba al menos una misión con display_html en el contrato"
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            is_sqlite = getattr(conn, "is_sqlite", False)
            backend_app._ensure_missions_seeded(cur, is_sqlite)
            cur.execute(
                "SELECT content_json FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            row = cur.fetchone() or {}
            content_raw = row.get("content_json")
            assert isinstance(content_raw, str) and content_raw.strip(), "La misión debe existir en la base de datos"
            content_payload = json.loads(content_raw)
            content_payload["display_html"] = "   "
            cur.execute(
                "UPDATE missions SET content_json = %s WHERE mission_id = %s",
                (json.dumps(content_payload, ensure_ascii=False), mission_id),
            )
            backend_app._ensure_presentations_in_storage(cur, is_sqlite)
            cur.execute(
                "SELECT content_json FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            updated_row = cur.fetchone() or {}
            updated_raw = updated_row.get("content_json")
    assert isinstance(updated_raw, str) and updated_raw.strip()
    updated_payload = json.loads(updated_raw)
    assert updated_payload.get("display_html") == expected_html


def test_mission_content_json_is_refreshed_from_contract(sqlite_backend):
    backend_app.init_db()
    contracts_payload = backend_app._load_contract_payload()
    presentations = backend_app._load_frontend_presentations()
    mission_id = None
    contract_entry = None
    for candidate_id, contract in contracts_payload.items():
        if isinstance(contract, dict) and "feedback_script_missing" in contract:
            mission_id = candidate_id
            contract_entry = contract
            break
    assert mission_id is not None, "Se esperaba al menos una misión con feedback_script_missing"
    seed_values = backend_app._build_mission_seed_values(
        mission_id,
        contract_entry,
        presentations,
    )
    assert seed_values is not None
    title, roles_json, desired_content_json = seed_values
    desired_payload = json.loads(desired_content_json)
    assert "feedback_script_missing" in desired_payload
    outdated_payload = dict(desired_payload)
    outdated_payload.pop("feedback_script_missing", None)
    outdated_content_json = json.dumps(outdated_payload, ensure_ascii=False)

    updated_raw = None
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            is_sqlite = getattr(conn, "is_sqlite", False)
            cur.execute("DELETE FROM missions WHERE mission_id = %s", (mission_id,))
            cur.execute(
                """
                INSERT INTO missions (mission_id, title, roles, content_json, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    mission_id,
                    title,
                    roles_json,
                    outdated_content_json,
                    backend_app._format_timestamp(datetime.utcnow()),
                ),
            )
            backend_app._ensure_missions_seeded(cur, is_sqlite)
            cur.execute(
                "SELECT content_json FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            row = cur.fetchone() or {}
            updated_raw = row.get("content_json")

    assert isinstance(updated_raw, str) and updated_raw.strip()
    updated_payload = json.loads(updated_raw)
    assert updated_payload.get("feedback_script_missing") == desired_payload.get("feedback_script_missing")


def test_outdated_display_html_is_replaced_from_contract(sqlite_backend):
    backend_app.init_db()
    contracts_payload = backend_app._load_contract_payload()
    mission_id = None
    expected_html = None
    for candidate_id, contract in contracts_payload.items():
        html_value = contract.get("display_html") if isinstance(contract, dict) else None
        if isinstance(html_value, str) and html_value.strip():
            mission_id = candidate_id
            expected_html = html_value
            break
    assert mission_id is not None, "Se esperaba al menos una misión con display_html en el contrato"
    with backend_app.get_db_connection() as conn:
        with conn.cursor() as cur:
            is_sqlite = getattr(conn, "is_sqlite", False)
            backend_app._ensure_missions_seeded(cur, is_sqlite)
            cur.execute(
                "SELECT content_json FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            row = cur.fetchone() or {}
            content_raw = row.get("content_json")
            assert isinstance(content_raw, str) and content_raw.strip(), "La misión debe existir en la base de datos"
            content_payload = json.loads(content_raw)
            content_payload["display_html"] = "<p>Contenido anterior</p>"
            cur.execute(
                "UPDATE missions SET content_json = %s WHERE mission_id = %s",
                (json.dumps(content_payload, ensure_ascii=False), mission_id),
            )
            backend_app._ensure_presentations_in_storage(cur, is_sqlite)
            cur.execute(
                "SELECT content_json FROM missions WHERE mission_id = %s",
                (mission_id,),
            )
            updated_row = cur.fetchone() or {}
            updated_raw = updated_row.get("content_json")
    assert isinstance(updated_raw, str) and updated_raw.strip()
    updated_payload = json.loads(updated_raw)
    assert updated_payload.get("display_html") == expected_html


def test_admin_mission_display_html_persists_after_update(sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    list_response = client.get("/api/admin/missions", headers=headers)
    assert list_response.status_code == 200
    missions = list_response.get_json().get("missions")
    assert isinstance(missions, list) and missions, "Se esperaba al menos una misión disponible"
    mission = next((m for m in missions if isinstance(m.get("content"), dict) and m["content"].get("display_html")), None)
    assert mission is not None, "Se esperaba encontrar una misión con display_html"
    mission_id = mission.get("mission_id")
    original_content = dict(mission["content"])
    new_html = "<section class=\"mission\"><h3>Historia</h3><p>Actualizado desde la prueba</p></section>"
    content_payload = dict(original_content)
    content_payload["display_html"] = new_html

    update_response = client.put(
        f"/api/admin/missions/{mission_id}",
        json={
            "title": mission.get("title"),
            "roles": mission.get("roles"),
            "content": content_payload,
        },
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.get_json().get("mission")
    assert updated and updated.get("content", {}).get("display_html") == new_html
    assert updated.get("content", {}).get("disable_contract_sync") is True

    reload_response = client.get("/api/admin/missions", headers=headers)
    assert reload_response.status_code == 200
    refreshed = next(
        (
            m
            for m in reload_response.get_json().get("missions", [])
            if m.get("mission_id") == mission_id
        ),
        None,
    )
    assert refreshed is not None, "La misión actualizada debe permanecer disponible"
    refreshed_content = refreshed.get("content", {})
    assert refreshed_content.get("display_html") == new_html
    assert refreshed_content.get("disable_contract_sync") is True


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

    mixed_case_response = client.get("/api/missions?role=Explorer")
    assert mixed_case_response.status_code == 200
    mixed_case_missions = mixed_case_response.get_json()["missions"]
    assert any(m["mission_id"] == create_payload["mission_id"] for m in mixed_case_missions)

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
                "INSERT INTO students (slug, role, email, is_admin) VALUES (%s, %s, %s, %s)",
                ("student", "admin", "student@example.com", 0),
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


def test_admin_mission_rejects_unknown_role(sqlite_backend):
    token = _prepare_admin()
    client = backend_app.app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/admin/missions",
        json={
            "mission_id": "invalid-role",
            "roles": ["ghost"],
            "content": {"verification_type": "evidence", "deliverables": []},
        },
        headers=headers,
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert "error" in payload


def test_public_missions_filter_by_slug(sqlite_backend):
    client = backend_app.app.test_client()
    response = client.get("/api/missions?role=ventas")
    assert response.status_code == 200
    missions = response.get_json()["missions"]
    assert any(mission.get("mission_id") == "m1" for mission in missions)


def test_public_mission_detail_includes_display_html(sqlite_backend):
    client = backend_app.app.test_client()
    response = client.get("/api/missions/m1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    mission = payload.get("mission")
    assert mission and mission.get("mission_id") == "m1"
    assert mission.get("title") == "M1 — La Puerta de la Base"
    assert mission.get("roles") == ["Ventas", "Operaciones"]
    content = mission.get("content") if isinstance(mission, dict) else None
    assert isinstance(content, dict)
    assert "display_html" in content
    assert isinstance(content.get("display_html"), str)
    assert "<section" in content.get("display_html", "")


def test_m3_contract_requires_dataframe_introspection():
    contracts_payload = backend_app._load_contract_payload()
    mission = contracts_payload.get("m3")
    assert isinstance(mission, dict), "La misión m3 debe existir en el contrato"

    deliverables = mission.get("deliverables", [])
    shape_requirement = next(
        (
            d
            for d in deliverables
            if d.get("type") == "file_contains"
            and d.get("path") == "scripts/m3_explorer.py"
            and d.get("content") == "df.shape"
        ),
        None,
    )
    columns_requirement = next(
        (
            d
            for d in deliverables
            if d.get("type") == "file_contains"
            and d.get("path") == "scripts/m3_explorer.py"
            and d.get("content") == "df.columns.tolist()"
        ),
        None,
    )

    assert shape_requirement is not None, "Se debe exigir la llamada a df.shape en el script"
    assert columns_requirement is not None, "Se debe exigir la llamada a df.columns.tolist() en el script"

    validations = mission.get("validations", [])
    dataframe_validation = next(
        (v for v in validations if v.get("type") == "dataframe_output"),
        None,
    )

    assert (
        dataframe_validation is not None
    ), "La misión m3 debe validar la salida completa del DataFrame"
    assert dataframe_validation.get("shape") == [
        3,
        7,
    ], "El contrato debe verificar la forma esperada del DataFrame"
    assert dataframe_validation.get("columns") == [
        "order_id",
        "customer_id",
        "product_id",
        "order_date",
        "status",
        "quantity",
        "unit_price",
    ]
    assert "order_id" in (dataframe_validation.get("dtypes") or {})


def test_verify_mission_prefers_operaciones_when_ventas_missing_files(monkeypatch):
    backend_app.app.config["TESTING"] = True

    monkeypatch.setattr(backend_app, "init_db", lambda: None)

    class _StubCursor:
        def __enter__(self) -> "_StubCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, query: str, params=None) -> None:
            return None

        def fetchone(self) -> dict:
            return {"role": ""}

    class _StubConnection:
        is_sqlite = True

        def __enter__(self) -> "_StubConnection":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def cursor(self) -> _StubCursor:
            return _StubCursor()

    monkeypatch.setattr(backend_app, "get_db_connection", lambda: _StubConnection())
    monkeypatch.setattr(
        backend_app,
        "validate_session",
        lambda token, slug=None, require_admin=False: True,
    )

    mission_roles = ["Ventas", "Operaciones"]
    contract = {
        "verification_type": "script_output",
        "script_path": "scripts/report.py",
        "required_files": ["sources/orders_seed.csv"],
        "source": {
            "repository": "default",
            "prefer_repository_by_role": True,
            "base_path": "students/{slug}",
        },
    }
    mission_record = {
        "mission_id": "m-operaciones",
        "roles": mission_roles,
        "content": contract,
    }

    monkeypatch.setattr(backend_app, "_get_mission_by_id", lambda mission_id: mission_record)
    monkeypatch.setattr(backend_app, "_fetch_missions_from_db", lambda mission_id=None: [])

    repositories = {
        "ventas": RepositoryInfo(
            key="ventas", repository="org/ventas", default_branch="main"
        ),
        "operaciones": RepositoryInfo(
            key="operaciones", repository="org/operaciones", default_branch="main"
        ),
    }

    monkeypatch.setattr(
        backend_app,
        "determine_student_repositories",
        lambda slug, role=None: repositories,
    )

    script_bytes = (
        "from pathlib import Path\n"
        "if __name__ == '__main__':\n"
        "    dataset = Path('sources/orders_seed.csv')\n"
        "    print(dataset.read_text().strip())\n"
    ).encode("utf-8")

    class _StubGitHubClient:
        def __init__(self, script_data: bytes) -> None:
            self._script = script_data
            self.requests: list[tuple[str, str]] = []

        def get_file_content(self, repository: str, path: str, ref: str | None) -> bytes:
            self.requests.append((repository, path))
            if path.endswith("scripts/report.py"):
                return self._script
            if repository == "org/operaciones" and path.endswith("sources/orders_seed.csv"):
                return b"order_id\n1\n"
            raise GitHubFileNotFoundError(
                "missing",
                repository=repository,
                path=path,
                ref=ref or "",
            )

        def download_workspace(self, selection, paths, destination):  # pragma: no cover - not used
            return None

    stub_client = _StubGitHubClient(script_bytes)
    monkeypatch.setattr(
        backend_app.GitHubClient,
        "from_settings",
        classmethod(lambda cls: stub_client),
    )

    client = backend_app.app.test_client()
    response = client.post(
        "/api/verify_mission",
        json={"slug": "student", "mission_id": "m-operaciones"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"verified": True, "feedback": []}

    dataset_requests = [
        repo for repo, path in stub_client.requests if path.endswith("sources/orders_seed.csv")
    ]
    assert "org/ventas" in dataset_requests
    assert "org/operaciones" in dataset_requests
