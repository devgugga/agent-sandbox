"""cli/asb/agents/codex.py — driver do Codex CLI.

Fonte do session-id comprovada em
docs/validation/2026-09-17-agent-session-contracts.md (medida no host):
exatamente um novo arquivo `.jsonl` sob `$CODEX_HOME/sessions/**` cuja
primeira linha e um registro
`{"type": "session_meta", "payload": {"id": "...", ...}}`. So a primeira
linha e lida (metadado de sessao, nunca conteudo de transcript).

O volume de sessao e do WORKSPACE, compartilhado por todos os checkouts
ligados a ele, e e varrido recursivamente: um rollout novo de OUTRA sessao
Codex viva no mesmo workspace pode aparecer durante a descoberta. Por isso
so conta como candidato o arquivo cujo `payload.cwd` (string, caminho
absoluto sem barra final) e o checkout de execucao desta sessao.

Uma sessao Codex pode abrir SUBAGENTES com o mesmo cwd (o piloto viu um
`guardian_review` criado por `approvals_reviewer = "auto_review"` junto com
o thread do usuario, na primeira mensagem). So conta o thread do usuario:
`payload` sem `parent_thread_id`, com `source` string (um `source` objeto,
`{"subagent": ...}`, e subagente) e `thread_source == "user"` (um
`codex exec` no mesmo checkout nao e a sessao). Na historia do Codex do
operador os dois marcadores de subagente coincidem em todos os arquivos, e
todo thread que nao e subagente tem `thread_source: "user"` (ver
docs/validation/2026-09-17-agent-session-contracts.md, secao 4.3).

Com `not_before` ou `contended` na evidencia, o `payload.timestamp` tem de
ser um instante com fuso, igual ou posterior a `not_before` e fora da vida
de toda outra sessao sem id do mesmo agente e cwd (`contended`); o id nao
pode ser de outra sessao ja guardada (`claimed_ids`).

O volume tambem e gravavel pelo AGENTE: a leitura abre sem seguir symlink
(`O_NOFOLLOW`), sem bloquear num FIFO (`O_NONBLOCK`), exige arquivo
regular (`fstat`) e le no maximo `_FIRST_LINE_LIMIT` bytes; uma primeira
linha que nao cabe nisso nao da id.

O trust do diretorio NAO e gravado: `~/.codex/config.toml` vive no volume
COMPARTILHADO de credenciais e o manifesto do entrypoint o copia do host a
cada start do container, entao uma entrada por workspace seria disputada
entre checkouts e apagada no proximo start. Em vez disso, o driver passa o
trust como override POR LANCAMENTO (`-c projects."<cwd>".trust_level=
"trusted"`), escopado ao checkout desta sessao: nada compartilhado e
mutado e nao ha corrida de ordem de inicio. O driver nunca le nem escreve
`~/.codex/config.toml`.

Dentro do sandbox, `$HOME/.codex/sessions` e o subpath `codex-sessions` do
volume de sessao do workspace; o driver o le PELO HOST, pelo mountpoint do
volume, via `sessions_root`. Sem `sessions_root` nao ha varredura: o
`~/.codex` do operador nunca e lido.

Regras de autenticacao (Tarefa 2 da decomposicao de `auth.py`): `codex
login status` reporta 'Not logged in' com codigo 1 quando deslogado; a
negativa explicita tem PRECEDENCIA sobre qualquer substring positiva
('Not logged in' contem 'logged in'). O login real e `codex login
--device-auth` — o OAuth padrao abre um servidor de callback numa porta
do container que o navegador do host nao alcanca, e trava. A verificacao
real usa `codex exec --skip-git-repo-check --sandbox read-only -o <file>`,
nunca o subcomando interativo padrao.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

from asb.agents.base import (AgentDriver, AuthResult, LaunchCommand, Lifetime,
                             SessionEvidence, _now_iso, _verify_setup_script,
                             _VERIFY_PROMPT, _VERIFY_PROVIDER_TIMEOUT)
from asb.sessions.model import AgentKind

# Teto da leitura da primeira linha (o `session_meta` medido tem ~1 KiB).
_FIRST_LINE_LIMIT = 64 * 1024

# Flag de override de configuracao do Codex (`-c, --config <key=value>`,
# caminho TOML pontilhado, valor parseado como TOML), presente tanto em
# `codex --help` quanto em `codex resume --help` no binario da imagem.
_CONFIG_FLAG = "-c"


class CodexDriver(AgentDriver):
    kind = AgentKind.CODEX
    binary = "codex"
    # Como o Orca lanca o Codex: sem aprovacoes nem o sandbox proprio do
    # Codex; o container e a fronteira. `codex resume [OPTIONS]
    # [SESSION_ID]`: a flag vem antes do id (conferido no binario da
    # imagem, 0.155.0).
    permission_args = ("--dangerously-bypass-approvals-and-sandbox",)
    resume_argv_prefix = ("codex", "resume", *permission_args)
    version_pattern = re.compile(r"^codex-cli\s+(\S+)$")
    resume_option_pattern = re.compile(r"(?m)^\s*resume\b")
    session_id_provable = True

    # -- autenticacao (Tarefa 2) -------------------------------------------

    provider = "codex"
    status_command = "codex login status"
    auth_evidence_markers = (
        "not logged in", "invalid_api_key", "incorrect api key provided",
        "no codex credentials were found",
    )

    def launch(self, cwd: Path,
               session_id: str | None = None) -> LaunchCommand:
        """Lancamento da base MAIS o override de trust do checkout: aqui o
        `cwd` ENTRA no argv (a base diz que nao entra; esta subclasse e a
        excecao). O override vai depois da flag de bypass, que mantem a
        posicao que sempre teve."""
        return _with_trust(super().launch(cwd, session_id), cwd)

    def resume(self, cwd: Path, session_id: str) -> LaunchCommand:
        """Resume da base MAIS o override de trust do checkout. Em
        `codex resume [OPTIONS] [SESSION_ID] [PROMPT]` o `-c` tambem e
        aceito DEPOIS do posicional (conferido no binario 0.155.0 da
        imagem), entao o id fica exatamente onde ja estava."""
        return _with_trust(super().resume(cwd, session_id), cwd)

    def _scan_root(self, cwd: Path) -> Path | None:
        return self._sessions_root

    def _list_paths(self, root: Path) -> Iterable[Path]:
        return root.rglob("*.jsonl")

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        if evidence.cwd is None:
            return None
        ids = [session_id for path in evidence.new_paths
               if path.suffix == ".jsonl"
               and (session_id := _session_id_for(
                   path, evidence.cwd, evidence.not_before,
                   evidence.contended))
               and session_id not in evidence.claimed_ids]
        return ids[0] if len(ids) == 1 else None

    def parse_auth_status(self, completed) -> AuthResult:
        """Interpreta `codex login status` (A1: 'Not logged in' com codigo 1
        quando deslogado; formato do texto de sucesso nao esta documentado
        com a mesma certeza).

        A negativa explicita ('not logged in') tem PRECEDENCIA sobre
        qualquer substring positiva: 'Not logged in' contem 'logged in', e
        grepar 'logged in' sem checar a negativa primeiro casaria os dois
        estados. Sem essa negativa, `authenticated` exige codigo 0 E a
        substring positiva; formato desconhecido vira `unknown`, nunca
        `authenticated` por otimismo.
        """
        checked_at = _now_iso()
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = getattr(completed, "stderr", "") or ""
        combined = f"{stdout or ''}\n{stderr or ''}".lower()

        if "not logged in" in combined:
            return AuthResult(
                provider="codex",
                state="unauthenticated",
                checked_at=checked_at,
                evidence="codex login status reportou 'Not logged in'",
                remediation="asb-agent login",
            )
        if returncode == 0 and "logged in" in combined:
            return AuthResult(
                provider="codex",
                state="authenticated",
                checked_at=checked_at,
                evidence="codex login status reportou sessao ativa (codigo 0)",
                remediation="",
            )
        return AuthResult(
            provider="codex",
            state="unknown",
            checked_at=checked_at,
            evidence=f"saida nao reconhecida de 'codex login status' (codigo {returncode})",
            remediation="asb-agent auth status --workspace <id> --agent codex --json",
        )

    def login_argv(self) -> tuple[str, ...]:
        return ("codex", "login", "--device-auth")

    def verify_argv(self) -> tuple[str, ...]:
        """Script remoto de UMA chamada real: `codex exec
        --skip-git-repo-check --sandbox read-only -o <file>`, flags
        confirmadas offline na versao fixada (`codex exec --help`).

        O stdout do `codex exec` nao participa da prova: algumas versoes
        tambem transmitem eventos/resposta ali. Somente o arquivo de `-o` e
        lido; stderr e revelado apenas na falha para classificacao.
        """
        prompt = shlex.quote(_VERIFY_PROMPT)
        setup = _verify_setup_script()
        return (
            f'{setup}OUT="$WORKDIR/codex-output"; '
            f'ERR="$WORKDIR/codex-error"; '
            f'timeout {_VERIFY_PROVIDER_TIMEOUT} asb-codex exec '
            f'--skip-git-repo-check --sandbox read-only -o "$OUT" {prompt} '
            f'< /dev/null > /dev/null 2>"$ERR"; RC=$?; '
            f'if [ "$RC" -eq 0 ]; then cat "$OUT" 2>/dev/null; '
            f'else cat "$ERR" >&2; fi; exit "$RC"',
        )


def _with_trust(command: LaunchCommand, cwd: Path) -> LaunchCommand:
    """`command` com o override de trust anexado ao FIM do argv; sem
    override, o `command` intacto."""
    override = _trust_override(cwd)
    if override is None:
        return command
    return LaunchCommand(argv=(*command.argv, _CONFIG_FLAG, override),
                         env=command.env)


def _trust_override(cwd: Path) -> str | None:
    """`projects."<cwd>".trust_level="trusted"` para o `-c` do Codex, ou
    `None` quando o caminho nao cabe numa string basica de TOML.

    A chave TEM de ser citada (uma chave nua de TOML nao aceita `/`), e a
    citacao nao e escapada: um caminho com aspa, contrabarra ou caractere
    de controle (inclusive quebra de linha) poderia sair da string, entao
    a flag inteira e OMITIDA — o Codex volta a perguntar pelo trust, que e
    o comportamento de hoje, em vez de receber um TOML quebrado.

    Um `=` tambem e recusado: o `-c` parte o argumento em `key=value` no
    primeiro `=`, entao um `=` dentro da chave citada a parte ao meio e o
    Codex recusa a config INTEIRA ("config could not be loaded", medido no
    binario 0.155.0 da imagem) — a sessao nem comecaria."""
    path = str(cwd)
    if '"' in path or "\\" in path or "=" in path \
            or any(char < " " or char == "\x7f" for char in path):
        return None
    return f'projects."{path}".trust_level="trusted"'


def _session_id_for(path: Path, cwd: Path,
                    not_before: datetime | None = None,
                    contended: tuple[Lifetime, ...] = ()) -> str | None:
    """`payload.id` do `session_meta` na primeira linha de `path`, somente
    se `payload.cwd` e o checkout `cwd`, o thread e do usuario (nao um
    subagente nem um `exec`) e, com `not_before`/`contended`, o
    `payload.timestamp` nao e anterior a `not_before` nem cai na vida de
    outra sessao sem id; senao `None`."""
    first_line = _read_first_line(path)
    if first_line is None:
        return None
    try:
        record = json.loads(first_line)
    except (ValueError, RecursionError):
        # A linha e do agente: `JSONDecodeError` (um `ValueError`), um
        # inteiro alem do limite de digitos (`ValueError`) ou `[` aninhado
        # alem da recursao do parser. Nada disso da id nem escapa: um stop
        # ou exit 0 roda esta descoberta DEPOIS de matar o tmux.
        return None
    if not isinstance(record, dict):
        return None
    if record.get("type") != "session_meta":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    session_cwd = payload.get("cwd")
    if not isinstance(session_cwd, str) \
            or PurePosixPath(session_cwd) != PurePosixPath(cwd):
        return None
    if "parent_thread_id" in payload \
            or not isinstance(payload.get("source"), str) \
            or payload.get("thread_source") != "user":
        return None
    if not_before is not None or contended:
        moment = _aware_instant(payload.get("timestamp"))
        if moment is None:
            return None
        if not_before is not None and moment < not_before:
            return None
        if any(lifetime.contains(moment) for lifetime in contended):
            return None
    session_id = payload.get("id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _aware_instant(value: object) -> datetime | None:
    """`value` como instante ISO-8601 COM fuso; qualquer outra coisa nao
    prova a ordem e vira `None`."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        return None
    return moment


def _read_first_line(path: Path) -> str | None:
    """Primeira linha de um arquivo REGULAR, sem seguir symlink, sem
    bloquear e lendo no maximo `_FIRST_LINE_LIMIT` bytes; `None` se o
    caminho nao e arquivo regular, nao abre, ou a linha nao termina dentro
    do teto."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, _FIRST_LINE_LIMIT)
    except OSError:
        return None
    finally:
        os.close(fd)
    line, newline, _rest = data.partition(b"\n")
    if not newline:
        return None
    return line.decode("utf-8", errors="replace")
