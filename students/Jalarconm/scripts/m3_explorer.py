from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
csv_path = BASE_DIR / "sources" / "orders_seed.csv"


def main() -> None:
    print(f"Directorio de trabajo actual: {Path.cwd()}")
    print(f"Ruta del CSV: {csv_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró {csv_path}")

    df = pd.read_csv(csv_path)
    print(df.head())


if __name__ == "__main__":
    main()
