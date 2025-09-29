import ast
import base64
import binascii
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import bcrypt

try:  # pragma: no cover - optional dependency
    import pymysql  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    class _MissingPyMySQLError(Exception):
        """Fallback error used when pymysql is not installed."""

    class _MissingPyMySQLErrors:
        IntegrityError = _MissingPyMySQLError

    class _MissingPyMySQLModule:
        err = _MissingPyMySQLErrors()

    pymysql = _MissingPyMySQLModule()  # type: ignore[assignment]
from flask import Flask, jsonify, request, send_from_directory

try:  # pragma: no cover - optional dependency
    from flask_cors import CORS
except ModuleNotFoundError:  # pragma: no cover - simple fallback
    def CORS(app, *args, **kwargs):
        return app

try:  # pragma: no cover - fallback for direct execution
    from .github_client import (
        GitHubClient,
        GitHubConfigurationError,
        GitHubDownloadError,
        GitHubFileNotFoundError,
        RepositoryFileAccessor,
        determine_student_repositories,
        select_repository_for_contract,
        _matches_operaciones,
        _matches_ventas,
    )
except ImportError:  # pragma: no cover - allow "python backend/app.py"
    from github_client import (  # type: ignore
        GitHubClient,
        GitHubConfigurationError,
        GitHubDownloadError,
        GitHubFileNotFoundError,
        RepositoryFileAccessor,
        determine_student_repositories,
        select_repository_for_contract,
        _matches_operaciones,
        _matches_ventas,
    )

try:  # pragma: no cover - fallback for direct execution
    from .llm import (
        APIConnectionError,
        APIError,
        LLMConfigurationError,
        LLMEvaluationError,
        OpenAI,
        OpenAILLMClient,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - allow "python backend/app.py"
    from llm import (  # type: ignore
        APIConnectionError,
        APIError,
        LLMConfigurationError,
        LLMEvaluationError,
        OpenAI,
        OpenAILLMClient,
        RateLimitError,
    )

try:  # pragma: no cover - fallback for direct execution
    from .script_runner import run_student_script
except ImportError:  # pragma: no cover - allow "python backend/app.py"
    from script_runner import run_student_script  # type: ignore

try:  # pragma: no cover - optional dependency
    import requests  # type: ignore
    _REQUESTS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _REQUESTS_AVAILABLE = False

    class _MissingRequestsException(RuntimeError):
        """Raised when the optional 'requests' dependency is unavailable."""

    class _MissingRequestsSession:
        def __init__(self, *args, **kwargs) -> None:
            raise _MissingRequestsException(
                "La librería opcional 'requests' es necesaria para validar credenciales de GitHub."
            )

    class _MissingRequestsModule:
        RequestException = _MissingRequestsException

        def Session(self, *args, **kwargs):  # type: ignore[override]
            return _MissingRequestsSession(*args, **kwargs)

    requests = _MissingRequestsModule()  # type: ignore[assignment]


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_PATH = os.path.join(BASE_DIR, "missions_contracts.json")
FRONTEND_DIR = Path(BASE_DIR).resolve().parents[1] / "frontend"
SECRET_KEY_FILE = Path(BASE_DIR) / ".flask_secret_key"

logger = logging.getLogger(__name__)

SESSION_DURATION_SECONDS = 60 * 60 * 8
DEFAULT_ADMIN_SLUGS = {"dalarcon80"}

ROLE_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,63})$")

DEFAULT_ROLE_SEEDS = [
    {
        "slug": "admin",
        "name": "admin",
        "metadata": {
            "is_admin": True,
            "aliases": [
                "administrador",
                "administradora",
                "administrator",
                "admin",
            ],
        },
    },
    {"slug": "learner", "name": "learner", "metadata": {}},
    {"slug": "explorer", "name": "explorer", "metadata": {}},
    {"slug": "ventas", "name": "Ventas", "metadata": {}},
    {"slug": "operaciones", "name": "Operaciones", "metadata": {}},
]


SERVICE_SETTINGS_SECRET_FILE = Path(BASE_DIR) / ".service_settings_key"

SERVICE_SETTINGS_DEFINITIONS = {
    "github_token": {
        "label": "Token personal de GitHub",
        "category": "github",
        "help_text": (
            "Token con permisos de lectura (scope repo). Formato esperado: ghp_xxxxxxxxx."  # noqa: E501
        ),
        "placeholder": "ghp_xxxxxxxxxxxxxxxxx",
        "secret": True,
    },
    "github_api_url": {
        "label": "API de GitHub",
        "category": "github",
        "help_text": (
            "URL base para la API de GitHub. Usa https://api.github.com salvo que tengas Enterprise."  # noqa: E501
        ),
        "placeholder": "https://api.github.com",
        "default": "https://api.github.com",
        "secret": False,
    },
    "github_timeout": {
        "label": "Timeout de GitHub (segundos)",
        "category": "github",
        "help_text": "Tiempo máximo en segundos para cada solicitud. Ejemplo: 10.",
        "placeholder": "10",
        "secret": False,
    },
    "openai_api_key": {
        "label": "API Key de OpenAI",
        "category": "openai",
        "help_text": (
            "Clave privada de OpenAI (prefijo sk-). Nunca la compartas fuera del panel administrativo."  # noqa: E501
        ),
        "placeholder": "sk-xxxxxxxxxxxxxxxx",
        "secret": True,
    },
    "openai_model": {
        "label": "Modelo de OpenAI",
        "category": "openai",
        "help_text": "Nombre del modelo de chat a utilizar. Ejemplo: gpt-3.5-turbo.",
        "placeholder": "gpt-3.5-turbo",
        "default": "gpt-3.5-turbo",
        "secret": False,
    },
    "openai_timeout": {
        "label": "Timeout de OpenAI (segundos)",
        "category": "openai",
        "help_text": "Tiempo máximo en segundos para la petición al modelo. Ejemplo: 30.",
        "placeholder": "30",
        "secret": False,
    },
}


def _use_sqlite_backend() -> bool:
    required_keys = ["DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"]
    return any(not os.environ.get(key) for key in required_keys)


def _normalize_setting_key(key: str) -> str:
    return (key or "").strip().lower()


def _get_setting_definition(key: str) -> Optional[dict]:
    normalized = _normalize_setting_key(key)
    return SERVICE_SETTINGS_DEFINITIONS.get(normalized)


_SERVICE_SETTINGS_SECRET_CACHE: Optional[bytes] = None


def _load_service_settings_secret() -> bytes:
    global _SERVICE_SETTINGS_SECRET_CACHE
    if _SERVICE_SETTINGS_SECRET_CACHE:
        return _SERVICE_SETTINGS_SECRET_CACHE

    try:
        if SERVICE_SETTINGS_SECRET_FILE.exists():
            encoded = SERVICE_SETTINGS_SECRET_FILE.read_text(encoding="utf-8").strip()
            if encoded:
                try:
                    secret_bytes = base64.urlsafe_b64decode(encoded.encode("utf-8"))
                except (ValueError, binascii.Error):  # pragma: no cover - defensive
                    secret_bytes = base64.urlsafe_b64decode(encoded + "==")
                _SERVICE_SETTINGS_SECRET_CACHE = secret_bytes
                return secret_bytes
    except (OSError, ValueError, binascii.Error) as exc:
        logger.warning(
            "Failed to read service settings secret key from %s: %s",
            SERVICE_SETTINGS_SECRET_FILE,
            exc,
        )

    secret_bytes = secrets.token_bytes(32)
    encoded_secret = base64.urlsafe_b64encode(secret_bytes).decode("utf-8")
    try:
        SERVICE_SETTINGS_SECRET_FILE.write_text(encoded_secret, encoding="utf-8")
        try:
            os.chmod(SERVICE_SETTINGS_SECRET_FILE, 0o600)
        except OSError:  # pragma: no cover - best effort on non-POSIX
            pass
    except OSError as exc:
        logger.warning(
            "Generated ephemeral service settings secret key; could not persist to %s: %s",
            SERVICE_SETTINGS_SECRET_FILE,
            exc,
        )
    _SERVICE_SETTINGS_SECRET_CACHE = secret_bytes
    return secret_bytes


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    key_length = len(key)
    if key_length == 0:
        raise ValueError("Encryption key must not be empty")
    return bytes(b ^ key[i % key_length] for i, b in enumerate(data))


def _encrypt_setting_value(value: str) -> str:
    key = _load_service_settings_secret()
    data = value.encode("utf-8")
    cipher = _xor_bytes(data, key)
    return base64.urlsafe_b64encode(cipher).decode("utf-8")


def _decrypt_setting_value(value: str) -> str:
    if not value:
        return ""
    key = _load_service_settings_secret()
    try:
        cipher = base64.urlsafe_b64decode(value.encode("utf-8"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Encrypted value has invalid format") from exc
    plain = _xor_bytes(cipher, key)
    return plain.decode("utf-8")


def _fetch_service_setting_row(cur, key: str):
    cur.execute(
        "SELECT setting_key, value, is_secret FROM service_settings WHERE setting_key = %s",
        (key,),
    )
    return cur.fetchone()


def get_service_setting(key: str) -> Optional[str]:
    definition = _get_setting_definition(key)
    if not definition:
        raise KeyError(f"Unknown service setting: {key}")
    normalized = _normalize_setting_key(key)
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                row = _fetch_service_setting_row(cur, normalized)
    except Exception as exc:
        logger.error("Failed to read service setting %s: %s", normalized, exc)
        return None
    if not row:
        return None
    if isinstance(row, Mapping):
        value = row.get("value")
    else:
        value = None
        try:  # pragma: no cover - defensive fallback
            value = row["value"]  # type: ignore[index]
        except Exception:
            try:
                value = row[1]  # type: ignore[index]
            except Exception:
                value = None
    if value is None:
        return None
    if definition.get("secret"):
        try:
            return _decrypt_setting_value(str(value))
        except ValueError as exc:
            logger.warning("Could not decrypt service setting %s: %s", normalized, exc)
            return None
    return str(value)


def load_service_settings(keys: Iterable[str]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    for key in keys:
        normalized = _normalize_setting_key(key)
        try:
            result[normalized] = get_service_setting(normalized)
        except KeyError:
            result[normalized] = None
    return result


def _validate_numeric_timeout(value: str, setting_key: str) -> None:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"El campo '{setting_key}' debe ser un número entero o decimal en segundos."
        ) from exc
    if timeout <= 0:
        raise ValueError(f"El campo '{setting_key}' debe ser mayor a cero segundos.")


def _validate_service_setting_input(key: str, value: Optional[str]) -> Optional[str]:
    definition = _get_setting_definition(key)
    if not definition:
        raise KeyError(f"Unknown service setting: {key}")
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    normalized = _normalize_setting_key(key)
    if normalized in {"github_timeout", "openai_timeout"}:
        _validate_numeric_timeout(cleaned, normalized)
    return cleaned


def _delete_service_setting(cur, key: str) -> None:
    cur.execute("DELETE FROM service_settings WHERE setting_key = %s", (key,))


def _store_service_setting(cur, key: str, value: str, is_secret: bool) -> None:
    if getattr(cur, "__class__", None).__name__ == "SQLiteCursorWrapper":
        cur.execute(
            """
            INSERT INTO service_settings (setting_key, value, is_secret)
            VALUES (%s, %s, %s)
            ON CONFLICT(setting_key)
            DO UPDATE SET value = excluded.value, is_secret = excluded.is_secret,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (key, value, 1 if is_secret else 0),
        )
    else:
        cur.execute(
            """
            INSERT INTO service_settings (setting_key, value, is_secret)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE value = VALUES(value),
                                    is_secret = VALUES(is_secret),
                                    updated_at = CURRENT_TIMESTAMP
            """,
            (key, value, 1 if is_secret else 0),
        )


def set_service_setting(key: str, value: Optional[str]) -> None:
    definition = _get_setting_definition(key)
    if not definition:
        raise KeyError(f"Unknown service setting: {key}")
    normalized = _normalize_setting_key(key)
    cleaned = _validate_service_setting_input(normalized, value)
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if cleaned is None:
                    _delete_service_setting(cur, normalized)
                else:
                    stored_value = (
                        _encrypt_setting_value(cleaned)
                        if definition.get("secret")
                        else cleaned
                    )
                    _store_service_setting(cur, normalized, stored_value, bool(definition.get("secret")))
    except Exception as exc:
        raise RuntimeError(f"Failed to persist service setting {normalized}: {exc}") from exc


class IntegrationValidationError(ValueError):
    """Raised when an external integration fails validation."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def _effective_setting_value(key: str, value: Optional[str]) -> Optional[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    elif value is not None:
        return str(value)
    definition = _get_setting_definition(key)
    if definition:
        default_value = definition.get("default")
        if isinstance(default_value, str):
            default_clean = default_value.strip()
            if default_clean:
                return default_clean
    return None


def _build_effective_settings(settings: Mapping[str, Optional[str]]) -> Dict[str, Optional[str]]:
    effective: Dict[str, Optional[str]] = {}
    for key in SERVICE_SETTINGS_DEFINITIONS:
        effective[key] = _effective_setting_value(key, settings.get(key))
    return effective


def _validate_github_credentials(settings: Mapping[str, Optional[str]]) -> None:
    token = settings.get("github_token")
    if not token:
        return
    if not _REQUESTS_AVAILABLE:
        raise IntegrationValidationError(
            "La librería opcional 'requests' es necesaria para validar las credenciales de GitHub. Instálala e intenta nuevamente.",
            field="github_token",
        )
    api_url = (settings.get("github_api_url") or "https://api.github.com").rstrip("/")
    timeout_raw = settings.get("github_timeout")
    timeout = 10.0
    if timeout_raw not in (None, ""):
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 10.0
    session = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": os.environ.get("GITHUB_USER_AGENT", "PortalKidsVerifier/1.0"),
    }
    try:
        session.headers.update(headers)  # type: ignore[call-arg]
    except AttributeError:
        session.headers = headers  # type: ignore[assignment]
    url = f"{api_url}/user/repos"
    try:
        response = session.get(url, params={"per_page": 1}, timeout=timeout)
    except requests.RequestException as exc:
        raise IntegrationValidationError(
            f"No se pudo conectar con GitHub usando el token proporcionado: {exc}",
            field="github_token",
        ) from exc
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - best effort
            pass
    status_code = getattr(response, "status_code", 0)
    if status_code >= 400:
        try:
            payload = response.json()
            details = payload.get("message") or response.text
        except ValueError:
            details = response.text
        details = (details or "").strip() or "Error desconocido"
        if status_code == 401:
            reason = "GitHub rechazó el token. Verifica que sea válido y tenga permisos de lectura."
        elif status_code == 403:
            reason = "GitHub denegó el acceso con el token proporcionado. Revisa los permisos y vigencia."
        else:
            reason = "GitHub devolvió un error al validar el token."
        raise IntegrationValidationError(
            f"{reason} Detalles: {details} (HTTP {status_code}).",
            field="github_token",
        )


def _validate_openai_credentials(settings: Mapping[str, Optional[str]]) -> None:
    api_key = settings.get("openai_api_key")
    if not api_key:
        return
    timeout_raw = settings.get("openai_timeout")
    timeout: float | None = None
    if timeout_raw not in (None, ""):
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = None
    try:
        client = OpenAI(api_key=api_key)
        if timeout is not None:
            with_options = getattr(client, "with_options", None)
            if callable(with_options):
                client = with_options(timeout=timeout)
        client.models.list()
    except RateLimitError as exc:
        raise IntegrationValidationError(
            "OpenAI reportó un límite de uso excedido. Espera unos minutos o usa otra clave.",
            field="openai_api_key",
        ) from exc
    except APIConnectionError as exc:
        raise IntegrationValidationError(
            "No se pudo conectar con OpenAI para validar la clave. Revisa tu conexión o intenta nuevamente.",
            field="openai_api_key",
        ) from exc
    except APIError as exc:
        message = getattr(exc, "message", "") or str(exc) or "Error desconocido"
        message = str(message).strip()
        raise IntegrationValidationError(
            "OpenAI rechazó la clave proporcionada. Verifica el valor ingresado. "
            f"Detalles: {message}.",
            field="openai_api_key",
        ) from exc
    except Exception as exc:
        raise IntegrationValidationError(
            "No se pudo validar la clave de OpenAI. Revisa los datos ingresados y vuelve a intentarlo.",
            field="openai_api_key",
        ) from exc


def _build_admin_setting_payload() -> List[dict]:
    payload: List[dict] = []
    for key, definition in SERVICE_SETTINGS_DEFINITIONS.items():
        try:
            stored_value = get_service_setting(key)
        except KeyError:
            stored_value = None
        entry = {
            "key": key,
            "label": definition.get("label", key),
            "category": definition.get("category", "general"),
            "help_text": definition.get("help_text", ""),
            "placeholder": definition.get("placeholder", ""),
            "is_secret": bool(definition.get("secret")),
            "configured": bool(stored_value),
        }
        if definition.get("secret"):
            entry["value"] = ""
        else:
            entry["value"] = stored_value or ""
        default_value = definition.get("default")
        if default_value:
            entry["default"] = default_value
        payload.append(entry)
    payload.sort(key=lambda item: (item.get("category", ""), item.get("label", "")))
    return payload


def list_service_settings_for_admin() -> List[dict]:
    return _build_admin_setting_payload()


def _import_pymysql():
    try:
        import pymysql  # type: ignore
        from pymysql.cursors import DictCursor  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "El backend de MySQL requiere el paquete 'pymysql'. "
            "Instálalo o configura las variables de entorno para usar SQLite."
        ) from exc
    return pymysql, DictCursor


class SQLiteCursorWrapper:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "SQLiteCursorWrapper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _normalize_query(query: str) -> str:
        return query.replace("%s", "?")

    def execute(self, query: str, params: Optional[Iterable] = None):
        normalized_query = self._normalize_query(query)
        if params is None:
            params = []
        self._cursor.execute(normalized_query, tuple(params))
        return self

    def executemany(self, query: str, seq_of_parameters):
        normalized_query = self._normalize_query(query)
        self._cursor.executemany(normalized_query, seq_of_parameters)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        return [dict(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def close(self) -> None:
        try:
            self._cursor.close()
        except Exception:  # pragma: no cover - defensive
            pass


class SQLiteConnectionWrapper:
    is_sqlite = True

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> "SQLiteConnectionWrapper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self.close()

    def cursor(self) -> SQLiteCursorWrapper:
        return SQLiteCursorWrapper(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        try:
            self._connection.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def __getattr__(self, item):  # pragma: no cover - delegation helper
        return getattr(self._connection, item)


class PasswordValidationError(ValueError):
    """Raised when the provided password cannot be processed."""


class PasswordHashingError(RuntimeError):
    """Raised when hashing a password fails unexpectedly."""


class PasswordVerificationError(RuntimeError):
    """Raised when verifying a stored password hash fails."""


def get_db_connection():
    if _use_sqlite_backend():
        sqlite_path = os.path.join(BASE_DIR, "database.db")
        connection = sqlite3.connect(sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:  # pragma: no cover - best-effort enforcement
            pass
        return SQLiteConnectionWrapper(connection)

    pymysql, DictCursor = _import_pymysql()
    db_config = {
        "database": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "host": os.environ.get("DB_HOST"),
        "cursorclass": DictCursor,
        "charset": "utf8mb4",
        "autocommit": True,
    }

    instance_connection = os.environ.get("DB_INSTANCE_CONNECTION_NAME")
    if instance_connection:
        socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
        db_config["unix_socket"] = os.path.join(socket_dir, instance_connection)

    port_value = os.environ.get("DB_PORT")
    if port_value:
        db_config["port"] = int(port_value)

    connect_timeout = os.environ.get("DB_CONNECT_TIMEOUT")
    if connect_timeout:
        db_config["connect_timeout"] = int(connect_timeout)

    return pymysql.connect(**db_config)


def _mark_default_admins(cursor) -> None:
    for slug in DEFAULT_ADMIN_SLUGS:
        try:
            cursor.execute(
                "UPDATE students SET is_admin = 1 WHERE slug = %s",
                (slug,),
            )
        except Exception:  # pragma: no cover - defensive best-effort update
            continue


def _seed_default_roles(cursor) -> None:
    for entry in DEFAULT_ROLE_SEEDS:
        slug = (entry.get("slug") or "").strip()
        name = (entry.get("name") or slug).strip() or slug
        metadata = entry.get("metadata") or {}
        if not slug:
            continue
        try:
            cursor.execute("SELECT slug FROM roles WHERE slug = %s", (slug,))
            row = cursor.fetchone()
        except Exception:  # pragma: no cover - defensive fallback
            continue
        if row:
            continue
        metadata_json = "{}"
        try:
            metadata_json = json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError):
            metadata_json = "{}"
        try:
            cursor.execute(
                "INSERT INTO roles (slug, name, metadata_json) VALUES (%s, %s, %s)",
                (slug, name, metadata_json),
            )
        except Exception:  # pragma: no cover - best-effort seed
            continue


def init_db():
    if _use_sqlite_backend():
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                def ensure_column(table: str, column: str, definition: str) -> None:
                    cur.execute(f"PRAGMA table_info({table})")
                    existing = {row["name"] for row in cur.fetchall()}
                    if column not in existing:
                        cur.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS students (
                        slug TEXT NOT NULL PRIMARY KEY,
                        name TEXT,
                        role TEXT,
                        workdir TEXT,
                        email TEXT,
                        password_hash TEXT,
                        is_admin INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS completed_missions (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        student_slug TEXT NOT NULL,
                        mission_id TEXT NOT NULL,
                        completed_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                        UNIQUE (student_slug, mission_id),
                        FOREIGN KEY (student_slug) REFERENCES students(slug) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT NOT NULL PRIMARY KEY,
                        student_slug TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY (student_slug) REFERENCES students(slug) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_student_slug ON sessions(student_slug)"
                )
                ensure_column(
                    "students", "created_at", "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)"
                )
                ensure_column("students", "password_hash", "TEXT")
                ensure_column("students", "is_admin", "INTEGER NOT NULL DEFAULT 0")
                ensure_column("students", "email", "TEXT")
                ensure_column("students", "workdir", "TEXT")
                ensure_column("students", "role", "TEXT")
                ensure_column("students", "name", "TEXT")
                _mark_default_admins(cur)
                ensure_column(
                    "completed_missions",
                    "completed_at",
                    "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
                )
                ensure_column("completed_missions", "mission_id", "TEXT")
                ensure_column("completed_missions", "student_slug", "TEXT")
                ensure_column("sessions", "created_at", "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
                ensure_column("sessions", "student_slug", "TEXT")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_student_mission_sqlite "
                    "ON completed_missions(student_slug, mission_id)"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS missions (
                        mission_id TEXT NOT NULL PRIMARY KEY,
                        title TEXT,
                        roles TEXT,
                        content_json TEXT,
                        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                    )
                    """
                )
                ensure_column("missions", "mission_id", "TEXT NOT NULL")
                ensure_column("missions", "title", "TEXT")
                ensure_column("missions", "roles", "TEXT")
                ensure_column("missions", "content_json", "TEXT")
                ensure_column(
                    "missions",
                    "updated_at",
                    "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS roles (
                        slug TEXT NOT NULL PRIMARY KEY,
                        name TEXT NOT NULL,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                    )
                    """
                )
                ensure_column("roles", "slug", "TEXT NOT NULL")
                ensure_column("roles", "name", "TEXT NOT NULL")
                ensure_column("roles", "metadata_json", "TEXT")
                ensure_column(
                    "roles",
                    "created_at",
                    "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
                )
                ensure_column(
                    "roles",
                    "updated_at",
                    "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
                )
                _seed_default_roles(cur)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS service_settings (
                        setting_key TEXT NOT NULL PRIMARY KEY,
                        value TEXT,
                        is_secret INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                    )
                    """
                )
                ensure_column("service_settings", "setting_key", "TEXT NOT NULL")
                ensure_column("service_settings", "value", "TEXT")
                ensure_column(
                    "service_settings",
                    "is_secret",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                ensure_column(
                    "service_settings",
                    "updated_at",
                    "TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
                )
        return

    db_name = os.environ.get("DB_NAME")
    if not db_name:
        raise RuntimeError("DB_NAME must be configured before initializing the database.")

    def ensure_column(cur, table: str, column: str, definition: str) -> None:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            (db_name, table, column),
        )
        if cur.fetchone():
            cur.execute(f"ALTER TABLE {table} MODIFY COLUMN {column} {definition}")
        else:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def ensure_primary_key(cur, table: str, columns: List[str]) -> None:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION
            """,
            (db_name, table),
        )
        existing = [row["COLUMN_NAME"] for row in cur.fetchall()]
        if existing != columns:
            if existing:
                cur.execute(f"ALTER TABLE {table} DROP PRIMARY KEY")
            cols_formatted = ", ".join(columns)
            cur.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({cols_formatted})")

    def ensure_unique_index(cur, table: str, index: str, columns: List[str]) -> None:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND INDEX_NAME = %s
            ORDER BY SEQ_IN_INDEX
            """,
            (db_name, table, index),
        )
        existing = [row["COLUMN_NAME"] for row in cur.fetchall()]
        if existing != columns:
            if existing:
                cur.execute(f"ALTER TABLE {table} DROP INDEX {index}")
            cols_formatted = ", ".join(columns)
            cur.execute(
                f"ALTER TABLE {table} ADD UNIQUE INDEX {index} ({cols_formatted})"
            )

    def ensure_foreign_key(
        cur,
        table: str,
        constraint: str,
        column: str,
        ref_table: str,
        ref_column: str,
        on_delete: str,
    ) -> None:
        cur.execute(
            """
            SELECT rc.CONSTRAINT_NAME, kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_NAME,
                   kcu.REFERENCED_COLUMN_NAME
            FROM information_schema.REFERENTIAL_CONSTRAINTS rc
            JOIN information_schema.KEY_COLUMN_USAGE kcu
              ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
            WHERE rc.CONSTRAINT_SCHEMA = %s
              AND rc.TABLE_NAME = %s
              AND rc.CONSTRAINT_NAME = %s
            """,
            (db_name, table, constraint),
        )
        row = cur.fetchone()
        if not row or (
            row["COLUMN_NAME"] != column
            or row["REFERENCED_TABLE_NAME"] != ref_table
            or row["REFERENCED_COLUMN_NAME"] != ref_column
        ):
            if row:
                cur.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {constraint}")
            cur.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY ({column}) "
                f"REFERENCES {ref_table}({ref_column}) ON DELETE {on_delete}"
            )

    def ensure_table_options(cur, table: str) -> None:
        cur.execute(
            """
            SELECT ENGINE, TABLE_COLLATION
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            """,
            (db_name, table),
        )
        row = cur.fetchone()
        if row and row.get("ENGINE", "").lower() != "innodb":
            cur.execute(f"ALTER TABLE {table} ENGINE=InnoDB")
        collation = (row or {}).get("TABLE_COLLATION")
        if not collation or not collation.lower().startswith("utf8mb4"):
            cur.execute(f"ALTER TABLE {table} CONVERT TO CHARACTER SET utf8mb4")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS students (
                    slug VARCHAR(255) NOT NULL PRIMARY KEY,
                    name VARCHAR(255),
                    role VARCHAR(100),
                    workdir VARCHAR(255),
                    email VARCHAR(255),
                    password_hash VARCHAR(255),
                    is_admin TINYINT(1) NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "students")
            ensure_column(cur, "students", "slug", "VARCHAR(255) NOT NULL")
            ensure_column(cur, "students", "name", "VARCHAR(255)")
            ensure_column(cur, "students", "role", "VARCHAR(100)")
            ensure_column(cur, "students", "workdir", "VARCHAR(255)")
            ensure_column(cur, "students", "email", "VARCHAR(255)")
            ensure_column(cur, "students", "password_hash", "VARCHAR(255)")
            ensure_column(
                cur,
                "students",
                "is_admin",
                "TINYINT(1) NOT NULL DEFAULT 0",
            )
            ensure_column(
                cur,
                "students",
                "created_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "students", ["slug"])
            _mark_default_admins(cur)

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_missions (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    student_slug VARCHAR(255) NOT NULL,
                    mission_id VARCHAR(255) NOT NULL,
                    completed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uniq_student_mission (student_slug, mission_id),
                    CONSTRAINT fk_completed_student
                        FOREIGN KEY (student_slug)
                        REFERENCES students(slug)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "completed_missions")
            ensure_column(cur, "completed_missions", "id", "BIGINT NOT NULL AUTO_INCREMENT")
            ensure_column(
                cur, "completed_missions", "student_slug", "VARCHAR(255) NOT NULL"
            )
            ensure_column(
                cur, "completed_missions", "mission_id", "VARCHAR(255) NOT NULL"
            )
            ensure_column(
                cur,
                "completed_missions",
                "completed_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "completed_missions", ["id"])
            ensure_unique_index(
                cur, "completed_missions", "uniq_student_mission", ["student_slug", "mission_id"]
            )
            ensure_foreign_key(
                cur,
                "completed_missions",
                "fk_completed_student",
                "student_slug",
                "students",
                "slug",
                "CASCADE",
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token VARCHAR(255) NOT NULL,
                    student_slug VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (token),
                    KEY idx_sessions_student_slug (student_slug),
                    CONSTRAINT fk_sessions_student
                        FOREIGN KEY (student_slug)
                        REFERENCES students(slug)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "sessions")
            ensure_column(cur, "sessions", "token", "VARCHAR(255) NOT NULL")
            ensure_column(cur, "sessions", "student_slug", "VARCHAR(255) NOT NULL")
            ensure_column(
                cur,
                "sessions",
                "created_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "sessions", ["token"])
            ensure_foreign_key(
                cur,
                "sessions",
                "fk_sessions_student",
                "student_slug",
                "students",
                "slug",
                "CASCADE",
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id VARCHAR(255) NOT NULL,
                    title VARCHAR(255),
                    roles TEXT,
                    content_json LONGTEXT,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (mission_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "missions")
            ensure_column(cur, "missions", "mission_id", "VARCHAR(255) NOT NULL")
            ensure_column(cur, "missions", "title", "VARCHAR(255)")
            ensure_column(cur, "missions", "roles", "TEXT")
            ensure_column(cur, "missions", "content_json", "LONGTEXT")
            ensure_column(
                cur,
                "missions",
                "updated_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "missions", ["mission_id"])

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    slug VARCHAR(100) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    metadata_json LONGTEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (slug)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "roles")
            ensure_column(cur, "roles", "slug", "VARCHAR(100) NOT NULL")
            ensure_column(cur, "roles", "name", "VARCHAR(255) NOT NULL")
            ensure_column(cur, "roles", "metadata_json", "LONGTEXT")
            ensure_column(
                cur,
                "roles",
                "created_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
            ensure_column(
                cur,
                "roles",
                "updated_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "roles", ["slug"])
            _seed_default_roles(cur)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS service_settings (
                    setting_key VARCHAR(150) NOT NULL,
                    value LONGTEXT,
                    is_secret TINYINT(1) NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (setting_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            ensure_table_options(cur, "service_settings")
            ensure_column(
                cur,
                "service_settings",
                "setting_key",
                "VARCHAR(150) NOT NULL",
            )
            ensure_column(cur, "service_settings", "value", "LONGTEXT")
            ensure_column(
                cur,
                "service_settings",
                "is_secret",
                "TINYINT(1) NOT NULL DEFAULT 0",
            )
            ensure_column(
                cur,
                "service_settings",
                "updated_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
            )


def hash_password(raw_password):
    """Hash a password using bcrypt returning the hash as text."""

    if not isinstance(raw_password, str):
        raw_password = str(raw_password or "")
    if not raw_password.strip():
        raise PasswordValidationError("La contraseña no puede estar vacía.")
    try:
        password_bytes = raw_password.encode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        raise PasswordValidationError("Formato de contraseña inválido.") from exc
    try:
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    except (ValueError, TypeError) as exc:
        raise PasswordHashingError("No se pudo procesar la contraseña.") from exc
    if isinstance(hashed, bytes):
        hashed = hashed.decode("utf-8")
    return hashed


def verify_password(raw_password, stored_hash):
    """Return True if the password matches the stored hash."""

    if not isinstance(raw_password, str):
        raw_password = str(raw_password or "")
    if not raw_password.strip():
        raise PasswordValidationError("Debes ingresar tu contraseña.")
    try:
        password_bytes = raw_password.encode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        raise PasswordValidationError("Formato de contraseña inválido.") from exc
    if not stored_hash:
        return False
    if isinstance(stored_hash, str):
        stored_hash_bytes = stored_hash.encode("utf-8")
    elif isinstance(stored_hash, bytes):
        stored_hash_bytes = stored_hash
    else:
        stored_hash_bytes = str(stored_hash).encode("utf-8")
    try:
        return bcrypt.checkpw(password_bytes, stored_hash_bytes)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PasswordVerificationError("No se pudo verificar la contraseña.") from exc


def _normalize_roles_input(raw_roles) -> List[str]:
    if raw_roles is None:
        return []
    if isinstance(raw_roles, (list, tuple, set)):
        result: List[str] = []
        for item in raw_roles:
            if isinstance(item, str):
                candidate = item.strip()
            else:
                candidate = str(item).strip()
            if candidate:
                result.append(candidate)
        return result
    if isinstance(raw_roles, str):
        text = raw_roles.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [part.strip() for part in text.split(",") if part.strip()]
        return _normalize_roles_input(decoded)
    return []


def _extract_main_inner(html_text: str) -> str:
    """Return the inner HTML of the first <main> element.

    The mission HTML files are simple static documents, so a small parser is
    enough and avoids pulling an additional dependency just for this task.
    """

    lowered = html_text.lower()
    start_tag = lowered.find("<main")
    if start_tag == -1:
        return ""
    start = lowered.find(">", start_tag)
    if start == -1:
        return ""
    end = lowered.find("</main>", start)
    if end == -1:
        return ""
    return html_text[start + 1 : end].strip()


@lru_cache(maxsize=1)
def _load_frontend_presentations() -> dict[str, str]:
    """Return a mapping of mission_id -> HTML snippet extracted from frontend."""

    presentations: dict[str, str] = {}
    if not FRONTEND_DIR.exists():
        return presentations
    try:
        mission_paths = sorted(FRONTEND_DIR.glob("m*.html"))
    except Exception:  # pragma: no cover - defensive guard
        return presentations
    for path in mission_paths:
        if not path.is_file():
            continue
        mission_id = path.stem
        try:
            html_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        inner = _extract_main_inner(html_text)
        if inner:
            presentations[mission_id] = inner
    return presentations


def _parse_roles_from_storage(raw_roles) -> List[str]:
    if raw_roles is None:
        return []
    if isinstance(raw_roles, (bytes, bytearray)):
        raw_roles = raw_roles.decode("utf-8", errors="ignore")
    if isinstance(raw_roles, str):
        text = raw_roles.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [part.strip() for part in text.split(",") if part.strip()]
        return _normalize_roles_input(decoded)
    if isinstance(raw_roles, (list, tuple, set)):
        return _normalize_roles_input(list(raw_roles))
    return []


def _parse_role_metadata(raw_metadata) -> dict:
    if raw_metadata is None:
        return {}
    if isinstance(raw_metadata, (bytes, bytearray)):
        raw_metadata = raw_metadata.decode("utf-8", errors="ignore")
    if isinstance(raw_metadata, str):
        payload = raw_metadata.strip()
        if not payload:
            return {}
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
        return {}
    if isinstance(raw_metadata, Mapping):
        return dict(raw_metadata)
    return {}


def _normalize_role_metadata_input(metadata) -> dict:
    if metadata is None:
        return {}
    if isinstance(metadata, Mapping):
        normalized: dict = {}
        for key, value in metadata.items():
            normalized[str(key)] = value
        return normalized
    raise ValueError("El campo 'metadata' debe ser un objeto JSON.")


def _serialize_role_row(row: Mapping[str, object]) -> dict:
    slug_value = _get_row_value(row, "slug") if row else None
    name_value = _get_row_value(row, "name") if row else None
    metadata_raw = _get_row_value(row, "metadata_json") if row else None
    created_raw = _get_row_value(row, "created_at") if row else None
    updated_raw = _get_row_value(row, "updated_at") if row else None
    slug = str(slug_value or "").strip()
    name = str(name_value or slug).strip() or slug
    metadata = _parse_role_metadata(metadata_raw)
    created_at = _parse_timestamp(created_raw)
    updated_at = _parse_timestamp(updated_raw)
    return {
        "slug": slug,
        "name": name,
        "metadata": metadata,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _list_roles(cursor, slug: str | None = None) -> List[dict]:
    if slug:
        cursor.execute(
            """
            SELECT slug, name, metadata_json, created_at, updated_at
            FROM roles
            WHERE slug = %s
            """,
            (slug,),
        )
    else:
        cursor.execute(
            """
            SELECT slug, name, metadata_json, created_at, updated_at
            FROM roles
            ORDER BY name, slug
            """
        )
    rows = cursor.fetchall()
    return [_serialize_role_row(row) for row in rows]


def _fetch_roles_from_db(slug: str | None = None) -> List[dict]:
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                return _list_roles(cur, slug)
    except Exception as exc:
        logger.error("Failed to load roles from database: %s", exc)
        return []


def _extract_role_tokens(role_entry: Mapping[str, object]) -> set[str]:
    tokens: set[str] = set()
    slug_value = str(role_entry.get("slug") or "").strip().lower()
    if slug_value:
        tokens.add(slug_value)
    name_value = str(role_entry.get("name") or "").strip().lower()
    if name_value:
        tokens.add(name_value)
    metadata = role_entry.get("metadata")
    if isinstance(metadata, Mapping):
        aliases = metadata.get("aliases")
        if isinstance(aliases, (list, tuple, set)):
            for alias in aliases:
                alias_str = str(alias or "").strip().lower()
                if alias_str:
                    tokens.add(alias_str)
    return tokens


def _find_role(identifier: str, *, roles: Optional[List[dict]] = None):
    if identifier is None:
        return None
    candidate = str(identifier).strip()
    if not candidate:
        return None
    lowered = candidate.lower()
    catalog = roles if roles is not None else _fetch_roles_from_db()
    for role_entry in catalog:
        tokens = _extract_role_tokens(role_entry)
        if lowered in tokens:
            return role_entry
    return None


def _normalize_role_slug(raw_slug: str) -> str:
    slug = str(raw_slug or "").strip().lower()
    if not slug or not ROLE_SLUG_PATTERN.match(slug):
        raise ValueError(
            "El campo 'slug' debe usar letras minúsculas, números, guiones o guiones bajos."
        )
    return slug


def _serialize_mission_row(
    row: Mapping[str, object], roles_catalog: Optional[List[dict]] = None
) -> dict:
    mission_id_raw = row.get("mission_id") if row else ""
    if isinstance(mission_id_raw, (bytes, bytearray)):
        mission_id_raw = mission_id_raw.decode("utf-8", errors="ignore")
    mission_id = str(mission_id_raw or "").strip()
    title_raw = row.get("title") if row else None
    if isinstance(title_raw, (bytes, bytearray)):
        title_raw = title_raw.decode("utf-8", errors="ignore")
    title = str(title_raw or "").strip() or mission_id
    roles_raw = _parse_roles_from_storage(row.get("roles") if row else None)
    catalog = roles_catalog if roles_catalog is not None else _fetch_roles_from_db()
    roles: List[str] = []
    for role_value in roles_raw:
        role_entry = _find_role(role_value, roles=catalog)
        if role_entry:
            role_name = str(role_entry.get("name") or role_entry.get("slug") or "").strip()
            roles.append(role_name or str(role_value))
        else:
            roles.append(str(role_value))
    content_raw = row.get("content_json") if row else None
    if isinstance(content_raw, (bytes, bytearray)):
        content_raw = content_raw.decode("utf-8", errors="ignore")
    content: dict = {}
    if isinstance(content_raw, str):
        payload = content_raw.strip()
        if payload:
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as exc:
                logger.error(
                    "Failed to decode mission %s content from storage: %s",
                    mission_id or "<sin-id>",
                    exc,
                )
            else:
                if isinstance(decoded, dict):
                    content = decoded
                else:
                    logger.error(
                        "Mission %s content must be a JSON object, got %s.",
                        mission_id or "<sin-id>",
                        type(decoded).__name__,
                    )
    elif isinstance(content_raw, dict):
        content = content_raw
    updated_at = _parse_timestamp(row.get("updated_at")) if row else None
    updated_at_iso = updated_at.isoformat() if updated_at else None
    return {
        "mission_id": mission_id,
        "title": title,
        "roles": roles,
        "content": content,
        "updated_at": updated_at_iso,
    }


def _build_mission_seed_values(
    mission_id: str,
    contract: Mapping | None,
    frontend_presentations: Mapping[str, str] | None,
) -> Optional[Tuple[str, str, str]]:
    contract_dict: Mapping = contract if isinstance(contract, Mapping) else {}
    content_payload = dict(contract_dict)
    if "display_html" not in content_payload:
        presentation_html = (
            frontend_presentations.get(mission_id, "")
            if isinstance(frontend_presentations, Mapping)
            else ""
        )
        if isinstance(presentation_html, str) and presentation_html.strip():
            content_payload["display_html"] = presentation_html
    title_raw = contract_dict.get("title") if isinstance(contract_dict, Mapping) else None
    if isinstance(title_raw, (bytes, bytearray)):
        title_raw = title_raw.decode("utf-8", errors="ignore")
    title = str(title_raw or "").strip() or mission_id
    roles_value = contract_dict.get("roles") if isinstance(contract_dict, Mapping) else None
    roles = _normalize_roles_input(roles_value)
    try:
        content_json = json.dumps(content_payload, ensure_ascii=False)
    except TypeError as exc:
        logger.error("Failed to serialize mission %s contract: %s", mission_id, exc)
        return None
    try:
        roles_json = json.dumps(roles, ensure_ascii=False)
    except TypeError as exc:
        logger.error("Failed to serialize mission %s roles: %s", mission_id, exc)
        return None
    return title, roles_json, content_json


def _seed_missions_from_file(cursor, is_sqlite: bool) -> None:
    if not os.path.exists(CONTRACTS_PATH):
        return
    try:
        with open(CONTRACTS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return
    except json.JSONDecodeError as exc:
        logger.error("Failed to decode missions contracts at %s: %s", CONTRACTS_PATH, exc)
        return
    if not isinstance(payload, dict):
        logger.error(
            "The missions contract file %s must contain a JSON object at the top level.",
            CONTRACTS_PATH,
        )
        return
    timestamp = _format_timestamp(datetime.utcnow())
    frontend_presentations = _load_frontend_presentations()
    for mission_id, contract in payload.items():
        normalized_id = str(mission_id or "").strip()
        if not normalized_id:
            continue
        seed_values = _build_mission_seed_values(
            normalized_id,
            contract if isinstance(contract, Mapping) else None,
            frontend_presentations,
        )
        if seed_values is None:
            continue
        title, roles_json, content_json = seed_values
        params = (normalized_id, title, roles_json, content_json, timestamp)
        if is_sqlite:
            cursor.execute(
                """
                INSERT INTO missions (mission_id, title, roles, content_json, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(mission_id) DO UPDATE SET
                    title = excluded.title,
                    roles = excluded.roles,
                    content_json = excluded.content_json,
                    updated_at = excluded.updated_at
                """,
                params,
            )
        else:
            cursor.execute(
                """
                INSERT INTO missions (mission_id, title, roles, content_json, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    roles = VALUES(roles),
                    content_json = VALUES(content_json),
                    updated_at = VALUES(updated_at)
                """,
                params,
            )


def _load_contract_payload() -> dict[str, dict]:
    if not os.path.exists(CONTRACTS_PATH):
        return {}
    try:
        with open(CONTRACTS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Failed to decode missions contracts at %s: %s", CONTRACTS_PATH, exc)
        return {}
    if not isinstance(payload, dict):
        logger.error(
            "The missions contract file %s must contain a JSON object at the top level.",
            CONTRACTS_PATH,
        )
        return {}
    normalized: dict[str, dict] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[str(key)] = value
    return normalized


def _ensure_presentations_in_storage(cursor, is_sqlite: bool) -> None:
    contracts = _load_contract_payload()
    frontend_presentations = _load_frontend_presentations()
    if not contracts and not frontend_presentations:
        return
    try:
        cursor.execute("SELECT mission_id, content_json FROM missions")
        rows = cursor.fetchall()
    except Exception as exc:
        logger.error("Failed to inspect stored missions for presentation content: %s", exc)
        return
    timestamp = _format_timestamp(datetime.utcnow())
    for row in rows:
        mission_id_raw = row.get("mission_id") if isinstance(row, Mapping) else None
        if isinstance(mission_id_raw, (bytes, bytearray)):
            mission_id_raw = mission_id_raw.decode("utf-8", errors="ignore")
        mission_id = str(mission_id_raw or "").strip()
        if not mission_id:
            continue
        content_raw = row.get("content_json") if isinstance(row, Mapping) else None
        if isinstance(content_raw, (bytes, bytearray)):
            content_raw = content_raw.decode("utf-8", errors="ignore")
        if not isinstance(content_raw, str) or not content_raw.strip():
            continue
        try:
            content_payload = json.loads(content_raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(content_payload, dict):
            continue
        if _coerce_db_bool(content_payload.get("disable_contract_sync")):
            continue
        existing_display_html = content_payload.get("display_html")
        contract_payload = contracts.get(mission_id) if isinstance(contracts, Mapping) else {}
        if not isinstance(contract_payload, Mapping):
            contract_payload = {}
        display_html = contract_payload.get("display_html")
        if not isinstance(display_html, str) or not display_html.strip():
            display_html = frontend_presentations.get(mission_id, "") if frontend_presentations else ""
        if not isinstance(display_html, str):
            display_html = ""
        existing_normalized = (
            existing_display_html.strip()
            if isinstance(existing_display_html, str)
            else ""
        )
        desired_normalized = display_html.strip()
        should_update = not isinstance(existing_display_html, str) or existing_normalized != desired_normalized
        if not should_update:
            continue
        content_payload["display_html"] = display_html
        try:
            encoded = json.dumps(content_payload, ensure_ascii=False)
        except TypeError:
            continue
        params = (encoded, timestamp, mission_id)
        if is_sqlite:
            cursor.execute(
                """
                UPDATE missions
                SET content_json = %s,
                    updated_at = %s
                WHERE mission_id = %s
                """,
                params,
            )
        else:
            cursor.execute(
                """
                UPDATE missions
                SET content_json = %s,
                    updated_at = %s
                WHERE mission_id = %s
                """,
                params,
            )


def _ensure_missions_seeded(cursor, is_sqlite: bool) -> None:
    try:
        cursor.execute("SELECT COUNT(*) AS count FROM missions")
        row = cursor.fetchone() or {}
    except Exception as exc:
        logger.error("Failed to inspect missions table: %s", exc)
        return
    count_value = row.get("count") if isinstance(row, Mapping) else None
    if count_value is None and isinstance(row, Mapping):
        count_value = row.get("COUNT(*)")
    try:
        count = int(count_value or 0)
    except (TypeError, ValueError):
        count = 0
    if count == 0:
        _seed_missions_from_file(cursor, is_sqlite)

    contracts_payload = _load_contract_payload()
    frontend_presentations = _load_frontend_presentations()
    timestamp = _format_timestamp(datetime.utcnow())

    blank_title_ids: List[str] = []
    try:
        cursor.execute(
            "SELECT mission_id FROM missions WHERE title IS NULL OR TRIM(title) = ''"
        )
        rows_with_blank_title = cursor.fetchall() or []
    except Exception as exc:
        logger.error("Failed to inspect mission titles: %s", exc)
        rows_with_blank_title = []

    for row in rows_with_blank_title:
        mission_id_raw = None
        if isinstance(row, Mapping):
            mission_id_raw = row.get("mission_id")
            if mission_id_raw is None:
                mission_id_raw = row.get("MISSION_ID")
        elif isinstance(row, (list, tuple)) and row:
            mission_id_raw = row[0]
        if mission_id_raw is None:
            continue
        mission_id = str(mission_id_raw or "").strip()
        if mission_id:
            blank_title_ids.append(mission_id)

    if blank_title_ids:
        for mission_id in blank_title_ids:
            contract_entry = (
                contracts_payload.get(mission_id)
                if isinstance(contracts_payload, Mapping)
                else None
            )
            seed_values = _build_mission_seed_values(
                mission_id,
                contract_entry if isinstance(contract_entry, Mapping) else None,
                frontend_presentations,
            )
            if seed_values is not None:
                title, roles_json, content_json = seed_values
                try:
                    cursor.execute(
                        """
                        UPDATE missions
                        SET title = %s,
                            roles = %s,
                            content_json = %s,
                            updated_at = %s
                        WHERE mission_id = %s
                        """,
                        (title, roles_json, content_json, timestamp, mission_id),
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to reseed mission %s contract: %s",
                        mission_id,
                        exc,
                    )
                continue
            contract_dict = contract_entry if isinstance(contract_entry, Mapping) else {}
            title_raw = contract_dict.get("title") if contract_dict else None
            if isinstance(title_raw, (bytes, bytearray)):
                title_raw = title_raw.decode("utf-8", errors="ignore")
            normalized_title = str(title_raw or "").strip() or mission_id
            try:
                cursor.execute(
                    """
                    UPDATE missions
                    SET title = %s,
                        updated_at = %s
                    WHERE mission_id = %s
                    """,
                    (normalized_title, timestamp, mission_id),
                )
            except Exception as exc:
                logger.error(
                    "Failed to update mission %s title from contracts: %s",
                    mission_id,
                    exc,
                )

    try:
        cursor.execute("SELECT mission_id, content_json FROM missions")
        rows_with_content = cursor.fetchall() or []
    except Exception as exc:
        logger.error("Failed to inspect mission content: %s", exc)
        rows_with_content = []

    for row in rows_with_content:
        mission_id_raw = None
        if isinstance(row, Mapping):
            mission_id_raw = row.get("mission_id")
            if mission_id_raw is None:
                mission_id_raw = row.get("MISSION_ID")
        elif isinstance(row, (list, tuple)) and row:
            mission_id_raw = row[0]
        if isinstance(mission_id_raw, (bytes, bytearray)):
            mission_id_raw = mission_id_raw.decode("utf-8", errors="ignore")
        mission_id = str(mission_id_raw or "").strip()
        if not mission_id:
            continue

        contract_entry = (
            contracts_payload.get(mission_id)
            if isinstance(contracts_payload, Mapping)
            else None
        )
        if not isinstance(contract_entry, Mapping):
            continue

        seed_values = _build_mission_seed_values(
            mission_id,
            contract_entry,
            frontend_presentations,
        )
        if seed_values is None:
            continue
        _, _, desired_content_json = seed_values
        if not isinstance(desired_content_json, str):
            continue

        content_raw = None
        if isinstance(row, Mapping):
            content_raw = row.get("content_json")
            if content_raw is None:
                content_raw = row.get("CONTENT_JSON")
        elif isinstance(row, (list, tuple)):
            content_raw = row[1] if len(row) > 1 else None
        if isinstance(content_raw, (bytes, bytearray)):
            content_raw = content_raw.decode("utf-8", errors="ignore")

        stored_payload: Optional[dict] = None
        stored_json: Optional[str] = None
        if isinstance(content_raw, str):
            stored_json = content_raw
            stripped = content_raw.strip()
            if stripped:
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    stored_payload = decoded
        elif isinstance(content_raw, Mapping):
            try:
                stored_payload = dict(content_raw)
            except Exception:
                stored_payload = None
            if stored_payload is not None:
                try:
                    stored_json = json.dumps(stored_payload, ensure_ascii=False)
                except TypeError:
                    stored_json = None

        try:
            desired_payload = json.loads(desired_content_json)
        except json.JSONDecodeError:
            continue

        needs_update = False
        if stored_payload is not None:
            if _coerce_db_bool(stored_payload.get("disable_contract_sync")):
                continue
            needs_update = stored_payload != desired_payload
        elif isinstance(stored_json, str):
            needs_update = stored_json.strip() != desired_content_json.strip()
        else:
            needs_update = True

        if not needs_update:
            continue

        try:
            cursor.execute(
                """
                UPDATE missions
                SET content_json = %s,
                    updated_at = %s
                WHERE mission_id = %s
                """,
                (desired_content_json, timestamp, mission_id),
            )
        except Exception as exc:
            logger.error(
                "Failed to refresh mission %s content from contracts: %s",
                mission_id,
                exc,
            )

    _ensure_presentations_in_storage(cursor, is_sqlite)


def _fetch_missions_from_db(mission_id: str | None = None) -> List[dict]:
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                is_sqlite = getattr(conn, "is_sqlite", False)
                _ensure_missions_seeded(cur, is_sqlite)
                if mission_id:
                    cur.execute(
                        """
                        SELECT mission_id, title, roles, content_json, updated_at
                        FROM missions
                        WHERE mission_id = %s
                        """,
                        (mission_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT mission_id, title, roles, content_json, updated_at
                        FROM missions
                        ORDER BY mission_id
                        """
                    )
                rows = cur.fetchall()
    except Exception as exc:
        logger.error("Failed to load missions from database: %s", exc)
        return []
    missions: List[dict] = []
    roles_catalog = _fetch_roles_from_db()
    for row in rows:
        try:
            missions.append(_serialize_mission_row(row, roles_catalog))
        except Exception as exc:  # pragma: no cover - defensive serialization
            logger.error("Failed to serialize mission row: %s", exc)
    return missions


def _get_mission_by_id(mission_id: str) -> Optional[dict]:
    mission_key = (mission_id or "").strip()
    if not mission_key:
        return None
    missions = _fetch_missions_from_db(mission_key)
    return missions[0] if missions else None


def _store_mission_record(
    mission_id: str,
    title: str,
    roles: List[str],
    content: Mapping[str, object],
    *,
    create: bool,
) -> Optional[dict]:
    normalized_id = (mission_id or "").strip()
    if not normalized_id:
        raise ValueError("El campo 'mission_id' es obligatorio.")
    normalized_title = str(title or "").strip() or normalized_id
    normalized_roles_input = _normalize_roles_input(roles)
    catalog = _fetch_roles_from_db()
    validated_roles: List[str] = []
    seen_tokens: set[str] = set()
    universal_tokens = {"*", "all", "todos", "todas"}
    for role_value in normalized_roles_input:
        candidate = str(role_value or "").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in universal_tokens:
            if lowered not in seen_tokens:
                seen_tokens.add(lowered)
                validated_roles.append(candidate)
            continue
        role_entry = _find_role(candidate, roles=catalog)
        if not role_entry:
            raise ValueError(f"El rol '{candidate}' no existe en el catálogo.")
        slug_value = str(role_entry.get("slug") or "").strip()
        if not slug_value:
            raise ValueError(f"El rol '{candidate}' no tiene un identificador válido.")
        lowered_slug = slug_value.lower()
        if lowered_slug in seen_tokens:
            continue
        seen_tokens.add(lowered_slug)
        validated_roles.append(slug_value)
    normalized_roles = validated_roles
    content_dict = dict(content)
    try:
        content_json = json.dumps(content_dict, ensure_ascii=False)
    except TypeError as exc:
        raise ValueError(f"El contenido de la misión no es serializable: {exc}") from exc
    roles_json = json.dumps(normalized_roles, ensure_ascii=False)
    timestamp = _format_timestamp(datetime.utcnow())
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if create:
                    cur.execute(
                        """
                        INSERT INTO missions (mission_id, title, roles, content_json, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (normalized_id, normalized_title, roles_json, content_json, timestamp),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE missions
                        SET title = %s, roles = %s, content_json = %s, updated_at = %s
                        WHERE mission_id = %s
                        """,
                        (
                            normalized_title,
                            roles_json,
                            content_json,
                            timestamp,
                            normalized_id,
                        ),
                    )
                    if cur.rowcount == 0:
                        return None
    except Exception:
        raise
    return _get_mission_by_id(normalized_id)


def load_contracts():
    missions = _fetch_missions_from_db()
    contracts: dict[str, dict] = {}
    for mission in missions:
        mission_id = (mission.get("mission_id") or "").strip()
        content = mission.get("content")
        if mission_id and isinstance(content, dict):
            contracts[mission_id] = content
    return contracts


def _session_expiration_threshold() -> datetime:
    return datetime.utcnow() - timedelta(seconds=SESSION_DURATION_SECONDS)


def _format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(candidate.replace(" ", "T"))
        except ValueError:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def _coerce_db_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {
            "1",
            "true",
            "t",
            "yes",
            "y",
            "on",
            "si",
            "sí",
        }
    return False


def _role_indicates_admin(role_value) -> bool:
    if not role_value:
        return False
    role_entry = _find_role(role_value)
    if role_entry:
        metadata = role_entry.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("is_admin"):
            return True
    if isinstance(role_value, str):
        normalized = role_value.strip().lower()
        return normalized in {"admin", "administrator", "administrador", "administradora"}
    return False


def _student_has_admin_privileges(student_row) -> bool:
    if not student_row:
        return False
    is_admin_value = None
    role_value = None
    has_admin_flag = False
    if isinstance(student_row, Mapping):
        if "is_admin" in student_row:
            has_admin_flag = True
            is_admin_value = student_row.get("is_admin")
        role_value = student_row.get("role")
    else:
        try:
            is_admin_value = student_row["is_admin"]
            has_admin_flag = True
        except (TypeError, KeyError):
            is_admin_value = None
        try:
            role_value = student_row["role"]
        except (TypeError, KeyError):
            role_value = None
    if has_admin_flag:
        return _coerce_db_bool(is_admin_value)
    return _role_indicates_admin(role_value)


def _serialize_student(row: Mapping[str, object]) -> dict:
    created_at = _parse_timestamp(row.get("created_at")) if row else None
    created_at_iso = created_at.isoformat() if created_at else None
    return {
        "slug": row.get("slug") if row else None,
        "name": row.get("name") if row else None,
        "role": row.get("role") if row else None,
        "workdir": row.get("workdir") if row else None,
        "email": row.get("email") if row else None,
        "created_at": created_at_iso,
        "is_admin": _coerce_db_bool(row.get("is_admin") if row else None),
    }


def _enrich_student_role(student: Mapping[str, object], *, roles: Optional[List[dict]] = None) -> dict:
    if not isinstance(student, Mapping):
        return dict(student)
    payload = dict(student)
    role_entry = _find_role(payload.get("role"), roles=roles)
    if role_entry:
        payload["role_name"] = role_entry.get("name")
        payload["role_metadata"] = role_entry.get("metadata")
    return payload


def _get_row_value(row, key):
    if isinstance(row, Mapping):
        return row.get(key)
    try:  # pragma: no cover - defensive branch for unexpected row types
        return row[key]
    except (TypeError, KeyError):
        return None


def _collect_completed_missions(cursor, slugs: Iterable[str]) -> dict[str, List[str]]:
    slug_list = [str(slug).strip() for slug in slugs if str(slug).strip()]
    if not slug_list:
        return {}
    placeholders = ", ".join(["%s"] * len(slug_list))
    cursor.execute(
        f"SELECT student_slug, mission_id FROM completed_missions "
        f"WHERE student_slug IN ({placeholders}) ORDER BY completed_at",
        tuple(slug_list),
    )
    mapping: dict[str, List[str]] = {slug: [] for slug in slug_list}
    for row in cursor.fetchall():
        slug_value = _get_row_value(row, "student_slug")
        mission_value = _get_row_value(row, "mission_id")
        if slug_value is None or mission_value is None:
            continue
        slug_key = str(slug_value).strip()
        mission_id = str(mission_value)
        if not slug_key:
            continue
        mapping.setdefault(slug_key, []).append(mission_id)
    return {slug: mapping.get(slug, []) for slug in slug_list}


def _purge_expired_sessions(cursor) -> None:
    cutoff = _session_expiration_threshold()
    cutoff_str = _format_timestamp(cutoff)
    cursor.execute("DELETE FROM sessions WHERE created_at < %s", (cutoff_str,))


def _fetch_valid_session(cursor, token: str):
    if not token:
        return None
    _purge_expired_sessions(cursor)
    cursor.execute(
        "SELECT student_slug, created_at FROM sessions WHERE token = %s",
        (token,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    created_at = _parse_timestamp(row.get("created_at")) if isinstance(row, Mapping) else None
    if created_at and created_at < _session_expiration_threshold():
        cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
        return None
    return row


def create_session(slug: str) -> str:
    try:
        init_db()
    except Exception as exc:
        raise RuntimeError("Failed to initialize session storage.") from exc
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                _purge_expired_sessions(cur)
                for _ in range(5):
                    token = secrets.token_urlsafe(32)
                    try:
                        cur.execute(
                            """
                            INSERT INTO sessions (token, student_slug, created_at)
                            VALUES (%s, %s, %s)
                            """,
                            (token, slug, _format_timestamp(datetime.utcnow())),
                        )
                        return token
                    except (pymysql.err.IntegrityError, sqlite3.IntegrityError):
                        continue
    except Exception as exc:
        raise RuntimeError("Failed to create session.") from exc
    raise RuntimeError("Failed to create session.")


def validate_session(
    token: str, slug: str | None = None, *, require_admin: bool = False
) -> bool:
    if not token:
        return False
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                row = _fetch_valid_session(cur, token)
                if not row:
                    return False
                stored_slug = ""
                if isinstance(row, Mapping):
                    stored_slug = (row.get("student_slug") or "").strip()
                else:
                    try:
                        stored_slug = (row["student_slug"] or "").strip()
                    except (TypeError, KeyError):
                        stored_slug = ""
                if slug and stored_slug != slug:
                    return False
                if require_admin:
                    if not stored_slug:
                        return False
                    cur.execute(
                        "SELECT slug, role, is_admin FROM students WHERE slug = %s",
                        (stored_slug,),
                    )
                    student_row = cur.fetchone()
                    if not _student_has_admin_privileges(student_row):
                        return False
                return True
    except Exception as exc:
        print(f"Database error during session validation: {exc}", file=sys.stderr)
        return False


def _get_student_for_token(token: str):
    if not token:
        return None
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                session_row = _fetch_valid_session(cur, token)
                if not session_row:
                    return None
                slug = (session_row.get("student_slug") or "").strip()
                if not slug:
                    return None
                cur.execute(
                    """
                    SELECT slug, name, role, workdir, email, is_admin, created_at
                    FROM students
                    WHERE slug = %s
                    """,
                    (slug,),
                )
                return cur.fetchone()
    except Exception as exc:
        print(f"Database error while resolving session owner: {exc}", file=sys.stderr)
        return None


def _resolve_admin_request():
    token = extract_token()
    if not token:
        return None, (jsonify({"error": "Unauthorized."}), 401)
    student_row = _get_student_for_token(token)
    if not student_row:
        return None, (jsonify({"error": "Unauthorized."}), 401)
    if not _student_has_admin_privileges(student_row):
        return None, (jsonify({"error": "Forbidden."}), 403)
    return student_row, None


def verify_evidence(
    files: RepositoryFileAccessor, contract: dict
) -> Tuple[bool, List[str]]:
    feedback: List[str] = []
    passed = True
    for item in contract.get("deliverables", []):
        item_type = (item.get("type") or "").strip()
        path = (item.get("path") or "").strip()
        if not path:
            passed = False
            feedback.append("El contrato tiene un deliverable sin ruta configurada.")
            continue
        if item_type == "file_exists":
            try:
                if not files.exists(path):
                    passed = False
                    message = item.get("feedback_fail", f"Missing file: {path}")
                    feedback.append(f"{message} (fuente: {files.describe_source(path)})")
            except GitHubDownloadError as exc:
                passed = False
                message = item.get(
                    "feedback_error",
                    f"No se pudo descargar {path} desde GitHub: {exc}",
                )
                feedback.append(str(message))
        elif item_type == "file_contains":
            content = item.get("content", "")
            try:
                file_data = files.read_text(path)
            except GitHubFileNotFoundError:
                passed = False
                message = item.get("feedback_fail", f"Missing file: {path}")
                feedback.append(f"{message} (fuente: {files.describe_source(path)})")
                continue
            except GitHubDownloadError as exc:
                passed = False
                message = item.get(
                    "feedback_error",
                    f"No se pudo descargar {path} desde GitHub: {exc}",
                )
                feedback.append(str(message))
                continue
            except UnicodeDecodeError:
                passed = False
                message = item.get(
                    "feedback_error",
                    f"No se pudo decodificar el archivo {path}; utiliza UTF-8.",
                )
                feedback.append(str(message))
                continue
            if content not in file_data:
                passed = False
                feedback.append(
                    item.get("feedback_fail", f"Content mismatch in {path}")
                )
        else:
            passed = False
            feedback.append(f"Unknown evidence type: {vtype}")
    return passed, feedback


def verify_script(files: RepositoryFileAccessor, contract: dict) -> Tuple[bool, List[str]]:
    feedback: List[str] = []
    script_path = (contract.get("script_path") or "").strip()
    if not script_path:
        return False, ["Missing script_path in contract."]

    def _format_feedback(template: str, **context: str) -> str:
        try:
            return template.format(**context)
        except Exception:
            return template

    def _normalize_relative(relative: str) -> PurePosixPath:
        relative_path = PurePosixPath(relative)
        parts: list[str] = []
        for part in relative_path.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("no se permiten rutas relativas con '..'")
            parts.append(part)
        return PurePosixPath("/".join(parts))

    def _write_file(root: str, relative: str, data: bytes) -> Path:
        normalized = _normalize_relative(relative)
        parts = list(normalized.parts)
        destination = Path(root).joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    try:
        script_bytes = files.read_bytes(script_path)
    except GitHubFileNotFoundError:
        script_source = files.describe_source(script_path)
        template = contract.get("feedback_script_missing")
        if template:
            message = _format_feedback(
                template,
                script_path=script_path,
                source=script_source,
            )
        else:
            message = (
                f"Script file not found: {script_path} (fuente: {script_source})"
            )
        return False, [message]
    except GitHubDownloadError as exc:
        return False, [f"No se pudo descargar el script {script_path}: {exc}"]

    try:
        normalized_script_path = _normalize_relative(script_path)
    except ValueError as exc:
        return False, [f"Ruta de script inválida {script_path}: {exc}"]

    script_prefix_candidates: List[str] = []
    script_parts = list(normalized_script_path.parts)
    for index in range(1, len(script_parts)):
        prefix = "/".join(script_parts[:index])
        if prefix:
            script_prefix_candidates.append(prefix)

    required_files = contract.get("required_files", [])
    workspace_paths = contract.get("workspace_paths") or []

    def _resolve_execution_root(tmpdir: str, base_path_value: str) -> Tuple[Path, List[Path]]:
        root = Path(tmpdir)
        candidate = PurePosixPath(base_path_value or "")
        parts: list[str] = []
        for part in candidate.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("la ruta base no puede contener '..'")
            parts.append(part)
        base_directories: List[Path] = [root]
        current = root
        for part in parts:
            current = current / part
            base_directories.append(current)
        for directory in base_directories[1:]:
            directory.mkdir(parents=True, exist_ok=True)
        return base_directories[-1], base_directories

    base_path_value = getattr(files, "base_path", "") or ""
    normalized_base_prefix = ""
    if base_path_value:
        base_parts: list[str] = []
        for part in PurePosixPath(base_path_value).parts:
            if part in {"", "."}:
                continue
            if part == "..":
                base_parts = []
                break
            base_parts.append(part)
        normalized_base_prefix = "/".join(base_parts)

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            execution_root, base_directories = _resolve_execution_root(
                tmpdir, base_path_value
            )
        except ValueError as exc:
            return False, [f"Ruta base inválida {base_path_value!r}: {exc}"]

        if workspace_paths and hasattr(files, "download_workspace"):
            if normalized_base_prefix:
                try:
                    files.download_workspace(workspace_paths, execution_root)
                except ValueError as exc:
                    return False, [f"Ruta de workspace inválida: {exc}"]
                except GitHubFileNotFoundError as exc:
                    workspace_source = files.describe_source(exc.path)
                    message = (
                        f"No se encontró la ruta de trabajo {exc.path} "
                        f"({workspace_source})."
                    )
                    return False, [message]
                except GitHubDownloadError as exc:
                    missing_path = getattr(exc, "path", None) or ""
                    details = f" {missing_path}" if missing_path else ""
                    return False, [f"No se pudo descargar la ruta de trabajo{details}: {exc}"]
            else:
                def _build_workspace_attempt(alias: Optional[str]) -> List[str]:
                    attempt: List[str] = []
                    seen_candidates: set[str] = set()
                    alias_clean = (alias or "").strip("/")

                    def _add_candidate(candidate: str, *, trailing: bool) -> None:
                        formatted = candidate
                        if trailing and formatted and not formatted.endswith("/"):
                            formatted = f"{formatted}/"
                        if formatted not in seen_candidates:
                            seen_candidates.add(formatted)
                            attempt.append(formatted)

                    for entry in workspace_paths:
                        entry_text = str(entry or "")
                        trailing = entry_text.endswith("/")
                        entry_clean = entry_text.strip("/")

                        if not alias_clean:
                            base_candidate = entry_text or entry_clean
                            _add_candidate(base_candidate, trailing=trailing)
                            continue

                        if not entry_clean:
                            base_candidate = entry_text or entry_clean
                            _add_candidate(base_candidate, trailing=trailing)
                            continue

                        if entry_clean.startswith(f"{alias_clean}/"):
                            remainder = entry_clean[len(alias_clean) + 1 :]
                            if remainder:
                                _add_candidate(remainder, trailing=trailing)

                        if alias_clean.endswith(f"/{entry_clean}"):
                            _add_candidate(alias_clean, trailing=trailing)

                        if (
                            alias_clean
                            and entry_clean
                            and alias_clean != entry_clean
                            and not entry_clean.startswith(f"{alias_clean}/")
                            and not alias_clean.endswith(f"/{entry_clean}")
                        ):
                            combined = "/".join(part for part in (alias_clean, entry_clean) if part)
                            if combined:
                                _add_candidate(combined, trailing=trailing)

                    return attempt

                fallback_aliases: List[str] = []
                for entry in workspace_paths:
                    entry_text = str(entry or "")
                    if not entry_text.strip():
                        continue
                    try:
                        normalized_entry = _normalize_relative(entry_text).as_posix()
                    except ValueError as exc:
                        return False, [f"Ruta de workspace inválida: {exc}"]
                    parent = PurePosixPath(normalized_entry).parent
                    while parent and parent != PurePosixPath("."):
                        parent_text = parent.as_posix()
                        if parent_text:
                            fallback_aliases.append(parent_text)
                        parent = parent.parent
                fallback_aliases.extend(script_prefix_candidates)

                seen_aliases: set[str] = set()
                alias_order: List[Optional[str]] = [None]
                for alias in fallback_aliases:
                    alias_clean = alias.strip("/")
                    if not alias_clean or alias_clean in seen_aliases:
                        continue
                    seen_aliases.add(alias_clean)
                    alias_order.append(alias_clean)

                workspace_errors: List[str] = []
                workspace_successful = False
                for alias in alias_order:
                    attempt_paths = _build_workspace_attempt(alias)
                    logger.debug(
                        "Trying workspace download with alias %r: %s",
                        alias,
                        attempt_paths,
                    )
                    try:
                        files.download_workspace(attempt_paths, execution_root)
                    except ValueError as exc:
                        return False, [f"Ruta de workspace inválida: {exc}"]
                    except GitHubFileNotFoundError as exc:
                        workspace_source = files.describe_source(exc.path)
                        message = (
                            f"No se encontró la ruta de trabajo {exc.path} "
                            f"({workspace_source})."
                        )
                        workspace_errors.append(message)
                        logger.debug("Workspace download failed for alias %r: %s", alias, message)
                        continue
                    except GitHubDownloadError as exc:
                        missing_path = getattr(exc, "path", None) or ""
                        details = f" {missing_path}" if missing_path else ""
                        message = f"No se pudo descargar la ruta de trabajo{details}: {exc}"
                        workspace_errors.append(message)
                        logger.debug("Workspace download failed for alias %r: %s", alias, message)
                        continue
                    workspace_successful = True
                    logger.debug(
                        "Workspace download succeeded with alias %r: %s",
                        alias,
                        attempt_paths,
                    )
                    break

                if not workspace_successful:
                    deduped_errors = []
                    seen_messages: set[str] = set()
                    for message in workspace_errors:
                        if message in seen_messages:
                            continue
                        seen_messages.add(message)
                        deduped_errors.append(message)
                    return False, deduped_errors or [
                        "No se pudo descargar la ruta de trabajo requerida."
                    ]
        try:
            local_script_path = _write_file(execution_root, script_path, script_bytes)
        except ValueError as exc:
            return False, [f"Ruta de script inválida {script_path}: {exc}"]

        required_files_bytes: Dict[str, bytes] = {}
        required_files_remote: Dict[str, str] = {}
        repository_root = Path(__file__).resolve().parent.parent

        for dependency in required_files:
            dep_path = (dependency or "").strip()
            if not dep_path:
                continue
            remote_path_override: Optional[str] = None
            try:
                dep_bytes = files.read_bytes(dep_path)
            except GitHubFileNotFoundError:
                backup_path = repository_root / dep_path
                if backup_path.exists():
                    dep_bytes = backup_path.read_bytes()
                    remote_path_override = backup_path.as_posix()
                    logger.debug(
                        "Using local backup for dependency %s at %s", dep_path, backup_path
                    )
                    # Continue with normal processing using the backup bytes.
                else:
                    dep_source = files.describe_source(dep_path)
                    template = contract.get("feedback_required_file_missing")
                    if template:
                        message = _format_feedback(
                            template,
                            required_path=dep_path,
                            source=dep_source,
                            script_path=script_path,
                        )
                    else:
                        message = (
                            f"No se encontró el archivo requerido {dep_path} "
                            f"({dep_source})."
                        )
                    return False, [message]
            except GitHubDownloadError as exc:
                return False, [f"No se pudo descargar {dep_path}: {exc}"]
            try:
                normalized_dep = _normalize_relative(dep_path)
            except ValueError as exc:
                return False, [f"Ruta inválida {dep_path}: {exc}"]
            canonical_path = normalized_dep.as_posix()
            required_files_bytes[canonical_path] = dep_bytes
            try:
                if remote_path_override is not None:
                    remote_path = remote_path_override
                else:
                    remote_path = files.resolve_remote_path(dep_path)
            except Exception:
                remote_path = remote_path_override or ""
            if remote_path:
                required_files_remote[canonical_path] = remote_path
            alias_prefixes = []
            if normalized_base_prefix:
                alias_prefixes.append(normalized_base_prefix)
            else:
                dependency_parent = normalized_dep.parent
                while dependency_parent and dependency_parent != PurePosixPath("."):
                    parent_prefix = dependency_parent.as_posix()
                    if parent_prefix:
                        alias_prefixes.append(parent_prefix)
                    dependency_parent = dependency_parent.parent
            alias_prefixes.extend(script_prefix_candidates)
            unique_alias_prefixes = sorted({prefix for prefix in alias_prefixes if prefix}, key=len, reverse=True)
            for prefix in unique_alias_prefixes:
                candidate_prefix = f"{prefix}/"
                if canonical_path.startswith(candidate_prefix):
                    trimmed_path = canonical_path[len(candidate_prefix) :]
                    if trimmed_path:
                        required_files_bytes.setdefault(trimmed_path, dep_bytes)
                        if trimmed_path not in required_files_remote:
                            required_files_remote[trimmed_path] = remote_path

        for relative_path, content in required_files_bytes.items():
            relative_parts = list(PurePosixPath(relative_path).parts)
            dest_path = Path(execution_root).joinpath(*relative_parts)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(content)

        anchor_candidates = list(base_directories)
        anchor_candidates.append(local_script_path.parent)
        anchor_paths: List[Path] = []
        seen: set[Path] = set()
        for anchor in anchor_candidates:
            resolved_anchor = anchor.resolve()
            if resolved_anchor in seen:
                continue
            seen.add(resolved_anchor)
            anchor_paths.append(resolved_anchor)

        repository = getattr(files, "repository", "")
        branch = getattr(files, "branch", "")

        try:
            result = run_student_script(
                python_executable=sys.executable,
                script_path=local_script_path,
                execution_root=execution_root,
                required_files=required_files_bytes,
                remote_file_map=required_files_remote,
                anchors=anchor_paths,
                repository=repository,
                branch=branch,
                timeout=30,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return False, [f"Error running script: {exc}"]

        if result.returncode != 0:
            stdout_text = (result.stdout or "").rstrip("\n")
            stderr_text = (result.stderr or "").rstrip("\n")
            failure_details = [
                f"STDOUT:\n{stdout_text}" if stdout_text else "STDOUT: (sin salida)",
                f"STDERR:\n{stderr_text}" if stderr_text else "STDERR: (sin salida)",
            ]
            message = (
                "La ejecución del script terminó con errores. "
                f"Código de salida: {result.returncode}.\n"
                + "\n".join(failure_details)
            )
            return False, [message]

        output = result.stdout or ""

    def _parse_dataframe_output(text: str) -> Dict[str, object]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        raw_lines = normalized.split("\n")

        def _normalize_line(line: str) -> str:
            stripped = line.lstrip()

            def _pattern(prefix: str) -> re.Pattern:
                return re.compile(
                    rf"^{prefix}\s*(?:=|:|->)(?P<rest>.*)$",
                    re.IGNORECASE,
                )

            normalization_rules = (
                (_pattern(r"df\.shape"), "Shape:"),
                (_pattern(r"shape"), "Shape:"),
                (_pattern(r"df\.columns(?:\.tolist\(\))?"), "Columns:"),
                (_pattern(r"columns(?:\.tolist\(\))?"), "Columns:"),
                (_pattern(r"df\.head\(\)"), "Head:"),
                (_pattern(r"head"), "Head:"),
                (_pattern(r"df\.dtypes"), "Dtypes:"),
                (_pattern(r"dtypes"), "Dtypes:"),
            )

            for pattern, label in normalization_rules:
                match = pattern.match(stripped)
                if match:
                    remainder = match.group("rest")
                    if remainder.startswith(" "):
                        remainder = remainder[1:]
                    remainder = remainder.rstrip()
                    return f"{label} {remainder}".rstrip()
            return line

        lines = [_normalize_line(line) for line in raw_lines]
        label_prefixes = ("Shape:", "Columns:", "Head:", "Dtypes:")

        summary: Dict[str, object] = {
            "shape": None,
            "shape_text": None,
            "columns": None,
            "columns_text": None,
            "head": None,
            "dtypes": None,
            "dtypes_text": None,
        }

        def _collect_block(start_index: int) -> Tuple[str, int]:
            collected: List[str] = []
            index = start_index
            while index < len(lines) and not any(
                lines[index].startswith(prefix) for prefix in label_prefixes
            ):
                collected.append(lines[index].rstrip())
                index += 1
            block = "\n".join(line for line in collected if line)
            return block, index

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("Shape:"):
                shape_text = line[len("Shape:") :].strip()
                summary["shape_text"] = shape_text
                try:
                    parsed_shape = ast.literal_eval(shape_text)
                    if isinstance(parsed_shape, (list, tuple)):
                        summary["shape"] = tuple(parsed_shape)
                except Exception:
                    summary["shape"] = None
                i += 1
                continue
            if line.startswith("Columns:"):
                columns_text = line[len("Columns:") :].strip()
                summary["columns_text"] = columns_text
                try:
                    parsed_columns = ast.literal_eval(columns_text)
                    if isinstance(parsed_columns, (list, tuple)):
                        summary["columns"] = [str(item) for item in parsed_columns]
                except Exception:
                    summary["columns"] = None
                i += 1
                continue
            if line.startswith("Head:"):
                inline_head = line[len("Head:") :]
                if inline_head.startswith(" "):
                    inline_head = inline_head[1:]
                inline_head = inline_head.rstrip()
                i += 1
                head_block, i = _collect_block(i)
                head_parts = []
                if inline_head:
                    head_parts.append(inline_head)
                if head_block:
                    head_parts.append(head_block)
                summary["head"] = "\n".join(head_parts)
                continue
            if line.startswith("Dtypes:"):
                inline_dtypes = line[len("Dtypes:") :]
                if inline_dtypes.startswith(" "):
                    inline_dtypes = inline_dtypes[1:]
                inline_dtypes = inline_dtypes.rstrip()
                i += 1
                dtypes_block, i = _collect_block(i)
                dtypes_parts = []
                if inline_dtypes:
                    dtypes_parts.append(inline_dtypes)
                if dtypes_block:
                    dtypes_parts.append(dtypes_block)
                combined_dtypes = "\n".join(dtypes_parts)
                summary["dtypes_text"] = combined_dtypes
                if combined_dtypes:
                    parsed: Dict[str, str] = {}
                    for dtype_line in combined_dtypes.split("\n"):
                        stripped = dtype_line.strip()
                        if not stripped or stripped.startswith("dtype:"):
                            continue
                        parts = stripped.split()
                        if len(parts) >= 2:
                            parsed[parts[0]] = parts[-1]
                    if parsed:
                        summary["dtypes"] = parsed
                continue
            i += 1

        return summary

    def _append_feedback(base_message: Optional[str], detail: str) -> None:
        if base_message:
            if "\n" in detail:
                feedback.append(f"{base_message}\n{detail}")
            else:
                feedback.append(f"{base_message} {detail}")
        else:
            feedback.append(detail)

    passed = True
    for validation in contract.get("validations", []):
        vtype = validation.get("type")
        if vtype == "output_contains":
            text = validation.get("text", "")
            if text not in output:
                passed = False
                feedback.append(
                    validation.get(
                        "feedback_fail", f"Expected output to contain '{text}'"
                    )
                )
        elif vtype == "dataframe_output":
            summary = _parse_dataframe_output(output)
            base_message = validation.get("feedback_fail")

            expected_shape = validation.get("shape")
            if expected_shape is not None:
                expected_shape_tuple = tuple(expected_shape)
                actual_shape = summary.get("shape")
                actual_shape_display = summary.get("shape_text")
                if actual_shape is None:
                    passed = False
                    detail = (
                        f"No se encontró df.shape en la salida. Esperado: {expected_shape_tuple}."
                    )
                    if actual_shape_display:
                        detail = (
                            f"df.shape no se pudo interpretar. Esperado: {expected_shape_tuple}. "
                            f"Obtenido: {actual_shape_display}."
                        )
                    _append_feedback(base_message, detail)
                elif tuple(actual_shape) != expected_shape_tuple:
                    passed = False
                    detail = (
                        f"df.shape no coincide. Esperado: {expected_shape_tuple}. "
                        f"Obtenido: {tuple(actual_shape)}."
                    )
                    _append_feedback(base_message, detail)

            expected_columns = validation.get("columns")
            if expected_columns is not None:
                expected_columns_list = [str(item) for item in expected_columns]
                actual_columns = summary.get("columns")
                actual_columns_display = summary.get("columns_text")
                if actual_columns is None:
                    passed = False
                    detail = (
                        "df.columns.tolist() no se pudo interpretar. Esperado: "
                        f"{expected_columns_list}. Obtenido: {actual_columns_display or '(sin salida)'}."
                    )
                    _append_feedback(base_message, detail)
                elif list(actual_columns) != expected_columns_list:
                    passed = False
                    detail = (
                        "df.columns.tolist() no coincide. Esperado: "
                        f"{expected_columns_list}. Obtenido: {list(actual_columns)}."
                    )
                    _append_feedback(base_message, detail)

            if "head" in validation:
                expected_head_value = str(validation.get("head") or "").strip("\n")
                actual_head_value = summary.get("head")
                normalized_actual_head = (
                    "\n".join(line.rstrip() for line in actual_head_value.split("\n"))
                    if isinstance(actual_head_value, str) and actual_head_value
                    else ""
                )
                normalized_expected_head = "\n".join(
                    line.rstrip() for line in expected_head_value.split("\n")
                )
                if normalized_actual_head != normalized_expected_head:
                    passed = False
                    detail = (
                        "df.head() no coincide.\n"
                        f"Esperado:\n{normalized_expected_head or '(sin salida)'}\n"
                        f"Obtenido:\n{normalized_actual_head or '(sin salida)'}"
                    )
                    _append_feedback(base_message, detail)

            if "dtypes" in validation:
                expected_dtypes_value = validation.get("dtypes") or {}
                if isinstance(expected_dtypes_value, dict):
                    expected_dtypes = {
                        str(key): str(value)
                        for key, value in expected_dtypes_value.items()
                    }
                elif isinstance(expected_dtypes_value, list):
                    expected_dtypes = {
                        str(item[0]): str(item[1])
                        for item in expected_dtypes_value
                        if isinstance(item, (list, tuple)) and len(item) == 2
                    }
                else:
                    expected_dtypes = {"_raw": str(expected_dtypes_value)}

                actual_dtypes = summary.get("dtypes")
                actual_dtypes_display = summary.get("dtypes_text")
                if not isinstance(actual_dtypes, dict):
                    passed = False
                    detail = (
                        "df.dtypes no se pudo interpretar. Esperado: "
                        f"{expected_dtypes}. Obtenido: {actual_dtypes_display or '(sin salida)'}."
                    )
                    _append_feedback(base_message, detail)
                elif actual_dtypes != expected_dtypes:
                    passed = False
                    detail = (
                        "df.dtypes no coincide. Esperado: "
                        f"{expected_dtypes}. Obtenido: {actual_dtypes}."
                    )
                    _append_feedback(base_message, detail)
        else:
            passed = False
            feedback.append(f"Unknown evidence type: {vtype}")
    return passed, feedback


def _normalize_contract_values(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple, set)):
        iterable = value
    else:
        iterable = [value]
    normalized: List[str] = []
    for item in iterable:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _stringify_instruction(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (list, tuple, set)):
        parts: List[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        return None
    text = str(value).strip()
    return text or None


def verify_llm(files: RepositoryFileAccessor, contract: dict) -> Tuple[bool, List[str]]:
    deliverable_path = (contract.get("deliverable_path") or "").strip()
    if not deliverable_path:
        return False, ["Missing deliverable_path in contract."]
    try:
        content = files.read_text(deliverable_path)
    except GitHubFileNotFoundError:
        return False, [
            (
                f"No se encontró el archivo de notas: {deliverable_path} "
                f"({files.describe_source(deliverable_path)})."
            )
        ]
    except GitHubDownloadError as exc:
        return False, [f"No se pudo descargar {deliverable_path}: {exc}"]
    except UnicodeDecodeError:
        return False, [
            f"No se pudo decodificar el archivo {deliverable_path}; usa UTF-8 para las notas."
        ]

    keywords = _normalize_contract_values(contract.get("expected_keywords"))
    criteria: List[str] = []
    for key in ("criteria", "evaluation_criteria", "llm_criteria", "expected_criteria"):
        criteria.extend(_normalize_contract_values(contract.get(key)))

    instructions = _stringify_instruction(
        contract.get("llm_instructions")
        or contract.get("llm_context")
        or contract.get("instructions")
        or contract.get("llm_prompt")
    )
    feedback_default = _stringify_instruction(contract.get("feedback_fail"))

    try:
        client = OpenAILLMClient.from_settings()
    except LLMConfigurationError as exc:
        return False, [str(exc)]

    try:
        evaluation = client.evaluate_deliverable(
            content=content,
            keywords=keywords,
            criteria=criteria,
            instructions=instructions,
        )
    except LLMEvaluationError as exc:
        return False, [str(exc)]

    if isinstance(evaluation, dict):
        status_value = evaluation.get("status")
        feedback_value = evaluation.get("feedback")
    else:
        status_value = getattr(evaluation, "status", "")
        feedback_value = getattr(evaluation, "feedback", "")

    status_lower = str(status_value or "").strip().lower()
    feedback_text = str(feedback_value or "").strip()
    status_compact = status_lower.replace(" ", "")

    completed_statuses = {
        "completado",
        "completada",
        "completo",
        "completa",
        "complete",
        "completed",
        "aprobado",
        "aprobada",
        "terminado",
        "terminada",
        "finalizado",
        "finalizada",
        "hecho",
        "lista",
        "listo",
        "ok",
        "satisfactorio",
        "satisfactoria",
        "success",
        "passed",
    }
    incomplete_statuses = {
        "incompleto",
        "incompleta",
        "incomplete",
        "no completado",
        "no completada",
        "faltante",
        "pendiente",
        "pending",
        "fail",
        "failed",
        "rechazado",
        "rechazada",
        "insuficiente",
    }
    completed_compact = {value.replace(" ", "") for value in completed_statuses}
    incomplete_compact = {value.replace(" ", "") for value in incomplete_statuses}

    if status_lower in completed_statuses or status_compact in completed_compact:
        return True, []
    if status_lower in incomplete_statuses or status_compact in incomplete_compact:
        message = feedback_text or feedback_default or (
            "La evaluación automática indica que faltan detalles en la entrega."
        )
        return False, [message]

    if status_value:
        return False, [
            (
                "No se pudo interpretar la respuesta del evaluador automático "
                f"(estado recibido: '{status_value}'). Intenta nuevamente o avisa a tu instructor."
            )
        ]

    return False, [
        feedback_default
        or "La evaluación automática no devolvió un estado reconocible. Intenta nuevamente más tarde."
    ]


def extract_token(allow_query: bool = False) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        header_token = auth_header[7:].strip()
    else:
        header_token = auth_header
    if allow_query:
        query_token = (request.args.get("token") or "").strip()
    else:
        query_token = ""
    return header_token or query_token


def get_request_json() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _get_env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "on"}


def _load_secret_key() -> str:
    env_secret = (os.environ.get("SECRET_KEY") or "").strip()
    if env_secret:
        return env_secret

    try:
        if SECRET_KEY_FILE.exists():
            stored_secret = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
            if stored_secret:
                logger.warning(
                    "SECRET_KEY environment variable not set; using fallback value stored in %s.",
                    SECRET_KEY_FILE,
                )
                return stored_secret
    except OSError as exc:
        logger.warning(
            "SECRET_KEY environment variable not set; failed to read fallback file %s: %s",
            SECRET_KEY_FILE,
            exc,
        )

    generated_secret = secrets.token_hex(32)
    try:
        SECRET_KEY_FILE.write_text(generated_secret, encoding="utf-8")
        try:
            os.chmod(SECRET_KEY_FILE, 0o600)
        except OSError:
            # Best effort on platforms that support chmod.
            pass
        logger.warning(
            "SECRET_KEY environment variable not set; generated a new secret key and stored it in %s.",
            SECRET_KEY_FILE,
        )
    except OSError as exc:
        logger.warning(
            "SECRET_KEY environment variable not set; generated an ephemeral secret key and could not persist it to %s: %s",
            SECRET_KEY_FILE,
            exc,
        )
    return generated_secret


_SECRET_KEY = _load_secret_key()


def _create_app() -> Flask:
    app_instance = Flask(__name__, static_folder="../frontend", static_url_path="/")
    app_instance.config["SECRET_KEY"] = _SECRET_KEY
    app_instance.config["SESSION_COOKIE_HTTPONLY"] = True
    app_instance.config["SESSION_COOKIE_SECURE"] = True
    app_instance.config["SESSION_COOKIE_SAMESITE"] = "None"
    app_instance.config["SESSION_COOKIE_PATH"] = os.environ.get("SESSION_COOKIE_PATH", "/")
    app_instance.config["SESSION_COOKIE_NAME"] = os.environ.get("SESSION_COOKIE_NAME", "session")
    return app_instance


app = _create_app()

cors_origins = os.environ.get("CORS_ORIGINS")
if cors_origins:
    origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    if not origins:
        origins = [cors_origins]
    CORS(app, origins=origins, supports_credentials=True)


@app.route("/healthz")
def healthcheck():
    return jsonify({"status": "ok"})


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    slug = (request.args.get("slug") or "").strip()
    if not slug:
        return jsonify({"error": "Missing slug."}), 400
    token = extract_token(allow_query=True)
    if not validate_session(token, slug):
        return jsonify({"error": "Unauthorized."}), 401
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug, name, role, workdir, email, is_admin, created_at FROM students WHERE slug = %s",
                    (slug,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Student not found."}), 404
                student = _serialize_student(row)
                cur.execute(
                    "SELECT mission_id FROM completed_missions WHERE student_slug = %s ORDER BY completed_at",
                    (slug,),
                )
                completed = [r["mission_id"] for r in cur.fetchall()]
    except Exception as exc:
        print(f"Database error on /api/status: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"student": student, "completed": completed})


@app.route("/api/students")
def api_students():
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT slug, name FROM students ORDER BY name")
                students = list(cur.fetchall())
    except Exception as exc:
        print(f"Database error on /api/students: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"students": students})


@app.route("/api/admin/roles", methods=["GET"])
def api_admin_list_roles():
    _, error = _resolve_admin_request()
    if error:
        return error
    roles: List[dict] = []
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                roles = _list_roles(cur)
    except Exception as exc:
        print(f"Database error on GET /api/admin/roles: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"roles": roles})


@app.route("/api/admin/roles", methods=["POST"])
def api_admin_create_role():
    _, error = _resolve_admin_request()
    if error:
        return error
    data = get_request_json()
    try:
        slug = _normalize_role_slug(data.get("slug"))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    name_raw = data.get("name")
    name = str(name_raw or "").strip()
    if not name:
        return jsonify({"error": "El campo 'name' es obligatorio."}), 400
    try:
        metadata_obj = _normalize_role_metadata_input(data.get("metadata"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        metadata_json = json.dumps(metadata_obj, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"No se pudo serializar 'metadata': {exc}"}), 400
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO roles (slug, name, metadata_json) VALUES (%s, %s, %s)",
                        (slug, name, metadata_json),
                    )
                except (sqlite3.IntegrityError, pymysql.err.IntegrityError):
                    return jsonify({"error": "Ya existe un rol con ese identificador."}), 409
                role_list = _list_roles(cur, slug)
                role_payload = role_list[0] if role_list else None
    except Exception as exc:
        print(f"Database error on POST /api/admin/roles: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    if not role_payload:
        return jsonify({"error": "No se pudo crear el rol."}), 500
    return jsonify({"role": role_payload}), 201


@app.route("/api/admin/roles/<slug>", methods=["GET"])
def api_admin_get_role(slug: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    try:
        normalized_slug = _normalize_role_slug(slug)
    except ValueError:
        return jsonify({"error": "Role not found."}), 404
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                role_list = _list_roles(cur, normalized_slug)
    except Exception as exc:
        print(f"Database error on GET /api/admin/roles/{slug}: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    if not role_list:
        return jsonify({"error": "Role not found."}), 404
    return jsonify({"role": role_list[0]})


@app.route("/api/admin/roles/<slug>", methods=["PUT"])
def api_admin_update_role(slug: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    try:
        normalized_slug = _normalize_role_slug(slug)
    except ValueError:
        return jsonify({"error": "Role not found."}), 404
    data = get_request_json()
    updates: List[str] = []
    params: List[object] = []
    if "name" in data:
        name_value = str(data.get("name") or "").strip()
        if not name_value:
            return jsonify({"error": "El campo 'name' es obligatorio."}), 400
        updates.append("name = %s")
        params.append(name_value)
    metadata_provided = False
    if "metadata" in data:
        metadata_provided = True
        try:
            metadata_obj = _normalize_role_metadata_input(data.get("metadata"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            metadata_json = json.dumps(metadata_obj, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"No se pudo serializar 'metadata': {exc}"}), 400
        updates.append("metadata_json = %s")
        params.append(metadata_json)
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if updates:
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    cur.execute(
                        f"UPDATE roles SET {', '.join(updates)} WHERE slug = %s",
                        tuple(params + [normalized_slug]),
                    )
                    if cur.rowcount == 0:
                        return jsonify({"error": "Role not found."}), 404
                elif not metadata_provided:
                    # Nothing to update; ensure role exists.
                    role_check = _list_roles(cur, normalized_slug)
                    if not role_check:
                        return jsonify({"error": "Role not found."}), 404
                role_list = _list_roles(cur, normalized_slug)
    except Exception as exc:
        print(f"Database error on PUT /api/admin/roles/{slug}: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    if not role_list:
        return jsonify({"error": "Role not found."}), 404
    return jsonify({"role": role_list[0]})


@app.route("/api/admin/roles/<slug>", methods=["DELETE"])
def api_admin_delete_role(slug: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    try:
        normalized_slug = _normalize_role_slug(slug)
    except ValueError:
        return jsonify({"error": "Role not found."}), 404
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                existing = _list_roles(cur, normalized_slug)
                if not existing:
                    return jsonify({"error": "Role not found."}), 404
                role_entry = existing[0]
                tokens = _extract_role_tokens(role_entry)
                cur.execute(
                    "SELECT COUNT(*) AS count FROM students WHERE role = %s",
                    (normalized_slug,),
                )
                row = cur.fetchone()
                count_value = _get_row_value(row, "count") if row else None
                if int(count_value or 0) > 0:
                    return jsonify({"error": "No se puede eliminar un rol asignado a estudiantes."}), 409
                cur.execute("SELECT mission_id, roles FROM missions")
                mission_rows = cur.fetchall()
                for mission_row in mission_rows:
                    mission_roles = _parse_roles_from_storage(
                        _get_row_value(mission_row, "roles")
                    )
                    for mission_role in mission_roles:
                        mission_token = str(mission_role or "").strip().lower()
                        if mission_token and mission_token in tokens:
                            return jsonify(
                                {
                                    "error": "No se puede eliminar un rol que está asignado a misiones.",
                                }
                            ), 409
                cur.execute("DELETE FROM roles WHERE slug = %s", (normalized_slug,))
                deleted = getattr(cur, "rowcount", 0)
                if not deleted:
                    return jsonify({"error": "Role not found."}), 404
    except Exception as exc:
        print(f"Database error on DELETE /api/admin/roles/{slug}: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"deleted": True})


@app.route("/api/admin/integrations", methods=["GET"])
def api_admin_list_integrations():
    _, error = _resolve_admin_request()
    if error:
        return error
    try:
        settings = list_service_settings_for_admin()
    except Exception as exc:
        print(f"Failed to list service settings: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"settings": settings})


@app.route("/api/admin/integrations", methods=["PUT"])
def api_admin_update_integrations():
    _, error = _resolve_admin_request()
    if error:
        return error
    data = get_request_json()
    updates_raw = data.get("updates")
    if not isinstance(updates_raw, list):
        return jsonify({"error": "El cuerpo debe incluir 'updates' como un arreglo."}), 400
    normalized_updates: List[Tuple[str, Optional[str]]] = []
    for item in updates_raw:
        if not isinstance(item, Mapping):
            return jsonify({"error": "Cada actualización debe ser un objeto con 'key' y 'value'."}), 400
        raw_key = item.get("key")
        key = _normalize_setting_key(raw_key if isinstance(raw_key, str) else str(raw_key or ""))
        if not key:
            return jsonify({"error": "Cada entrada debe indicar la clave a actualizar."}), 400
        if not _get_setting_definition(key):
            return jsonify({"error": f"La clave '{key}' no corresponde a una integración conocida."}), 400
        if item.get("clear"):
            normalized_updates.append((key, None))
            continue
        value = item.get("value")
        if value is None:
            normalized_updates.append((key, None))
        elif isinstance(value, str):
            normalized_updates.append((key, value))
        else:
            normalized_updates.append((key, str(value)))
    if not normalized_updates:
        settings = list_service_settings_for_admin()
        return jsonify({"settings": settings, "updated_keys": []})
    current_settings = load_service_settings(SERVICE_SETTINGS_DEFINITIONS.keys())
    pending_settings: Dict[str, Optional[str]] = {}
    for setting_key in SERVICE_SETTINGS_DEFINITIONS:
        pending_settings[setting_key] = current_settings.get(setting_key)
    prepared_updates: List[Tuple[str, Optional[str]]] = []
    for key, value in normalized_updates:
        try:
            cleaned_value = _validate_service_setting_input(key, value)
        except ValueError as exc:
            return jsonify({"error": str(exc), "field": key}), 400
        pending_settings[key] = cleaned_value
        prepared_updates.append((key, cleaned_value))
    effective_settings = _build_effective_settings(pending_settings)
    try:
        _validate_github_credentials(effective_settings)
        _validate_openai_credentials(effective_settings)
    except IntegrationValidationError as exc:
        payload = {"error": str(exc)}
        if exc.field:
            payload["field"] = exc.field
        return jsonify(payload), 400
    applied: List[str] = []
    for key, cleaned_value in prepared_updates:
        try:
            set_service_setting(key, cleaned_value)
        except ValueError as exc:
            return jsonify({"error": str(exc), "field": key}), 400
        except RuntimeError as exc:
            print(f"Failed to update service setting {key}: {exc}", file=sys.stderr)
            return jsonify({"error": "Database connection error."}), 500
        applied.append(key)
    try:
        settings = list_service_settings_for_admin()
    except Exception as exc:
        print(f"Failed to refresh service settings after update: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"settings": settings, "updated_keys": applied})


@app.route("/api/admin/students", methods=["GET"])
def api_admin_list_students():
    _, error = _resolve_admin_request()
    if error:
        return error
    students: List[dict] = []
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slug, name, role, workdir, email, is_admin, created_at
                    FROM students
                    ORDER BY name
                    """
                )
                rows = list(cur.fetchall())
                roles_catalog = _list_roles(cur)
                students = [
                    _enrich_student_role(_serialize_student(row), roles=roles_catalog)
                    for row in rows
                ]
                slugs = [student.get("slug") for student in students if student.get("slug")]
                completed_map = _collect_completed_missions(cur, slugs)
                for student in students:
                    slug_value = student.get("slug")
                    student["completed_missions"] = completed_map.get(slug_value, [])
    except Exception as exc:
        print(f"Database error on GET /api/admin/students: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"students": students})


@app.route("/api/admin/students/<slug>", methods=["PUT"])
def api_admin_update_student(slug: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    data = get_request_json()
    student_payload: dict | None = None
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slug, name, role, workdir, email, is_admin, password_hash, created_at
                    FROM students
                    WHERE slug = %s
                    """,
                    (slug,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Student not found."}), 404
                stored_hash = _get_row_value(row, "password_hash")
                assignments: List[Tuple[str, object]] = []
                if "name" in data:
                    name_value = data.get("name")
                    formatted = None if name_value is None else str(name_value).strip()
                    assignments.append(("name", formatted))
                if "email" in data:
                    email_value = data.get("email")
                    formatted_email = None if email_value is None else str(email_value).strip()
                    assignments.append(("email", formatted_email))
                if "role" in data:
                    role_value = data.get("role")
                    if role_value in (None, ""):
                        formatted_role = None
                    else:
                        role_entry = _find_role(role_value)
                        if not role_entry:
                            return jsonify({"error": "El rol proporcionado no es válido."}), 400
                        formatted_role = str(role_entry.get("slug") or "").strip()
                        if not formatted_role:
                            return jsonify({"error": "El rol proporcionado no es válido."}), 400
                    assignments.append(("role", formatted_role))
                if "is_admin" in data:
                    is_admin_value = 1 if _coerce_db_bool(data.get("is_admin")) else 0
                    assignments.append(("is_admin", is_admin_value))
                if "password" in data:
                    password_raw = data.get("password")
                    current_password = data.get("current_password")
                    if current_password not in (None, ""):
                        if stored_hash:
                            try:
                                password_matches = verify_password(current_password, stored_hash)
                            except PasswordValidationError as exc:
                                return jsonify({"error": str(exc)}), 400
                            except PasswordVerificationError as exc:
                                print(
                                    "Password verification error on admin student update: %s"
                                    % exc,
                                    file=sys.stderr,
                                )
                                return jsonify({"error": "No se pudo verificar la contraseña actual."}), 500
                            if not password_matches:
                                return jsonify({"error": "La contraseña actual no es válida."}), 400
                        else:
                            return jsonify({"error": "El estudiante no tiene una contraseña registrada."}), 400
                    try:
                        new_password_hash = hash_password(password_raw)
                    except PasswordValidationError as exc:
                        return jsonify({"error": str(exc)}), 400
                    except PasswordHashingError as exc:
                        print(
                            "Password hashing error on admin student update: %s" % exc,
                            file=sys.stderr,
                        )
                        return jsonify({"error": "No se pudo actualizar la contraseña."}), 500
                    assignments.append(("password_hash", new_password_hash))
                if assignments:
                    set_clause = ", ".join(f"{column} = %s" for column, _ in assignments)
                    params = [value for _, value in assignments] + [slug]
                    cur.execute(
                        f"UPDATE students SET {set_clause} WHERE slug = %s",
                        tuple(params),
                    )
                    cur.execute(
                        """
                        SELECT slug, name, role, workdir, email, is_admin, password_hash, created_at
                        FROM students
                        WHERE slug = %s
                        """,
                        (slug,),
                    )
                    row = cur.fetchone()
                slug_key = str(_get_row_value(row, "slug") or slug).strip()
                roles_catalog = _list_roles(cur)
                student_payload = _enrich_student_role(
                    _serialize_student(row), roles=roles_catalog
                )
                completed_map = _collect_completed_missions(cur, [slug_key])
                student_payload["completed_missions"] = completed_map.get(slug_key, [])
    except Exception as exc:
        print(f"Database error on PUT /api/admin/students/{slug}: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"student": student_payload})


@app.route("/api/admin/students/<slug>", methods=["DELETE"])
def api_admin_delete_student(slug: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug FROM students WHERE slug = %s",
                    (slug,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Student not found."}), 404
                cur.execute("DELETE FROM students WHERE slug = %s", (slug,))
                deleted = getattr(cur, "rowcount", 0)
                if not deleted:
                    return jsonify({"error": "Student not found."}), 404
                cur.execute(
                    "DELETE FROM completed_missions WHERE student_slug = %s",
                    (slug,),
                )
    except Exception as exc:
        print(f"Database error on DELETE /api/admin/students/{slug}: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"deleted": True})


@app.route("/api/enroll", methods=["POST"])
def api_enroll():
    data = get_request_json()
    slug = (data.get("slug") or "").strip()
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip()
    workdir = (data.get("workdir") or "").strip()
    email = (data.get("email") or "").strip()
    password_raw = data.get("password")
    password_for_check = (
        password_raw if isinstance(password_raw, str) else str(password_raw or "")
    )
    if (
        not slug
        or not name
        or not role
        or not workdir
        or not email
        or not password_for_check
        or not password_for_check.strip()
    ):
        return jsonify({"error": "Missing required fields."}), 400
    role_entry = _find_role(role)
    if not role_entry:
        return jsonify({"error": "El rol seleccionado no es válido."}), 400
    role_slug = str(role_entry.get("slug") or "").strip()
    if not role_slug:
        return jsonify({"error": "El rol seleccionado no es válido."}), 400
    try:
        password_hash = hash_password(password_raw)
    except PasswordValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except PasswordHashingError as exc:
        print(f"Password hashing error on /api/enroll: {exc}", file=sys.stderr)
        return jsonify({"error": "Failed to process password."}), 500
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                params = (slug, name, role_slug, workdir, email, password_hash)
                if getattr(conn, "is_sqlite", False):
                    cur.execute(
                        """
                        INSERT INTO students (slug, name, role, workdir, email, password_hash)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(slug) DO UPDATE SET
                            name = excluded.name,
                            role = excluded.role,
                            workdir = excluded.workdir,
                            email = excluded.email,
                            password_hash = excluded.password_hash
                        """,
                        params,
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO students (slug, name, role, workdir, email, password_hash)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            name = VALUES(name),
                            role = VALUES(role),
                            workdir = VALUES(workdir),
                            email = VALUES(email),
                            password_hash = VALUES(password_hash)
                        """,
                        params,
                    )
    except Exception as exc:
        print(f"Database error on /api/enroll: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"status": "ok"})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = get_request_json()
    slug = (data.get("slug") or "").strip()
    password_raw = data.get("password")
    password_for_check = (
        password_raw if isinstance(password_raw, str) else str(password_raw or "")
    )
    if not slug or not password_for_check or not password_for_check.strip():
        return jsonify({"error": "Missing slug or password."}), 400
    row = None
    completed: List[str] = []
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug, name, role, workdir, email, is_admin, password_hash, created_at FROM students WHERE slug = %s",
                    (slug,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "SELECT mission_id FROM completed_missions WHERE student_slug = %s ORDER BY completed_at",
                        (slug,),
                    )
                    completed = [r["mission_id"] for r in cur.fetchall()]
    except Exception as exc:
        print(f"Database error on /api/login lookup: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    if not row or not row.get("password_hash"):
        return (
            jsonify({"authenticated": False, "error": "Invalid credentials."}),
            401,
        )
    try:
        password_matches = verify_password(password_for_check, row.get("password_hash"))
    except PasswordValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except PasswordVerificationError as exc:
        print(f"Password verification error on /api/login: {exc}", file=sys.stderr)
        return jsonify({"error": "Failed to verify credentials."}), 500
    if not password_matches:
        return (
            jsonify({"authenticated": False, "error": "Invalid credentials."}),
            401,
        )
    try:
        token = create_session(slug)
    except RuntimeError as exc:
        print(f"Session creation error on /api/login: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    student = _serialize_student(row)
    return jsonify(
        {
            "authenticated": True,
            "token": token,
            "student": student,
            "completed": completed,
        }
    )


@app.route("/api/admin/missions", methods=["GET"])
def api_admin_list_missions():
    _, error = _resolve_admin_request()
    if error:
        return error
    missions = _fetch_missions_from_db()
    return jsonify({"missions": missions})


@app.route("/api/admin/missions", methods=["POST"])
def api_admin_create_mission():
    _, error = _resolve_admin_request()
    if error:
        return error
    data = get_request_json()
    mission_id = (data.get("mission_id") or "").strip()
    if not mission_id:
        return jsonify({"error": "El campo 'mission_id' es obligatorio."}), 400
    content = data.get("content")
    if not isinstance(content, Mapping):
        return jsonify({"error": "El campo 'content' debe ser un objeto."}), 400
    content_payload = dict(content)
    content_payload["disable_contract_sync"] = True
    title_value = str(data.get("title") or "").strip() or mission_id
    roles_value = _normalize_roles_input(data.get("roles"))
    try:
        mission = _store_mission_record(
            mission_id,
            title_value,
            roles_value,
            content_payload,
            create=True,
        )
    except (sqlite3.IntegrityError, pymysql.err.IntegrityError):
        return jsonify({"error": f"La misión '{mission_id}' ya existe."}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"Database error on POST /api/admin/missions: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"mission": mission}), 201


@app.route("/api/admin/missions/<mission_id>", methods=["PUT"])
def api_admin_update_mission(mission_id: str):
    _, error = _resolve_admin_request()
    if error:
        return error
    data = get_request_json()
    payload_id = (data.get("mission_id") or "").strip()
    if payload_id and payload_id != mission_id:
        return jsonify({"error": "El identificador de la misión no coincide."}), 400
    existing = _get_mission_by_id(mission_id)
    if not existing:
        return jsonify({"error": "Misión no encontrada."}), 404
    content = data.get("content")
    if not isinstance(content, Mapping):
        return jsonify({"error": "El campo 'content' debe ser un objeto."}), 400
    content_payload = dict(content)
    content_payload["disable_contract_sync"] = True
    title_value = data.get("title")
    if title_value is None:
        title_value = existing.get("title") or mission_id
    else:
        title_value = str(title_value or "").strip() or mission_id
    roles_value = data.get("roles")
    if roles_value is None:
        roles_value = existing.get("roles") or []
    normalized_roles = _normalize_roles_input(roles_value)
    try:
        mission = _store_mission_record(
            mission_id,
            title_value,
            normalized_roles,
            content_payload,
            create=False,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(
            f"Database error on PUT /api/admin/missions/{mission_id}: {exc}",
            file=sys.stderr,
        )
        return jsonify({"error": "Database connection error."}), 500
    if mission is None:
        return jsonify({"error": "Misión no encontrada."}), 404
    return jsonify({"mission": mission})


@app.route("/api/roles", methods=["GET"])
def api_public_roles():
    try:
        roles = _fetch_roles_from_db()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Database error on /api/roles: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    return jsonify({"roles": roles})


@app.route("/api/missions", methods=["GET"])
def api_public_missions():
    role_filter = (request.args.get("role") or "").strip().lower()
    missions = _fetch_missions_from_db()
    if role_filter:
        universal_tokens = {"*", "all", "todos", "todas"}
        catalog = _fetch_roles_from_db()
        matched_role = _find_role(role_filter, roles=catalog)
        if matched_role:
            filter_tokens = _extract_role_tokens(matched_role)
        else:
            filter_tokens = {role_filter}
        filtered: List[dict] = []
        for mission in missions:
            mission_roles = _normalize_roles_input(mission.get("roles"))
            if not mission_roles:
                filtered.append(mission)
                continue
            mission_tokens: set[str] = set()
            for mission_role in mission_roles:
                matched = _find_role(mission_role, roles=catalog)
                if matched:
                    mission_tokens.update(_extract_role_tokens(matched))
                else:
                    mission_tokens.add(str(mission_role or "").strip().lower())
            if not mission_tokens:
                filtered.append(mission)
                continue
            if mission_tokens.intersection(universal_tokens) or mission_tokens.intersection(filter_tokens):
                filtered.append(mission)
        missions = filtered
    return jsonify({"missions": missions})


@app.route("/api/missions/<mission_id>", methods=["GET"])
def api_public_mission_detail(mission_id: str):
    mission = _get_mission_by_id(mission_id)
    if not mission:
        return jsonify({"error": "Misión no encontrada."}), 404
    return jsonify({"mission": mission})


@app.route("/api/verify_mission", methods=["POST"])
def api_verify_mission():
    data = get_request_json()
    slug = (data.get("slug") or "").strip()
    mission_id = (data.get("mission_id") or "").strip()
    if not slug or not mission_id:
        return jsonify({"error": "Missing slug or mission_id."}), 400
    token = extract_token()
    if not validate_session(token, slug):
        return jsonify({"error": "Unauthorized."}), 401
    role = ""
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT role FROM students WHERE slug = %s", (slug,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Student not found."}), 404
                role = (row.get("role") or "").strip()
    except Exception as exc:
        print(f"Database error on /api/verify_mission lookup: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    mission_record = _get_mission_by_id(mission_id)
    if not mission_record:
        missions_snapshot = _fetch_missions_from_db()
        if not missions_snapshot:
            return jsonify(
                {
                    "verified": False,
                    "feedback": [
                        "No hay contratos de misión disponibles. Contacta a la persona administradora."
                    ],
                }
            )
        return jsonify(
            {"verified": False, "feedback": [f"No se encontró contrato para {mission_id}"]}
        )
    mission_roles = None
    if isinstance(mission_record, Mapping):
        mission_roles = mission_record.get("roles")
        contract = mission_record.get("content")
    else:
        contract = None
    normalized_mission_roles = _normalize_roles_input(mission_roles)
    if not contract:
        return jsonify(
            {"verified": False, "feedback": [f"No se encontró contrato para {mission_id}"]}
        )
    try:
        github_client = GitHubClient.from_settings()
    except GitHubConfigurationError as exc:
        print(f"GitHub configuration error: {exc}", file=sys.stderr)
        return jsonify({"verified": False, "feedback": [str(exc)]})
    try:
        available_repos = determine_student_repositories(slug, role)
    except GitHubConfigurationError as exc:
        print(f"Repository selection error: {exc}", file=sys.stderr)
        return jsonify({"verified": False, "feedback": [str(exc)]})
    source_config = contract.get("source") or {}
    vtype = contract.get("verification_type")
    requested_value = source_config.get("repository") or "default"
    requested_key = str(requested_value).strip().lower() or "default"
    prefer_by_role = bool(source_config.get("prefer_repository_by_role"))
    slug_lower = slug.strip().lower()
    role_lower = (role or "").strip().lower()

    identity_matches: set[str] = set()
    for token in (slug_lower, role_lower):
        if _matches_ventas(token):
            identity_matches.add("ventas")
        if _matches_operaciones(token):
            identity_matches.add("operaciones")

    candidate_keys: List[str] = []
    if (
        vtype == "script_output"
        and prefer_by_role
        and requested_key == "default"
        and len(available_repos) > 1
        and not identity_matches
    ):
        seen_candidates: set[str] = set()
        for mission_role_name in normalized_mission_roles:
            normalized_role = mission_role_name.strip().lower()
            if not normalized_role:
                continue
            candidate_key = None
            if _matches_ventas(normalized_role):
                candidate_key = "ventas"
            elif _matches_operaciones(normalized_role):
                candidate_key = "operaciones"
            if (
                candidate_key
                and candidate_key in available_repos
                and candidate_key not in seen_candidates
            ):
                candidate_keys.append(candidate_key)
                seen_candidates.add(candidate_key)

    passed = False
    feedback: List[str] = []
    verification_attempted = False

    def _should_retry_on_missing_artifacts(
        current_accessor: RepositoryFileAccessor,
    ) -> bool:
        script_path = (contract.get("script_path") or "").strip()
        if script_path:
            try:
                current_accessor.read_bytes(script_path)
            except GitHubFileNotFoundError:
                return True
            except GitHubDownloadError:
                return False
        required_files = contract.get("required_files") or []
        for dependency in required_files:
            dep_path = (dependency or "").strip()
            if not dep_path:
                continue
            try:
                current_accessor.read_bytes(dep_path)
            except GitHubFileNotFoundError:
                return True
            except GitHubDownloadError:
                return False
        return False

    filtered_candidates = [
        key for key in candidate_keys if key in available_repos
    ]
    if filtered_candidates:
        candidate_attempted = False
        for index, repo_key in enumerate(filtered_candidates):
            try:
                selection = select_repository_for_contract(
                    source_config,
                    slug,
                    available_repos,
                    role=role,
                    mission_roles=normalized_mission_roles,
                    preferred_repository_key=repo_key,
                )
            except GitHubConfigurationError as exc:
                feedback = [str(exc)]
                continue
            file_accessor = RepositoryFileAccessor(github_client, selection)
            candidate_attempted = True
            passed, feedback = verify_script(file_accessor, contract)
            if passed:
                verification_attempted = True
                break
            should_retry = (
                index + 1 < len(filtered_candidates)
                and _should_retry_on_missing_artifacts(file_accessor)
            )
            if not should_retry:
                verification_attempted = True
                break
        if candidate_attempted and not verification_attempted:
            verification_attempted = True

    if not verification_attempted:
        try:
            selection = select_repository_for_contract(
                source_config,
                slug,
                available_repos,
                role=role,
                mission_roles=normalized_mission_roles,
            )
        except GitHubConfigurationError as exc:
            print(f"Contract repository selection error: {exc}", file=sys.stderr)
            return jsonify({"verified": False, "feedback": [str(exc)]})
        file_accessor = RepositoryFileAccessor(github_client, selection)
        if vtype == "evidence":
            passed, feedback = verify_evidence(file_accessor, contract)
        elif vtype == "script_output":
            passed, feedback = verify_script(file_accessor, contract)
        elif vtype == "llm_evaluation":
            passed, feedback = verify_llm(file_accessor, contract)
        else:
            return jsonify(
                {
                    "verified": False,
                    "feedback": [f"Tipo de verificación desconocido: {vtype}"],
                }
            )
    if passed:
        try:
            init_db()
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    params = (slug, mission_id)
                    if getattr(conn, "is_sqlite", False):
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO completed_missions (student_slug, mission_id)
                            VALUES (%s, %s)
                            """,
                            params,
                        )
                    else:
                        cur.execute(
                            """
                            INSERT IGNORE INTO completed_missions (student_slug, mission_id)
                            VALUES (%s, %s)
                            """,
                            params,
                        )
        except Exception as exc:
            print(
                f"Database error on /api/verify_mission record: {exc}", file=sys.stderr
            )
            return jsonify({"error": "Database connection error."}), 500
    return jsonify({"verified": passed, "feedback": feedback})


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def serve_static(path: str):
    if path.startswith("api/"):
        return jsonify({"error": "Not Found"}), 404
    full_path = os.path.join(app.static_folder, path)
    if os.path.isdir(full_path):
        return send_from_directory(full_path, "index.html")
    if os.path.exists(full_path):
        relative_path = os.path.relpath(full_path, app.static_folder)
        return send_from_directory(app.static_folder, relative_path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    try:
        init_db()
    except Exception as exc:  # pragma: no cover - startup logging
        print(f"Database initialization failed: {exc}", file=sys.stderr)
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
