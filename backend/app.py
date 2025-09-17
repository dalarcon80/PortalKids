import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import List, Tuple

import bcrypt
import pymysql
from pymysql.cursors import DictCursor
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_PATH = os.path.join(BASE_DIR, "missions_contracts.json")

SESSION_DURATION_SECONDS = 60 * 60 * 8


class PasswordValidationError(ValueError):
    """Raised when the provided password cannot be processed."""


class PasswordHashingError(RuntimeError):
    """Raised when hashing a password fails unexpectedly."""


class PasswordVerificationError(RuntimeError):
    """Raised when verifying a stored password hash fails."""


def get_db_connection():
    db_config = {
        "database": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "cursorclass": DictCursor,
        "charset": "utf8mb4",
        "autocommit": True,
    }

    missing = [key for key, value in db_config.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required database configuration values: " + ", ".join(missing)
        )

    host = os.environ.get("DB_HOST")
    instance_connection = os.environ.get("DB_INSTANCE_CONNECTION_NAME")

    if host:
        db_config["host"] = host
        db_config["port"] = int(os.environ.get("DB_PORT", "3306"))
    elif instance_connection:
        socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
        db_config["unix_socket"] = os.path.join(socket_dir, instance_connection)
    else:
        raise RuntimeError("DB_HOST or DB_INSTANCE_CONNECTION_NAME must be provided.")

    connect_timeout = os.environ.get("DB_CONNECT_TIMEOUT")
    if connect_timeout:
        db_config["connect_timeout"] = int(connect_timeout)

    return pymysql.connect(**db_config)


def init_db():
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


def _purge_expired_sessions(cursor) -> None:
    cutoff = _session_expiration_threshold()
    cursor.execute("DELETE FROM sessions WHERE created_at < %s", (cutoff,))


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
                            VALUES (%s, %s, UTC_TIMESTAMP())
                            """,
                            (token, slug),
                        )
                        return token
                    except pymysql.err.IntegrityError:
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
                created_at = row.get("created_at")
                if isinstance(created_at, datetime):
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


def verify_llm(files: RepositoryFileAccessor, contract: dict) -> Tuple[bool, List[str]]:
    deliverable_path = (contract.get("deliverable_path") or "").strip()
    if not deliverable_path:
        return False, ["Missing deliverable_path in contract."]
    try:
        content = files.read_text(deliverable_path).lower()
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
    feedback: List[str] = []
    missing: List[str] = []
    for keyword in contract.get("expected_keywords", []):
        if keyword.lower() not in content:
            missing.append(keyword)
    if missing:
        feedback.append(
            contract.get(
                "feedback_fail", f"Faltan detalles para: {', '.join(missing)}."
            )
        )
        return False, feedback
    return True, []


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


app = Flask(__name__, static_folder="../frontend", static_url_path="/")
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set before starting the application."
    )
app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_PATH"] = os.environ.get("SESSION_COOKIE_PATH", "/")
app.config["SESSION_COOKIE_NAME"] = os.environ.get("SESSION_COOKIE_NAME", "session")

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
                student = dict(row)
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
                    (slug, name, role, workdir, email, password_hash),
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
    student = {
        "slug": row.get("slug"),
        "name": row.get("name"),
        "role": row.get("role"),
        "workdir": row.get("workdir"),
        "email": row.get("email"),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }
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
                    cur.execute(
                        """
                        INSERT IGNORE INTO completed_missions (student_slug, mission_id)
                        VALUES (%s, %s)
                        """,
                        (slug, mission_id),
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
