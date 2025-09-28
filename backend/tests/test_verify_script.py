from __future__ import annotations

from backend import app as backend_app
from backend.github_client import GitHubFileNotFoundError


class _DummyFiles:
    def __init__(self, existing: dict[str, bytes] | None = None) -> None:
        self._existing = existing or {}

    def read_bytes(self, path: str) -> bytes:
        if path in self._existing:
            return self._existing[path]
        raise GitHubFileNotFoundError(
            f"missing {path}", repository="repo", path=path, ref="main"
        )

    def describe_source(self, path: str | None = None) -> str:
        if path is None:
            return "repo/main"
        return f"repo/main en {path}"


def test_verify_script_uses_custom_message_when_script_missing() -> None:
    files = _DummyFiles()
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "feedback_script_missing": "Falta el script {script_path}. Revísalo en {source}.",
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is False
    assert feedback == [
        "Falta el script scripts/m3_explorer.py. Revísalo en repo/main en scripts/m3_explorer.py."
    ]


def test_verify_script_uses_custom_message_when_dependency_missing() -> None:
    files = _DummyFiles({"scripts/m3_explorer.py": b"print('ok')"})
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["data/input.csv"],
        "feedback_required_file_missing": "Hace falta {required_path} para ejecutar el script ({source}).",
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is False
    assert feedback == [
        "Hace falta data/input.csv para ejecutar el script (repo/main en data/input.csv)."
    ]


def test_verify_script_runs_with_required_files(tmp_path) -> None:
    script_code = (
        "from pathlib import Path\n"
        "print(Path('sources/orders_seed.csv').read_text(encoding='utf-8').splitlines()[0])\n"
    )
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "sources/orders_seed.csv": b"order_id,customer_id\n1,C001\n",
        }
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_reports_missing_dataframe_calls(tmp_path) -> None:
    script_code = (
        "def main():\n"
        "    print('Hola exploradora')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles({"scripts/m3_explorer.py": script_code.encode()})
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "validations": [
            {
                "type": "output_contains",
                "text": "Shape: ",
                "feedback_fail": "La salida de tu script no incluye el resultado de llamar a df.shape (usa print(f\"Shape: {df.shape}\")).",
            },
            {
                "type": "output_contains",
                "text": "Columns:",
                "feedback_fail": "La salida de tu script no muestra la lista de columnas obtenida con df.columns.tolist().",
            },
        ],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is False
    assert any("df.shape" in message for message in feedback)
    assert any("df.columns.tolist()" in message for message in feedback)
