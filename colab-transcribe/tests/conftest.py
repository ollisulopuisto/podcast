import pytest

from colabtranscribe import gdrive, onboarding, session


@pytest.fixture(autouse=True)
def isolate_colab_sessions(tmp_path_factory, monkeypatch):
    """Eristä testit kehittäjän omasta ~/.config/colab-cli/sessions.json -tiedostosta."""
    empty_dir = tmp_path_factory.mktemp("isolated_colab_config")
    fake_config = empty_dir / "sessions.json"
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: fake_config)

    # Eristä testit myös käyttäjän omista Google-tunnistetiedostoista ja quota-projekteista
    fake_token = empty_dir / "token.json"
    fake_adc = empty_dir / "adc.json"
    monkeypatch.setattr(gdrive, "COLAB_TOKEN_PATH", fake_token)
    monkeypatch.setattr(gdrive, "ADC_PATH", fake_adc)
    monkeypatch.setenv("COLAB_QUOTA_PROJECT", "test-quota-project")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_bundled_colab: käytä oikeaa onboarding.bundled_colabia"
    )


@pytest.fixture(autouse=True)
def no_bundled_colab(request, monkeypatch):
    """Työtilan ympäristössä on oma ``colab`` (riippuvuus), joten testit
    näkisivät sen PATHin sijaan. Oletuksena sitä ei ole; testi joka mittaa
    juuri sitä merkitään ``real_bundled_colab``."""
    if request.node.get_closest_marker("real_bundled_colab") is None:
        monkeypatch.setattr(onboarding, "bundled_colab", lambda: None)
