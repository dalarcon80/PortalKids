import json
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Mapping, Optional, Tuple

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
    )

try:  # pragma: no cover - fallback for direct execution
    from .llm import (
        LLMConfigurationError,
        LLMEvaluationError,
        OpenAILLMClient,
    )
except ImportError:  # pragma: no cover - allow "python backend/app.py"
    from llm import (  # type: ignore
        LLMConfigurationError,
        LLMEvaluationError,
        OpenAILLMClient,
    )


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_PATH = os.path.join(BASE_DIR, "missions_contracts.json")
SECRET_KEY_FILE = Path(BASE_DIR) / ".flask_secret_key"

logger = logging.getLogger(__name__)

SESSION_DURATION_SECONDS = 60 * 60 * 8


def _use_sqlite_backend() -> bool:
    required_keys = ["DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"]
    return any(not os.environ.get(key) for key in required_keys)


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
                ensure_column("students", "email", "TEXT")
                ensure_column("students", "workdir", "TEXT")
                ensure_column("students", "role", "TEXT")
                ensure_column("students", "name", "TEXT")
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
                "created_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
            ensure_primary_key(cur, "students", ["slug"])

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


def load_contracts():
    if not os.path.exists(CONTRACTS_PATH):
        return {}
    with open(CONTRACTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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
    }


def _purge_expired_sessions(cursor) -> None:
    cutoff = _session_expiration_threshold()
    cutoff_str = _format_timestamp(cutoff)
    cursor.execute("DELETE FROM sessions WHERE created_at < %s", (cutoff_str,))


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


def validate_session(token: str, slug: str | None = None) -> bool:
    if not token:
        return False
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                _purge_expired_sessions(cur)
                cur.execute(
                    "SELECT student_slug, created_at FROM sessions WHERE token = %s",
                    (token,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                created_at = _parse_timestamp(row.get("created_at"))
                if created_at:
                    expiration_threshold = _session_expiration_threshold()
                    if created_at < expiration_threshold:
                        cur.execute(
                            "DELETE FROM sessions WHERE token = %s",
                            (token,),
                        )
                        return False
                if slug:
                    stored_slug = (row.get("student_slug") or "").strip()
                    if stored_slug != slug:
                        return False
                return True
    except Exception as exc:
        print(f"Database error during session validation: {exc}", file=sys.stderr)
        return False


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
            feedback.append(f"Unknown evidence type: {item_type}")
    return passed, feedback


def verify_script(files: RepositoryFileAccessor, contract: dict) -> Tuple[bool, List[str]]:
    feedback: List[str] = []
    script_path = (contract.get("script_path") or "").strip()
    if not script_path:
        return False, ["Missing script_path in contract."]

    def _write_file(root: str, relative: str, data: bytes) -> Path:
        relative_path = PurePosixPath(relative)
        parts: list[str] = []
        for part in relative_path.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("no se permiten rutas relativas con '..'")
            parts.append(part)
        destination = Path(root).joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    try:
        script_bytes = files.read_bytes(script_path)
    except GitHubFileNotFoundError:
        return False, [
            f"Script file not found: {script_path} (fuente: {files.describe_source(script_path)})"
        ]
    except GitHubDownloadError as exc:
        return False, [f"No se pudo descargar el script {script_path}: {exc}"]

    required_files = contract.get("required_files", [])
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            local_script_path = _write_file(tmpdir, script_path, script_bytes)
        except ValueError as exc:
            return False, [f"Ruta de script inválida {script_path}: {exc}"]

        for dependency in required_files:
            dep_path = (dependency or "").strip()
            if not dep_path:
                continue
            try:
                dep_bytes = files.read_bytes(dep_path)
            except GitHubFileNotFoundError:
                return False, [
                    f"No se encontró el archivo requerido {dep_path} "
                    f"({files.describe_source(dep_path)})."
                ]
            except GitHubDownloadError as exc:
                return False, [f"No se pudo descargar {dep_path}: {exc}"]
            try:
                _write_file(tmpdir, dep_path, dep_bytes)
            except ValueError as exc:
                return False, [f"Ruta inválida {dep_path}: {exc}"]

        try:
            result = subprocess.run(
                [sys.executable, str(local_script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=tmpdir,
                timeout=30,
            )
            output = result.stdout or ""
        except Exception as exc:  # pragma: no cover - defensive
            return False, [f"Error running script: {exc}"]

    passed = True
    for validation in contract.get("validations", []):
        if validation.get("type") == "output_contains":
            text = validation.get("text", "")
            if text not in output:
                passed = False
                feedback.append(
                    validation.get(
                        "feedback_fail", f"Expected output to contain '{text}'"
                    )
                )
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
        client = OpenAILLMClient.from_env()
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
                    "SELECT slug, name, role, workdir, email, created_at FROM students WHERE slug = %s",
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
                params = (slug, name, role, workdir, email, password_hash)
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
                    "SELECT slug, name, role, workdir, email, password_hash, created_at FROM students WHERE slug = %s",
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
    contracts = load_contracts()
    contract = contracts.get(mission_id)
    if not contract:
        return jsonify(
            {"verified": False, "feedback": [f"No se encontró contrato para {mission_id}"]}
        )
    try:
        github_client = GitHubClient.from_env()
    except GitHubConfigurationError as exc:
        print(f"GitHub configuration error: {exc}", file=sys.stderr)
        return jsonify({"verified": False, "feedback": [str(exc)]})
    try:
        available_repos = determine_student_repositories(slug, role)
    except GitHubConfigurationError as exc:
        print(f"Repository selection error: {exc}", file=sys.stderr)
        return jsonify({"verified": False, "feedback": [str(exc)]})
    try:
        selection = select_repository_for_contract(
            contract.get("source"), slug, available_repos
        )
    except GitHubConfigurationError as exc:
        print(f"Contract repository selection error: {exc}", file=sys.stderr)
        return jsonify({"verified": False, "feedback": [str(exc)]})
    file_accessor = RepositoryFileAccessor(github_client, selection)
    vtype = contract.get("verification_type")
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
