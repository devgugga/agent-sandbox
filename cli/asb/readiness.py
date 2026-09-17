"""cli/asb/readiness.py — sondas tipadas de prontidão observacional.

Implementa ProbeResult, wait_until com monotonic clock, e sondas tipadas
para host, proxy, SSH, keyring e workspaces, conforme o desenho §5.1.
"""
from __future__ import annotations

import errno
import getpass
import os
import shutil
import socket
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Sequence
from time import monotonic, sleep

# Emenda A: o piloto T2 mostrou que `unshare` na rede rootless NAO recupera um
# namespace sem egresso, e que esse mesmo unshare no boot era o que o criava
# quebrado. O unico boot que se recuperou foi aquele em que nada mantinha o
# namespace aberto: ele foi recriado ja com rede. Isso e hipotese, nao prova
# (docs/validation/startup-auth-pilot.md §6.4), e a orientacao diz isso.
DEAD_UPLINK_REMEDIATION = (
    "com a rede do host ativa, suspenda e retome TODOS os workspaces "
    "(asb-agent suspend --workspace <id>; depois asb-agent resume --workspace <id>) "
    "para o namespace rootless ser recriado com rede; hipotese do piloto T2, "
    "ver docs/validation/startup-auth-pilot.md §6.4"
)


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
            return ProbeResult("host", "unreachable", "no_route", elapsed, "sem rota ate o destino; verifique a conexao de rede do host")
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
            return ProbeResult("proxy", "unreachable", "no_route", elapsed, DEAD_UPLINK_REMEDIATION)
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
            return ProbeResult("proxy", "failed", f"http_{code}", elapsed,
                               f"proxy retornou status inesperado; veja "
                               f"podman logs --tail 50 {proxy_host}")

        if res.returncode != 0 and not output.strip():
            return ProbeResult("proxy", "unreachable", "proxy_unreachable", elapsed, "proxy nao respondeu na porta 3128")

        # A remediacao vai para o stderr do operador e para o journal:
        # saida capturada nunca entra nela (§ credenciais da revisao final).
        return ProbeResult("proxy", "failed", "unknown_response", elapsed,
                           f"resposta desconhecida do proxy; veja "
                           f"podman logs --tail 50 {proxy_host}")
    except subprocess.TimeoutExpired:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("proxy", "unreachable", "timeout", elapsed, "timeout na sonda de egresso do proxy")
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("proxy", "failed", "exec_error", elapsed, str(exc))


def probe_ssh(
    port: int,
    user: str | None = None,
    key: Path | None = None,
    timeout: float = 5.0,
) -> ProbeResult:
    """Executa 'true' via SSH com chave e porta informadas.

    `user` omitido resolve para o usuario real do host (`getpass.getuser()`),
    NUNCA para um nome literal: a imagem base e construida espelhando
    `id -un` do host (`lifecycle.build`) e `emit` publica esse mesmo nome no
    JSON de conexao. Um default literal fazia a sonda discar como outro
    usuario em toda maquina cujo operador nao se chamasse assim — inclusive
    dentro do ExecStartPost gravado em disco por `--runtime systemd`, onde a
    falha marca como failed um container saudavel.
    """
    started = monotonic()
    if user is None:
        user = getpass.getuser()
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
        ok, label, fix = check_keyring_service(container, timeout=timeout)
        elapsed = int((monotonic() - started) * 1000)
        if ok:
            return ProbeResult("keyring", "healthy", "ok", elapsed, "")
        state = "unreachable" if ("parado" in label or "ausente" in label) else "failed"
        code = "keyring_stopped" if "parado" in label else "keyring_unavailable"
        return ProbeResult("keyring", state, code, elapsed, fix)
    except Exception as exc:
        elapsed = int((monotonic() - started) * 1000)
        return ProbeResult("keyring", "failed", "keyring_error", elapsed, str(exc))


def probe_host_ports(agent_container: str, ports: Sequence[int],
                     timeout: float = 5.0) -> ProbeResult:
    """Prova que cada porta de `[docker] host_ports` tem listener no agente.

    O entrypoint sobe um `socat` por porta declarada, em segundo plano. Sem
    esta sonda o `up` imprimia o JSON de conexao com a porta prometida ao
    projeto simplesmente ausente — o servico "nao esta la" e nada reprova.
    """
    started = monotonic()
    if not ports:
        return ProbeResult("host_ports", "healthy", "ok", 0, "")
    podman_bin = shutil.which("podman") or "podman"
    missing: list[int] = []
    for port in ports:
        try:
            res = subprocess.run(
                # bash, nao sh: /dev/tcp e recurso do bash, e o `sh` da
                # imagem (dash) falha SEMPRE — a sonda reprovaria um listener
                # saudavel.
                [podman_bin, "exec", "-u", "1000", agent_container, "bash", "-c",
                 f"exec 3<>/dev/tcp/127.0.0.1/{int(port)}"],
                capture_output=True, text=True, timeout=timeout)
            if res.returncode != 0:
                missing.append(int(port))
        except subprocess.TimeoutExpired:
            missing.append(int(port))
    elapsed = int((monotonic() - started) * 1000)
    if missing:
        listed = ", ".join(str(p) for p in missing)
        return ProbeResult(
            "host_ports", "failed", "no_listener", elapsed,
            f"sem listener para as portas declaradas em host_ports: {listed}; "
            f"veja 'podman logs --tail 50 {agent_container}'")
    return ProbeResult("host_ports", "healthy", "ok", elapsed, "")


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
