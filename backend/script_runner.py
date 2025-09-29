from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping


_CONFIG_ENV_VAR = "PORTALKIDS_SCRIPT_RUNNER_CONFIG"

_SITECUSTOMIZE_TEMPLATE = """
import base64
import builtins
import io
import json
import locale
import os
from pathlib import Path, PurePosixPath


_CONFIG_ENV = __CONFIG_ENV__
_raw_config = os.environ.pop(_CONFIG_ENV, None)
if _raw_config:
    _CONFIG = json.loads(_raw_config)
else:
    _CONFIG = None


def _load_client():
    try:
        from backend.github_client import GitHubClient  # type: ignore
    except ImportError:  # pragma: no cover - fallback for direct execution
        from github_client import GitHubClient  # type: ignore
    repository = _CONFIG.get("repository", "")
    branch = _CONFIG.get("branch", "") or None
    client = GitHubClient.from_settings()
    return client, repository, branch


if _CONFIG is None:
    _FILES = {}
    _REMOTE = {}
    _ANCHORS = []
    _DEFAULT_ENCODING = locale.getpreferredencoding(False) or "utf-8"
    _CLIENT_CACHE = None
else:
    _FILES = {
        key: base64.b64decode(value)
        for key, value in (_CONFIG.get("files") or {}).items()
    }
    _REMOTE = _CONFIG.get("remote_map") or {}
    _ANCHORS = [Path(item) for item in (_CONFIG.get("anchors") or [])]
    _DEFAULT_ENCODING = locale.getpreferredencoding(False) or "utf-8"
    _CLIENT_CACHE = None


def _unique(sequence):
    seen = set()
    for item in sequence:
        if item in seen:
            continue
        seen.add(item)
        yield item


def _normalize_candidates(target: Path):
    candidates = []
    try:
        resolved = target if target.is_absolute() else (Path.cwd() / target)
        resolved = resolved.resolve(strict=False)
    except Exception:
        resolved = (Path.cwd() / target).resolve(strict=False)

    for anchor in _ANCHORS:
        try:
            relative = resolved.relative_to(anchor.resolve(strict=False))
        except ValueError:
            continue
        relative_text = PurePosixPath(relative.as_posix()).as_posix()
        candidates.append(relative_text)

    raw_text = PurePosixPath(target).as_posix()
    candidates.append(raw_text)
    normalized_raw = raw_text.lstrip("./")
    if normalized_raw and normalized_raw != raw_text:
        candidates.append(normalized_raw)

    return list(_unique(candidates))


def _resolve_bytes(path_like):
    if _CONFIG is None:
        return None

    try:
        target = Path(path_like)
    except TypeError:
        return None

    keys = _normalize_candidates(target)
    for key in keys:
        if key in _FILES:
            return _FILES[key]

    for key in keys:
        remote_path = _REMOTE.get(key)
        if not remote_path:
            continue
        global _CLIENT_CACHE
        if _CLIENT_CACHE is None:
            try:
                _CLIENT_CACHE = _load_client()
            except Exception:
                _CLIENT_CACHE = ()
        if not _CLIENT_CACHE:
            continue
        client, repository, branch = _CLIENT_CACHE
        try:
            data = client.get_file_content(repository, remote_path, branch)
        except Exception:
            continue
        _FILES[key] = data
        return data
    return None


_ORIGINAL_OPEN = builtins.open


def _patched_open(file, mode="r", *args, **kwargs):
    if "w" in mode or "a" in mode or "+" in mode or "x" in mode:
        return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

    data = _resolve_bytes(file)
    if data is None:
        return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

    if "b" in mode:
        buffer = io.BytesIO(data)
        try:
            buffer.name = str(file)
        except Exception:
            pass
        return buffer

    encoding = kwargs.get("encoding") or _DEFAULT_ENCODING
    newline = kwargs.get("newline")
    text = data.decode(encoding)
    buffer = io.StringIO(text, newline=newline)
    try:
        buffer.name = str(file)
    except Exception:
        pass
    return buffer


def _patched_path_open(self, *args, **kwargs):
    return _patched_open(self, *args, **kwargs)


if _CONFIG is not None:
    builtins.open = _patched_open
    from pathlib import Path as _Path

    _Path.open = _patched_path_open  # type: ignore[assignment]
"""


_SITECUSTOMIZE_CODE = _SITECUSTOMIZE_TEMPLATE.replace("__CONFIG_ENV__", repr(_CONFIG_ENV_VAR))


def run_student_script(
    *,
    python_executable: str,
    script_path: Path,
    execution_root: Path,
    required_files: Mapping[str, bytes],
    remote_file_map: Mapping[str, str],
    anchors: Iterable[Path],
    repository: str,
    branch: str,
    timeout: int,
) -> subprocess.CompletedProcess:
    """Run a student script intercepting file access to required files."""

    config = {
        "files": {
            str(key): base64.b64encode(value).decode("ascii")
            for key, value in required_files.items()
        },
        "remote_map": dict(remote_file_map),
        "anchors": [str(Path(anchor)) for anchor in anchors],
        "repository": repository,
        "branch": branch,
    }

    sitecustomize_dir = Path(execution_root) / "_runner_helpers"
    sitecustomize_dir.mkdir(parents=True, exist_ok=True)
    (sitecustomize_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE_CODE, encoding="utf-8")

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join([str(sitecustomize_dir), existing_pythonpath])
    else:
        env["PYTHONPATH"] = str(sitecustomize_dir)

    env[_CONFIG_ENV_VAR] = json.dumps(config)

    return subprocess.run(
        [python_executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(execution_root),
        timeout=timeout,
        env=env,
    )
