"""cli/asb/readiness.py — sondas tipadas de prontidão observacional.

Implementa ProbeResult, wait_until com monotonic clock, e sondas tipadas
para host, proxy, SSH, keyring e workspaces, conforme o desenho §5.1.
"""
from __future__ import annotations

import errno
import os
import shutil
import socket
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic, sleep


@dataclass(frozen=True)
class ProbeResult:
    component: str
    state: str       # "healthy", "failed", "unreachable", "process_running", etc.
    code: str        # error or status code
    elapsed_ms: int
    remediation: str


def wait_until(
    probe: Callable[[float], ProbeResult],
    *,
    timeout: float,
    interval: float = 1.0,
) -> ProbeResult:
    """Executa probe repetidamente até que retorne state=='healthy' ou expire o timeout."""
    if timeout <= 0 or interval <= 0:
        raise ValueError("timeout e interval devem ser positivos")
    started = monotonic()
    deadline = started + timeout
    last = ProbeResult("probe", "failed", "timeout", 0, "inspect_component")
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return replace(last, elapsed_ms=int((monotonic() - started) * 1000))
        last = probe(min(5.0, remaining))
        if last.state == "healthy":
            return replace(last, elapsed_ms=int((monotonic() - started) * 1000))
        remaining = deadline - monotonic()
        if remaining <= 0:
            return replace(last, elapsed_ms=int((monotonic() - started) * 1000))
        sleep(min(interval, max(0.0, remaining)))


def probe_host(target: str = "github.com:443", timeout: float = 5.0) -> ProbeResult:
    """Checa rota, TCP e TLS do host até o destino de controle declarado."""
    started = monotonic()
    if ":" in target:
        host, port_str = target.rsplit(":", 1)
        port = int(port_str)
    else:
        host, port = target, 443

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            if port == 443:
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(sock, server_hostname=host):
                    pass
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("host", "healthy", "ok", elapsed, "")
    except socket.gaierror:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("host", "unreachable", "dns_failed", elapsed, "verifique resolucao DNS e conexao de rede")
    except (TimeoutError, socket.timeout):
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("host", "unreachable", "timeout", elapsed, "timeout ao conectar ao destino de controle")
    except ssl.SSLError:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("host", "failed", "tls_failed", elapsed, "falha no handshake TLS com destino")
    except OSError as exc:
        elapsed = int((monotonic() - started) * 1000)
        if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
            return ProbeResult("host", "unreachable", "no_route", elapsed, "podman unshare --rootless-netns true")
        elif exc.errno == errno.ECONNREFUSED:
            return ProbeResult("host", "failed", "connection_refused", elapsed, "conexao recusada pelo destino")
        else:
            return ProbeResult("host", "failed", f"os_error_{exc.errno}", elapsed, f"erro de conexao: {exc}")
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("host", "failed", "unexpected_error", elapsed, str(exc))


def probe_proxy(
    agent_container: str,
    proxy_container: str,
    target: str = "github.com:443",
    timeout: float = 5.0,
) -> ProbeResult:
    """Checa CONNECT através do proxy até o destino declarado."""
    started = monotonic()
    from . import podman

    # Verificar se o proxy está rodando
    try:
        if not podman.running(proxy_container):
            elapsed = int((monotonic() - started) * 1000)
            ws_hint = proxy_container.replace("asb-", "").replace("-proxy", "")
            return ProbeResult(
                "proxy",
                "unreachable",
                "proxy_stopped",
                elapsed,
                f"asb-agent resume --workspace {ws_hint}",
            )
    except Exception:
        pass

    if ":" not in target:
        target = f"{target}:443"

    # Se o container do agente estiver rodando, a sonda roda de dentro dele apontando para o proxy.
    # Para admissão anterior ao agente, roda do próprio proxy apontando para 127.0.0.1:3128.
    source_container = proxy_container
    proxy_host = "127.0.0.1"
    try:
        if agent_container and podman.running(agent_container):
            source_container = agent_container
            proxy_host = proxy_container
    except Exception:
        pass

    target_host, target_port = target.split(":", 1) if ":" in target else (target, "443")
    nc_timeout = max(1, int(timeout))
    podman_bin = shutil.which("podman") or "podman"
    probe_script = (
        f'nc -z -v -w {nc_timeout} -X connect -x {proxy_host}:3128 {target_host} {target_port} 2>&1 || '
        f'(printf "CONNECT {target} HTTP/1.1\\r\\nHost: {target}\\r\\n\\r\\n" | nc -w {nc_timeout} -q 1 {proxy_host} 3128 2>&1)'
    )

    try:
        res = subprocess.run(
            [podman_bin, "exec", source_container, "sh", "-c", probe_script],
            capture_output=True,
            text=True,
            timeout=timeout + 2.0,
        )
        elapsed = int((monotonic() - started) * 1000)
        output = (res.stdout or "") + (res.stderr or "")

        if "Network is unreachable" in output or "Network unreachable" in output:
            return ProbeResult("proxy", "unreachable", "no_route", elapsed, "podman unshare --rootless-netns true")
        if "succeeded" in output or " 200 " in output:
            return ProbeResult("proxy", "healthy", "ok", elapsed, "")
        if " 403 " in output:
            return ProbeResult("proxy", "failed", "connect_denied", elapsed, "adicione o dominio em [network] allow")
        if " 503 " in output:
            return ProbeResult("proxy", "failed", "connect_failed", elapsed, "verifique conectividade do destino ou uplink")
        if "Connection refused" in output:
            return ProbeResult("proxy", "unreachable", "proxy_unreachable", elapsed, f"proxy nao responde em {proxy_host}:3128")

        # Se houve outro código HTTP
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        first_line = lines[0] if lines else ""
        if "HTTP/" in first_line:
            parts = first_line.split()
            code = parts[1] if len(parts) > 1 else "unknown_http"
            return ProbeResult("proxy", "failed", f"http_{code}", elapsed, f"proxy retornou status inesperado: {first_line}")

        if res.returncode != 0 and not output.strip():
            return ProbeResult("proxy", "unreachable", "proxy_unreachable", elapsed, "proxy nao respondeu na porta 3128")

        return ProbeResult("proxy", "failed", "unknown_response", elapsed, output.strip() or "resposta desconhecida do proxy")
    except subprocess.TimeoutExpired:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("proxy", "unreachable", "timeout", elapsed, "timeout na sonda de egresso do proxy")
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("proxy", "failed", "exec_error", elapsed, str(exc))


def probe_ssh(
    port: int,
    user: str = "v",
    key: Path | None = None,
    timeout: float = 5.0,
) -> ProbeResult:
    """Executa 'true' via SSH com chave e porta informadas."""
    started = monotonic()
    if key is None:
        from .lifecycle import SSH_KEY
        key = SSH_KEY

    ssh_cmd = [
        "ssh",
        "-p", str(port),
        "-i", str(key),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={max(1, int(timeout))}",
        "-o", "LogLevel=ERROR",
        f"{user}@127.0.0.1",
        "true",
    ]

    try:
        res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = int((monotonic() - started) * 1000)
        if res.returncode == 0:
            return ProbeResult("ssh", "healthy", "ok", elapsed, "")

        stderr = res.stderr or ""
        if "Permission denied" in stderr or "publickey" in stderr:
            return ProbeResult("ssh", "failed", "key_refused", elapsed, "chave recusada: verifique chave SSH configurada")
        if "Connection refused" in stderr:
            return ProbeResult("ssh", "failed", "connection_refused", elapsed, "conexao recusada: verifique se sshd esta ativo")
        if "timed out" in stderr.lower():
            return ProbeResult("ssh", "unreachable", "timeout", elapsed, "timeout ao conectar via ssh")

        return ProbeResult("ssh", "failed", f"ssh_error_{res.returncode}", elapsed, stderr.strip() or "falha na conexao ssh")
    except subprocess.TimeoutExpired:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("ssh", "unreachable", "timeout", elapsed, "timeout ao executar comando via ssh")
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("ssh", "failed", "exec_error", elapsed, str(exc))


def probe_keyring(container: str | None = None, timeout: float = 5.0) -> ProbeResult:
    """Checa saúde do Secret Service / keyring singleton."""
    started = monotonic()
    try:
        from .lifecycle import check_keyring_service
        ok, label, fix = check_keyring_service(container)
        elapsed = int((monotonic() - started) * 1000)
        if ok:
            return ProbeResult("keyring", "healthy", "ok", elapsed, "")
        state = "unreachable" if ("parado" in label or "ausente" in label) else "failed"
        code = "keyring_stopped" if "parado" in label else "keyring_unavailable"
        return ProbeResult("keyring", state, code, elapsed, fix)
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("keyring", "failed", "keyring_error", elapsed, str(exc))


def probe_workspace(ws: str) -> list[ProbeResult]:
    """Executa o conjunto de probes de prontidão para o workspace informado."""
    results: list[ProbeResult] = []

    # 1. Host probe
    results.append(probe_host())

    # 2. Proxy probe
    from .lifecycle import names
    n = names(ws)
    results.append(probe_proxy(agent_container=n["agent"], proxy_container=n["proxy"]))

    # 3. SSH probe
    from . import podman
    ssh_port: int | None = None
    agent_running = False
    try:
        agent_running = podman.running(n["agent"])
        if agent_running:
            mapping = podman.out("port", n["agent"], "22")
            if mapping:
                ssh_port = int(mapping.splitlines()[0].rsplit(":", 1)[-1])
    except Exception:
        pass

    if ssh_port is not None:
        results.append(probe_ssh(port=ssh_port))
    else:
        results.append(
            ProbeResult(
                "ssh",
                "unreachable",
                "agent_not_running" if not agent_running else "port_not_found",
                0,
                f"asb-agent resume --workspace {ws}",
            )
        )

    # 4. Keyring probe
    results.append(probe_keyring())

    return results
