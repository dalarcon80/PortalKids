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
