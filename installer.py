import base64
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from colorama import Fore, Style, init

init(autoreset=True)

VERSION = "1.3.3"
APP_NAME = "ov-panel"
INSTALL_DIR = Path(f"/opt/{APP_NAME}")
REPO = "anonysec/ov"
REPO_SUBDIR = "panel"
MAIN_TARBALL_URL = f"https://github.com/{REPO}/archive/refs/heads/main.tar.gz"


def create_secret_key(length: int = 64) -> str:
    return base64.b64encode(secrets.token_bytes(length)).decode("utf-8").rstrip("=")


def safe_clear() -> None:
    subprocess.run("clear", shell=True, check=False)


def get_server_ip() -> str:
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, check=True)
        ips = result.stdout.strip().split()
        return ips[0] if ips else "your-server-ip"
    except Exception:
        return "your-server-ip"


def get_uv_path() -> str:
    for candidate in (
        shutil.which("uv"),
        os.path.expanduser("~/.local/bin/uv"),
        "/root/.local/bin/uv",
        "/usr/local/bin/uv",
        "/usr/bin/uv",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "uv"


def command_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = f"{os.path.expanduser('~/.local/bin')}:/root/.local/bin:{env.get('PATH', '')}"
    return env


def run_command(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, env=command_env(), check=check)


def download_latest_tarball(filename: str) -> None:
    # Prefer the latest GitHub release, fallback to main branch.
    api = f"https://api.github.com/repos/{REPO}/releases/latest"
    url = ""
    try:
        result = subprocess.run(
            ["bash", "-lc", f"curl -fsSL {api!r} | grep '\"tarball_url\"' | cut -d '\"' -f 4"],
            capture_output=True,
            text=True,
            check=False,
        )
        url = result.stdout.strip()
    except Exception:
        url = ""
    if not url:
        url = MAIN_TARBALL_URL
    run_command(["curl", "-L", "--fail", "-o", filename, url])


def extract_repo_subdir(tarball: str, subdir: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            parts = member.name.split("/", 2)
            if len(parts) < 3 or parts[1] != subdir:
                continue
            member.name = parts[2]
            if member.name:
                members.append(member)
        if not members:
            raise RuntimeError(f"Could not find '{subdir}/' in downloaded source")
        tar.extractall(destination, members)


def display_panel_info(port: str, path: str) -> None:
    server_ip = get_server_ip()
    clean_path = path.strip("/")
    url = f"http://{server_ip}:{port}/{clean_path}" if clean_path else f"http://{server_ip}:{port}/"
    print(f"\n{Fore.CYAN}Access URL: {url}{Style.RESET_ALL}\n")


def ask_user(prompt: str, allow_empty: bool = False, input_type: str = "text") -> str:
    while True:
        try:
            value = getpass.getpass(prompt) if input_type == "password" else input(prompt)
            value = value.strip()
            if not allow_empty and not value:
                print(Fore.RED + "Input cannot be empty. Please try again...")
                time.sleep(1)
                continue
            if input_type == "port" and value:
                try:
                    port = int(value)
                    if not (1 <= port <= 65535):
                        raise ValueError
                except ValueError:
                    print(Fore.RED + "Port must be a number between 1 and 65535.")
                    time.sleep(1)
                    continue
            return value
        except KeyboardInterrupt:
            print(f"\n\n{Fore.GREEN}Thank you for using OV-Panel!{Style.RESET_ALL}\n")
            sys.exit(0)


def ask_password(prompt: str) -> str:
    while True:
        password = ask_user(prompt, input_type="password")
        confirm = ask_user("Confirm password: ", input_type="password")
        if password == confirm:
            return password
        print(Fore.RED + "Passwords do not match. Please try again...")
        time.sleep(1)


def ask_confirmation(prompt: str) -> bool:
    while True:
        value = ask_user(prompt, allow_empty=False).lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print(Fore.RED + "Please enter y or n")


def show_banner() -> None:
    safe_clear()
    print(
        f"""
{Fore.CYAN}
╔════════════════════════╗
║   OVPANEL  v{VERSION}     ║
╚════════════════════════╝
{Style.RESET_ALL}
"""
    )


def show_menu() -> None:
    show_banner()
    print(f"{Fore.YELLOW}Please choose an option:{Style.RESET_ALL}\n")
    print(f"  {Fore.GREEN}[1]{Style.RESET_ALL} Install")
    print(f"  {Fore.CYAN}[2]{Style.RESET_ALL} Update")
    print(f"  {Fore.BLUE}[3]{Style.RESET_ALL} Restart")
    print(f"  {Fore.RED}[4]{Style.RESET_ALL} Uninstall")
    print(f"  {Fore.YELLOW}[5]{Style.RESET_ALL} Exit\n")


def ask_choice() -> str:
    while True:
        choice = ask_user(f"{Fore.YELLOW}Enter your choice: {Style.RESET_ALL}")
        if choice in {"1", "2", "3", "4", "5"}:
            return choice
        print(Fore.RED + "Invalid choice. Please enter 1-5.")
        time.sleep(1)


def default_env() -> str:
    return """# Admin Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin

# UVICORN Settings
HOST=0.0.0.0
URLPATH=dashboard
VITE_URLPATH=dashboard
PORT=9000

### Ssl Configuration
# SSL_KEYFILE="/path/to/keyfile"
# SSL_CERTFILE="/path/to/certfile"

### Development Settings
# DEBUG=INFO
# DOC=True

### Security Settings
JWT_SECRET_KEY="random string here"
JWT_ACCESS_TOKEN_EXPIRES=86400

# SUBSCRIPTION_URL_PREFIX="https://example.com"
# SUBSCRIPTION_PATH="sub"
"""


def write_env(replacements: dict) -> None:
    env_path = Path(".env")
    example_path = Path(".env.example")
    if example_path.exists():
        content = example_path.read_text(encoding="utf-8")
    else:
        content = default_env()

    keys_done = set()
    lines = []
    for line in content.splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in replacements:
            key = match.group(1)
            lines.append(f"{key}={replacements[key]}")
            keys_done.add(key)
        else:
            lines.append(line)
    for key, value in replacements.items():
        if key not in keys_done:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_panel_path(path: str) -> str:
    path = path.strip().strip("/")
    reserved = {"api", "assets", "doc", "openapi.json", "health", "sub"}
    if path in reserved:
        raise ValueError(f"Panel path '{path}' is reserved. Choose another path.")
    if path and not re.fullmatch(r"[A-Za-z0-9._-]+", path):
        raise ValueError("Panel path may only contain letters, numbers, dot, dash and underscore.")
    return path


def setup_panel() -> None:
    try:
        os.chdir(Path(__file__).resolve().parent)
        safe_clear()
        print(f"\n{Fore.YELLOW}OV-Panel Configuration{Style.RESET_ALL}\n")

        username = ask_user(f"{Fore.GREEN}> Panel username: {Style.RESET_ALL}")
        password = ask_password(f"{Fore.RED}> Panel password: {Style.RESET_ALL}")
        port = ask_user(f"{Fore.GREEN}> Panel port number: {Style.RESET_ALL}", input_type="port")
        panel_path = validate_panel_path(
            ask_user(f"{Fore.GREEN}> Panel path (optional): {Style.RESET_ALL}", allow_empty=True)
        )

        write_env(
            {
                "ADMIN_USERNAME": username,
                "ADMIN_PASSWORD": password,
                "PORT": port,
                "URLPATH": panel_path,
                "VITE_URLPATH": panel_path,
                "JWT_SECRET_KEY": create_secret_key(),
            }
        )

        run_command([get_uv_path(), "sync"])
        if not build_frontend():
            print(Fore.RED + "Frontend build failed!" + Style.RESET_ALL)
            return
        apply_migrations()
        start_service()

        safe_clear()
        print(f"\n{Fore.GREEN}Installation Complete!{Style.RESET_ALL}")
        display_panel_info(port, panel_path)
        input(f"{Fore.YELLOW}Press Enter to return to menu...{Style.RESET_ALL}")
        main_menu()
    except Exception as e:
        print(f"\n{Fore.RED}Installation failed: {e}{Style.RESET_ALL}")
        input(f"\n{Fore.YELLOW}Press Enter to return to menu...{Style.RESET_ALL}")
        main_menu()


def refresh_panel() -> None:
    install_dir = INSTALL_DIR
    env_file = install_dir / ".env"
    data_dir = install_dir / "data"
    backup_env = Path("/tmp/ov-panel.env.bak")
    backup_data = Path("/tmp/ov-panel.data.bak")
    tarball = "/tmp/ov-panel-latest.tar.gz"

    if not install_dir.exists():
        print(Fore.RED + "OV-Panel is not installed." + Style.RESET_ALL)
        input("Press Enter to return to menu...")
        main_menu()
        return

    try:
        print(f"\n{Fore.YELLOW}Updating OV-Panel...{Style.RESET_ALL}")
        download_latest_tarball(tarball)

        if env_file.exists():
            shutil.copy2(env_file, backup_env)
        if data_dir.exists():
            shutil.rmtree(backup_data, ignore_errors=True)
            shutil.copytree(data_dir, backup_data)

        shutil.rmtree(install_dir, ignore_errors=True)
        install_dir.mkdir(parents=True, exist_ok=True)
        extract_repo_subdir(tarball, REPO_SUBDIR, install_dir)

        if backup_env.exists():
            shutil.move(str(backup_env), str(env_file))
        if backup_data.exists():
            shutil.rmtree(data_dir, ignore_errors=True)
            shutil.move(str(backup_data), str(data_dir))

        os.chdir(install_dir)
        run_command([get_uv_path(), "sync", "--refresh"])
        if not build_frontend():
            print(Fore.RED + "Frontend build failed!" + Style.RESET_ALL)
            return
        apply_migrations()
        start_service()
        print(f"\n{Fore.GREEN}Update Complete!{Style.RESET_ALL}\n")
        input("Press Enter to return to menu...")
        main_menu()
    except Exception as e:
        print(f"\n{Fore.RED}Update failed: {e}{Style.RESET_ALL}")
        input("Press Enter to return to menu...")
        main_menu()


def restart_panel() -> None:
    if not INSTALL_DIR.exists():
        print(Fore.RED + "OV-Panel is not installed." + Style.RESET_ALL)
        input("Press Enter to return to menu...")
        main_menu()
        return
    try:
        run_command(["systemctl", "restart", "ov-panel"])
        print(Fore.GREEN + "OV-Panel restarted successfully!" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"Restart failed: {e}" + Style.RESET_ALL)
    input("Press Enter to return to menu...")
    main_menu()


def remove_panel() -> None:
    if not INSTALL_DIR.exists():
        print(Fore.RED + "OV-Panel is not installed." + Style.RESET_ALL)
        input("Press Enter to return to menu...")
        main_menu()
        return
    if not ask_confirmation("Do you want to uninstall OV-Panel and remove all data? (y/n): "):
        main_menu()
        return
    stop_service()
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    service_file = Path("/etc/systemd/system/ov-panel.service")
    if service_file.exists():
        service_file.unlink()
    run_command(["systemctl", "daemon-reload"], check=False)
    run_command(["systemctl", "reset-failed"], check=False)
    print(Fore.GREEN + "OV-Panel removed." + Style.RESET_ALL)
    input("Press Enter to return to menu...")
    main_menu()


def build_frontend() -> bool:
    try:
        root = Path.cwd()
        frontend_dir = root / "frontend"
        if not frontend_dir.is_dir():
            frontend_dir = INSTALL_DIR / "frontend"
        if not frontend_dir.is_dir():
            print(Fore.RED + f"Frontend directory not found: {frontend_dir}" + Style.RESET_ALL)
            return False
        print(Fore.YELLOW + f"Building frontend in {frontend_dir}..." + Style.RESET_ALL)
        run_command(["npm", "install"], cwd=frontend_dir)
        run_command(["npm", "run", "build"], cwd=frontend_dir)
        return True
    except Exception as e:
        print(Fore.RED + f"Failed to build frontend: {e}" + Style.RESET_ALL)
        return False


def apply_migrations() -> None:
    current = Path.cwd()
    backend_dir = current / "backend" if (current / "backend").is_dir() else INSTALL_DIR / "backend"
    if not backend_dir.is_dir() or not (backend_dir / "alembic.ini").exists():
        return
    try:
        print(Fore.YELLOW + "Running Alembic migrations..." + Style.RESET_ALL)
        run_command([get_uv_path(), "run", "alembic", "upgrade", "head"], cwd=backend_dir)
        print(Fore.GREEN + "Database migrated successfully!" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"Database migration failed: {e}" + Style.RESET_ALL)


def start_service() -> None:
    service_file = Path("/etc/systemd/system/ov-panel.service")
    uv_bin = get_uv_path()
    service_file.write_text(
        f"""[Unit]
Description=OV-Panel App
After=network.target

[Service]
WorkingDirectory={INSTALL_DIR}
ExecStart={uv_bin} run main.py
Restart=always
RestartSec=5
User=root
Environment="PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
""",
        encoding="utf-8",
    )
    run_command(["systemctl", "daemon-reload"], check=False)
    run_command(["systemctl", "enable", "ov-panel"], check=False)
    run_command(["systemctl", "restart", "ov-panel"], check=False)


def stop_service() -> None:
    run_command(["systemctl", "stop", "ov-panel"], check=False)
    run_command(["systemctl", "disable", "ov-panel"], check=False)


def main_menu() -> None:
    show_menu()
    choice = ask_choice()
    if choice == "1":
        setup_panel()
    elif choice == "2":
        refresh_panel()
    elif choice == "3":
        restart_panel()
    elif choice == "4":
        remove_panel()
    elif choice == "5":
        print(f"\n{Fore.GREEN}Thank you for using OV-Panel!{Style.RESET_ALL}\n")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.GREEN}Thank you for using OV-Panel!{Style.RESET_ALL}\n")
        sys.exit(0)
