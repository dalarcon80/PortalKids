"""Helpers to resolve student mission files directly from GitHub."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict
from urllib.parse import quote

import requests


class GitHubConfigurationError(RuntimeError):
    """Raised when GitHub integration is misconfigured."""


class GitHubDownloadError(RuntimeError):
    """Raised when a download from GitHub fails unexpectedly."""

    def __init__(
        self,
        message: str,
        *,
        repository: str | None = None,
        path: str | None = None,
        ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.repository = repository
        self.path = path
        self.ref = ref


class GitHubFileNotFoundError(FileNotFoundError):
    """Raised when a file cannot be found in the configured repository."""

    def __init__(self, message: str, *, repository: str, path: str, ref: str) -> None:
        super().__init__(message)
        self.repository = repository
        self.path = path
        self.ref = ref


@dataclass(frozen=True)
class RepositoryInfo:
    key: str
    repository: str
    default_branch: str


@dataclass(frozen=True)
class RepositorySelection:
    info: RepositoryInfo
    branch: str
    base_path: str

    def resolve_path(self, relative_path: str) -> str:
        relative = (relative_path or "").strip("/")
        base = (self.base_path or "").strip("/")
        if base and relative:
            return f"{base}/{relative}"
        if base:
            return base
        return relative


class GitHubClient:
    """Thin wrapper around the GitHub Contents API."""

    def __init__(self, token: str, api_url: str = "https://api.github.com", timeout: float = 10.0) -> None:
        if not token:
            raise GitHubConfigurationError(
                "Configura la variable de entorno GITHUB_TOKEN para habilitar la verificación remota."
            )
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": os.environ.get("GITHUB_USER_AGENT", "PortalKidsVerifier/1.0"),
            }
        )

    @classmethod
    def from_env(cls) -> "GitHubClient":
        token = os.environ.get("GITHUB_TOKEN")
        api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        timeout_value = os.environ.get("GITHUB_TIMEOUT", "10")
        try:
            timeout = float(timeout_value)
        except (TypeError, ValueError):
            timeout = 10.0
        return cls(token=token or "", api_url=api_url, timeout=timeout)

    def get_file_content(self, repository: str, path: str, ref: str | None) -> bytes:
        if not repository:
            raise GitHubConfigurationError("El repositorio de GitHub no está configurado.")
        clean_path = (path or "").strip("/")
        if not clean_path:
            raise GitHubConfigurationError("La ruta solicitada al repositorio de GitHub está vacía.")
        quoted_path = quote(clean_path, safe="/")
        url = f"{self.api_url}/repos/{repository}/contents/{quoted_path}"
        params = {"ref": ref} if ref else None
        headers = {"Accept": "application/vnd.github.v3.raw"}
        try:
            response = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GitHubDownloadError(
                f"No se pudo conectar con GitHub para leer {repository}:{clean_path}: {exc}",
                repository=repository,
                path=clean_path,
                ref=ref or "",
            ) from exc
        if response.status_code == 404:
            raise GitHubFileNotFoundError(
                f"No se encontró {repository}:{clean_path} en la rama {ref or 'predeterminada'}.",
                repository=repository,
                path=clean_path,
                ref=ref or "",
            )
        if response.status_code >= 400:
            details: str
            try:
                payload = response.json()
                details = payload.get("message") or response.text
            except ValueError:
                details = response.text
            raise GitHubDownloadError(
                (
                    f"GitHub respondió {response.status_code} al leer "
                    f"{repository}:{clean_path} (rama {ref or 'predeterminada'}): {details}"
                ),
                repository=repository,
                path=clean_path,
                ref=ref or "",
            )
        return response.content


def determine_student_repositories(slug: str, role: str | None = None) -> Dict[str, RepositoryInfo]:
    slug_lower = (slug or "").lower()
    role_lower = (role or "").lower()

    keys: list[str] = []
    if _matches_ventas(slug_lower) or _matches_ventas(role_lower):
        keys.append("ventas")
    if _matches_operaciones(slug_lower) or _matches_operaciones(role_lower):
        keys.append("operaciones")

    if not keys:
        keys = [key for key in ("ventas", "operaciones") if _env_repository_configured(key)]

    repositories: Dict[str, RepositoryInfo] = {}
    for key in keys:
        info = _build_repository_info(key)
        repositories[key] = info

    if not repositories:
        raise GitHubConfigurationError(
            "No hay repositorios de GitHub configurados para el estudiante. "
            "Verifica las variables GITHUB_VENTAS_REPO y GITHUB_OPERACIONES_REPO."
        )
    return repositories


def select_repository_for_contract(
    source_config: dict | None,
    slug: str,
    repositories: Dict[str, RepositoryInfo],
) -> RepositorySelection:
    source = source_config or {}
    requested_key = (source.get("repository") or "default").lower()

    if requested_key == "default":
        if len(repositories) == 1:
            info = next(iter(repositories.values()))
        elif "ventas" in repositories:
            info = repositories["ventas"]
        elif "operaciones" in repositories:
            info = repositories["operaciones"]
        else:
            info = next(iter(repositories.values()))
    else:
        info = repositories.get(requested_key)
        if not info:
            raise GitHubConfigurationError(
                f"El contrato requiere el repositorio '{requested_key}', pero el estudiante no lo tiene asignado."
            )

    branch_env = source.get("branch_env")
    branch_override = os.environ.get(branch_env, "") if branch_env else ""
    branch = branch_override or source.get("branch") or source.get("default_branch") or info.default_branch

    base_path_template = source.get("base_path", "") or ""
    try:
        formatted_base = base_path_template.format(slug=slug)
    except KeyError as exc:  # pragma: no cover - defensive
        raise GitHubConfigurationError(
            f"La plantilla de ruta base '{base_path_template}' es inválida: falta la clave {exc}."
        ) from exc
    base_path = (formatted_base or "").strip("/")

    return RepositorySelection(info=info, branch=branch or info.default_branch, base_path=base_path)


class RepositoryFileAccessor:
    """Provides convenience helpers to access files in a remote repository."""

    def __init__(self, client: GitHubClient, selection: RepositorySelection) -> None:
        self._client = client
        self._selection = selection
        self._cache: Dict[str, bytes] = {}

    @property
    def repository(self) -> str:
        return self._selection.info.repository

    @property
    def branch(self) -> str:
        return self._selection.branch

    def describe_source(self, relative_path: str | None = None) -> str:
        base = f"{self.repository} (rama {self.branch})"
        if relative_path is None:
            return base
        remote_path = self._selection.resolve_path(relative_path)
        if remote_path:
            return f"{base} en {remote_path}"
        return base

    def read_bytes(self, relative_path: str) -> bytes:
        remote_path = self._selection.resolve_path(relative_path)
        if remote_path in self._cache:
            return self._cache[remote_path]
        content = self._client.get_file_content(self.repository, remote_path, self.branch)
        self._cache[remote_path] = content
        return content

    def read_text(self, relative_path: str) -> str:
        return self.read_bytes(relative_path).decode("utf-8")

    def exists(self, relative_path: str) -> bool:
        try:
            self.read_bytes(relative_path)
        except GitHubFileNotFoundError:
            return False
        return True

    def resolve_remote_path(self, relative_path: str) -> str:
        return self._selection.resolve_path(relative_path)


def _matches_ventas(text: str) -> bool:
    if not text:
        return False
    return any(
        token in text
        for token in (
            "ventas",
            "venta",
            "sales",
        )
    ) or text.endswith("-v") or text.endswith("_v") or text.endswith("v")


def _matches_operaciones(text: str) -> bool:
    if not text:
        return False
    return any(
        token in text
        for token in (
            "oper",
            "ops",
            "operaciones",
        )
    ) or text.endswith("-o") or text.endswith("_o") or text.endswith("o")


def _env_repository_configured(key: str) -> bool:
    env_name = f"GITHUB_{key.upper()}_REPO"
    return bool(os.environ.get(env_name))


def _build_repository_info(key: str) -> RepositoryInfo:
    repo_env = f"GITHUB_{key.upper()}_REPO"
    repo_value = (os.environ.get(repo_env) or "").strip()
    if not repo_value:
        raise GitHubConfigurationError(
            f"Configura la variable de entorno {repo_env} para habilitar el repositorio '{key}'."
        )
    branch_env = f"GITHUB_{key.upper()}_BRANCH"
    default_branch = (os.environ.get(branch_env) or "main").strip() or "main"
    return RepositoryInfo(key=key, repository=repo_value, default_branch=default_branch)
