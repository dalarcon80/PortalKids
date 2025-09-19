"""Utilidades para interactuar con la API de OpenAI."""

from __future__ import annotations

import json
from typing import Any, Dict

import requests

API_URL = 'https://api.openai.com/v1'
USER_AGENT = 'PortalKids/1.0'


def _extract(config: Dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, dict):
        return str(value.get('value', '')).strip()
    if value is None:
        return ''
    return str(value).strip()


def build_client(config: Dict[str, Any]) -> requests.Session:
    """Construye un cliente HTTP autenticado para OpenAI."""

    api_key = _extract(config, 'api_key')
    if not api_key:
        raise ValueError('Debes ingresar una API key de OpenAI (formato sk-...).')
    session = requests.Session()
    session.headers.update(
        {
            'Authorization': f'Bearer {api_key}',
            'User-Agent': USER_AGENT,
        }
    )
    organization = _extract(config, 'organization')
    if organization:
        session.headers['OpenAI-Organization'] = organization
    project = _extract(config, 'project')
    if project:
        session.headers['OpenAI-Project'] = project
    base_url = _extract(config, 'base_url')
    if base_url:
        session.base_url = base_url.rstrip('/')  # type: ignore[attr-defined]
    return session


def _get_base_url(session: requests.Session) -> str:
    base_url = getattr(session, 'base_url', '').strip()
    return base_url or API_URL


def test_credentials(config: Dict[str, Any]) -> Dict[str, Any]:
    """Verifica que las credenciales de OpenAI permitan listar modelos."""

    try:
        session = build_client(config)
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}

    url = f"{_get_base_url(session)}/models"
    try:
        response = session.get(url, timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - errores de red reales
        return {
            'ok': False,
            'message': f'No se pudo conectar con OpenAI: {exc}',
        }
    if 200 <= response.status_code < 300:
        try:
            payload = response.json()
            models = payload.get('data')
            if isinstance(models, list) and models:
                first_model = models[0]
                if isinstance(first_model, dict) and first_model.get('id'):
                    model_name = first_model['id']
                    return {
                        'ok': True,
                        'message': f'Credenciales válidas. Se detectó el modelo "{model_name}".',
                    }
        except (ValueError, json.JSONDecodeError):
            pass
        return {
            'ok': True,
            'message': 'Credenciales válidas de OpenAI.',
        }
    if response.status_code == 401:
        return {'ok': False, 'message': 'OpenAI rechazó la API key proporcionada.'}
    if response.status_code == 404:
        return {
            'ok': False,
            'message': 'La ruta de modelos no existe para la cuenta configurada. Revisa la URL base o la organización.',
        }
    try:
        payload = response.json()
        message = payload.get('error', {}).get('message')
    except (ValueError, json.JSONDecodeError):
        message = ''
    message = message or f'OpenAI respondió con un error {response.status_code}.'
    return {'ok': False, 'message': message}
