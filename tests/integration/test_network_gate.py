"""Integracao real: a espera por rede segura unidades dependentes (Emenda A §7.1).

Sem Podman. Duas unidades de usuario isoladas pela SandboxFixture: a espera,
sondando uma porta TCP local ainda fechada, e uma dependente com `Requires=` e
`After=` nela. A dependente nao pode partir enquanto a porta esta fechada, e
deve partir sozinha quando um listener aparece.
"""
from __future__ import annotations

import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
sys.path.insert(0, str(ROOT))
from asb import supervisor  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _is_active(unit: str) -> str:
    return subprocess.run(["systemctl", "--user", "is-active", unit],
                          capture_output=True, text=True).stdout.strip()


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return predicate()


def _user_manager_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(["systemctl", "--user", "show-environment"],
                          capture_output=True).returncode == 0


@unittest.skipUnless(_user_manager_available(), "requer systemd de usuario")
class TestNetworkGateHoldsDependents(unittest.TestCase):
    def test_dependent_waits_while_probe_fails_and_starts_when_network_appears(self):
        port = _free_port()
        with SandboxFixture("netgate", auto_setup=False) as fx:
            gate_unit = fx.register_unit(f"{fx._prefix}-network.service")
            dep_unit = fx.register_unit(f"{fx._prefix}-dep.service")
            fx.state_root.mkdir(parents=True, exist_ok=True)

            wrapper = fx.state_root / "network_gate_wrapper.py"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'cli')!r})\n"
                "from asb.network_gate import main\n"
                "sys.exit(main())\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)

            (fx._unit_dir / gate_unit).write_text(
                supervisor.render_network_unit(wrapper, target=f"127.0.0.1:{port}"),
                encoding="utf-8",
            )
            (fx._unit_dir / dep_unit).write_text(
                "[Unit]\n"
                f"Requires={gate_unit}\n"
                f"After={gate_unit}\n"
                "\n"
                "[Service]\n"
                "Type=exec\n"
                "ExecStart=/usr/bin/sleep 300\n",
                encoding="utf-8",
            )
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "start", "--no-block", dep_unit], check=True)

            # Porta fechada: a espera fica ativando e a dependente nao parte.
            self.assertTrue(_wait_for(lambda: _is_active(gate_unit) == "activating", 15.0),
                            _is_active(gate_unit))
            time.sleep(6.0)
            self.assertEqual(_is_active(gate_unit), "activating")
            self.assertNotEqual(_is_active(dep_unit), "active")

            server = socketserver.TCPServer(("127.0.0.1", port), socketserver.BaseRequestHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertTrue(_wait_for(lambda: _is_active(dep_unit) == "active", 30.0),
                                f"gate={_is_active(gate_unit)} dep={_is_active(dep_unit)}")
                self.assertEqual(_is_active(gate_unit), "active")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
