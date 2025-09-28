import pytest


import backend.github_client as github_client


class _SessionFailure:
    def __init__(self, *args, **kwargs):
        raise github_client.GitHubConfigurationError("session unavailable")


def test_github_client_session_failure_surface(monkeypatch):
    monkeypatch.setattr(github_client.requests, "Session", _SessionFailure)
    with pytest.raises(github_client.GitHubConfigurationError) as exc:
        github_client.GitHubClient(token="token")
    assert "session unavailable" in str(exc.value)


def test_github_client_from_env_session_failure(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token-env")
    monkeypatch.setenv("GITHUB_API_URL", "https://example.invalid")
    monkeypatch.setenv("GITHUB_TIMEOUT", "5")
    monkeypatch.setattr(github_client.requests, "Session", _SessionFailure)
    with pytest.raises(github_client.GitHubConfigurationError):
        github_client.GitHubClient.from_env()


def test_select_repository_for_contract_strips_branch_overrides(monkeypatch):
    repositories = {
        "ventas": github_client.RepositoryInfo(
            key="ventas", repository="org/repo", default_branch="main"
        )
    }
    monkeypatch.setenv("CUSTOM_BRANCH", "   ")
    selection = github_client.select_repository_for_contract(
        {
            "repository": "ventas",
            "branch_env": "CUSTOM_BRANCH",
            "branch": " \n ",
            "default_branch": "\t",
        },
        slug="student-x",
        repositories=repositories,
    )
    assert selection.branch == "main"


def test_select_repository_for_contract_prefers_role_when_enabled():
    repositories = {
        "ventas": github_client.RepositoryInfo(
            key="ventas", repository="org/ventas", default_branch="main"
        ),
        "operaciones": github_client.RepositoryInfo(
            key="operaciones", repository="org/operaciones", default_branch="main"
        ),
    }

    selection = github_client.select_repository_for_contract(
        {"repository": "default", "prefer_repository_by_role": True},
        slug="student",  # slug without hints should fall back to role
        repositories=repositories,
        role="Operaciones",
    )

    assert selection.info.key == "operaciones"

    selection_from_slug = github_client.select_repository_for_contract(
        {"repository": "default", "prefer_repository_by_role": True},
        slug="aprendiz-v",  # sufijo -v coincide con repositorio de ventas
        repositories=repositories,
    )

    assert selection_from_slug.info.key == "ventas"
