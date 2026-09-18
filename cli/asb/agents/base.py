"""cli/asb/agents/base.py — driver base de provedor de agente de IA.

Um `AgentDriver` apenas RETORNA comandos (`LaunchCommand`); ele nunca inicia
um processo, nunca envia um prompt e nunca contata a API de um provedor.
`launch()` e `resume()` sao funcoes puras sobre os dados de entrada. Quem
efetivamente executa o `argv` retornado (com `shell=False`) e um chamador
fora deste modulo.

`probe()` recebe um `run` injetado em vez de chamar `subprocess` diretamente,
para que o driver permaneca testavel sem processos reais e sem tocar em
containers. O contrato esperado do `run` de producao (fora do escopo desta
tarefa): `shell=False`, timeout de `_PROBE_TIMEOUT_SECONDS` segundos por
chamada. `probe()` sempre passa esse timeout explicitamente para `run`.

Nenhum modulo deste pacote importa `asb.auth` ou qualquer outro segredo de
autenticacao nesta etapa.
"""
from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar, Iterable, Mapping

from asb.sessions.model import AgentKind, ProviderSessionId

_PROBE_TIMEOUT_SECONDS = 5.0

# Excecoes que uma chamada de `run()` pode levantar sem indicar um defeito
# do driver: binario ausente, tempo esgotado, ou outro erro de SO ao
# executar o processo. Qualquer outra excecao propaga (nao mascaramos
# defeitos inesperados atras de um "indisponivel").
_PROBE_FAILURE_EXCEPTIONS = (FileNotFoundError, subprocess.TimeoutExpired,
                             TimeoutError, OSError)

RunFn = Callable[..., str]


class ResumeUnsupported(Exception):
    """Levantada quando `resume()` e chamado sem a opcao de resume
    confirmada (por probe() ou pelo estado inicial otimista do driver)."""


@dataclass(frozen=True)
class LaunchCommand:
    """Um comando pronto para execucao externa — nunca executado aqui."""

    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentAvailability:
    """Resultado sanitizado de `probe()`.

    `resume_supported` e o unico valor que o resto do sistema pode usar
    para decidir se oferece resume: e `True` somente quando a opcao de
    resume foi observada no `--help` do binario instalado E o driver tem
    uma fonte de session-id comprovada (`session_id_provable`). Um driver
    nunca anuncia uma capacidade que nao provou.
    """

    available: bool
    version: str | None
    resume_supported: bool
    reason: str


@dataclass(frozen=True)
class SessionEvidence:
    """Instantaneo de CAMINHOS de estado do provedor — nunca conteudo de
    transcript. `scan_root` e o diretorio observado, ou `None` quando o
    provedor nao tem um local de estado comprovado neste host.

    `capture_before()` preenche `known_paths` com o que ja existia.
    `capture_after()` preenche `new_paths` com o que apareceu desde entao.
    """

    scan_root: Path | None
    known_paths: frozenset[Path] = frozenset()
    new_paths: frozenset[Path] = frozenset()


def _first_line(text: str) -> str:
    """Sanitiza a saida de `--version` para a primeira linha apenas."""
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


class AgentDriver(ABC):
    """Driver de um provedor de agente. Subclasses fixam `kind`, `binary`,
    `resume_argv_prefix`, `version_pattern` e `session_id_provable`."""

    kind: ClassVar[AgentKind]
    binary: ClassVar[str]
    resume_argv_prefix: ClassVar[tuple[str, ...]]
    version_pattern: ClassVar[re.Pattern[str]]
    resume_option_pattern: ClassVar[re.Pattern[str]]
    session_id_provable: ClassVar[bool] = True

    def __init__(self, sessions_root: Path | None = None) -> None:
        # Otimista ate que probe() prove o contrario: os testes do brief
        # constroem um driver novo e chamam resume() sem prober antes.
        self._resume_confirmed = True
        # Diretorio de sessoes do provedor COMO CAMINHO DO HOST: o subpath
        # do volume de sessao do workspace que o container monta sobre o
        # diretorio do provedor (ver `lifecycle.SESSION_STATE_DIRS`). Sem
        # padrao no host: `None` significa "nenhuma evidencia", nunca o
        # `~/.codex`/`~/.claude` do operador, cuja sessao pessoal viraria o
        # id de uma sessao do sandbox.
        self._sessions_root = sessions_root

    # -- comandos (nunca executados aqui) --------------------------------

    def launch(self, cwd: Path) -> LaunchCommand:
        """`cwd` nao entra no argv: `LaunchCommand` nao tem campo de cwd
        porque quem executa o comando define o cwd do subprocesso; o
        parametro existe para simetria com `resume()` e uso futuro."""
        return LaunchCommand(argv=(self.binary,))

    def resume(self, cwd: Path, session_id: str) -> LaunchCommand:
        # session_id_provable e um fato ESTATICO do driver (nao depende de
        # probe()): sem uma fonte de session-id comprovada, nao ha id
        # confiavel para colocar neste argv, entao esta checagem roda em
        # toda chamada, antes de qualquer outra coisa — mesmo num driver
        # nunca probado.
        if not self.session_id_provable:
            raise ResumeUnsupported(
                f"{self.kind}: fonte do session-id nao comprovada nesta "
                f"instalacao")
        if not self._resume_confirmed:
            raise ResumeUnsupported(
                f"{self.kind}: resume nao confirmado nesta instalacao")
        validated = ProviderSessionId(session_id)
        return LaunchCommand(argv=(*self.resume_argv_prefix, validated))

    # -- caracterizacao (via runner injetado) ----------------------------

    def probe(self, run: RunFn) -> AgentAvailability:
        try:
            raw_version = run([self.binary, "--version"],
                               timeout=_PROBE_TIMEOUT_SECONDS)
        except _PROBE_FAILURE_EXCEPTIONS as exc:
            self._resume_confirmed = False
            return AgentAvailability(
                available=False, version=None, resume_supported=False,
                reason=f"{self.kind}: falha ao executar --version ({exc})")

        version_line = _first_line(raw_version)
        match = self.version_pattern.match(version_line)
        if match is None:
            self._resume_confirmed = False
            return AgentAvailability(
                available=False, version=None, resume_supported=False,
                reason=(f"{self.kind}: saida de --version nao "
                        f"reconhecida: {version_line!r}"))
        version = match.group(1)

        try:
            raw_help = run([self.binary, "--help"],
                            timeout=_PROBE_TIMEOUT_SECONDS)
        except _PROBE_FAILURE_EXCEPTIONS as exc:
            self._resume_confirmed = False
            return AgentAvailability(
                available=True, version=version, resume_supported=False,
                reason=f"{self.kind}: falha ao executar --help ({exc})")

        option_present = self.resume_option_pattern.search(raw_help) \
            is not None
        resume_supported = option_present and self.session_id_provable
        self._resume_confirmed = resume_supported
        if resume_supported:
            reason = "ok"
        elif not option_present:
            reason = (f"{self.kind}: opcao de resume nao encontrada em "
                       f"--help")
        else:
            reason = (f"{self.kind}: opcao de resume presente, mas a "
                       f"fonte do session-id nao esta comprovada")
        return AgentAvailability(available=True, version=version,
                                  resume_supported=resume_supported,
                                  reason=reason)

    # -- evidencia de sessao (caminhos e metadados, nunca transcript) ----

    def capture_before(self, cwd: Path) -> SessionEvidence:
        root = self._scan_root(cwd)
        return SessionEvidence(scan_root=root, known_paths=self._scan(root))

    def capture_after(self, baseline: SessionEvidence) -> SessionEvidence:
        root = baseline.scan_root
        current = self._scan(root)
        new_paths = frozenset(current - baseline.known_paths)
        return SessionEvidence(scan_root=root, known_paths=current,
                                new_paths=new_paths)

    @abstractmethod
    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        """Zero candidatos ou mais de um candidato retornam `None` — nunca
        adivinha o "mais recente"."""

    def _scan_root(self, cwd: Path) -> Path | None:
        """`None` quando o provedor nao tem um local de estado comprovado
        (ver docs/validation/2026-09-17-agent-session-contracts.md) ou
        quando o driver foi construido sem `sessions_root`."""
        return None

    def _scan(self, root: Path | None) -> frozenset[Path]:
        if root is None or not root.is_dir():
            return frozenset()
        return frozenset(self._list_paths(root))

    def _list_paths(self, root: Path) -> Iterable[Path]:
        return root.glob("*.jsonl")
