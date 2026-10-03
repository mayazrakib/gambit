import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_DIRECTORY = Path(__file__,).resolve().parents[1]
SERVICE_NAMES = ("gambit.service", "gambit_tunnel.service",)

def escape_unit_path(path: str,) -> str:
    return path.replace(
        "\\",
        "\\\\",
    ).replace(
        '"',
        '\\"',
    ).replace(
        "%",
        "%%",
    )

def render_service(
    template: str,
    package_directory: Path,
    python_executable: str,
    tunnel_executable: str,
) -> str:
    replacements = {
        "@GAMBIT_DIRECTORY@": str(package_directory,),
        "@PYTHON_EXECUTABLE@": python_executable,
        "@TUNNEL_EXECUTABLE@": tunnel_executable,
    }

    for placeholder, replacement in replacements.items():
        template = template.replace(
            placeholder,
            escape_unit_path(replacement,),
        )

    return template

def main() -> None:
    tunnel_executable = shutil.which("tunnel-client",)

    if tunnel_executable is None or shutil.which("systemctl",) is None:
        raise SystemExit("Install tunnel-client and systemd before installing the services.",)

    environment_path = PACKAGE_DIRECTORY / ".env"

    if not environment_path.is_file():
        raise SystemExit("Create the package-local .env from .env.example before installing the services.",)

    environment_path.chmod(0o600,)
    configuration_directory = Path(os.environ.get(
        "XDG_CONFIG_HOME",
        str(Path.home() / ".config",),
    ),)
    service_directory = configuration_directory / "systemd" / "user"
    service_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for service_name in SERVICE_NAMES:
        template = (PACKAGE_DIRECTORY / "deploy" / service_name).read_text()
        rendered = render_service(
            template,
            PACKAGE_DIRECTORY,
            sys.executable,
            tunnel_executable,
        )
        destination = service_directory / service_name

        if destination.exists() and str(PACKAGE_DIRECTORY,) not in destination.read_text():
            raise SystemExit(f"Refusing to overwrite an unrelated service: {service_name}.",)

        destination.write_text(rendered,)

    subprocess.run(
        ["systemctl", "--user", "daemon-reload",],
        check=True,
    )
    subprocess.run(
        ["systemctl", "--user", "enable", *SERVICE_NAMES,],
        check=True,
    )
    subprocess.run(
        ["systemctl", "--user", "restart", *SERVICE_NAMES,],
        check=True,
    )
    print("Gambit and its OpenAI tunnel services are installed and enabled.",)

if __name__ == "__main__":
    main()
