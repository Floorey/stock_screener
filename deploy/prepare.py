"""Create private, local runtime config once; never overwrite credentials."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def prepare(address):
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not any(ip in ipaddress.ip_network(cidr) for cidr in
                                  ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise ValueError("LAN-Adresse muss eine private IPv4-Adresse sein")
    runtime = ROOT / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    os.chmod(runtime, 0o700)
    if any((runtime / name).exists() for name in ("runtime.env", "Caddyfile", "access.txt")):
        raise FileExistsError("Runtime existiert bereits; keine Zugangsdaten überschrieben")
    password = secrets.token_urlsafe(24)
    db_password = secrets.token_urlsafe(32)
    hashed = subprocess.run(
        ["docker", "run", "--rm", "-i", "caddy:2", "caddy", "hash-password"],
        input=password + "\n", text=True, capture_output=True, check=True,
    ).stdout.strip()
    files = {
        "runtime.env": f"POSTGRES_PASSWORD={db_password}\n"
                       f"ANALYTICS_DATABASE_URL=postgresql://analytics:{db_password}@127.0.0.1:15439/analytics\n"
                       "ALPACA_BASE_URL=https://paper-api.alpaca.markets\n"
                       "ALPACA_TRADING_ENABLED=false\n"
                       "TIMELINE_BASE_URL=http://127.0.0.1:8081\n",
        "Caddyfile": "{\n    admin off\n    auto_https disable_redirects\n}\n"
                     f"https://{address}:8443 {{\n    bind {address}\n    tls internal\n"
                     f"    basic_auth {{\n        operator {hashed}\n    }}\n"
                     "    reverse_proxy 127.0.0.1:8501\n}\n",
        "access.txt": f"URL: https://{address}:8443\nBenutzer: operator\nPasswort: {password}\n",
    }
    for name, content in files.items():
        fd = os.open(runtime / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
    print("Private Konfiguration in .runtime erstellt; Zugang in .runtime/access.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan-address", required=True)
    prepare(parser.parse_args().lan_address)
