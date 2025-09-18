"""Utility to migrate mission presentation HTML into mission contracts."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
CONTRACTS_PATH = ROOT / "backend" / "missions_contracts.json"


def extract_main_inner(html_text: str) -> str:
    """Return the inner HTML of the first <main> tag found."""

    lower = html_text.lower()
    start_tag = lower.find("<main")
    if start_tag == -1:
        raise ValueError("No <main> tag found")
    start = lower.find(">", start_tag)
    if start == -1:
        raise ValueError("Malformed <main> tag")
    end = lower.find("</main>", start)
    if end == -1:
        raise ValueError("No closing </main> tag found")
    inner = html_text[start + 1 : end]
    return inner.strip()


def build_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in FRONTEND_DIR.glob("m*.html"):
        mission_id = path.stem
        html_text = path.read_text(encoding="utf-8")
        inner = extract_main_inner(html_text)
        mapping[mission_id] = inner
    return mapping


def main() -> None:
    mapping = build_mapping()
    data = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))
    for mission_id, html in mapping.items():
        contract = data.get(mission_id)
        if not isinstance(contract, dict):
            continue
        contract["display_html"] = html
    CONTRACTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
