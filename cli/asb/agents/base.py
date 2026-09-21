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

Alem dos comandos de sessao (`launch`/`resume`), um driver tambem pode expor
as REGRAS de autenticacao do seu fornecedor (Tarefa 2 da decomposicao de
`auth.py`): `parse_auth_status(completed)` interpreta a saida do comando de
status nativo (quando existe: ver `status_command`), `login_argv()` e o
comando de login interativo, e `verify_argv()`/`classify_verification()`
cobrem a chamada real de verificacao e sua classificacao. Nenhuma dessas
tres e `@abstractmethod`: durante a decomposicao (Tarefa 2) um driver por
vez recebe a implementacao, e uma ABC forcaria os tres a migrar juntos. O
padrao default aqui levanta `NotImplementedError` explicito em vez de
deixar a chamada cair num `AttributeError` cru.

`classify_verification` E CONCRETO aqui, nao por driver: o pipeline de
classificacao (rede, limite de taxa, erro de servico) e IDENTICO entre os
tres fornecedores — so os marcadores de evidencia propria
(`auth_evidence_markers`) e o formato de sucesso (`_verify_success`) variam
por driver. Mesmo padrao de `probe()` acima: o algoritmo mora na base, os
dados especificos moram no driver.

Nenhum modulo deste pacote importa `asb.auth`: a dependencia e sempre na
direcao auth.py -> agents/*, nunca o inverso.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar, Iterable, Mapping

from asb.sessions.model import AgentKind, ProviderSessionId

_PROBE_TIMEOUT_SECONDS = 5.0

# ---------------------------------------------------------------------------
# Autenticacao (Tarefa 2): tipo de resultado e pipeline de classificacao
# compartilhados entre os tres drivers. Movido de `cli/asb/auth.py`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthResult:
    provider: str
    state: str
    checked_at: str
    evidence: str
    remediation: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Prompt sintetico e resposta esperada, compartilhados entre claude e codex.
# `agy` NAO usa prompt algum: o brief proibe explicitamente usar prompt como
# teste local do agy — `agy -p` bloqueia ate 60s aguardando input quando
# deslogado — e o subcomando `agy models` prova a mesma coisa sem esse risco.
_VERIFY_PROMPT = ("Responda apenas, sem nenhum texto adicional antes ou "
                  "depois, com a frase exata: ASB_AUTH_VERIFY_OK")
_VERIFY_EXPECTED_RESPONSE = "ASB_AUTH_VERIFY_OK"

# Orcamento de tempo da PROPRIA chamada, do lado de DENTRO do container: o
# `timeout` do coreutils mata o comando do fornecedor mesmo que ele fique
# esperando entrada (o cenario mais parecido com o bloqueio de 60s do agy
# deslogado).
_VERIFY_PROVIDER_TIMEOUT = 60   # segundos, `timeout N` dentro do container


def _verify_setup_script() -> str:
    """Script remoto compartilhado: cria e remove um diretorio sintetico
    explicito em `/tmp` e muda para ele antes de chamar o wrapper do
    fornecedor, fechando stdin no chamador. Assim uma futura mudanca de
    WORKDIR na imagem nao consegue mover a verificacao para dentro do
    projeto montado ou para perto de secrets do workspace."""
    return (
        "WORKDIR=$(mktemp -d /tmp/asb-auth-verify.XXXXXX) || exit 70; "
        "trap 'rm -rf \"$WORKDIR\"' EXIT HUP INT TERM; "
        "cd \"$WORKDIR\" || exit 70; "
    )


# Marcadores de rede: aparecem na saida real de qualquer CLI de fornecedor
# quando a chamada nao alcanca a rede (timeout, DNS, conexao recusada).
# Nunca uma prova de conta: a REDE falhou, nao a credencial.
#
# "timeout" sozinho fica DE FORA de proposito: e um substring que tambem
# aparece em nomes de flag e linhas de configuracao benignas (ex.:
# "print-timeout: 5m0s" numa saida de sucesso do agy). "timed out" (duas
# palavras) e o fragmento que realmente aparece em mensagens de falha real
# de rede, e nao casa esses falsos positivos — mesmo espirito do R4 do
# catalogo de regressoes (docs/domains/sandbox/known-regressions.md),
# ainda que aqui o problema seja um substring de TEXTO, nao de codigo
# numerico.
_NETWORK_MARKERS: tuple[str, ...] = (
    "timed out", "connection refused", "connection reset",
    "network is unreachable", "temporary failure in name resolution",
    "could not resolve host", "name or service not known", "econnrefused",
    "etimedout", "enetunreach",
)

# Limite de taxa: o fornecedor RESPONDEU, mas recusou a chamada por volume.
# Nunca apaga credencial, nunca vira `unauthenticated`. O codigo numerico fica
# SEPARADO dos marcadores de texto: casar "429" como substring tambem casaria
# uma porta ou contagem de bytes (docs/domains/sandbox/known-regressions.md
# R4 — "403" em output tambem casou a porta 40300). `_contains_code` exige
# delimitador dos dois lados.
_RATE_LIMIT_CODES: tuple[str, ...] = ("429",)
_RATE_LIMIT_TEXT_MARKERS: tuple[str, ...] = ("rate limit", "too many requests")

# Indisponibilidade do lado do fornecedor (5xx). Mesma regra: nunca vira
# credencial invalida, e o mesmo cuidado de delimitacao do codigo numerico.
_SERVICE_ERROR_CODES: tuple[str, ...] = ("500", "502", "503")
_SERVICE_ERROR_TEXT_MARKERS: tuple[str, ...] = (
    "bad gateway", "service unavailable", "internal server error", "overloaded",
)


def _contains_code(text: str, codes: tuple[str, ...]) -> bool:
    """Casa um CODIGO NUMERICO delimitado (nao digito antes nem depois).

    R4 do catalogo de regressoes: `"403" in output` tambem casa a porta
    40300 ou uma contagem de bytes qualquer que contenha o mesmo digitos em
    sequencia. `(?<!\\d)CODE(?!\\d)` exige que a ocorrencia nao seja parte de
    um numero maior — o mesmo espirito do "match delimited" que o catalogo
    recomenda.
    """
    return any(re.search(rf"(?<!\d){code}(?!\d)", text) for code in codes)

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

    `probed_fully` e `True` so quando as DUAS chamadas (`--version` e
    `--help`) completaram sem levantar: e o unico resultado definitivo o
    bastante para ser guardado em cache. Uma falha ao executar qualquer
    delas pode ser transitoria.
    """

    available: bool
    version: str | None
    resume_supported: bool
    reason: str
    probed_fully: bool = False


@dataclass(frozen=True)
class Lifetime:
    """Janela `[start, end]` de uma OUTRA sessao do mesmo agente e cwd
    sem id do provedor. `end=None`: ainda aberta. `start=None` (registro
    antigo, inicio desconhecido): contem todo instante."""

    start: datetime | None
    end: datetime | None

    def contains(self, moment: datetime) -> bool:
        if self.start is None:
            return True
        return self.start <= moment and (self.end is None
                                         or moment <= self.end)


@dataclass(frozen=True)
class SessionEvidence:
    """Instantaneo de CAMINHOS de estado do provedor — nunca conteudo de
    transcript. `scan_root` e o diretorio observado, ou `None` quando o
    provedor nao tem um local de estado comprovado neste host.

    `capture_before()` preenche `known_paths` com o que ja existia e grava
    em `cwd` o checkout de execucao da sessao; `capture_after()` preenche
    `new_paths` com o que apareceu desde entao e repassa o mesmo `cwd`, para
    que a descoberta recuse arquivos de OUTRO checkout do mesmo workspace.

    `capture_since()` (descoberta preguicosa, sem baseline) poe em
    `new_paths` TODO arquivo atual; `not_before` (inicio da sessao) e
    `claimed_ids` (ids de outras sessoes guardadas) substituem o baseline
    como filtro.
    """

    scan_root: Path | None
    known_paths: frozenset[Path] = frozenset()
    new_paths: frozenset[Path] = frozenset()
    cwd: Path | None = None
    not_before: datetime | None = None
    claimed_ids: frozenset[str] = frozenset()
    contended: tuple[Lifetime, ...] = ()


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
    # Flags que lancam o agente sem prompts de permissao, como o Orca o
    # lanca: o sandbox e a fronteira de isolamento. Vazio = modo padrao.
    permission_args: ClassVar[tuple[str, ...]] = ()
    # Argv depois do id no resume (o id fica sempre logo apos o prefixo).
    resume_argv_suffix: ClassVar[tuple[str, ...]] = ()
    # `True` quando o provedor aceita um id escolhido por nos no
    # lancamento: o manager gera o UUID, o passa a `launch()` e o grava
    # como `provider_session_id` antes de lancar, sem descoberta.
    assigns_session_id_at_launch: ClassVar[bool] = False

    # -- autenticacao (Tarefa 2): dados especificos do fornecedor ---------

    # Nome curto usado em `AuthResult.provider` e nas mensagens de
    # remediacao ("asb-agent auth verify --agent <provider>"). Distinto de
    # `kind` (AgentKind de sessions/model.py): `AgentKind.ANTIGRAVITY` vale
    # "antigravity", nao "agy" — o contrato JSON congelado de `auth.py`
    # exige literalmente "agy".
    provider: ClassVar[str]

    # Comando de LEITURA de status nativo, ou `None` quando o fornecedor
    # nao expoe um comprovado (agy: `agy -p ping` bloqueia ate 60s aguardando
    # entrada quando deslogado — nunca arriscar esse bloqueio numa checagem
    # de diagnostico). `None` e o sinal para o chamador NUNCA tocar podman.
    status_command: ClassVar[str | None] = None

    # Marcadores de evidencia PROPRIA do fornecedor de que a credencial e
    # invalida. Um 401/403 puro nunca entra aqui: tambem e a assinatura de
    # uma negativa de ACL do proxy, e so a evidencia do FORNECEDOR conta.
    auth_evidence_markers: ClassVar[tuple[str, ...]] = ()

    # Evidencia enlatada de sucesso da chamada real de verificacao. Igual
    # para claude/codex; so `AntigravityDriver` a sobrescreve.
    verify_success_evidence: ClassVar[str] = (
        "chamada real ao fornecedor respondeu no formato solicitado, com "
        "codigo 0")

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

    def launch(self, cwd: Path,
               session_id: str | None = None) -> LaunchCommand:
        """`cwd` nao entra no argv AQUI: `LaunchCommand` nao tem campo de
        cwd porque quem executa o comando define o cwd do subprocesso; o
        parametro existe para simetria com `resume()` e para as subclasses
        que precisam do caminho no argv (o `CodexDriver` o usa no override
        de trust).
        `session_id` so e aceito por quem `assigns_session_id_at_launch`:
        aqui ele seria descartado em silencio, entao e recusado."""
        if session_id is not None:
            raise ValueError(
                f"{self.kind}: o lancamento nao aceita um session id")
        return LaunchCommand(argv=(self.binary, *self.permission_args))

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
        return LaunchCommand(argv=(*self.resume_argv_prefix, validated,
                                   *self.resume_argv_suffix))

    # -- autenticacao (Tarefa 2): regras do fornecedor --------------------

    def parse_auth_status(self, completed) -> AuthResult:
        """Interpreta a saida de `status_command` (um objeto com
        `.returncode`, `.stdout` e `.stderr`, tipicamente um
        `subprocess.CompletedProcess`). Nao e `@abstractmethod` (ver
        docstring do modulo); o default so existe para reportar alto e
        claro um driver ainda nao migrado."""
        raise NotImplementedError(
            f"{self.kind}: parse_auth_status nao implementado")

    def login_argv(self) -> tuple[str, ...]:
        """Comando de login interativo deste fornecedor."""
        raise NotImplementedError(
            f"{self.kind}: login_argv nao implementado")

    def verify_argv(self) -> tuple[str, ...]:
        """Argv final (apos o transporte SSH) da chamada real de
        verificacao: tipicamente uma tupla de um elemento so, o script
        remoto completo — SSH trata o ultimo argumento como a linha de
        comando remota, entao nao ha o que "separar" alem disso."""
        raise NotImplementedError(
            f"{self.kind}: verify_argv nao implementado")

    def _verify_success(self, output: str) -> bool:
        """A saida da chamada real bate com o formato de sucesso deste
        fornecedor? Default: resposta exata ao prompt sintetico
        compartilhado (claude/codex). `AntigravityDriver` sobrescreve com a
        validacao da lista de modelos."""
        normalized = " ".join((output or "").split())
        return normalized == _VERIFY_EXPECTED_RESPONSE

    def classify_verification(self, completed, network_state: bool) -> AuthResult:
        """Classifica o RESULTADO de uma chamada real (ou a decisao de nao
        faze-la). Pura: nenhum I/O, nenhum podman, nenhuma chamada.

        Ordem das checagens, deliberada: rede primeiro (nunca vira logout),
        depois categorias de resposta do fornecedor que TAMBEM nunca podem
        apagar credencial (limite de taxa, erro de servico), so entao a
        evidencia PROPRIA de credencial invalida — e so quando o fornecedor
        fala, nunca a partir de um 401/403 generico que um proxy tambem
        emite.

        A evidencia devolvida e sempre texto enlatado (categoria), nunca o
        `output` bruto: e ali que apareceriam tokens e codigos OAuth.

        `completed` carrega `.returncode`, `.stdout` e `.stderr`; para uma
        decisao tomada ANTES de qualquer chamada (rede indisponivel,
        transporte caido), o chamador constroi um `CompletedProcess`
        sintetico — o mesmo padrao que `auth.py` ja usava antes desta
        tarefa.
        """
        checked_at = _now_iso()
        combined = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        text = combined.lower()

        if not network_state:
            return AuthResult(
                provider=self.provider, state="unreachable",
                checked_at=checked_at,
                evidence="rede indisponivel antes da chamada; nenhuma "
                         "chamada foi contada no orcamento",
                remediation="asb-agent doctor")

        if completed.returncode == 124:
            return AuthResult(
                provider=self.provider, state="unreachable",
                checked_at=checked_at,
                evidence="chamada ao fornecedor atingiu o limite interno "
                         "de tempo (codigo 124); nunca interpretado como "
                         "logout",
                remediation="tente novamente mais tarde")

        if any(marker in text for marker in _NETWORK_MARKERS):
            return AuthResult(
                provider=self.provider, state="unreachable",
                checked_at=checked_at,
                evidence="chamada ao fornecedor falhou por rede (timeout "
                         "ou conexao); nunca interpretado como logout",
                remediation="asb-agent doctor")

        if _contains_code(text, _RATE_LIMIT_CODES) or any(
                marker in text for marker in _RATE_LIMIT_TEXT_MARKERS):
            return AuthResult(
                provider=self.provider, state="provider_error",
                checked_at=checked_at,
                evidence="fornecedor respondeu limite de taxa (429); rate "
                         "limit nunca apaga a credencial",
                remediation="aguarde e tente novamente mais tarde; nao "
                           "repita a chamada agora")

        if _contains_code(text, _SERVICE_ERROR_CODES) or any(
                marker in text for marker in _SERVICE_ERROR_TEXT_MARKERS):
            return AuthResult(
                provider=self.provider, state="provider_error",
                checked_at=checked_at,
                evidence="fornecedor reportou erro de servico (5xx); "
                         "indisponibilidade nunca apaga a credencial",
                remediation="tente novamente mais tarde")

        if any(marker in text for marker in self.auth_evidence_markers):
            return AuthResult(
                provider=self.provider, state="unauthenticated",
                checked_at=checked_at,
                evidence=f"o proprio fornecedor {self.provider} reportou "
                         "credencial invalida (nao um 401/403 generico de "
                         "proxy)",
                remediation="asb-agent login")

        success_format = self._verify_success(combined)
        if completed.returncode == 0 and success_format:
            return AuthResult(
                provider=self.provider, state="authenticated",
                checked_at=checked_at,
                evidence=self.verify_success_evidence,
                remediation="")

        if completed.returncode == 0:
            return AuthResult(
                provider=self.provider, state="unknown", checked_at=checked_at,
                evidence="chamada real retornou codigo 0, mas a resposta "
                         "nao bateu com o formato esperado (erro de "
                         "formato, registrado separado de erro de "
                         "credencial)",
                remediation=f"asb-agent auth verify --agent {self.provider}")

        return AuthResult(
            provider=self.provider, state="unknown", checked_at=checked_at,
            evidence="saida nao reconhecida da chamada real ao fornecedor "
                     f"(codigo {completed.returncode})",
            remediation=f"asb-agent auth verify --agent {self.provider}")

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
                                  reason=reason, probed_fully=True)

    # -- evidencia de sessao (caminhos e metadados, nunca transcript) ----

    def capture_before(self, cwd: Path) -> SessionEvidence:
        root = self._scan_root(cwd)
        return SessionEvidence(scan_root=root, known_paths=self._scan(root),
                               cwd=cwd)

    def capture_after(self, baseline: SessionEvidence) -> SessionEvidence:
        root = baseline.scan_root
        current = self._scan(root)
        new_paths = frozenset(current - baseline.known_paths)
        return SessionEvidence(scan_root=root, known_paths=current,
                                new_paths=new_paths, cwd=baseline.cwd)

    def capture_since(self, cwd: Path, not_before: datetime | None = None,
                      claimed_ids: Iterable[str] = (),
                      contended: Iterable[Lifetime] = ()) -> SessionEvidence:
        """Evidencia para a descoberta preguicosa: sem baseline, todo
        arquivo atual e candidato; quem filtra e `discover_session_id`."""
        root = self._scan_root(cwd)
        return SessionEvidence(scan_root=root, new_paths=self._scan(root),
                               cwd=cwd, not_before=not_before,
                               claimed_ids=frozenset(claimed_ids),
                               contended=tuple(contended))

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
        """So arquivos REGULARES, julgados por `lstat` (nunca seguindo
        symlink). A raiz e gravavel pelo agente: um symlink, FIFO, socket
        ou device ali nunca e candidato, e uma raiz (ou o `sessions_root`)
        que virou symlink nao e varrida — o host leria outro diretorio."""
        if root is None:
            return frozenset()
        for directory in {root, self._sessions_root} - {None}:
            if not _is_real_dir(directory):
                return frozenset()
        return frozenset(path for path in self._list_paths(root)
                         if _is_regular_file(path))

    def _list_paths(self, root: Path) -> Iterable[Path]:
        return root.glob("*.jsonl")


def _is_real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False
