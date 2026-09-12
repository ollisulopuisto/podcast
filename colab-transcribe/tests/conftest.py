import pytest

from colabtranscribe import gdrive, session


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
