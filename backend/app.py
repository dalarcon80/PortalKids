import os
import sys
import json
import secrets
import subprocess
import time
import psycopg
from psycopg.rows import dict_row
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import bcrypt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONTRACTS_PATH = os.path.join(BASE_DIR, 'missions_contracts.json')
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')


SESSION_DURATION_SECONDS = 60 * 60 * 8
ACTIVE_SESSIONS = {}


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
    except Exception as exc:
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
    except Exception as exc:
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


class PortalHTTPRequestHandler(SimpleHTTPRequestHandler):
    """
    Maneja solicitudes HTTP para el portal.
    Sirve archivos estáticos y endpoints de la API.
    """

    def _set_headers(self, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.end_headers()

    def _send_json(self, data, status=200):
        resp = json.dumps(data)
        self._set_headers(status, 'application/json')
        self.wfile.write(resp.encode('utf-8'))

    def _extract_token(self, params=None):
        header_token = ''
        if hasattr(self, 'headers') and self.headers:
            auth_header = self.headers.get('Authorization', '')
            if auth_header and auth_header.lower().startswith('bearer '):
                header_token = auth_header[7:].strip()
            else:
                header_token = auth_header.strip()
        query_token = ''
        if params:
            query_token = (params.get('token', ['']) or [''])[0].strip()
        return header_token or query_token

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/health'):
            self._send_json({"ok": True})
            return
        if path.startswith('/api/status'):
            params = parse_qs(parsed.query)
            slug = params.get('slug', [''])[0].strip()
            if not slug:
                self._send_json({"error": "Missing slug."}, status=400)
                return
            token = self._extract_token(params)
            if not validate_session(token, slug):
                self._send_json({"error": "Unauthorized."}, status=401)
                return
            try:
                with get_db_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            'SELECT slug, name, role, workdir, email, created_at FROM students WHERE slug = %s',
                            (slug,),
                        )
                        row = cur.fetchone()
                        if not row:
                            self._send_json({"error": "Student not found."}, status=404)
                            return
                        student = dict(row)
                        cur.execute(
                            'SELECT mission_id FROM completed_missions WHERE student_slug = %s ORDER BY completed_at',
                            (slug,),
                        )
                        completed = [r['mission_id'] for r in cur.fetchall()]
            except Exception as exc:
                print(f"Database error on /api/status: {exc}", file=sys.stderr)
                self._send_json({"error": "Database connection error."}, status=500)
                return
            self._send_json({"student": student, "completed": completed})
            return
        if path == '/api/students':
            try:
                with get_db_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute('SELECT slug, name FROM students ORDER BY name')
                        students = [dict(row) for row in cur.fetchall()]
            except Exception as exc:
                print(f"Database error on /api/students: {exc}", file=sys.stderr)
                self._send_json({"error": "Database connection error."}, status=500)
                return
            self._send_json({"students": students})
            return
        # Serve static files
        # Root or index
        if path == '/' or path == '' or path == '/index.html':
            self.serve_static_file('index.html')
            return
        # Missions pages
        if path.startswith('/m') and path.endswith('.html'):
            # remove leading /
            filename = path.lstrip('/')
            self.serve_static_file(filename)
            return
        # Assets (css/js)
        if path.startswith('/assets/'):
            filename = path.lstrip('/')
            self.serve_static_file(filename)
            return
        # default: 404
        self.send_error(404, 'Not Found')

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(length).decode('utf-8')
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        if path == '/api/enroll':
            slug = (data.get('slug') or '').strip()
            name = (data.get('name') or '').strip()
            role = (data.get('role') or '').strip()
            workdir = (data.get('workdir') or '').strip()
            email = (data.get('email') or '').strip()
            password_raw = data.get('password')
            password_for_check = (
                password_raw
                if isinstance(password_raw, str)
                else str(password_raw or '')
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
                self._send_json({"error": "Missing required fields."}, status=400)
                return
            try:
                password_hash = hash_password(password_raw)
            except PasswordValidationError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except PasswordHashingError as exc:
                print(f"Password hashing error on /api/enroll: {exc}", file=sys.stderr)
                self._send_json({"error": "Failed to process password."}, status=500)
                return
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
                self._send_json({"error": "Database connection error."}, status=500)
                return
            self._send_json({"status": "ok"})
            return
        if path == '/api/login':
            slug = (data.get('slug') or '').strip()
            password_raw = data.get('password')
            password_for_check = (
                password_raw
                if isinstance(password_raw, str)
                else str(password_raw or '')
            )
            if not slug or not password_for_check or not password_for_check.strip():
                self._send_json({"error": "Missing slug or password."}, status=400)
                return
            row = None
            completed = []
            try:
                with get_db_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            'SELECT slug, name, role, workdir, email, password_hash, created_at FROM students WHERE slug = %s',
                            (slug,),
                        )
                        row = cur.fetchone()
                        if row:
                            cur.execute(
                                'SELECT mission_id FROM completed_missions WHERE student_slug = %s ORDER BY completed_at',
                                (slug,),
                            )
                            completed = [r['mission_id'] for r in cur.fetchall()]
            except Exception as exc:
                print(f"Database error on /api/login lookup: {exc}", file=sys.stderr)
                self._send_json({"error": "Database connection error."}, status=500)
                return
            if not row or not row.get('password_hash'):
                self._send_json({"authenticated": False, "error": "Invalid credentials."}, status=401)
                return
            try:
                password_bytes = password_for_check.encode('utf-8')
            except Exception:
                self._send_json({"error": "Formato de contraseña inválido."}, status=400)
                return
            stored_hash = row.get('password_hash')
            if isinstance(stored_hash, str):
                stored_hash_bytes = stored_hash.encode('utf-8')
            elif isinstance(stored_hash, bytes):
                stored_hash_bytes = stored_hash
            else:
                stored_hash_bytes = str(stored_hash or '').encode('utf-8')
            try:
                password_matches = bcrypt.checkpw(password_bytes, stored_hash_bytes)
            except (ValueError, TypeError, AttributeError) as exc:
                print(f"Password verification error on /api/login: {exc}", file=sys.stderr)
                self._send_json({"error": "Failed to verify credentials."}, status=500)
                return
            if not password_matches:
                self._send_json({"authenticated": False, "error": "Invalid credentials."}, status=401)
                return
            token = create_session(slug)
            student = {
                'slug': row.get('slug'),
                'name': row.get('name'),
                'role': row.get('role'),
                'workdir': row.get('workdir'),
                'email': row.get('email'),
                'created_at': row.get('created_at').isoformat() if row.get('created_at') else None,
            }
            self._send_json({
                "authenticated": True,
                "token": token,
                "student": student,
                "completed": completed,
            })
            return
        if path == '/api/verify_mission':
            slug = (data.get('slug') or '').strip()
            mission_id = (data.get('mission_id') or '').strip()
            if not slug or not mission_id:
                self._send_json({"error": "Missing slug or mission_id."}, status=400)
                return
            token = self._extract_token()
            if not validate_session(token, slug):
                self._send_json({"error": "Unauthorized."}, status=401)
                return
            # Fetch student workdir
            try:
                with get_db_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute('SELECT workdir FROM students WHERE slug = %s', (slug,))
                        row = cur.fetchone()
                        if not row:
                            self._send_json({"error": "Student not found."}, status=404)
                            return
                        workdir = row['workdir']
            except Exception as exc:
                print(f"Database error on /api/verify_mission lookup: {exc}", file=sys.stderr)
                self._send_json({"error": "Database connection error."}, status=500)
                return
            # Load contracts
            contracts = load_contracts()
            contract = contracts.get(mission_id)
            if not contract:
                self._send_json({"verified": False, "feedback": [f"No se encontró contrato para {mission_id}"]})
                return
            vtype = contract.get('verification_type')
            if vtype == 'evidence':
                passed, feedback = self.verify_evidence(workdir, contract)
            elif vtype == 'script_output':
                passed, feedback = self.verify_script(workdir, contract)
            elif vtype == 'llm_evaluation':
                passed, feedback = self.verify_llm(workdir, contract)
            else:
                self._send_json({"verified": False, "feedback": [f"Tipo de verificación desconocido: {vtype}"]})
                return
            # If passed, record mission
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
                    print(f"Database error on /api/verify_mission record: {exc}", file=sys.stderr)
                    self._send_json({"error": "Database connection error."}, status=500)
                    return
            self._send_json({"verified": passed, "feedback": feedback})
            return
        # Unknown POST path
        self.send_error(404, 'Not Found')

    def verify_evidence(self, workdir, contract):
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

    def verify_script(self, workdir, contract):
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
        except Exception as e:
            return False, [f"Error running script: {e}"]
        validations = contract.get('validations', [])
        passed = True
        for v in validations:
            if v.get('type') == 'output_contains':
                text = v.get('text', '')
                if text not in output:
                    passed = False
                    feedback.append(v.get('feedback_fail', f"Expected output to contain '{text}'"))
        return passed, feedback

    def verify_llm(self, workdir, contract):
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
        for kw in keywords:
            if kw.lower() not in content:
                missing.append(kw)
        if missing:
            feedback.append(contract.get('feedback_fail', f"Faltan detalles para: {', '.join(missing)}."))
            return False, feedback
        return True, []

    def serve_static_file(self, filename):
        file_path = os.path.join(FRONTEND_DIR, filename)
        if os.path.isdir(file_path):
            file_path = os.path.join(file_path, 'index.html')
        if not os.path.exists(file_path):
            self.send_error(404, 'File Not Found')
            return
        # Determine content type
        if file_path.endswith('.html'):
            content_type = 'text/html'
        elif file_path.endswith('.css'):
            content_type = 'text/css'
        elif file_path.endswith('.js'):
            content_type = 'application/javascript'
        else:
            content_type = 'application/octet-stream'
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            self._set_headers(200, content_type)
            self.wfile.write(content)
        except Exception:
            self.send_error(500, 'Internal Server Error')


def run(server_class=HTTPServer, handler_class=PortalHTTPRequestHandler, port=8000):
    init_db()
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Iniciando servidor en puerto {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('Deteniendo servidor...')
    httpd.server_close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    run(port=port)
