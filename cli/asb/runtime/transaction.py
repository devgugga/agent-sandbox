"""cli/asb/runtime/transaction.py — livro-razao de posse de recursos criados
durante a transacao de `up`, e reversao estrita por ID.

Extraido de cli/asb/lifecycle.py (Tarefa 4 da decomposicao de modulos) SEM
mudar comportamento: mesmos metodos, mesma ordem de rollback (containers,
redes, volumes, arquivos sobrescritos, unidades systemd), mesmas mensagens de
aviso. `lifecycle.py` reexporta `WorkspaceTransaction` (mesmo padrao ja usado
para as extracoes anteriores) para quem ja importava daqui.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import podman, supervisor


class WorkspaceTransaction:
    """Rastreia recursos criados durante a transacao de up para rollback estrito por ID."""

    def __init__(self, ws: str, is_existing: bool) -> None:
        self.ws = ws
        self.is_existing = is_existing
        self.created_containers: list[str] = []
        self.created_networks: list[str] = []
        self.created_volumes: list[str] = []
        self.created_units: list[Path] = []
        # Arquivos que existiam ANTES e esta transacao sobrescreveu: a espera
        # por rede e compartilhada por todos os workspaces, entao um `up` que
        # falha nao pode deixar a versao dele no lugar.
        self.overwritten: list[tuple[Path, str]] = []

    def record_container(self, container_id: str) -> None:
        if container_id and container_id not in self.created_containers:
            self.created_containers.append(container_id)

    def record_network(self, network_name: str) -> None:
        if network_name and network_name not in self.created_networks:
            self.created_networks.append(network_name)

    def record_volume(self, volume_name: str) -> None:
        if volume_name and volume_name not in self.created_volumes:
            self.created_volumes.append(volume_name)

    def record_unit(self, unit_path: Path) -> None:
        if unit_path and unit_path not in self.created_units:
            self.created_units.append(unit_path)

    def record_restore(self, path: Path, previous: str) -> None:
        if path and all(path != p for p, _ in self.overwritten):
            self.overwritten.append((path, previous))

    def rollback(self) -> None:
        # Falha em workspace existente NUNCA executa sweep destrutivo de containers preexistentes
        if self.is_existing:
            return

        # Rollback atinge EXCLUSIVAMENTE os IDs dos recursos criados nesta transacao
        for cid in self.created_containers:
            podman.run("rm", "-f", cid, check=False)

        for net in self.created_networks:
            if podman.exists("network", net):
                podman.run("network", "rm", "-f", net, check=False)

        for vol in self.created_volumes:
            if podman.exists("volume", vol):
                podman.run("volume", "rm", "-f", vol, check=False)

        for path, previous in self.overwritten:
            try:
                path.write_text(previous, encoding="utf-8")
            except OSError as exc:
                print(f"aviso: falha ao restaurar {path} durante rollback: {exc}",
                      file=sys.stderr)

        if self.created_units:
            try:
                supervisor.remove_workspace_units(self.ws)
            except Exception as exc:
                # Nunca silenciar: uma falha aqui deixa unidades systemd
                # orfas apontando para containers que o rollback acabou de
                # remover. O rollback continua (o erro original de `up`
                # segue tendo prioridade), mas o operador precisa saber.
                print(
                    f"aviso: falha ao remover unidades systemd de '{self.ws}' "
                    f"durante rollback: {exc}",
                    file=sys.stderr,
                )
