from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from backend import app as backend_app
from backend.github_client import GitHubFileNotFoundError


class _DummyFiles:
    def __init__(
        self, existing: dict[str, bytes] | None = None, *, base_path: str = ""
    ) -> None:
        self._existing = existing or {}
        self._base_path = base_path
        self.workspace_calls: list[list[str]] = []

    @property
    def base_path(self) -> str:
        return self._base_path

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

    def resolve_remote_path(self, path: str) -> str:
        clean = "/".join(PurePosixPath(path).parts)
        if self._base_path:
            base_clean = "/".join(
                part for part in PurePosixPath(self._base_path).parts if part not in {"", "."}
            )
            if not base_clean:
                return clean
            if clean.startswith(f"{base_clean}/") or clean == base_clean:
                return clean or base_clean
            if clean:
                return f"{base_clean}/{clean}"
            return base_clean
        return clean

    def download_workspace(self, workspace_paths, destination: str | Path) -> None:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        snapshot = [str(entry) for entry in workspace_paths]
        self.workspace_calls.append(snapshot)
        for entry in workspace_paths:
            candidate = PurePosixPath(entry or "")
            parts: list[str] = []
            for part in candidate.parts:
                if part in {"", "."}:
                    continue
                if part == "..":
                    raise ValueError("no '..' allowed")
                parts.append(part)
            if not parts:
                continue
            normalized = "/".join(parts)
            prefix = normalized + "/"
            matched = False
            for key, content in self._existing.items():
                key_path = "/".join(PurePosixPath(key).parts)
                if key_path == normalized or key_path.startswith(prefix):
                    matched = True
                    destination_path = root.joinpath(*PurePosixPath(key_path).parts)
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    destination_path.write_bytes(content)
            if not matched:
                raise GitHubFileNotFoundError(
                    f"missing {normalized}",
                    repository="repo",
                    path=normalized,
                    ref="main",
                )


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
        "from helpers import dataset_path\n"
        "from pathlib import Path\n"
        "print(Path(dataset_path()).read_text(encoding='utf-8').splitlines()[0])\n"
    )
    helper_code = "def dataset_path():\n    return 'sources/orders_seed.csv'\n"
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "scripts/helpers.py": helper_code.encode(),
            "sources/orders_seed.csv": b"order_id,customer_id\n1,C001\n",
        }
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
        "workspace_paths": ["scripts/", "sources/"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_honors_base_path_when_accessing_files() -> None:
    script_code = (
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    csv_path = Path(__file__).resolve().parents[3] / 'students' / 'student' / 'sources' / 'orders_seed.csv'\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "sources/orders_seed.csv": b"order_id,customer_id\n1,C001\n",
        },
        base_path="students/student",
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
        "workspace_paths": ["sources/"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_attempts_workspace_aliases_without_base_path() -> None:
    script_code = "print('ok')\n"
    files = _DummyFiles(
        {
            "students/student/scripts/m3_explorer.py": script_code.encode(),
            "students/student/sources/orders_seed.csv": b"order_id\n1\n",
        }
    )
    contract = {
        "script_path": "students/student/scripts/m3_explorer.py",
        "workspace_paths": ["sources/"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []
    assert files.workspace_calls == [
        ["sources/"],
        ["students/sources/"],
        ["students/student/sources/"],
    ]


def test_verify_script_allows_parent_directory_access() -> None:
    script_code = (
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    csv_path = Path('../sources/orders_seed.csv')\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "sources/orders_seed.csv": b"order_id,customer_id\n1,C001\n",
        },
        base_path="students/student",
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_reads_required_file_after_chdir() -> None:
    script_code = (
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        "def main():\n"
        "    os.chdir(Path(__file__).parent)\n"
        "    csv_path = Path('sources/orders_seed.csv')\n"
        "    if csv_path.exists():\n"
        "        raise RuntimeError('CSV should not exist locally')\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
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


def test_verify_script_reads_prefixed_required_file_after_chdir() -> None:
    script_code = (
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        "def main():\n"
        "    os.chdir(Path(__file__).parent)\n"
        "    csv_path = Path('sources/orders_seed.csv')\n"
        "    if csv_path.exists():\n"
        "        raise RuntimeError('CSV should not exist locally')\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "students/student/sources/orders_seed.csv": b"order_id,customer_id\\n1,C001\\n",
        },
        base_path="students/student",
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["students/student/sources/orders_seed.csv"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_handles_prefixed_dependency_without_base_path() -> None:
    script_code = (
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        "def main():\n"
        "    os.chdir(Path(__file__).parent)\n"
        "    csv_path = Path('sources/orders_seed.csv')\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "    try:\n"
        "        import pandas as pd\n"
        "    except Exception:\n"
        "        print('pandas not available')\n"
        "    else:\n"
        "        df = pd.read_csv(csv_path)\n"
        "        print(df.shape)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "students/student/sources/orders_seed.csv": b"order_id,customer_id\\n1,C001\\n",
        },
        base_path="",
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["students/student/sources/orders_seed.csv"],
        "workspace_paths": ["scripts/"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_handles_student_prefix_without_base_path() -> None:
    script_code = (
        "from pathlib import Path\n"
        "import os\n"
        "\n"
        "def main():\n"
        "    os.chdir(Path(__file__).parent)\n"
        "    csv_path = Path('sources/orders_seed.csv')\n"
        "    if csv_path.exists():\n"
        "        raise RuntimeError('CSV should not exist locally')\n"
        "    print(csv_path.read_text(encoding='utf-8').splitlines()[0])\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles(
        {
            "students/student/scripts/m3_explorer.py": script_code.encode(),
            "students/student/sources/orders_seed.csv": b"order_id,customer_id\n1,C001\n",
        },
        base_path="",
    )
    contract = {
        "script_path": "students/student/scripts/m3_explorer.py",
        "required_files": ["students/student/sources/orders_seed.csv"],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_reports_script_exception() -> None:
    script_code = "import nonexistent_module\n"
    files = _DummyFiles({"scripts/m3_explorer.py": script_code.encode()})
    contract = {"script_path": "scripts/m3_explorer.py"}

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is False
    assert len(feedback) == 1
    message = feedback[0]
    assert "Código de salida" in message
    assert "STDERR:" in message
    assert "ModuleNotFoundError" in message
    assert "No module named 'nonexistent_module'" in message


def test_verify_script_reports_dataframe_summary_mismatch() -> None:
    script_code = (
        "def main():\n"
        "    print('Shape: (1, 1)')\n"
        "    print(\"Columns: ['fake']\")\n"
        "    print('Head:')\n"
        "    print('solo texto')\n"
        "    print('Dtypes:')\n"
        "    print('dtype: object')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    files = _DummyFiles({"scripts/m3_explorer.py": script_code.encode()})
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "validations": [
            {
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
        ],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is False
    assert any("df.shape" in message for message in feedback)
    assert any("df.columns.tolist()" in message for message in feedback)
    assert any("df.head()" in message for message in feedback)
    assert any("df.dtypes" in message for message in feedback)
    assert any("Esperado: (3, 7)" in message for message in feedback)
    assert any("Obtenido: (1, 1)" in message for message in feedback)


def test_verify_script_accepts_valid_dataframe_summary() -> None:
    pytest.importorskip("pandas")

    script_code = (
        "import pandas as pd\n"
        "from helpers import dataset_path\n"
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    df = pd.read_csv(Path(dataset_path()))\n"
        "    print(f\"Shape: {df.shape}\")\n"
        "    print('Columns:', df.columns.tolist())\n"
        "    print('Head:')\n"
        "    print(df.head().to_string())\n"
        "    print('Dtypes:')\n"
        "    print(df.dtypes)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    helper_code = "def dataset_path():\n    return 'sources/orders_seed.csv'\n"
    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "scripts/helpers.py": helper_code.encode(),
            "sources/orders_seed.csv": Path('sources/orders_seed.csv').read_bytes(),
        }
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
        "workspace_paths": ["scripts/", "sources/"],
        "validations": [
            {
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
        ],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_accepts_dataframe_summary_with_df_prefix_format() -> None:
    script_code = (
        "def main():\n"
        "    print('df.shape = (3, 7)')\n"
        "    print(\"df.columns.tolist(): ['order_id', 'customer_id', 'product_id', 'order_date', 'status', 'quantity', 'unit_price']\")\n"
        "    print('df.head() ->')\n"
        "    print('   order_id customer_id product_id  order_date     status  quantity  unit_price')\n"
        "    print('0      1001        C001       P001  2024-01-05    Shipped         2       19.99')\n"
        "    print('1      1002        C002       P003  2024-01-06    Pending         1       49.50')\n"
        "    print('2      1003        C001       P002  2024-01-08  Cancelled         3       12.00')\n"
        "    print('df.dtypes =')\n"
        "    print('order_id int64')\n"
        "    print('customer_id object')\n"
        "    print('product_id object')\n"
        "    print('order_date object')\n"
        "    print('status object')\n"
        "    print('quantity int64')\n"
        "    print('unit_price float64')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    files = _DummyFiles({"scripts/m3_explorer.py": script_code.encode()})
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "validations": [
            {
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
        ],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []


def test_verify_script_accepts_dataframe_summary_with_label_variations() -> None:
    pytest.importorskip("pandas")

    script_code = (
        "import pandas as pd\n"
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    df = pd.read_csv(Path('sources/orders_seed.csv'))\n"
        "    print('Shape =', df.shape)\n"
        "    print('Columns =', df.columns.tolist())\n"
        "    print('Head:', df.head())\n"
        "    print('Dtypes:', df.dtypes)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    files = _DummyFiles(
        {
            "scripts/m3_explorer.py": script_code.encode(),
            "sources/orders_seed.csv": Path('sources/orders_seed.csv').read_bytes(),
        }
    )
    contract = {
        "script_path": "scripts/m3_explorer.py",
        "required_files": ["sources/orders_seed.csv"],
        "validations": [
            {
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
        ],
    }

    passed, feedback = backend_app.verify_script(files, contract)

    assert passed is True
    assert feedback == []
