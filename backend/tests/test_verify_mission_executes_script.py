from __future__ import annotations

from backend import app as backend_app
from backend.github_client import RepositoryInfo, RepositorySelection


class _DummyCursor:
    def __enter__(self) -> "_DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no cleanup required
        return None

    def execute(self, query: str, params=None) -> None:  # pragma: no cover - no-op
        return None

    def fetchone(self) -> dict:
        return {"role": "explorer"}

    def fetchall(self) -> list:
        return []


class _DummyConnection:
    is_sqlite = True

    def __enter__(self) -> "_DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no cleanup required
        return None

    def cursor(self) -> _DummyCursor:
        return _DummyCursor()


def test_verify_mission_executes_m3_script_with_pandas(monkeypatch):
    backend_app.app.config["TESTING"] = True

    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(backend_app, "get_db_connection", lambda: _DummyConnection())
    monkeypatch.setattr(
        backend_app,
        "validate_session",
        lambda token, slug=None, require_admin=False: True,
    )

    contract = {
        "verification_type": "script_output",
        "script_path": "scripts/m3_explorer.py",
        "validations": [
            {"type": "output_contains", "text": "Shape: "},
            {"type": "output_contains", "text": "Columns:"},
        ],
        "source": {
            "repository": "default",
            "default_branch": "main",
            "base_path": "students/{slug}",
        },
    }

    monkeypatch.setattr(
        backend_app,
        "_get_mission_by_id",
        lambda mission_id: {"mission_id": mission_id, "content": contract},
    )
    monkeypatch.setattr(
        backend_app,
        "_fetch_missions_from_db",
        lambda mission_id=None: [],
    )

    def _dummy_determine_repos(slug: str, role: str | None = None):
        return {
            "default": RepositoryInfo(
                key="default",
                repository="dummy/repo",
                default_branch="main",
            )
        }

    def _dummy_select_repo(source, slug: str, repositories):
        info = repositories["default"]
        return RepositorySelection(info=info, branch="main", base_path=f"students/{slug}")

    monkeypatch.setattr(backend_app, "determine_student_repositories", _dummy_determine_repos)
    monkeypatch.setattr(backend_app, "select_repository_for_contract", _dummy_select_repo)

    script_bytes = b"""import pandas as pd\n\n\nif __name__ == \"__main__\":\n    df = pd.DataFrame({\"a\": [1, 2]})\n    print(f\"Shape: {df.shape}\")\n    print(\"Columns:\", ", ".join(df.columns))\n"""

    class _DummyGitHubClient:
        def get_file_content(self, repository: str, path: str, ref: str | None) -> bytes:
            assert repository == "dummy/repo"
            assert ref == "main"
            expected_path = "students/student/scripts/m3_explorer.py"
            if path != expected_path:
                raise AssertionError(f"Unexpected path requested: {path}")
            return script_bytes

    monkeypatch.setattr(
        backend_app.GitHubClient,
        "from_settings",
        classmethod(lambda cls: _DummyGitHubClient()),
    )

    client = backend_app.app.test_client()
    response = client.post(
        "/api/verify_mission",
        json={"slug": "student", "mission_id": "m3"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"verified": True, "feedback": []}
