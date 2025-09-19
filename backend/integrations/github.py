"""Utilidades para interactuar con la API de GitHub."""

from __future__ import annotations

import json
from typing import Any, Dict

import requests

API_URL = 'https://api.github.com'
USER_AGENT = 'PortalKids/1.0'


def _extract(config: Dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, dict):
        return str(value.get('value', '')).strip()
    if value is None:
        return ''
    return str(value).strip()


def build_client(config: Dict[str, Any]) -> requests.Session:
    """Construye un cliente autenticado de GitHub."""

    token = _extract(config, 'token')
    if not token:
        raise ValueError('Falta el token personal de GitHub.')
    session = requests.Session()
    session.headers.update(
        {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github+json',
            'User-Agent': USER_AGENT,
        }
    )
    return session


def _handle_response(response: requests.Response, default_error: str) -> Dict[str, Any]:
    if 200 <= response.status_code < 300:
        return {'ok': True, 'message': ''}
    if response.status_code == 401:
        return {'ok': False, 'message': 'Credenciales de GitHub inválidas.'}
    if response.status_code == 403:
        try:
            payload = response.json()
            message = payload.get('message') or default_error
        except (ValueError, json.JSONDecodeError):
            message = default_error
        if 'rate limit' in message.lower():
            return {
                'ok': False,
                'message': 'GitHub rechazó la solicitud por límites de uso. Verifica el token y los permisos.',
            }
    try:
        payload = response.json()
        message = payload.get('message')
    except (ValueError, json.JSONDecodeError):
        message = ''
    message = message or default_error
    return {'ok': False, 'message': message}


def test_credentials(config: Dict[str, Any]) -> Dict[str, Any]:
    """Realiza una verificación mínima de las credenciales de GitHub."""

    try:
        session = build_client(config)
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}

    owner = _extract(config, 'owner')
    repository = _extract(config, 'repository')

    try:
        user_response = session.get(f'{API_URL}/user', timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - errores de red reales
        return {
            'ok': False,
            'message': f'Error al conectar con GitHub: {exc}',
        }

    result = _handle_response(user_response, 'No fue posible validar el token personal de GitHub.')
    if not result['ok']:
        return result

    if owner and repository:
        try:
            repo_response = session.get(
                f'{API_URL}/repos/{owner}/{repository}',
                timeout=10,
            )
        except requests.RequestException as exc:  # pragma: no cover - errores de red reales
            return {
                'ok': False,
                'message': f'Error verificando el repositorio {owner}/{repository}: {exc}',
            }
        repo_result = _handle_response(
            repo_response,
            f'GitHub no permitió acceder al repositorio {owner}/{repository}.',
        )
        if not repo_result['ok']:
            return repo_result
        return {
            'ok': True,
            'message': f'Credenciales válidas para {owner}/{repository}.',
        }

    try:
        repos_response = session.get(
            f'{API_URL}/user/repos',
            params={'per_page': 1},
            timeout=10,
        )
    except requests.RequestException as exc:  # pragma: no cover - errores de red reales
        return {
            'ok': False,
            'message': f'No se pudo listar los repositorios del usuario autenticado: {exc}',
        }
    repos_result = _handle_response(
        repos_response,
        'No se pudieron listar repositorios con el token proporcionado.',
    )
    if not repos_result['ok']:
        return repos_result
    return {
        'ok': True,
        'message': 'Token válido. Se accedió correctamente a la cuenta de GitHub.',
    }
