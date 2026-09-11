import pytest

from colabtranscribe import session


@pytest.fixture(autouse=True)
def isolate_colab_sessions(tmp_path_factory, monkeypatch):
    """Eristä testit kehittäjän omasta ~/.config/colab-cli/sessions.json -tiedostosta."""
    empty_dir = tmp_path_factory.mktemp("isolated_colab_config")
    fake_config = empty_dir / "sessions.json"
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: fake_config)
