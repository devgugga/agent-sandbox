"""cli/asb/podman.py — invólucro fino sobre o binário podman.

Fino de proposito: sem cache, sem estado, sem reintentos escondidos. Todo o
raciocinio de ciclo de vida vive em lifecycle.py, onde da para ler.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class PodmanError(Exception):
    pass


def require_binary() -> str:
    found = shutil.which("podman")
    if not found:
        raise PodmanError("podman nao encontrado no PATH")
    return found


def run(*args: str, check: bool = True,
        capture: bool = False,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    """`timeout`, quando informado, limita o lado do HOST (subprocess.run) e
    levanta `subprocess.TimeoutExpired` se excedido — nao deve ser confundido
    com um `timeout` passado como argumento do proprio comando podman."""
    result = subprocess.run(
        [require_binary(), *args],
        capture_output=capture, text=True,
        stdout=None if capture else subprocess.DEVNULL,
        timeout=timeout)
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise PodmanError(f"podman {' '.join(args)} falhou: {detail}")
    return result


def out(*args: str, timeout: float | None = None) -> str:
    result = subprocess.run([require_binary(), *args], capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode != 0:
        raise PodmanError(
            f"podman {' '.join(args)} falhou: {result.stderr.strip()}")
    return result.stdout.strip()


def json_out(*args: str, timeout: float | None = None) -> Any:
    return json.loads(out(*args, "--format", "json", timeout=timeout))


_KINDS = {"container": "container", "network": "network",
          "image": "image", "volume": "volume"}


def exists(kind: str, name: str, timeout: float | None = None) -> bool:
    if kind not in _KINDS:
        raise PodmanError(f"tipo desconhecido: {kind}")
    return subprocess.run(
        [require_binary(), kind, "exists", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=timeout).returncode == 0


def running(name: str, timeout: float | None = None) -> bool:
    return bool(out("ps", "--filter", f"name=^{name}$", "--filter",
                    "status=running", "--quiet", timeout=timeout))

