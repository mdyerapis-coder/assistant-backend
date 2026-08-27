from app.providers import PROVIDERS, available_providers, get_provider


def test_provider_names_are_unique():
    names = [p.name for p in PROVIDERS]
    assert len(names) == len(set(names))


def test_available_providers_filters_on_env(monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(p.api_key_env, raising=False)
    assert available_providers() == []

    monkeypatch.setenv(PROVIDERS[0].api_key_env, "fake-key")
    assert available_providers() == [PROVIDERS[0]]


def test_get_provider_returns_none_when_key_unset(monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(p.api_key_env, raising=False)
    assert get_provider(PROVIDERS[0].name) is None


def test_get_provider_returns_provider_when_key_set(monkeypatch):
    target = PROVIDERS[0]
    monkeypatch.setenv(target.api_key_env, "fake-key")
    assert get_provider(target.name) == target
