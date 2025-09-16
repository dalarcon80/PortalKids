import json
import os
import secrets
import subprocess
import sys
import time
from typing import List, Tuple

import bcrypt
import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_PATH = os.path.join(BASE_DIR, "missions_contracts.json")

SESSION_DURATION_SECONDS = 60 * 60 * 8
ACTIVE_SESSIONS: dict[str, dict[str, object]] = {}


class PasswordValidationError(ValueError):
    """Raised when the provided password cannot be processed."""


class PasswordHashingError(RuntimeError):
    """Raised when hashing a password fails unexpectedly."""


class PasswordVerificationError(RuntimeError):
    """Raised when verifying a stored password hash fails."""


def get_db_connection():
    db_config = {
        "dbname": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
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
        db_config["port"] = os.environ.get("DB_PORT", "5432")
    elif instance_connection:
        socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
        db_config["host"] = os.path.join(socket_dir, instance_connection)
    else:
        raise RuntimeError("DB_HOST or DB_INSTANCE_CONNECTION_NAME must be provided.")

    connect_timeout = os.environ.get("DB_CONNECT_TIMEOUT")
    if connect_timeout:
        db_config["connect_timeout"] = int(connect_timeout)

    sslmode = os.environ.get("DB_SSLMODE")
    if sslmode:
        db_config["sslmode"] = sslmode

    return psycopg.connect(**db_config)


def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS students (
                    slug TEXT PRIMARY KEY,
                    name TEXT,
                    role TEXT,
                    workdir TEXT,
                    email TEXT,
                    password_hash TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT"
            )
            cur.execute(
                "ALTER TABLE students ADD COLUMN IF NOT EXISTS password_hash TEXT"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_missions (
                    id BIGSERIAL PRIMARY KEY,
                    student_slug TEXT NOT NULL REFERENCES students(slug) ON DELETE CASCADE,
                    mission_id TEXT NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (student_slug, mission_id)
                )
                """
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


def create_session(slug: str) -> str:
    now = time.time()
    expired_tokens = [
        token
        for token, info in ACTIVE_SESSIONS.items()
        if not info or now - (info.get("created_at") or 0) > SESSION_DURATION_SECONDS
    ]
    for token in expired_tokens:
        ACTIVE_SESSIONS.pop(token, None)
    token = secrets.token_urlsafe(32)
    ACTIVE_SESSIONS[token] = {
        "slug": slug,
        "created_at": now,
    }
    return token


def validate_session(token: str, slug: str | None = None) -> bool:
    if not token:
        return False
    session = ACTIVE_SESSIONS.get(token)
    if not session:
        return False
    created_at = session.get("created_at") or 0
    if time.time() - created_at > SESSION_DURATION_SECONDS:
        ACTIVE_SESSIONS.pop(token, None)
        return False
    if slug and session.get("slug") != slug:
        return False
    return True


def verify_evidence(workdir: str, contract: dict) -> Tuple[bool, List[str]]:
    feedback: List[str] = []
    passed = True
    for item in contract.get("deliverables", []):
        item_type = item.get("type")
        path = item.get("path", "")
        full_path = os.path.join(workdir, path)
        if item_type == "file_exists":
            if not os.path.isfile(full_path):
                passed = False
                feedback.append(item.get("feedback_fail", f"Missing file: {path}"))
        elif item_type == "file_contains":
            content = item.get("content", "")
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    file_data = f.read()
                if content not in file_data:
                    passed = False
                    feedback.append(
                        item.get("feedback_fail", f"Content mismatch in {path}")
                    )
            except FileNotFoundError:
                passed = False
                feedback.append(item.get("feedback_fail", f"Missing file: {path}"))
        else:
            passed = False
            feedback.append(f"Unknown evidence type: {item_type}")
    return passed, feedback


def verify_script(workdir: str, contract: dict) -> Tuple[bool, List[str]]:
    feedback: List[str] = []
    script_path = contract.get("script_path")
    if not script_path:
        return False, ["Missing script_path in contract."]
    full_script_path = os.path.join(workdir, script_path)
    if not os.path.isfile(full_script_path):
        return False, [f"Script file not found: {script_path}"]
    try:
        result = subprocess.run(
            [sys.executable, full_script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=workdir,
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


def verify_llm(workdir: str, contract: dict) -> Tuple[bool, List[str]]:
    deliverable_path = contract.get("deliverable_path")
    if not deliverable_path:
        return False, ["Missing deliverable_path in contract."]
    full_path = os.path.join(workdir, deliverable_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read().lower()
    except FileNotFoundError:
        return False, [f"No se encontró el archivo de notas: {deliverable_path}"]
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
            with conn.cursor(row_factory=dict_row) as cur:
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
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT slug, name FROM students ORDER BY name")
                students = [dict(row) for row in cur.fetchall()]
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
                    ON CONFLICT (slug) DO UPDATE
                    SET name = EXCLUDED.name,
                        role = EXCLUDED.role,
                        workdir = EXCLUDED.workdir,
                        email = EXCLUDED.email,
                        password_hash = EXCLUDED.password_hash
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
            with conn.cursor(row_factory=dict_row) as cur:
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
    token = create_session(slug)
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
    try:
        init_db()
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT workdir FROM students WHERE slug = %s", (slug,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Student not found."}), 404
                workdir = row["workdir"]
    except Exception as exc:
        print(f"Database error on /api/verify_mission lookup: {exc}", file=sys.stderr)
        return jsonify({"error": "Database connection error."}), 500
    contracts = load_contracts()
    contract = contracts.get(mission_id)
    if not contract:
        return jsonify(
            {"verified": False, "feedback": [f"No se encontró contrato para {mission_id}"]}
        )
    vtype = contract.get("verification_type")
    if vtype == "evidence":
        passed, feedback = verify_evidence(workdir, contract)
    elif vtype == "script_output":
        passed, feedback = verify_script(workdir, contract)
    elif vtype == "llm_evaluation":
        passed, feedback = verify_llm(workdir, contract)
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
                        INSERT INTO completed_missions (student_slug, mission_id)
                        VALUES (%s, %s)
                        ON CONFLICT (student_slug, mission_id) DO NOTHING
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
