import json
import os
import secrets
import subprocess
import sys
import time

import bcrypt
import psycopg
from flask import Flask, abort, jsonify, request, send_from_directory
from psycopg.rows import dict_row


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONTRACTS_PATH = os.path.join(BASE_DIR, 'missions_contracts.json')
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')
FRONTEND_DIR_ABS = os.path.abspath(FRONTEND_DIR)


SESSION_DURATION_SECONDS = 60 * 60 * 8
ACTIVE_SESSIONS = {}
_DB_INITIALIZED = False


class PasswordValidationError(ValueError):
    """Raised when the provided password cannot be processed."""


class PasswordHashingError(RuntimeError):
    """Raised when hashing a password fails unexpectedly."""


class PasswordVerificationError(RuntimeError):
    """Raised when verifying a stored password hash fails."""


def get_db_connection():
    db_config = {
        'dbname': os.environ.get('DB_NAME'),
        'user': os.environ.get('DB_USER'),
        'password': os.environ.get('DB_PASSWORD'),
    }

    missing = [key for key, value in db_config.items() if not value]
    if missing:
        raise RuntimeError(
            'Missing required database configuration values: '
            + ', '.join(missing)
        )

    host = os.environ.get('DB_HOST')
    instance_connection = os.environ.get('DB_INSTANCE_CONNECTION_NAME')

    if host:
        db_config['host'] = host
        db_config['port'] = os.environ.get('DB_PORT', '5432')
    elif instance_connection:
        socket_dir = os.environ.get('DB_SOCKET_DIR', '/cloudsql')
        db_config['host'] = os.path.join(socket_dir, instance_connection)
    else:
        raise RuntimeError('DB_HOST or DB_INSTANCE_CONNECTION_NAME must be provided.')

    connect_timeout = os.environ.get('DB_CONNECT_TIMEOUT')
    if connect_timeout:
        db_config['connect_timeout'] = int(connect_timeout)

    sslmode = os.environ.get('DB_SSLMODE')
    if sslmode:
        db_config['sslmode'] = sslmode

    return psycopg.connect(**db_config)


def hash_password(raw_password):
    """Hash a password using bcrypt returning the hash as text."""

    if not isinstance(raw_password, str):
        raw_password = str(raw_password or '')
    if not raw_password.strip():
        raise PasswordValidationError('La contraseña no puede estar vacía.')
    try:
        password_bytes = raw_password.encode('utf-8')
    except Exception as exc:  # pragma: no cover - defensive encoding guard
        raise PasswordValidationError('Formato de contraseña inválido.') from exc
    try:
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    except (ValueError, TypeError) as exc:
        raise PasswordHashingError('No se pudo procesar la contraseña.') from exc
    if isinstance(hashed, bytes):
        hashed = hashed.decode('utf-8')
    return hashed


def verify_password(raw_password, stored_hash):
    """Return True if the password matches the stored hash."""

    if not isinstance(raw_password, str):
        raw_password = str(raw_password or '')
    if not raw_password.strip():
        raise PasswordValidationError('Debes ingresar tu contraseña.')
    try:
        password_bytes = raw_password.encode('utf-8')
    except Exception as exc:  # pragma: no cover - defensive encoding guard
        raise PasswordValidationError('Formato de contraseña inválido.') from exc
    if not stored_hash:
        return False
    if isinstance(stored_hash, str):
        stored_hash_bytes = stored_hash.encode('utf-8')
    elif isinstance(stored_hash, bytes):
        stored_hash_bytes = stored_hash
    else:
        stored_hash_bytes = str(stored_hash).encode('utf-8')
    try:
        return bcrypt.checkpw(password_bytes, stored_hash_bytes)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PasswordVerificationError('No se pudo verificar la contraseña.') from exc


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


def load_contracts():
    if not os.path.exists(CONTRACTS_PATH):
        return {}
    with open(CONTRACTS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_session(slug):
    now = time.time()
    expired_tokens = [
        token
        for token, info in ACTIVE_SESSIONS.items()
        if not info or now - (info.get('created_at') or 0) > SESSION_DURATION_SECONDS
    ]
    for token in expired_tokens:
        ACTIVE_SESSIONS.pop(token, None)
    token = secrets.token_urlsafe(32)
    ACTIVE_SESSIONS[token] = {
        'slug': slug,
        'created_at': now,
    }
    return token


def validate_session(token, slug=None):
    if not token:
        return False
    session = ACTIVE_SESSIONS.get(token)
    if not session:
        return False
    created_at = session.get('created_at') or 0
    if time.time() - created_at > SESSION_DURATION_SECONDS:
        ACTIVE_SESSIONS.pop(token, None)
        return False
    if slug and session.get('slug') != slug:
        return False
    return True


def extract_token():
    header_token = ''
    auth_header = request.headers.get('Authorization', '') if request.headers else ''
    if auth_header:
        if auth_header.lower().startswith('bearer '):
            header_token = auth_header[7:].strip()
        else:
            header_token = auth_header.strip()
    query_token = (request.args.get('token') or '').strip()
    return header_token or query_token


def verify_evidence(workdir, contract):
    feedback = []
    passed = True
    deliverables = contract.get('deliverables', [])
    for item in deliverables:
        item_type = item.get('type')
        path = item.get('path', '')
        full_path = os.path.join(workdir, path)
        if item_type == 'file_exists':
            if not os.path.isfile(full_path):
                passed = False
                feedback.append(item.get('feedback_fail', f"Missing file: {path}"))
        elif item_type == 'file_contains':
            content = item.get('content', '')
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    file_data = f.read()
                if content not in file_data:
                    passed = False
                    feedback.append(item.get('feedback_fail', f"Content mismatch in {path}"))
            except FileNotFoundError:
                passed = False
                feedback.append(item.get('feedback_fail', f"Missing file: {path}"))
        else:
            passed = False
            feedback.append(f"Unknown evidence type: {item_type}")
    return passed, feedback


def verify_script(workdir, contract):
    feedback = []
    script_path = contract.get('script_path')
    if not script_path:
        return False, ["Missing script_path in contract."]
    full_script_path = os.path.join(workdir, script_path)
    if not os.path.isfile(full_script_path):
        return False, [f"Script file not found: {script_path}"]
    try:
        result = subprocess.run(
            ['python', full_script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=workdir,
            timeout=30,
        )
        output = result.stdout or ''
    except Exception as exc:  # pragma: no cover - external execution guard
        return False, [f"Error running script: {exc}"]
    validations = contract.get('validations', [])
    passed = True
    for validation in validations:
        if validation.get('type') == 'output_contains':
            text = validation.get('text', '')
            if text not in output:
                passed = False
                feedback.append(
                    validation.get(
                        'feedback_fail', f"Expected output to contain '{text}'"
                    )
                )
    return passed, feedback


def verify_llm(workdir, contract):
    feedback = []
    deliverable_path = contract.get('deliverable_path')
    if not deliverable_path:
        return False, ["Missing deliverable_path in contract."]
    full_path = os.path.join(workdir, deliverable_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read().lower()
    except FileNotFoundError:
        return False, [f"No se encontró el archivo de notas: {deliverable_path}"]
    keywords = contract.get('expected_keywords', [])
    missing = []
    for keyword in keywords:
        if keyword.lower() not in content:
            missing.append(keyword)
    if missing:
        feedback.append(
            contract.get(
                'feedback_fail', f"Faltan detalles para: {', '.join(missing)}."
            )
        )
        return False, feedback
    return True, []


def _serve_frontend_file(relative_path):
    safe_path = os.path.normpath(relative_path).lstrip(os.sep)
    file_path = os.path.abspath(os.path.join(FRONTEND_DIR_ABS, safe_path))
    if not file_path.startswith(FRONTEND_DIR_ABS):
        abort(404)
    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, 'index.html')
    if not os.path.exists(file_path):
        abort(404)
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path))


app = Flask(__name__)


@app.before_request
def _ensure_database_initialized():
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    try:
        init_db()
    except Exception as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        raise
    _DB_INITIALIZED = True


@app.get('/api/health')
def api_health():
    return jsonify({'ok': True})


@app.get('/api/status')
def api_status():
    slug = (request.args.get('slug') or '').strip()
    if not slug:
        return jsonify({'error': 'Missing slug.'}), 400
    token = extract_token()
    if not validate_session(token, slug):
        return jsonify({'error': 'Unauthorized.'}), 401
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    'SELECT slug, name, role, workdir, email, created_at FROM students WHERE slug = %s',
                    (slug,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({'error': 'Student not found.'}), 404
                student = dict(row)
                cur.execute(
                    'SELECT mission_id FROM completed_missions WHERE student_slug = %s ORDER BY completed_at',
                    (slug,),
                )
                completed = [r['mission_id'] for r in cur.fetchall()]
    except Exception as exc:
        print(f"Database error on /api/status: {exc}", file=sys.stderr)
        return jsonify({'error': 'Database connection error.'}), 500
    return jsonify({'student': student, 'completed': completed})


@app.get('/api/students')
def api_students():
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT slug, name FROM students ORDER BY name')
                students = [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        print(f"Database error on /api/students: {exc}", file=sys.stderr)
        return jsonify({'error': 'Database connection error.'}), 500
    return jsonify({'students': students})


@app.post('/api/enroll')
def api_enroll():
    data = request.get_json(silent=True) or {}
    slug = (data.get('slug') or '').strip()
    name = (data.get('name') or '').strip()
    role = (data.get('role') or '').strip()
    workdir = (data.get('workdir') or '').strip()
    email = (data.get('email') or '').strip()
    password_raw = data.get('password')
    password_for_check = (
        password_raw if isinstance(password_raw, str) else str(password_raw or '')
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
        return jsonify({'error': 'Missing required fields.'}), 400
    try:
        password_hash = hash_password(password_raw)
    except PasswordValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except PasswordHashingError as exc:
        print(f"Password hashing error on /api/enroll: {exc}", file=sys.stderr)
        return jsonify({'error': 'Failed to process password.'}), 500
    try:
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
        return jsonify({'error': 'Database connection error.'}), 500
    return jsonify({'status': 'ok'})


@app.post('/api/login')
def api_login():
    data = request.get_json(silent=True) or {}
    slug = (data.get('slug') or '').strip()
    password_raw = data.get('password')
    password_for_check = (
        password_raw if isinstance(password_raw, str) else str(password_raw or '')
    )
    if not slug or not password_for_check or not password_for_check.strip():
        return jsonify({'error': 'Missing slug or password.'}), 400
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    'SELECT slug, name, role, workdir, email, password_hash, created_at FROM students WHERE slug = %s',
                    (slug,),
                )
                row = cur.fetchone()
    except Exception as exc:
        print(f"Database error on /api/login lookup: {exc}", file=sys.stderr)
        return jsonify({'error': 'Database connection error.'}), 500
    if not row or not row.get('password_hash'):
        return jsonify({'authenticated': False, 'error': 'Invalid credentials.'}), 401
    try:
        password_matches = verify_password(password_raw, row.get('password_hash'))
    except PasswordValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except PasswordVerificationError as exc:
        print(f"Password verification error on /api/login: {exc}", file=sys.stderr)
        return jsonify({'error': 'Failed to verify credentials.'}), 500
    if not password_matches:
        return jsonify({'authenticated': False, 'error': 'Invalid credentials.'}), 401
    token = create_session(slug)
    student = {
        'slug': row.get('slug'),
        'name': row.get('name'),
        'role': row.get('role'),
        'workdir': row.get('workdir'),
        'email': row.get('email'),
        'created_at': row.get('created_at').isoformat() if row.get('created_at') else None,
    }
    return jsonify({'authenticated': True, 'token': token, 'student': student})


@app.post('/api/verify_mission')
def api_verify_mission():
    data = request.get_json(silent=True) or {}
    slug = (data.get('slug') or '').strip()
    mission_id = (data.get('mission_id') or '').strip()
    if not slug or not mission_id:
        return jsonify({'error': 'Missing slug or mission_id.'}), 400
    token = extract_token()
    if not validate_session(token, slug):
        return jsonify({'error': 'Unauthorized.'}), 401
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT workdir FROM students WHERE slug = %s', (slug,))
                row = cur.fetchone()
                if not row:
                    return jsonify({'error': 'Student not found.'}), 404
                workdir = row['workdir']
    except Exception as exc:
        print(f"Database error on /api/verify_mission lookup: {exc}", file=sys.stderr)
        return jsonify({'error': 'Database connection error.'}), 500
    contracts = load_contracts()
    contract = contracts.get(mission_id)
    if not contract:
        return jsonify(
            {
                'verified': False,
                'feedback': [f"No se encontró contrato para {mission_id}"],
            }
        )
    verification_type = contract.get('verification_type')
    if verification_type == 'evidence':
        passed, feedback = verify_evidence(workdir, contract)
    elif verification_type == 'script_output':
        passed, feedback = verify_script(workdir, contract)
    elif verification_type == 'llm_evaluation':
        passed, feedback = verify_llm(workdir, contract)
    else:
        return jsonify(
            {
                'verified': False,
                'feedback': [f"Tipo de verificación desconocido: {verification_type}"],
            }
        )
    if passed:
        try:
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
                f"Database error on /api/verify_mission record: {exc}",
                file=sys.stderr,
            )
            return jsonify({'error': 'Database connection error.'}), 500
    return jsonify({'verified': passed, 'feedback': feedback})


@app.route('/')
@app.route('/index.html')
def serve_index():
    return _serve_frontend_file('index.html')


@app.route('/m/<path:filename>')
@app.route('/<mission_id>.html')
def serve_mission_page(filename=None, mission_id=None):
    if mission_id is not None:
        target_filename = f'{mission_id}.html'
    else:
        target_filename = filename or ''

    normalized = os.path.normpath(target_filename).lstrip(os.sep)
    if not normalized:
        abort(404)

    base_name = os.path.basename(normalized)
    if normalized != base_name:
        abort(404)

    base_lower = base_name.lower()
    if not base_lower.startswith('m') or not base_lower.endswith('.html'):
        abort(404)

    return _serve_frontend_file(base_name)


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return _serve_frontend_file(os.path.join('assets', filename))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    app.run(host='0.0.0.0', port=port)
