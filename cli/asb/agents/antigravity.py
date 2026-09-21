"""cli/asb/agents/antigravity.py — driver do Antigravity CLI (`agy`).

O binario de HOST usado para caracterizar este driver expoe `--conversation`
no seu `--help` (ver
docs/validation/2026-09-17-agent-session-contracts.md), mas isso NAO prova
resume: nenhum diretorio de estado local foi encontrado neste host para
`agy`, entao nao ha fonte de session-id comprovada. `discover_session_id()`
sempre retorna `None` e `probe()` nunca reporta `resume_supported=True`
neste host — o binario da IMAGEM do container e o gate autoritativo para
essa opcao, e so pode ser verificado apos o checkpoint humano (fora do
escopo desta tarefa).

Regras de autenticacao (Tarefa 2 da decomposicao de `auth.py`): `agy` NAO
tem comando de status local comprovado — `status_command` fica `None`
(herdado da base) e `parse_auth_status` sempre devolve o mesmo resultado
`unknown` enlatado, sem tocar podman: `agy -p ping` bloqueia ate 60s
aguardando entrada quando deslogado (A1), e nao ha comando alternativo
comprovado. O binario nu abre a TUI, que autentica no primeiro uso — nao ha
subcomando `login`. A verificacao real usa `agy models` (nunca `-p`/
`--print`, que enviaria prompt), cuja saida de sucesso e uma LISTA de
identificadores de modelo, nao uma frase fixa — por isso este driver
sobrescreve `_verify_success`.
"""
from __future__ import annotations

import re
from pathlib import Path

from asb.agents.base import (AgentDriver, AuthResult, SessionEvidence,
                             _now_iso, _verify_setup_script,
                             _VERIFY_PROVIDER_TIMEOUT)
from asb.sessions.model import AgentKind

# Evidencia offline disponivel para `agy models`: o piloto A1 registrou uma
# lista positiva de 16 linhas com nomes de modelos; o binario fixado 1.1.27
# contem familias Gemini/Claude/GPT/Flash/Sonnet/Opus. A saida bruta nao foi
# preservada, portanto nao inventamos colunas ou headers. Este guarda falha
# fechado: cada linha precisa ter a forma conservadora de um IDENTIFICADOR
# (um token com separador), conter uma familia conhecida e ao menos um
# componente numerico de versao/modelo.
# Prosa que apenas menciona modelos vira `unknown`, assim como qualquer formato
# futuro diferente — falso negativo seguro em vez de falso `authenticated`.
_AGY_MODEL_FAMILY = re.compile(
    r"(?<![a-z0-9])(?:gemini|claude|gpt|flash|sonnet|opus)(?![a-z0-9])",
    re.IGNORECASE)
_AGY_MODEL_IDENTIFIER = re.compile(
    r"[a-z0-9]+(?:[._:/-][a-z0-9]+)+", re.IGNORECASE)
# O sufixo de unidade e obrigatorio de tolerar: `gpt-oss-120b-medium` aparece
# na saida real, e exigir digito sem letra depois reprovava uma linha de
# modelo legitima. Continua exigindo DIGITO: nomes de erro tokenizados
# (`gemini-unavailable`, `error:gemini`) seguem reprovados, que e a razao de
# ser desta regra.
_AGY_MODEL_NUMBER = re.compile(r"(?<![a-z0-9])\d+[a-z]*(?![a-z0-9])",
                               re.IGNORECASE)


def _agy_model_row(line: str) -> bool:
    """A linha e uma LINHA DE MODELO da lista do agy?

    O formato real (capturado no piloto T2, binario 1.1.27) e
    `identificador<TAB>rotulo humano`. So a COLUNA DO IDENTIFICADOR decide:
    o rotulo humano ("Gemini 3.8 Flash (High)") nunca pode sustentar familia
    nem numero, senao qualquer prosa com nome de modelo viraria credencial
    valida.
    """
    identifier = line.split("\t", 1)[0].strip()
    return bool(
        _AGY_MODEL_IDENTIFIER.fullmatch(identifier)
        and _AGY_MODEL_FAMILY.search(identifier)
        and _AGY_MODEL_NUMBER.search(identifier))


def _agy_models_output_valid(output: str) -> bool:
    """Continua falhando FECHADO; so reconhece o formato real.

    A guarda anterior exigia que TODA linha fosse um identificador nu. A
    saida real tem duas colunas separadas por TAB e e precedida da linha de
    prosa `Fetching available models...`, entao `fullmatch` reprovava as 15
    linhas e a classificacao SO podia devolver `unknown`, qualquer que fosse
    o estado da credencial. A saida bruta de A1 nao foi preservada (ver o
    comentario acima), e a guarda tinha sido escrita contra a lembranca dela.

    `classify_verification` monta `combined = f"{stdout}\\n{stderr}"`, entao
    a prosa de stderr chega DEPOIS das linhas de modelo. Por `podman exec`
    ela aparece antes. As duas ordens sao toleradas; o que nao e tolerado e
    prosa NO MEIO.

    O que continua valendo, para nao fabricar um `authenticated` falso:
    - pelo menos DUAS linhas de modelo;
    - as linhas de modelo sao CONTIGUAS — prosa entre elas reprova a lista
      inteira, que e o caso de um erro interrompendo a listagem;
    - qualquer linha tolerada (antes ou depois do bloco) nunca pode citar uma
      familia de modelo conhecida.
    """
    lines = [line.strip() for line in (output or "").splitlines()
             if line.strip()]
    indexes = [i for i, line in enumerate(lines) if _agy_model_row(line)]
    if len(indexes) < 2:
        return False
    first, last = indexes[0], indexes[-1]
    if indexes != list(range(first, last + 1)):
        return False
    return not any(_AGY_MODEL_FAMILY.search(line)
                   for line in lines[:first] + lines[last + 1:])


class AntigravityDriver(AgentDriver):
    kind = AgentKind.ANTIGRAVITY
    binary = "agy"
    resume_argv_prefix = ("agy", "--conversation")
    version_pattern = re.compile(r"^(\d+(?:\.\d+){1,3})$")
    resume_option_pattern = re.compile(r"--conversation\b")
    # Nao comprovado neste host: nenhum diretorio de estado local foi
    # encontrado para `agy` (~/.agy, ~/.config/agy, ~/.local/share/agy
    # inexistentes). probe() nunca anuncia resume_supported=True aqui,
    # mesmo com a opcao presente no --help.
    session_id_provable = False

    # -- autenticacao (Tarefa 2) -------------------------------------------

    provider = "agy"
    # `status_command` fica None (herdado da base): nenhum comando de
    # status local comprovado. Ver docstring do modulo e `parse_auth_status`.
    auth_evidence_markers = ("authentication required", "authentication failed")
    verify_success_evidence = (
        "'agy models' retornou uma lista de nomes de modelos com codigo 0; "
        "prova acesso a lista, nao geracao")

    def _scan_root(self, cwd: Path) -> Path | None:
        # Decisao explicita (ver docstring do modulo), nao apenas a
        # heranca silenciosa do padrao da classe base: nenhum diretorio
        # de estado local foi encontrado para `agy` neste host.
        return None

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        return None

    def parse_auth_status(self, completed=None) -> AuthResult:
        """Sempre `unknown`, SEM tocar podman: `agy` nao possui comando de
        status local comprovado, e `agy -p ping` bloqueia ate 60s aguardando
        entrada quando deslogado (A1). `completed` e ignorado de proposito —
        nao ha saida de fornecedor alguma para interpretar aqui; o chamador
        (`auth.check_status`) nunca executa um comando para este driver
        (`status_command is None`) e passa `None`."""
        return AuthResult(
            provider="agy",
            state="unknown",
            checked_at=_now_iso(),
            evidence=(
                "agy nao possui comando de status local comprovado; "
                "'agy -p ping' bloqueia ate 60s aguardando entrada quando deslogado"
            ),
            remediation="asb-agent auth verify --workspace <id> --agent agy",
        )

    def login_argv(self) -> tuple[str, ...]:
        return ("agy",)

    def verify_argv(self) -> tuple[str, ...]:
        """Script remoto de UMA chamada real: `agy models`, sem prompt e
        sem `-p`/`--print` — um subcomando REAL (nao uma flag inventada)
        que nao envia mensagem alguma ao modelo. `--print-timeout` existe
        na versao fixada mas sua aplicabilidade a `models` (em vez de `-p`)
        nao foi confirmada sem uma chamada real — o orcamento de tempo usa
        APENAS o `timeout` externo do bash."""
        setup = _verify_setup_script()
        return (f"{setup}timeout {_VERIFY_PROVIDER_TIMEOUT} "
                "asb-agy models < /dev/null",)

    def _verify_success(self, output: str) -> bool:
        """`agy models` responde uma LISTA de identificadores, nunca a
        frase fixa que claude/codex ecoam — prova acesso a lista, nao
        geracao."""
        return _agy_models_output_valid(output)
