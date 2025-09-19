import os
import sys
import time
from types import SimpleNamespace

import pytest
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.app as backend_app


@pytest.fixture
def client(monkeypatch):
    backend_app._DB_INITIALIZED = True
    backend_app.ACTIVE_SESSIONS.clear()
    backend_app.ACTIVE_SESSIONS['valid-token'] = {
        'slug': 'admin',
        'created_at': time.time(),
    }

    store = {'github': {}, 'openai': {}}

    def fake_load_rows(service=None):
        rows = []
        for service_name, data in store.items():
            if service and service_name != service:
                continue
            for key, payload in data.items():
                rows.append(
                    {
                        'service': service_name,
                        'key': key,
                        'value': payload.get('value', ''),
                        'description': payload.get('description', ''),
                        'metadata': payload.get('metadata', {}),
                        'updated_at': payload.get('updated_at'),
                    }
                )
        return rows

    def fake_load_values(service):
        return {key: payload.get('value', '') for key, payload in store.get(service, {}).items()}

    def fake_persist(service, updates):
        service_store = store.setdefault(service, {})
        for key, payload in updates.items():
            service_store[key] = {
                'value': payload.get('value', ''),
                'description': payload.get('description') or '',
                'metadata': payload.get('metadata') or {},
                'updated_at': '2024-01-01T00:00:00Z',
            }

    def fake_get_student_record(slug):
        if slug == 'admin':
            return {'slug': 'admin', 'role': 'Admin', 'name': 'Admin User'}
        return None

    monkeypatch.setattr(backend_app, 'load_service_config_rows', fake_load_rows)
    monkeypatch.setattr(backend_app, 'load_service_config_values', fake_load_values)
    monkeypatch.setattr(backend_app, 'persist_service_config', fake_persist)
    monkeypatch.setattr(backend_app, 'get_student_record', fake_get_student_record)

    import werkzeug

    if not hasattr(werkzeug, '__version__'):
        monkeypatch.setattr(werkzeug, '__version__', '3.1.3', raising=False)

    return backend_app.app.test_client(), store


def auth_headers(slug='admin', token='valid-token'):
    return {'Authorization': f'Bearer {token}'}, {'slug': slug}


def test_admin_get_requires_slug(client):
    test_client, _ = client
    response = test_client.get('/api/admin/service-configs')
    assert response.status_code == 400
    data = response.get_json()
    assert 'slug' in (data.get('error') or '').lower()


def test_admin_get_returns_definitions(client):
    test_client, _ = client
    headers, params = auth_headers()
    response = test_client.get('/api/admin/service-configs', query_string=params, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert 'services' in data
    github_fields = data['services']['github']['fields']
    assert 'token' in github_fields
    assert github_fields['token']['sensitive'] is True
    assert github_fields['token']['value'] == ''


def test_post_github_invalid_credentials(client, monkeypatch):
    test_client, store = client

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10, params=None):
            return FakeResponse(401, {'message': 'Bad credentials'})

    from backend.integrations import github as github_integration

    monkeypatch.setattr(github_integration.requests, 'Session', lambda: FakeSession())

    headers, params = auth_headers()
    payload = {
        'slug': params['slug'],
        'service': 'github',
        'values': {'token': 'bad', 'owner': 'org', 'repository': 'repo'},
    }
    response = test_client.post('/api/admin/service-configs', json=payload, headers=headers)
    assert response.status_code == 400
    data = response.get_json()
    assert 'GitHub' in data.get('error', '') or 'token' in data.get('error', '').lower()
    assert store['github'] == {}


def test_post_github_success(client, monkeypatch):
    test_client, store = client

    class FakeResponse(SimpleNamespace):
        def json(self):
            return getattr(self, 'payload', {})

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10, params=None):
            if url.endswith('/user'):
                return FakeResponse(status_code=200, payload={'login': 'admin'})
            if '/repos/' in url:
                return FakeResponse(status_code=200, payload={'full_name': 'blockcorp/portal'})
            if url.endswith('/user/repos'):
                return FakeResponse(status_code=200, payload={'data': []})
            raise AssertionError(f'Unexpected GitHub URL {url}')

    from backend.integrations import github as github_integration

    monkeypatch.setattr(github_integration.requests, 'Session', lambda: FakeSession())

    headers, params = auth_headers()
    payload = {
        'slug': params['slug'],
        'service': 'github',
        'values': {
            'token': 'ghp_demo',
            'owner': 'blockcorp',
            'repository': 'portal',
        },
    }
    response = test_client.post('/api/admin/service-configs', json=payload, headers=headers)
    assert response.status_code == 201
    data = response.get_json()
    assert data['test_result']['ok'] is True
    assert store['github']['token']['value'] == 'ghp_demo'
    assert store['github']['owner']['value'] == 'blockcorp'
    assert store['github']['repository']['value'] == 'portal'


def test_put_github_updates_token_only(client, monkeypatch):
    test_client, store = client
    store['github'] = {
        'token': {
            'value': 'old-token',
            'description': '',
            'metadata': {},
            'updated_at': '2024-01-01T00:00:00Z',
        },
        'owner': {
            'value': 'blockcorp',
            'description': '',
            'metadata': {},
            'updated_at': '2024-01-01T00:00:00Z',
        },
        'repository': {
            'value': 'portal',
            'description': '',
            'metadata': {},
            'updated_at': '2024-01-01T00:00:00Z',
        },
    }

    class FakeResponse(SimpleNamespace):
        def json(self):
            return getattr(self, 'payload', {})

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10, params=None):
            if url.endswith('/user'):
                return FakeResponse(status_code=200, payload={'login': 'admin'})
            if '/repos/' in url:
                return FakeResponse(status_code=200, payload={'full_name': 'blockcorp/portal'})
            raise AssertionError(f'Unexpected GitHub URL {url}')

    from backend.integrations import github as github_integration

    monkeypatch.setattr(github_integration.requests, 'Session', lambda: FakeSession())

    headers, params = auth_headers()
    payload = {
        'slug': params['slug'],
        'service': 'github',
        'values': {
            'token': 'ghp_updated',
        },
    }
    response = test_client.put('/api/admin/service-configs', json=payload, headers=headers)
    assert response.status_code == 200
    assert store['github']['token']['value'] == 'ghp_updated'
    assert store['github']['owner']['value'] == 'blockcorp'
    assert store['github']['repository']['value'] == 'portal'


def test_post_openai_connection_error(client, monkeypatch):
    test_client, _ = client

    class FailingSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10):
            raise requests.RequestException('boom')

    from backend.integrations import openai as openai_integration

    monkeypatch.setattr(openai_integration.requests, 'Session', lambda: FailingSession())

    headers, params = auth_headers()
    payload = {
        'slug': params['slug'],
        'service': 'openai',
        'values': {
            'api_key': 'sk-test',
        },
    }
    response = test_client.post('/api/admin/service-configs', json=payload, headers=headers)
    assert response.status_code == 400
    data = response.get_json()
    assert 'OpenAI' in data.get('error', '') or 'credenciales' in data.get('error', '').lower()
