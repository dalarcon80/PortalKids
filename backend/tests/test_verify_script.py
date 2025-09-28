from __future__ import annotations

from pathlib import Path

import pytest

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
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    df = pd.read_csv(Path('sources/orders_seed.csv'))\n"
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
