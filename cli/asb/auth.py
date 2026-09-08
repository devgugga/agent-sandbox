"""cli/asb/auth.py — status de CONTA por fornecedor (Tarefa A2).

Separa tres coisas que o `doctor` v1 misturava: se a CONTA de um fornecedor
esta autenticada, se a REDE alcanca o fornecedor, e se a INFRAESTRUTURA local
(keyring, containers) esta saudavel. Este modulo responde SOMENTE a primeira
pergunta. Rede e infraestrutura ja tem seus proprios sensores dedicados
(cli/asb/readiness.py, cli/asb/keyring.py).

Duas metades com fronteira explicita:

* DIAGNOSTICO (`check_status`, `status`, os `parse_*`): nunca inicia login,
  nunca faz logout, nunca envia prompt. Apenas LE o estado corrente do
  fornecedor, como uid 1000, com o ambiente do workspace e timeout limitado
  (10s) — o mesmo perfil das demais sondas.
* LOGIN (`login`, `login_command`, `operator_lock`, `verify_fresh_client`,
  Tarefa A3): unico caminho que muta estado, sempre sob pedido explicito do
  operador, sempre com TTY, sempre com lock por fornecedor.

Nenhuma das duas metades interpola saida capturada do fornecedor em evidencia
ou remediacao: e ali que tokens e codigos OAuth apareceriam. A evidencia e
sempre texto enlatado somado a um codigo de retorno.

Um retorno "authenticated" aqui prova que o comando de status do fornecedor
respondeu como autenticado agora; nao e prova de que uma chamada real foi
aceita pelo servidor remoto (isso cabe a `verify`, Tarefa A4).
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import keyring, lifecycle, podman


@dataclass(frozen=True)
class AuthResult:
    provider: str
    state: str
    checked_at: str
    evidence: str
    remediation: str


# Comandos de LEITURA de status, um por fornecedor. Nenhum aqui muta estado:
# nao ha `/login`, `login --device-auth` nem `logout` nesta tabela.
STATUS_COMMANDS: dict[str, str] = {
    "claude": "claude auth status --json",
    "codex": "codex login status",
}

# Fronteira publica de `status()`: aceita "all" alem dos tres fornecedores.
_INDIVIDUAL_PROVIDERS = frozenset({"claude", "codex", "agy"})
_PUBLIC_PROVIDERS = _INDIVIDUAL_PROVIDERS | {"all"}

# Orcamento de tempo do lado do HOST para as chamadas podman deste modulo.
# O comando do fornecedor ja e limitado por `timeout 10` DENTRO do container
# (linha do exec abaixo); estes valores cobrem a ida-e-volta do proprio
# podman no host (podman ps / podman exec), para que um podman travado ou um
# rootless preso nunca bloqueiem o CLI indefinidamente. _EXEC_HOST_TIMEOUT e
# maior que o timeout interno para dar folga ao `timeout 10` de fato matar o
# comando do fornecedor e ao exec retornar antes do host desistir.
_RUNNING_CHECK_HOST_TIMEOUT = 10
_EXEC_HOST_TIMEOUT = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_claude_status(returncode: int, stdout: str) -> AuthResult:
    """Interpreta `claude auth status --json` (A1: contrato estavel, JSON
    limpo em stdout com o campo `loggedIn`).

    A saida negativa explicita (`loggedIn: false`) e suficiente para
    `unauthenticated` sozinha. Ja `authenticated` exige ACORDO entre o
    payload (`loggedIn: true`) e o codigo de saida (0): um `loggedIn: true`
    com codigo != 0 e contraditorio e vira `unknown`, nunca um falso
    positivo. Qualquer coisa que nao seja JSON valido com o campo
    `loggedIn` (JSON invalido, saida vazia por timeout/comando ausente,
    formato inesperado) tambem vira `unknown`.
    """
    checked_at = _now_iso()
    text = stdout if isinstance(stdout, str) else ""
    data = None
    if text.strip():
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
    logged_in = data.get("loggedIn") if isinstance(data, dict) else None

    if logged_in is False:
        return AuthResult(
            provider="claude",
            state="unauthenticated",
            checked_at=checked_at,
            evidence="claude auth status --json reportou loggedIn=false",
            remediation="asb-agent login",
        )
    if logged_in is True and returncode == 0:
        return AuthResult(
            provider="claude",
            state="authenticated",
            checked_at=checked_at,
            evidence="claude auth status --json reportou loggedIn=true (codigo 0)",
            remediation="",
        )
    return AuthResult(
        provider="claude",
        state="unknown",
        checked_at=checked_at,
        evidence=f"saida nao reconhecida de 'claude auth status --json' (codigo {returncode})",
        remediation="asb-agent auth status --workspace <id> --agent claude --json",
    )


def parse_codex_status(returncode: int, stdout: str, stderr: str) -> AuthResult:
    """Interpreta `codex login status` (A1: 'Not logged in' com codigo 1
    quando deslogado; formato do texto de sucesso nao esta documentado com
    a mesma certeza).

    A negativa explicita ('not logged in') tem PRECEDENCIA sobre qualquer
    substring positiva: 'Not logged in' contem 'logged in', e grepar
    'logged in' sem checar a negativa primeiro casaria os dois estados (o
    mesmo erro historico da tabela LOGIN_CHECKS, removida na A3). Sem essa
    negativa, `authenticated` exige codigo 0 E a substring positiva; formato
    desconhecido vira `unknown`, nunca `authenticated` por otimismo.
    """
    checked_at = _now_iso()
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


def check_status(provider: str, container: str) -> AuthResult:
    """Verifica o status de UM fornecedor. Nunca inicia login, logout ou
    envia prompt: e leitura pura.

    `provider` aceita apenas claude/codex/agy — 'all' e resolvido por
    `status()`, chamando esta funcao uma vez por fornecedor, e e rejeitado
    aqui.

    Executa como uid 1000 dentro do container do workspace, com o ambiente
    do proprio workspace (nenhuma variavel extra e injetada) e timeout de
    10s via `timeout 10` dentro do container — o mesmo perfil de bounded
    timeout das demais sondas (readiness.py).
    """
    if provider not in _INDIVIDUAL_PROVIDERS:
        raise ValueError(
            f"provider invalido para checagem individual: {provider!r} "
            "(use 'claude', 'codex' ou 'agy'; 'all' so e aceito por status())"
        )

    checked_at = _now_iso()

    if provider == "agy":
        # A1 (empirico): agy nao expoe comando de status local, e
        # `agy -p ping` bloqueia ate 60s aguardando entrada quando deslogado.
        # Sem comando comprovado, respondemos unknown SEM tocar podman —
        # jamais arriscar o bloqueio de 60s numa checagem de diagnostico.
        return AuthResult(
            provider="agy",
            state="unknown",
            checked_at=checked_at,
            evidence=(
                "agy nao possui comando de status local comprovado; "
                "'agy -p ping' bloqueia ate 60s aguardando entrada quando deslogado"
            ),
            remediation="use 'asb-agent auth verify --agent agy' quando disponivel (Tarefa A4)",
        )

    try:
        container_running = podman.running(
            container, timeout=_RUNNING_CHECK_HOST_TIMEOUT)
    except (podman.PodmanError, subprocess.TimeoutExpired) as exc:
        # `podman.running` chama `podman ps`, que pode levantar PodmanError
        # (binario ausente, "podman ps" falhou) ou estourar o timeout do
        # lado do host (podman travado). Nenhum dos dois e "conta ausente":
        # e falha de infraestrutura, e tem que ganhar de qualquer estado de
        # conta na precedencia do codigo agregado (2 > 1).
        return AuthResult(
            provider=provider,
            state="provider_error",
            checked_at=checked_at,
            evidence=f"falha ao verificar se o container {container} esta em execucao: {exc}",
            remediation="asb-agent doctor",
        )

    if not container_running:
        # Infraestrutura parada != conta deslogada: nunca reportar
        # unauthenticated quando nem foi possivel perguntar ao fornecedor.
        # ws_hint deriva "demo" de "asb-demo-agent" (mesmo padrao usado em
        # readiness.probe_proxy) para deixar a remediacao copia-e-cola.
        ws_hint = container.removeprefix("asb-").removesuffix("-agent")
        return AuthResult(
            provider=provider,
            state="unreachable",
            checked_at=checked_at,
            evidence=f"container {container} nao esta em execucao",
            remediation=f"asb-agent resume --workspace {ws_hint}",
        )

    command = STATUS_COMMANDS[provider]
    try:
        result = podman.run(
            "exec", "-u", "1000", container,
            "timeout", "10", "bash", "-lc", command,
            check=False, capture=True, timeout=_EXEC_HOST_TIMEOUT,
        )
    except (podman.PodmanError, subprocess.TimeoutExpired) as exc:
        # Falha ao invocar o proprio podman (binario ausente, exec falhou)
        # ou estouro do orcamento de tempo do lado do host: erro de
        # infraestrutura, nunca reportado como conta deslogada.
        return AuthResult(
            provider=provider,
            state="provider_error",
            checked_at=checked_at,
            evidence=f"falha ao executar checagem via podman: {exc}",
            remediation="asb-agent doctor",
        )

    stdout = result.stdout or ""
    stderr = getattr(result, "stderr", "") or ""
    returncode = result.returncode

    if provider == "claude":
        parsed = parse_claude_status(returncode, stdout)
    else:
        parsed = parse_codex_status(returncode, stdout, stderr)
    return replace(parsed, checked_at=checked_at)


def _aggregate_exit_code(results: list[AuthResult]) -> int:
    """0 se todos authenticated; 1 se conta ausente/expirada; 2 se algum
    unknown/unreachable/provider_error — com precedencia sobre 1."""
    states = {r.state for r in results}
    if states & {"unknown", "unreachable", "provider_error"}:
        return 2
    if "unauthenticated" in states:
        return 1
    return 0


def status(ws: str, provider: str, *, json_output: bool) -> int:
    """`asb-agent auth status`: relatorio schema 1 de status de conta por
    fornecedor, para um workspace. Nunca inicia login, logout ou envia
    prompt — apenas le.

    Em modo JSON, stdout carrega SOMENTE o relatorio (nada mais e impresso
    ali); diagnosticos vao para stderr em qualquer modo.
    """
    if provider not in _PUBLIC_PROVIDERS:
        raise ValueError(
            f"provedor invalido: {provider!r} (use claude, codex, agy ou all)")

    providers = ("claude", "codex", "agy") if provider == "all" else (provider,)
    container = lifecycle.names(ws)["agent"]
    results = [check_status(p, container) for p in providers]
    checked_at = _now_iso()

    if json_output:
        report = {
            "schemaVersion": 1,
            "workspace": ws,
            "checkedAt": checked_at,
            "results": [
                {
                    "provider": r.provider,
                    "state": r.state,
                    "checkedAt": r.checked_at,
                    "evidence": r.evidence,
                    "remediation": r.remediation,
                }
                for r in results
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        print(f"agent-sandbox auth status ({ws})", file=sys.stderr)
        for r in results:
            marker = "ok   " if r.state == "authenticated" else "FALTA"
            line = f"  {marker} {r.provider}: {r.state} ({r.evidence})"
            if r.remediation:
                line += f"  ->  {r.remediation}"
            print(line, file=sys.stderr)

    return _aggregate_exit_code(results)


# ---------------------------------------------------------------------------
# LOGIN (Tarefa A3) — a unica metade deste modulo que muta estado.
# ---------------------------------------------------------------------------

# Comandos de LOGIN, um por fornecedor, verbatim do brief da A3.
#
# `claude auth login`: `claude /login` responde "isn't available in this
# environment" e sai com codigo 0 SEM logar (A1, Claude Code 2.1.263). Um
# codigo 0 de CLI de fornecedor nunca e prova de que a acao aconteceu — e por
# isso que todo login aqui termina em `verify_fresh_client`.
# `codex login --device-auth`: device-auth de proposito. O OAuth padrao abre
# um servidor de callback numa porta do container que o navegador do host nao
# alcanca, e trava.
# `agy`: o binario nu abre a TUI, que autentica no primeiro uso. Nao ha
# subcomando `login`; `agy login` falha com "unexpected argument".
LOGIN_COMMANDS: dict[str, tuple[str, ...]] = {
    "claude": ("claude", "auth", "login"),
    "codex": ("codex", "login", "--device-auth"),
    "agy": ("agy",),
}

_LOGIN_ORDER = ("claude", "codex", "agy")

# Codigo de saida com que a maioria dos shells reporta SIGINT.
_SIGINT_EXIT = 130


class LoginBusy(Exception):
    """Ja existe uma sessao de login deste fornecedor nesta maquina."""

    def __init__(self, provider: str):
        super().__init__(
            f"ja existe uma sessao de login de {provider} em andamento; "
            f"conclua ou cancele a outra antes de repetir")
        self.provider = provider


def login_command(provider: str) -> tuple[str, ...]:
    """Comando interativo de login de UM fornecedor. 'all' e rejeitado: quem
    resolve o conjunto e `login()`, uma chamada por fornecedor."""
    try:
        return LOGIN_COMMANDS[provider]
    except KeyError:
        raise ValueError(
            f"provedor invalido para login: {provider!r} "
            "(use 'claude', 'codex' ou 'agy')") from None


def _lock_path(provider: str) -> Path:
    return keyring.CONFIG / "locks" / f"login-{provider}.lock"


@contextmanager
def operator_lock(provider: str):
    """Lock por FORNECEDOR, `flock` NAO bloqueante.

    Nao bloqueante de proposito: um login e interativo e pode ficar dezenas de
    minutos aberto esperando o operador. Um lock bloqueante deixaria a segunda
    invocacao pendurada sem explicacao; aqui ela recebe `LoginBusy` na hora e
    o operador decide.

    O lock e por fornecedor, e nao global, porque logins de fornecedores
    diferentes sao independentes e o contrato do projeto e um login por
    fornecedor compartilhado entre workspaces — nunca um login por workspace.
    """
    path = _lock_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    handle = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LoginBusy(provider) from exc
        try:
            yield path
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def _client_name(kind: str, provider: str) -> str:
    """Nome UNICO por execucao.

    O nome fixo `asb-login` era compartilhado: duas execucoes concorrentes
    removiam o container uma da outra. Com pid + sufixo aleatorio, o cleanup
    so pode citar o ID que a propria execucao criou.
    """
    return f"asb-{kind}-{provider}-{os.getpid()}-{secrets.token_hex(3)}"


def _client_run_args(name: str) -> tuple[str, ...]:
    """Cliente efemero de login/verificacao.

    FORA da rede interna de proposito: o device-auth precisa de egresso
    direto, e nao ha proxy algum neste caminho.

    As credenciais chegam como DIRETORIOS montados (`~/.claude`, `~/.codex`),
    nunca como symlink de arquivo: A1 provou que `rename` sobre symlink
    substitui o proprio symlink e corta o vinculo com o volume, e que sobre um
    arquivo bind-montado o mesmo `rename` falha com EBUSY.
    """
    home = Path(os.path.expanduser("~"))
    return (
        "run", "-d", "--name", name,
        "--userns", "keep-id:uid=1000,gid=1000",
        "-v", f"{lifecycle.ensure_keyring_runtime_volume()}:/run/asb-keyring:ro,z",
        "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}",
        "-v", f"{lifecycle.ensure_credentials_volume()}:/run/asb-credentials:z",
        "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,"
                   "ro,notmpcopyup,tmpfs-mode=000",
        *lifecycle.credential_mount_args(home),
        lifecycle.IMAGE,
    )


def verify_fresh_client(provider: str) -> AuthResult:
    """Sobe um cliente NOVO e pergunta a ele se a credencial pegou.

    Perguntar ao proprio cliente de login provaria pouco: ele tem o estado
    quente do fluxo que acabou de rodar. O que este redesenho existe para
    garantir e que a credencial sobreviva ao container, entao a verificacao
    acontece num container que nunca viu o login — exatamente o que o piloto
    do operador fez a mao com os clientes `-fresh`.
    """
    if provider not in _INDIVIDUAL_PROVIDERS:
        raise ValueError(
            f"provedor invalido para verificacao: {provider!r} "
            "(use 'claude', 'codex' ou 'agy')")

    if provider == "agy":
        # A1: agy nao tem status local, e `agy -p ping` bloqueia 60s quando
        # deslogado. Ate a A4 integrar `verify_client`, o resultado e
        # explicitamente PENDENTE — jamais "authenticated" por otimismo, e
        # jamais autorizando anunciar login completo de `all`.
        return AuthResult(
            provider="agy",
            state="pending",
            checked_at=_now_iso(),
            evidence=("agy nao possui status local comprovado; a verificacao "
                      "depende do verify_client limitado da Tarefa A4"),
            remediation="asb-agent auth verify --agent agy (Tarefa A4)",
        )

    name = _client_name("verify", provider)
    try:
        # A criacao fica DENTRO do try: um Ctrl-C entre o `run` retornar e o
        # `try` comecar deixaria o cliente de pe para sempre. `rm -f` de um
        # container que nunca existiu e inofensivo.
        podman.run(*_client_run_args(name))
        return check_status(provider, name)
    finally:
        podman.run("rm", "-f", name, check=False)


def _run_interactive_login(provider: str) -> None:
    """Roda o login interativo num cliente proprio e o encerra em seguida.

    A saida NAO e capturada: o exec herda o TTY do operador. Capturar traria
    codigo de device-auth e token para dentro deste processo, de onde vazariam
    para qualquer log — e o codigo de retorno do fornecedor nao e evidencia de
    nada (A1), entao nao ha o que ganhar capturando.
    """
    name = _client_name("login", provider)
    home = str(Path(os.path.expanduser("~")))
    try:
        podman.run(*_client_run_args(name))
        # `bash -lc` nao e decoracao: sem shell de login o agy nao esta no
        # PATH e DBUS_SESSION_BUS_ADDRESS esta ausente, que e exatamente como
        # a credencial acaba em texto claro em vez do keyring.
        # -w garante execucao no HOME do usuario em vez da raiz /.
        result = subprocess.run(
            [podman.require_binary(), "exec", "-it", "-u", "1000",
             "-w", home, name, "bash", "-lc",
             " ".join(login_command(provider))])
        if result.returncode == _SIGINT_EXIT:
            raise KeyboardInterrupt
    finally:
        # Encerrar o cliente de login ANTES de verificar: a verificacao so
        # prova persistencia se o container que fez o login ja nao existe.
        podman.run("rm", "-f", name, check=False)


def _login_exit_code(results: list[AuthResult]) -> int:
    """0 so quando TODOS os fornecedores pedidos foram verificados como
    autenticados por um cliente novo.

    Mesma precedencia do agregado de `status()`: 2 (infraestrutura) ganha de
    1 (conta). `pending` entra em 1 — nao e falha de infraestrutura, mas
    tambem nao e prova de login, e nao pode virar 0.
    """
    states = {r.state for r in results}
    if states & {"unknown", "unreachable", "provider_error"}:
        return 2
    if states & {"unauthenticated", "pending"}:
        return 1
    return 0


def _report_login(result: AuthResult) -> None:
    marker = {"authenticated": "ok      ",
              "pending": "PENDENTE"}.get(result.state, "FALHOU  ")
    line = f"  {marker} {result.provider}: {result.state} ({result.evidence})"
    if result.remediation:
        line += f"  ->  {result.remediation}"
    print(line, file=sys.stderr)


def login(root: Path, provider: str = "all") -> int:
    """`asb-agent login [--agent X]`: autentica UM fornecedor, ou todos.

    Seletivo de proposito. O laco indiscriminado do v1 obrigava o operador a
    passar pelos tres para consertar um, e um fornecedor que falhava no meio
    levava os outros junto. Aqui cada fornecedor tem lock, cliente, resultado
    e erro proprios, e o codigo agregado nunca e 0 sem prova de todos.
    """
    if provider not in _PUBLIC_PROVIDERS:
        raise ValueError(
            f"provedor invalido: {provider!r} (use claude, codex, agy ou all)")

    providers = _LOGIN_ORDER if provider == "all" else (provider,)

    if not sys.stdin.isatty():
        # Sem TTY o `podman exec -it` nao tem como apresentar o fluxo e o
        # processo ficaria pendurado. Falhar com orientacao e melhor que
        # travar num cron ou num pipe.
        print("asb-agent login precisa de um terminal interativo: o fluxo de "
              "device-auth le codigo do operador.\n"
              "Rode o comando direto no seu terminal, sem pipe, sem redirecionar "
              "a entrada e sem 'ssh -T'.", file=sys.stderr)
        return 2

    if not podman.exists("image", lifecycle.IMAGE):
        raise podman.PodmanError(
            f"imagem {lifecycle.IMAGE} ausente; execute 'asb-agent build'")

    lifecycle.ensure_keyring_service()

    print("\nEntre em cada agente. Use SEMPRE fluxos de device-auth: o OAuth "
          "padrao abre um servidor de callback numa porta do container que o "
          "navegador do host nao alcanca, e trava.\n", file=sys.stderr)

    results: list[AuthResult] = []
    for name in providers:
        print(f"--- {name} ---", file=sys.stderr)
        if name == "claude":
            print("Aviso: se o Claude Code solicitar 'Quick safety check', use "
                  "a seta\npara baixo e selecione 'Yes, I trust this folder' "
                  "(o padrao 'No, exit' aborta o login).\n", file=sys.stderr)
        try:
            with operator_lock(name):
                _run_interactive_login(name)
                results.append(verify_fresh_client(name))
        except LoginBusy as exc:
            # Sessao ocupada e infraestrutura, nao conta ausente: nada foi
            # perguntado ao fornecedor.
            results.append(AuthResult(
                provider=name,
                state="provider_error",
                checked_at=_now_iso(),
                evidence="ja existe uma sessao de login deste fornecedor",
                remediation="conclua ou cancele a outra sessao e repita"))
            print(f"asb-agent: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            # Cancelar preserva dados: o cliente efemero desta execucao ja foi
            # removido pelo `finally`, e nenhuma credencial e apagada. Nunca
            # apagamos credencial para "recuperar" de um cancelamento.
            print(f"\nlogin de {name} cancelado; nenhuma credencial foi "
                  "alterada", file=sys.stderr)
            # O que ja foi verificado antes do cancelamento continua valendo e
            # e reportado; so o codigo de saida vira 130.
            for done in results:
                _report_login(done)
            return _SIGINT_EXIT

    for result in results:
        _report_login(result)
    if any(r.state == "pending" for r in results):
        print("um resultado PENDENTE nao autoriza declarar login concluido; "
              "a verificacao do agy depende da Tarefa A4", file=sys.stderr)
    return _login_exit_code(results)
