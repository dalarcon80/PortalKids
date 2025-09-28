from __future__ import annotations

from pathlib import Path

import pytest
import werkzeug

from backend import app as backend_app
from backend.github_client import RepositoryInfo, RepositorySelection


if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "0"


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


def _dataframe_validation_contract():
    return {
        "type": "dataframe_output",
        "shape": [3, 7],
        "columns": [
            "order_id",
            "customer_id",
            "product_id",
            "order_date",
            "status",
            "quantity",
            "unit_price",
        ],
        "head": (
            "   order_id customer_id product_id  order_date     status  quantity  unit_price\n"
            "0      1001        C001       P001  2024-01-05    Shipped         2       19.99\n"
            "1      1002        C002       P003  2024-01-06    Pending         1       49.50\n"
            "2      1003        C001       P002  2024-01-08  Cancelled         3       12.00"
        ),
        "dtypes": {
            "order_id": "int64",
            "customer_id": "object",
            "product_id": "object",
            "order_date": "object",
            "status": "object",
            "quantity": "int64",
            "unit_price": "float64",
        },
    }


def test_verify_mission_executes_m3_script_with_pandas(monkeypatch):
    pytest.importorskip("pandas")
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
        "required_files": ["sources/orders_seed.csv"],
        "workspace_paths": ["scripts/", "sources/"],
        "validations": [_dataframe_validation_contract()],
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

    def _dummy_select_repo(
        source, slug: str, repositories, role=None, preferred_repository_key=None
    ):
        info = repositories["default"]
        return RepositorySelection(info=info, branch="main", base_path=f"students/{slug}")

    monkeypatch.setattr(backend_app, "determine_student_repositories", _dummy_determine_repos)
    monkeypatch.setattr(backend_app, "select_repository_for_contract", _dummy_select_repo)

    script_bytes = (
        "import pandas as pd\n"
        "from helpers import dataset_path\n"
        "from pathlib import Path\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    df = pd.read_csv(Path(dataset_path()))\n"
        "    print('Shape =', df.shape)\n"
        "    print('Columns =', df.columns.tolist())\n"
        "    print('Head:', df.head())\n"
        "    print('Dtypes:', df.dtypes)\n"
    ).encode()
    helper_bytes = b"def dataset_path():\n    return 'sources/orders_seed.csv'\n"

    class _DummyGitHubClient:
        def get_file_content(self, repository: str, path: str, ref: str | None) -> bytes:
            assert repository == "dummy/repo"
            assert ref == "main"
            if path == "students/student/scripts/m3_explorer.py":
                return script_bytes
            if path == "students/student/sources/orders_seed.csv":
                return Path("sources/orders_seed.csv").read_bytes()
            if path == "students/student/scripts/helpers.py":
                return helper_bytes
            raise AssertionError(f"Unexpected path requested: {path}")

        def download_workspace(self, selection, paths, destination):
            root = Path(destination)
            for entry in paths:
                cleaned = (entry or "").strip("/")
                if cleaned == "scripts":
                    target = root / "scripts"
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "helpers.py").write_bytes(helper_bytes)
                elif cleaned == "sources":
                    target = root / "sources"
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "orders_seed.csv").write_bytes(
                        Path("sources/orders_seed.csv").read_bytes()
                    )

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


def test_verify_mission_reports_dataframe_summary_errors(monkeypatch):
    contract = {
        "verification_type": "script_output",
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
        "workspace_paths": ["scripts/", "sources/"],
        "validations": [_dataframe_validation_contract()],
        "source": {
            "repository": "default",
            "default_branch": "main",
            "base_path": "students/{slug}",
        },
    }

    backend_app.app.config["TESTING"] = True

    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(backend_app, "get_db_connection", lambda: _DummyConnection())
    monkeypatch.setattr(
        backend_app,
        "validate_session",
        lambda token, slug=None, require_admin=False: True,
    )
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

    def _dummy_select_repo(
        source, slug: str, repositories, role=None, preferred_repository_key=None
    ):
        info = repositories["default"]
        return RepositorySelection(info=info, branch="main", base_path=f"students/{slug}")

    monkeypatch.setattr(backend_app, "determine_student_repositories", _dummy_determine_repos)
    monkeypatch.setattr(backend_app, "select_repository_for_contract", _dummy_select_repo)

    script_bytes = (
        "from helpers import dataset_path\n"
        "\n"
        "def main():\n"
        "    print('Shape: (1, 1)')\n"
        "    print(\"Columns: ['fake']\")\n"
        "    print('Head:')\n"
        "    print(dataset_path())\n"
        "    print('Dtypes:')\n"
        "    print('dtype: object')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    ).encode()
    helper_bytes = b"def dataset_path():\n    return 'sources/orders_seed.csv'\n"

    class _DummyGitHubClientFailure:
        def get_file_content(self, repository: str, path: str, ref: str | None) -> bytes:
            assert repository == "dummy/repo"
            assert ref == "main"
            if path == "students/student/scripts/m3_explorer.py":
                return script_bytes
            if path == "students/student/sources/orders_seed.csv":
                return Path("sources/orders_seed.csv").read_bytes()
            if path == "students/student/scripts/helpers.py":
                return helper_bytes
            raise AssertionError(f"Unexpected path requested: {path}")

        def download_workspace(self, selection, paths, destination):
            root = Path(destination)
            for entry in paths:
                cleaned = (entry or "").strip("/")
                if cleaned == "scripts":
                    target = root / "scripts"
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "helpers.py").write_bytes(helper_bytes)

    monkeypatch.setattr(
        backend_app.GitHubClient,
        "from_settings",
        classmethod(lambda cls: _DummyGitHubClientFailure()),
    )

    client = backend_app.app.test_client()
    response = client.post(
        "/api/verify_mission",
        json={"slug": "student", "mission_id": "m3"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["verified"] is False
    joined_feedback = " ".join(payload.get("feedback", []))
    assert "df.shape" in joined_feedback
    assert "df.columns.tolist()" in joined_feedback
