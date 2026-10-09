import os
import subprocess
import sys
from pathlib import Path

import pytest

from gambit.infrastructure import configuration
from scripts.install_services import render_service

def test_dotenv_is_package_local_and_preserves_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_directory = tmp_path / "gambit"
    module_path = package_directory / "src" / "gambit" / "infrastructure" / "configuration.py"
    module_path.parent.mkdir(parents=True,)
    (tmp_path / ".env").write_text("GAMBIT_TEST_PARENT=parent\n",)
    (package_directory / ".env").write_text("GAMBIT_TEST_LOCAL=package\nGAMBIT_TEST_OVERRIDE=package\n",)
    monkeypatch.setattr(
        configuration,
        "__file__",
        str(module_path,),
    )
    monkeypatch.delenv(
        "GAMBIT_TEST_PARENT",
        raising=False,
    )
    monkeypatch.delenv(
        "GAMBIT_TEST_LOCAL",
        raising=False,
    )
    monkeypatch.setenv(
        "GAMBIT_TEST_OVERRIDE",
        "existing",
    )
    configuration.load_package_environment()
    assert os.environ["GAMBIT_TEST_LOCAL"] == "package"
    assert os.environ["GAMBIT_TEST_OVERRIDE"] == "existing"
    assert "GAMBIT_TEST_PARENT" not in os.environ

def test_missing_package_dotenv_does_not_search_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_path = tmp_path / "gambit" / "src" / "gambit" / "infrastructure" / "configuration.py"
    module_path.parent.mkdir(parents=True,)
    (tmp_path / ".env").write_text("GAMBIT_TEST_PARENT=parent\n",)
    monkeypatch.setattr(
        configuration,
        "__file__",
        str(module_path,),
    )
    monkeypatch.delenv(
        "GAMBIT_TEST_PARENT",
        raising=False,
    )
    configuration.load_package_environment()
    assert "GAMBIT_TEST_PARENT" not in os.environ

def test_service_templates_keep_credentials_out_of_arguments() -> None:
    package_directory = Path(__file__,).resolve().parents[1]
    template = (package_directory / "deploy" / "gambit_tunnel.service").read_text()
    rendered = render_service(
        template,
        package_directory,
        "/venv/bin/python",
        "/bin/tunnel-client",
    )
    assert f"EnvironmentFile={package_directory}/.env" in rendered
    assert "env:OPENAI_API_KEY" in rendered
    assert "Restart=on-failure" in rendered
    assert "@TUNNEL_EXECUTABLE@" not in rendered
    assert "sk-proj-" not in rendered

@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "192.168.1.10",],
)
def test_http_rejects_network_listeners(host: str,) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "gambit.main", "serve", "--transport", "streamable-http", "--host", host,],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 2
    assert "loopback" in process.stderr
