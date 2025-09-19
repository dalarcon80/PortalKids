import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import bcrypt
import psycopg
from flask import Flask, abort, jsonify, request, send_from_directory
from psycopg.rows import dict_row


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONTRACTS_PATH = os.path.join(BASE_DIR, 'missions_contracts.json')
MIGRATIONS_DIR = os.path.join(BASE_DIR, 'migrations')
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')
FRONTEND_DIR_ABS = os.path.abspath(FRONTEND_DIR)


SESSION_DURATION_SECONDS = 60 * 60 * 8
ACTIVE_SESSIONS = {}
_DB_INITIALIZED = False

ADMIN_ROLE_NAMES = {'admin', 'administrador'}

SERVICE_FIELD_DEFINITIONS: Dict[str, Dict[str, Dict[str, Any]]] = {
    'github': {
        'token': {
            'label': 'Token personal (PAT)',
            'description': (
                'Token classic con permisos de lectura a repositorios privados '
                'y acceso a la API REST.'
            ),
            'required': True,
            'sensitive': True,
            'metadata': {'placeholder': 'ghp_XXXX'},
        },
        'owner': {
            'label': 'Propietario u organización',
            'description': 'Cuenta o organización donde vive el repositorio.',
            'required': True,
            'metadata': {'example': 'blockcorp-data'},
        },
        'repository': {
            'label': 'Repositorio principal',
            'description': 'Nombre del repositorio que se usará para sincronizar misiones.',
            'required': True,
            'metadata': {'example': 'portal-misiones'},
        },
    },
    'openai': {
        'api_key': {
            'label': 'API key',
            'description': 'Clave secreta iniciando con sk- y con permisos para listar modelos.',
            'required': True,
            'sensitive': True,
            'metadata': {'placeholder': 'sk-live-XXXX'},
        },
        'organization': {
            'label': 'Organización',
            'description': 'Identificador opcional de organización (org-...).',
            'required': False,
            'metadata': {'placeholder': 'org-XXXX'},
        },
        'project': {
            'label': 'Proyecto',
            'description': 'Project ID opcional para cuentas empresariales.',
            'required': False,
        },
        'base_url': {
            'label': 'URL base',
            'description': 'Endpoint alternativo (por ejemplo, proxies empresariales).',
            'required': False,
            'metadata': {'placeholder': 'https://api.openai.com/v1'},
        },
        'default_model': {
            'label': 'Modelo por defecto',
            'description': 'Nombre del modelo que utilizará el portal (ej. gpt-4o-mini).',
            'required': False,
        },
    },
}

SUPPORTED_SERVICE_NAMES = set(SERVICE_FIELD_DEFINITIONS.keys())
MIGRATIONS_TABLE = 'schema_migrations'


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


def is_admin_role(role: Optional[str]) -> bool:
    if not role:
        return False
    return role.strip().lower() in ADMIN_ROLE_NAMES


def _normalize_metadata(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def apply_sql_migrations(conn) -> None:
    if not os.path.isdir(MIGRATIONS_DIR):
        return
    try:
        filenames = sorted(
            file
            for file in os.listdir(MIGRATIONS_DIR)
            if file.endswith('.sql')
        )
    except FileNotFoundError:
        return
    if not filenames:
        return
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for filename in filenames:
            cur.execute(
                f'SELECT 1 FROM {MIGRATIONS_TABLE} WHERE filename = %s',
                (filename,),
            )
            if cur.fetchone():
                continue
            path = os.path.join(MIGRATIONS_DIR, filename)
            with open(path, 'r', encoding='utf-8') as f:
                sql_statements = f.read().strip()
            if not sql_statements:
                continue
            cur.execute(sql_statements)
            cur.execute(
                f'INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES (%s)',
                (filename,),
            )


def load_service_config_rows(service: Optional[str] = None) -> Iterable[Dict[str, Any]]:
    query = (
        'SELECT service, key, value, description, metadata, updated_at '
        'FROM service_integrations'
    )
    params: tuple = ()
    if service:
        query += ' WHERE service = %s'
        params = (service,)
    query += ' ORDER BY service, key'
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    normalized = []
    for row in rows:
        normalized.append(
            {
                'service': row['service'],
                'key': row['key'],
                'value': row.get('value') or '',
                'description': row.get('description') or '',
                'metadata': _normalize_metadata(row.get('metadata')),
                'updated_at': row.get('updated_at'),
            }
        )
    return normalized


def load_service_config_values(service: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for row in load_service_config_rows(service):
        values[row['key']] = row.get('value') or ''
    return values


def persist_service_config(
    service: str,
    updates: Dict[str, Dict[str, Any]],
) -> None:
    if not updates:
        return
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for key, payload in updates.items():
                metadata = payload.get('metadata') or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                try:
                    metadata_json = json.dumps(metadata)
                except (TypeError, ValueError):
                    metadata_json = '{}'
                cur.execute(
                    """
                    INSERT INTO service_integrations (
                        service, key, value, description, metadata, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
                    ON CONFLICT (service, key) DO UPDATE
                    SET value = EXCLUDED.value,
                        description = EXCLUDED.description,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        service,
                        key,
                        payload.get('value') or '',
                        payload.get('description'),
                        metadata_json,
                    ),
                )


def build_service_config_response(
    service: Optional[str] = None,
) -> Dict[str, Any]:
    rows = list(load_service_config_rows(service))
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row['service'], {})[row['key']] = row
    services: Dict[str, Any] = {}
    service_keys = set(grouped.keys()) | SUPPORTED_SERVICE_NAMES
    if service:
        service_keys = {service}
    for service_name in sorted(service_keys):
        definitions = SERVICE_FIELD_DEFINITIONS.get(service_name, {})
        stored = grouped.get(service_name, {})
        fields: Dict[str, Any] = {}
        updated_candidates: list[str] = []
        for key, definition in definitions.items():
            stored_row = stored.get(key)
            metadata = (
                stored_row['metadata']
                if stored_row
                else _normalize_metadata(definition.get('metadata'))
            )
            updated_at = stored_row.get('updated_at') if stored_row else None
            if updated_at:
                if isinstance(updated_at, datetime):
                    updated_candidates.append(updated_at.isoformat())
                else:
                    updated_candidates.append(str(updated_at))
            value = stored_row.get('value') if stored_row else ''
            has_value = bool(value)
            description = (
                stored_row.get('description') if stored_row and stored_row.get('description') else definition.get('description', '')
            )
            fields[key] = {
                'key': key,
                'label': definition.get('label', key.title()),
                'description': description,
                'metadata': metadata,
                'required': bool(definition.get('required')), 
                'sensitive': bool(definition.get('sensitive')),
                'has_value': has_value,
                'value': '' if definition.get('sensitive') else value,
            }
        for key, stored_row in stored.items():
            if key in fields:
                continue
            updated_at = stored_row.get('updated_at')
            if updated_at:
                if isinstance(updated_at, datetime):
                    updated_candidates.append(updated_at.isoformat())
                else:
                    updated_candidates.append(str(updated_at))
            fields[key] = {
                'key': key,
                'label': key.title(),
                'description': stored_row.get('description') or '',
                'metadata': stored_row.get('metadata') or {},
                'required': False,
                'sensitive': False,
                'has_value': bool(stored_row.get('value')),
                'value': stored_row.get('value') or '',
            }
        updated_value = max(updated_candidates) if updated_candidates else None
        services[service_name] = {
            'service': service_name,
            'fields': fields,
            'updated_at': updated_value,
        }
    return {'services': services}


def run_service_test(service: str, config: Dict[str, str]) -> Dict[str, Any]:
    service_key = (service or '').lower()
    if service_key not in SUPPORTED_SERVICE_NAMES:
        raise ValueError(f'Servicio no soportado: {service}')
    if service_key == 'github':
        from backend.integrations import github as integration_module
    elif service_key == 'openai':
        from backend.integrations import openai as integration_module
    else:  # pragma: no cover - guardia adicional
        raise ValueError(f'Servicio no soportado: {service_key}')
    result = integration_module.test_credentials(config)
    if isinstance(result, dict):
        payload = dict(result)
        if 'ok' not in payload:
            payload['ok'] = bool(payload.get('success'))
        if 'message' not in payload:
            payload['message'] = payload.get('detail', '')
        return payload
    if isinstance(result, tuple):
        ok, message = (bool(result[0]), result[1] if len(result) > 1 else '')
    else:
        ok = bool(result)
        message = ''
    return {'ok': ok, 'message': message}


def get_integration_client(service: str):
    service_key = (service or '').lower()
    config = load_service_config_values(service_key)
    if not config:
        raise RuntimeError(
            f'No hay configuración almacenada para el servicio {service_key}.'
        )
    if service_key == 'github':
        from backend.integrations import github as integration_module
    elif service_key == 'openai':
        from backend.integrations import openai as integration_module
    else:  # pragma: no cover - guardia adicional
        raise ValueError(f'Servicio no soportado: {service_key}')
    return integration_module.build_client(config)


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
        apply_sql_migrations(conn)


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


def get_student_record(slug: str) -> Optional[Dict[str, Any]]:
    if not slug:
        return None
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                'SELECT slug, name, role, email FROM students WHERE slug = %s',
                (slug,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def ensure_admin_access(slug: str, token: str) -> Tuple[bool, Any]:
    if not slug:
        return False, (jsonify({'error': 'Falta el slug del administrador.'}), 400)
    if not token or not validate_session(token, slug):
        return False, (jsonify({'error': 'Sesión inválida o expirada.'}), 401)
    student = get_student_record(slug)
    if not student:
        return False, (jsonify({'error': 'Administrador no encontrado.'}), 404)
    if not is_admin_role(student.get('role')):
        return False, (jsonify({'error': 'No tienes permisos administrativos.'}), 403)
    return True, student


def _handle_service_config_save():
    data = request.get_json(silent=True) or {}
    slug = (data.get('slug') or '').strip()
    token = extract_token()
    ok, result = ensure_admin_access(slug, token)
    if not ok:
        return result
    service = (data.get('service') or '').strip().lower()
    if not service:
        return jsonify({'error': 'Debes indicar el servicio a configurar.'}), 400
    definitions = SERVICE_FIELD_DEFINITIONS.get(service, {})
    if service not in SUPPORTED_SERVICE_NAMES:
        return jsonify({'error': f'Servicio desconocido: {service}.'}), 400
    raw_values = data.get('values') or {}
    if not isinstance(raw_values, dict):
        return jsonify({'error': 'El campo "values" debe ser un objeto.'}), 400
    raw_descriptions = data.get('descriptions') or {}
    if not isinstance(raw_descriptions, dict):
        raw_descriptions = {}
    raw_metadata = data.get('metadata') or {}
    if not isinstance(raw_metadata, dict):
        raw_metadata = {}

    sanitized_values: Dict[str, str] = {}
    for key, raw in raw_values.items():
        definition = definitions.get(key, {})
        if raw is None:
            value = ''
        else:
            value = str(raw).strip()
        if definition.get('sensitive') and not value:
            continue
        sanitized_values[key] = value

    existing_rows = list(load_service_config_rows(service))
    existing_by_key = {row['key']: row for row in existing_rows}
    merged_values = {key: row['value'] for key, row in existing_by_key.items()}
    for key, value in sanitized_values.items():
        merged_values[key] = value

    missing_required = []
    for key, definition in definitions.items():
        if not definition.get('required'):
            continue
        value = merged_values.get(key, '')
        if not str(value).strip():
            missing_required.append(definition.get('label') or key)
    if missing_required:
        return (
            jsonify(
                {
                    'error': 'Faltan campos obligatorios: ' + ', '.join(missing_required)
                }
            ),
            400,
        )

    try:
        test_result = run_service_test(service, merged_values)
    except Exception as exc:  # pragma: no cover - log de validación
        print(f'Error al validar credenciales de {service}: {exc}', file=sys.stderr)
        return (
            jsonify({'error': f'No se pudo validar las credenciales de {service}.'}),
            500,
        )
    if not test_result.get('ok'):
        message = test_result.get('message') or 'Las credenciales no son válidas.'
        return jsonify({'error': message, 'test_result': test_result}), 400

    keys_to_update = (
        set(merged_values.keys())
        | set(raw_descriptions.keys())
        | set(raw_metadata.keys())
    )
    updates: Dict[str, Dict[str, Any]] = {}
    for key in keys_to_update:
        definition = definitions.get(key, {})
        existing_row = existing_by_key.get(key) or {}
        value = merged_values.get(key, '')
        description = raw_descriptions.get(key)
        if description is None:
            description = existing_row.get('description') or definition.get('description')
        metadata_value = raw_metadata.get(key)
        if metadata_value is None:
            metadata_value = existing_row.get('metadata') or definition.get('metadata')
        if not isinstance(metadata_value, dict):
            metadata_value = {}
        updates[key] = {
            'value': value,
            'description': description,
            'metadata': metadata_value,
        }

    try:
        persist_service_config(service, updates)
    except Exception as exc:  # pragma: no cover - log de guardado
        print(f'Error guardando configuración de {service}: {exc}', file=sys.stderr)
        return (
            jsonify({'error': 'No se pudo guardar la configuración del servicio.'}),
            500,
        )

    try:
        refreshed = build_service_config_response(service)['services'].get(service)
    except Exception as exc:  # pragma: no cover - log de recarga
        print(f'Error recargando configuración de {service}: {exc}', file=sys.stderr)
        return (
            jsonify(
                {
                    'error': 'La configuración se guardó, pero no se pudo recargar.',
                    'test_result': test_result,
                }
            ),
            500,
        )

    status_code = 201 if not existing_rows else 200
    return (
        jsonify({'service': service, 'config': refreshed, 'test_result': test_result}),
        status_code,
    )


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


@app.get('/api/admin/service-configs')
def api_admin_get_service_configs():
    slug = (request.args.get('slug') or '').strip()
    service_filter = (request.args.get('service') or '').strip().lower()
    token = extract_token()
    ok, result = ensure_admin_access(slug, token)
    if not ok:
        return result
    try:
        if service_filter:
            if service_filter not in SUPPORTED_SERVICE_NAMES:
                return jsonify({'error': f'Servicio desconocido: {service_filter}.'}), 400
            payload = build_service_config_response(service_filter)
        else:
            payload = build_service_config_response()
    except Exception as exc:  # pragma: no cover - errores de carga
        print(f'Error cargando configuraciones de servicio: {exc}', file=sys.stderr)
        return (
            jsonify({'error': 'No se pudo cargar la configuración de servicios.'}),
            500,
        )
    return jsonify(payload)


@app.post('/api/admin/service-configs')
def api_admin_create_service_config():
    return _handle_service_config_save()


@app.put('/api/admin/service-configs')
def api_admin_update_service_config():
    return _handle_service_config_save()


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
