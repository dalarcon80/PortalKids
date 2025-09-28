"""Helpers to resolve student mission files directly from GitHub."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable
from urllib.parse import quote


class GitHubConfigurationError(RuntimeError):
    """Raised when GitHub integration is misconfigured."""


try:  # pragma: no cover - optional dependency
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    class _MissingRequestsException(GitHubConfigurationError):
        """Raised when the optional 'requests' dependency is unavailable."""

    class _MissingRequestsSession:
        def __init__(self, *args, **kwargs) -> None:
            raise _MissingRequestsException(
                "El cliente de GitHub requiere la dependencia opcional 'requests'. "
                "Instálala para habilitar las descargas remotas."
            )

    class _MissingRequestsModule:
        RequestException = _MissingRequestsException

        def Session(self, *args, **kwargs):  # type: ignore[override]
            return _MissingRequestsSession(*args, **kwargs)

    requests = _MissingRequestsModule()  # type: ignore[assignment]


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
                "Configura la integración de GitHub desde el panel administrativo o define la variable de entorno GITHUB_TOKEN."
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

    @classmethod
    def from_settings(cls) -> "GitHubClient":
        try:
            from . import app as app_module  # type: ignore
        except ImportError:  # pragma: no cover - fallback for direct execution
            import app as app_module  # type: ignore

        settings = app_module.load_service_settings(
            ["github_token", "github_api_url", "github_timeout"]
        )
        token = settings.get("github_token") or os.environ.get("GITHUB_TOKEN")
        api_url = (
            settings.get("github_api_url")
            or os.environ.get("GITHUB_API_URL")
            or "https://api.github.com"
        )
        timeout_value = (
            settings.get("github_timeout")
            or os.environ.get("GITHUB_TIMEOUT")
            or "10"
        )
        try:
            timeout = float(timeout_value) if timeout_value is not None else 10.0
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

    def download_workspace(
        self,
        selection: RepositorySelection,
        paths: Iterable[str],
        destination: str | os.PathLike[str],
    ) -> None:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        for entry in paths:
            normalized = self._normalize_workspace_entry(entry)
            if not normalized:
                continue
            try:
                self._download_workspace_path(selection, normalized, root)
            except GitHubFileNotFoundError as exc:
                raise GitHubFileNotFoundError(
                    exc.args[0],
                    repository=selection.info.repository,
                    path=normalized,
                    ref=selection.branch,
                ) from exc

    def _download_workspace_path(
        self,
        selection: RepositorySelection,
        relative_path: str,
        destination_root: Path,
    ) -> None:
        repository = selection.info.repository
        remote_path = selection.resolve_path(relative_path)
        metadata = self._fetch_contents_metadata(
            repository,
            remote_path,
            selection.branch,
            relative_label=relative_path,
        )

        if isinstance(metadata, list):
            destination_root.joinpath(*PurePosixPath(relative_path).parts).mkdir(
                parents=True, exist_ok=True
            )
            for item in metadata:
                name = item.get("name")
                if not name:
                    continue
                child_relative = "/".join(filter(None, [relative_path, name]))
                self._download_workspace_path(selection, child_relative, destination_root)
            return

        content_type = metadata.get("type")
        if content_type == "dir":
            listing = self._fetch_contents_metadata(
                repository,
                remote_path,
                selection.branch,
                relative_label=relative_path,
            )
            if isinstance(listing, list):
                destination_root.joinpath(*PurePosixPath(relative_path).parts).mkdir(
                    parents=True, exist_ok=True
                )
                for item in listing:
                    name = item.get("name")
                    if not name:
                        continue
                    child_relative = "/".join(filter(None, [relative_path, name]))
                    self._download_workspace_path(selection, child_relative, destination_root)
                return
            raise GitHubDownloadError(
                f"No se pudo listar el contenido de {repository}:{remote_path}",
                repository=repository,
                path=remote_path,
                ref=selection.branch,
            )

        if content_type == "file":
            content = self.get_file_content(repository, remote_path, selection.branch)
            destination = destination_root.joinpath(*PurePosixPath(relative_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return

        raise GitHubDownloadError(
            f"Tipo de contenido no soportado al descargar {repository}:{remote_path} ({content_type}).",
            repository=repository,
            path=remote_path,
            ref=selection.branch,
        )

    def _fetch_contents_metadata(
        self,
        repository: str,
        path: str,
        ref: str,
        *,
        relative_label: str,
    ):
        clean_path = (path or "").strip("/")
        url = f"{self.api_url}/repos/{repository}/contents/{quote(clean_path, safe='/')}"
        params = {"ref": ref} if ref else None
        headers = {"Accept": "application/vnd.github.v3+json"}
        try:
            response = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GitHubDownloadError(
                f"No se pudo conectar con GitHub para listar {repository}:{clean_path}: {exc}",
                repository=repository,
                path=clean_path,
                ref=ref,
            ) from exc
        if response.status_code == 404:
            raise GitHubFileNotFoundError(
                f"No se encontró {relative_label} en el repositorio {repository} (rama {ref}).",
                repository=repository,
                path=relative_label,
                ref=ref,
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
                    f"GitHub respondió {response.status_code} al listar "
                    f"{repository}:{clean_path} (rama {ref}): {details}"
                ),
                repository=repository,
                path=clean_path,
                ref=ref,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubDownloadError(
                f"GitHub devolvió una respuesta inválida al listar {repository}:{clean_path}.",
                repository=repository,
                path=clean_path,
                ref=ref,
            ) from exc

    @staticmethod
    def _normalize_workspace_entry(entry: str | None) -> str | None:
        candidate = PurePosixPath(entry or "")
        parts: list[str] = []
        for part in candidate.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("workspace_paths no permite rutas relativas ascendentes")
            parts.append(part)
        if not parts:
            return None
        return "/".join(parts)


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
    *,
    role: str | None = None,
    mission_roles: Iterable[str] | None = None,
) -> RepositorySelection:
    source = source_config or {}
    requested_value = source.get("repository") or "default"
    requested_key = str(requested_value).strip().lower() or "default"
    prefer_by_role = bool(source.get("prefer_repository_by_role"))

    role_lower = (role or "").strip().lower()
    slug_lower = (slug or "").strip().lower()

    if isinstance(mission_roles, str):
        mission_role_values: Iterable[str] = [mission_roles]
    elif mission_roles is None:
        mission_role_values = []
    else:
        mission_role_values = mission_roles

    def _match_repository_from_value(value: str) -> str | None:
        if not value:
            return None
        if _matches_ventas(value) and "ventas" in repositories:
            return "ventas"
        if _matches_operaciones(value) and "operaciones" in repositories:
            return "operaciones"
        return None

    if prefer_by_role and requested_key == "default" and len(repositories) > 1:
        matched_key = _match_repository_from_value(role_lower)
        if matched_key is None:
            matched_key = _match_repository_from_value(slug_lower)
        if matched_key is None:
            for mission_role in mission_role_values:
                normalized = str(mission_role or "").strip().lower()
                matched_key = _match_repository_from_value(normalized)
                if matched_key:
                    break
        if matched_key:
            requested_key = matched_key

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
    branch_override = _normalize_branch(os.environ.get(branch_env)) if branch_env else None
    branch = (
        branch_override
        or _normalize_branch(source.get("branch"))
        or _normalize_branch(source.get("default_branch"))
        or info.default_branch
    )

    base_path_template = source.get("base_path", "") or ""
    try:
        formatted_base = base_path_template.format(slug=slug)
    except KeyError as exc:  # pragma: no cover - defensive
        raise GitHubConfigurationError(
            f"La plantilla de ruta base '{base_path_template}' es inválida: falta la clave {exc}."
        ) from exc
    base_path = (formatted_base or "").strip("/")

    return RepositorySelection(info=info, branch=branch or info.default_branch, base_path=base_path)


def _normalize_branch(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


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

    def download_workspace(
        self, paths: Iterable[str], destination: str | os.PathLike[str]
    ) -> None:
        self._client.download_workspace(self._selection, paths, destination)


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
