"""Run the real UI while denying non-loopback socket connections in this process.

This does not change Windows networking/firewall settings. Browser access to
127.0.0.1 remains available. External source links require an online browser.
"""
import ipaddress
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def check_address(sock, address):
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    host = address[0]
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise OSError(f"Offline demo denies outbound connection: {host}")


def offline_connect(sock, address):
    check_address(sock, address)
    return original_connect(sock, address)


def offline_connect_ex(sock, address):
    check_address(sock, address)
    return original_connect_ex(sock, address)


socket.socket.connect = offline_connect
socket.socket.connect_ex = offline_connect_ex
os.environ["IR_HW1_OFFLINE_DEMO"] = "1"

if __name__ == "__main__":
    from streamlit.web.cli import main
    sys.argv = ["streamlit", "run", str(ROOT / "app.py"), "--server.address", "127.0.0.1", "--server.port", "8501"]
    raise SystemExit(main())
