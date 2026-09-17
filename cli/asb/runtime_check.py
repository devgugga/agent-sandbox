"""cli/asb/runtime_check.py — entry point para sondas de prontidão do systemd.

Consome um manifesto validado e o papel do container ('proxy', 'agent') ou, para 'keyring', o nome do container.
Retorna 0 se o container estiver saudável e pronto, ou código de erro se falhar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .readiness import probe_host, probe_keyring, probe_proxy, probe_ssh, wait_until


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Runtime readiness check for systemd units")
    parser.add_argument("pos_manifest", nargs="?", default=None, help="Caminho do manifesto runtime.json")
    parser.add_argument("pos_role", nargs="?", default=None, choices=["proxy", "agent", "keyring"], help="Papel do container")
    parser.add_argument("--manifest", dest="manifest", default=None, help="Caminho do manifesto runtime.json")
    parser.add_argument("--role", dest="role", default=None, choices=["proxy", "agent", "keyring"], help="Papel do container")
    parser.add_argument("--container", dest="container", default=None, help="Container do keyring (papel keyring)")

    args = parser.parse_args(argv)

    manifest_path_str = args.manifest or args.pos_manifest
    role = args.role or args.pos_role

    # Emenda A §5: o keyring singleton nao tem manifesto de workspace. A unidade
    # so fica ativa depois que o Secret Service responde; sem isso, o
    # `After=` do agente esperaria apenas o inicio do processo.
    if role == "keyring":
        if not args.container:
            print("runtime_check [keyring]: --container e obrigatorio", file=sys.stderr)
            return 2
        keyring_res = wait_until(
            lambda t: probe_keyring(container=args.container, timeout=t),
            timeout=30.0,
            interval=1.0,
        )
        if keyring_res.state != "healthy":
            print(f"runtime_check [keyring]: keyring indisponivel: {keyring_res.code} -> {keyring_res.remediation}", file=sys.stderr)
            return 1
        return 0

    if not manifest_path_str or not role:
        print("runtime_check: manifesto e papel (--role proxy|agent) sao obrigatorios", file=sys.stderr)
        return 2

    manifest_file = Path(manifest_path_str).resolve()
    if not manifest_file.is_file():
        print(f"runtime_check: manifesto nao encontrado em {manifest_file}", file=sys.stderr)
        return 2

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"runtime_check: falha ao ler manifesto JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        print("runtime_check: manifesto invalido ou schemaVersion != 1", file=sys.stderr)
        return 2

    ws = manifest.get("workspace", "")
    containers = manifest.get("containers", {})

    for var in (
        "ASB_CONFIG_ROOT",
        "ASB_KEYRING_CONTAINER",
        "ASB_CREDENTIALS_VOLUME",
        "ASB_TOOLCACHE_VOLUME",
        "ASB_KEYRING_DATA_VOLUME",
        "ASB_KEYRING_RUNTIME_VOLUME",
        "ASB_KEYRING_PASS_FILE",
    ):
        if var in manifest and manifest[var]:
            os.environ[var] = str(manifest[var])
    if "config_dir" in manifest and manifest["config_dir"]:
        os.environ["ASB_CONFIG_ROOT"] = str(manifest["config_dir"])
    if "keyring_container" in manifest and manifest["keyring_container"]:
        os.environ["ASB_KEYRING_CONTAINER"] = str(manifest["keyring_container"])
    ssh_key_path = Path(manifest["ssh_key"]) if "ssh_key" in manifest and manifest["ssh_key"] else None

    # Resolver nomes dos containers a partir do manifesto ou padrão
    proxy_info = containers.get("proxy", {})
    proxy_name = (
        proxy_info.get("name")
        if isinstance(proxy_info, dict)
        else (proxy_info if isinstance(proxy_info, str) else "")
    ) or f"asb-{ws}-proxy"

    agent_info = containers.get("agent", {})
    agent_name = (
        agent_info.get("name")
        if isinstance(agent_info, dict)
        else (agent_info if isinstance(agent_info, str) else "")
    ) or f"asb-{ws}-agent"

    ssh_port = None
    if isinstance(agent_info, dict) and "port" in agent_info:
        ssh_port = int(agent_info["port"])

    if role == "proxy":
        # Sonda do Host: rota utilizável + TCP/TLS até destino de controle (limite 90s)
        host_res = wait_until(lambda t: probe_host(timeout=t), timeout=90.0, interval=1.0)
        if host_res.state != "healthy":
            print(f"runtime_check [proxy]: sonda de host falhou: {host_res.code} -> {host_res.remediation}", file=sys.stderr)
            return 1

        # Sonda do Proxy: CONNECT local até destino (limite 30s)
        proxy_res = wait_until(
            lambda t: probe_proxy(agent_container="", proxy_container=proxy_name, timeout=t),
            timeout=30.0,
            interval=1.0,
        )
        if proxy_res.state != "healthy":
            print(f"runtime_check [proxy]: sonda de proxy falhou: {proxy_res.code} -> {proxy_res.remediation}", file=sys.stderr)
            return 1

        return 0

    elif role == "agent":
        # 1. Proxy CONNECT a partir do agente (limite 30s)
        proxy_res = wait_until(
            lambda t: probe_proxy(agent_container=agent_name, proxy_container=proxy_name, timeout=t),
            timeout=30.0,
            interval=1.0,
        )
        if proxy_res.state != "healthy":
            print(f"runtime_check [agent]: proxy indisponivel: {proxy_res.code} -> {proxy_res.remediation}", file=sys.stderr)
            return 1

        # 2. Keyring Secret Service (limite 10s)
        keyring_res = wait_until(
            lambda t: probe_keyring(container=manifest.get("keyring_container"), timeout=t),
            timeout=10.0,
            interval=1.0,
        )
        if keyring_res.state != "healthy":
            print(f"runtime_check [agent]: keyring indisponivel: {keyring_res.code} -> {keyring_res.remediation}", file=sys.stderr)
            return 1

        # 3. SSH executa true (limite 30s)
        if ssh_port is None:
            # Tentar resolver porta a partir de inspect/port se não veio no manifesto
            from . import podman
            try:
                mapping = podman.out("port", agent_name, "22")
                if mapping:
                    ssh_port = int(mapping.splitlines()[0].rsplit(":", 1)[-1])
            except Exception:
                pass

        if ssh_port is None:
            print("runtime_check [agent]: porta SSH nao encontrada para o agente", file=sys.stderr)
            return 1

        ssh_res = wait_until(
            lambda t: probe_ssh(port=ssh_port, key=ssh_key_path, timeout=t),
            timeout=30.0,
            interval=1.0,
        )
        if ssh_res.state != "healthy":
            print(f"runtime_check [agent]: sonda SSH falhou: {ssh_res.code} -> {ssh_res.remediation}", file=sys.stderr)
            return 1

        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
