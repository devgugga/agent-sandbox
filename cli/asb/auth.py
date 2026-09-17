"""cli/asb/auth.py — status de CONTA por fornecedor (Tarefa A2).

Separa tres coisas que o `doctor` v1 misturava: se a CONTA de um fornecedor
esta autenticada, se a REDE alcanca o fornecedor, e se a INFRAESTRUTURA local
(keyring, containers) esta saudavel. Este modulo responde SOMENTE a primeira
pergunta. Rede e infraestrutura ja tem seus proprios sensores dedicados
(cli/asb/readiness.py, cli/asb/keyring.py).

Tres metades com fronteira explicita:

* DIAGNOSTICO (`check_status`, `status`, os `parse_*`): nunca inicia login,
  nunca faz logout, nunca envia prompt. Apenas LE o estado corrente do
  fornecedor, como uid 1000, com o ambiente do workspace e timeout limitado
  (10s) — o mesmo perfil das demais sondas.
* LOGIN (`login`, `login_command`, `operator_lock`, `verify_fresh_client`,
  Tarefa A3): unico caminho que muta estado, sempre sob pedido explicito do
  operador, sempre com TTY, sempre com lock por fornecedor.
* VERIFICACAO (`verify`, `verify_client`, `classify_verification`, Tarefa
  A4): nunca muta estado, mas faz UMA chamada real ao fornecedor por
  execucao — sem retry — dentro do container do WORKSPACE ja em execucao
  (o mesmo caminho de proxy/allowlist do agente real), para provar que o
  servidor aceitou a credencial, e nao apenas que o cliente local acha que
  esta logado. E o unico caminho capaz de tirar `agy` (sem comando de
  status local, A1) do estado `unknown`/`pending`.

Nenhuma das tres metades interpola saida capturada do fornecedor em
evidencia ou remediacao: e ali que tokens e codigos OAuth apareceriam. A
evidencia e sempre texto enlatado somado a um codigo de retorno; a
classificacao de VERIFICACAO usa uma ALLOWLIST de marcadores conhecidos e
seguros (ex.: "429", "not logged in"), nunca uma regex que promete varrer
segredo arbitrario da saida.

Um retorno "authenticated" do DIAGNOSTICO prova que o comando de status do
fornecedor respondeu como autenticado agora; nao e prova de que uma chamada
real foi aceita pelo servidor remoto — essa prova e o que `verify` entrega.
"""
from __future__ import annotations

import fcntl
import getpass
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import keyring, lifecycle, podman, readiness


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


# Os dois conjuntos abaixo sao ALLOWLISTS, nunca blocklists. A versao antiga
# testava os estados RUINS e devolvia 0 para todo o resto: qualquer estado novo
# — `pending`, criado nesta mesma tarefa — nascia valendo "exit 0 = todos
# autenticados". "Sucesso sem prova" e a falha que este redesenho existe para
# eliminar, entao a funcao nega por padrao: so o conjunto explicito de estados
# saudaveis produz 0, e um estado desconhecido cai no 2 junto da infraestrutura.
_AUTHENTICATED_STATES = frozenset({"authenticated"})
_ACCOUNT_MISSING_STATES = frozenset({"unauthenticated", "pending"})


def _aggregate_exit_code(results: list[AuthResult]) -> int:
    """Codigo agregado, NEGANDO POR PADRAO.

    0 exige que todo resultado esteja num estado comprovadamente saudavel;
    1 e reservado a "conta ausente ou nao comprovada" (`unauthenticated`,
    `pending`); qualquer outra coisa — infraestrutura (`unknown`,
    `unreachable`, `provider_error`) ou um estado que ninguem previu — vira 2,
    mantendo a precedencia 2 > 1 > 0. Lista vazia tambem e 2: nao ter
    perguntado a ninguem nao e prova de nada.
    """
    if not results:
        return 2
    states = {r.state for r in results}
    if states <= _AUTHENTICATED_STATES:
        return 0
    if states <= _AUTHENTICATED_STATES | _ACCOUNT_MISSING_STATES:
        return 1
    return 2


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

    lifecycle.ensure_keyring_service(lifecycle.ensure_runtime(root))

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
        except podman.PodmanError as exc:
            # Falha de infraestrutura de UM fornecedor nao pode levar os
            # outros junto: deixar a excecao escapar do laco descartava em
            # silencio um sucesso ja verificado momentos antes, e o brief
            # exige resultado separado por fornecedor com os erros
            # PRESERVADOS. A evidencia continua sendo texto enlatado somado
            # ao erro do podman (que nunca carrega saida do fornecedor).
            results.append(AuthResult(
                provider=name,
                state="provider_error",
                checked_at=_now_iso(),
                evidence=f"falha de infraestrutura durante o login: {exc}",
                remediation="asb-agent doctor"))
            print(f"asb-agent: login de {name} falhou: {exc}", file=sys.stderr)
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
    # Mesmo agregado do `status()`, de proposito: um unico lugar decide o que
    # vale 0, e ele nega por padrao. Duas copias da regra eram como `pending`
    # ficou correto num caminho e valendo 0 no outro.
    return _aggregate_exit_code(results)


# ---------------------------------------------------------------------------
# VERIFICACAO (Tarefa A4) — chamada REAL ao fornecedor, orcamento explicito.
# ---------------------------------------------------------------------------
#
# Diferente de LOGIN (que verifica um cliente NOVO local, via status nativo)
# e de DIAGNOSTICO (que nunca sai do host), VERIFICACAO roda dentro do
# container do WORKSPACE ja em execucao — o mesmo caminho de rede (proxy,
# allowlist) que o agente real usa — e manda um prompt sintetico. So essa
# chamada prova que o SERVIDOR aceitou a credencial; tudo antes disso e
# opiniao do cliente local.
#
# Orcamento: uma chamada por fornecedor por `verify_client()`, sem retry.
# Duas checagens de infraestrutura rodam ANTES da chamada; se qualquer uma
# falhar, a chamada NUNCA acontece — o orcamento fica intacto e o resultado
# e `unreachable`, nunca `unauthenticated`: rede ruim jamais vira "logout"
# (motivo do primeiro teste desta tarefa).

# Prompt sintetico e resposta esperada, compartilhados entre claude e codex.
# `agy` NAO usa prompt algum (ver `_verify_command`): o brief proibe
# explicitamente usar prompt como teste local do agy — `agy -p` bloqueia ate
# 60s aguardando input quando deslogado (A1) — e o subcomando `agy models`
# (real e documentado em `agy --help` na versao fixada 1.1.27; confirmado no
# piloto, docs/validation/2026-09-07-auth-pilot-live.md: falha RAPIDO sem
# credencial) prova a mesma coisa sem esse risco.
_VERIFY_PROMPT = ("Responda apenas, sem nenhum texto adicional antes ou "
                  "depois, com a frase exata: ASB_AUTH_VERIFY_OK")
_VERIFY_EXPECTED_RESPONSE = "ASB_AUTH_VERIFY_OK"

# Orcamento de tempo da PROPRIA chamada, do lado de DENTRO do container: o
# `timeout` do coreutils mata o comando do fornecedor mesmo que ele fique
# esperando entrada (o cenario mais parecido com o bloqueio de 60s do agy
# deslogado). O timeout do lado do HOST (_VERIFY_EXEC_HOST_TIMEOUT) tem
# folga para o interno matar primeiro — mesmo padrao de _EXEC_HOST_TIMEOUT
# acima. Nenhum dos dois pode estourar sem que o resultado vire
# `unreachable`: nunca `unauthenticated` por ausencia de resposta.
_VERIFY_PROVIDER_TIMEOUT = 60   # segundos, `timeout N` dentro do container
_VERIFY_EXEC_HOST_TIMEOUT = 70  # segundos, do lado do host


def _verify_command(provider: str) -> str:
    """Script remoto de UMA chamada real, executado via SSH no workspace.

    O script cria e remove um diretorio sintetico explicito em `/tmp`, muda
    para ele antes de chamar o wrapper configurado e fecha stdin. Assim uma
    futura mudanca de WORKDIR na imagem nao consegue mover a verificacao para
    dentro do projeto montado ou para perto de secrets do workspace.

    Cada flag usada aqui foi confirmada na versao fixada, offline, sem
    tocar rede (`agy --help`, `codex exec --help`): `agy models`,
    `codex exec --skip-git-repo-check --sandbox read-only -o <file>`,
    `claude -p`. Nenhuma e uma flag imaginada.
    """
    prompt = shlex.quote(_VERIFY_PROMPT)
    setup = (
        "WORKDIR=$(mktemp -d /tmp/asb-auth-verify.XXXXXX) || exit 70; "
        "trap 'rm -rf \"$WORKDIR\"' EXIT HUP INT TERM; "
        "cd \"$WORKDIR\" || exit 70; "
    )
    if provider == "claude":
        return (f"{setup}timeout {_VERIFY_PROVIDER_TIMEOUT} "
                f"asb-claude -p {prompt} < /dev/null")
    if provider == "codex":
        # O stdout do `codex exec` nao participa da prova: algumas versoes
        # tambem transmitem eventos/resposta ali. Somente o arquivo de `-o`
        # e lido; stderr e revelado apenas na falha para classificacao.
        return (
            f'{setup}OUT="$WORKDIR/codex-output"; '
            f'ERR="$WORKDIR/codex-error"; '
            f'timeout {_VERIFY_PROVIDER_TIMEOUT} asb-codex exec '
            f'--skip-git-repo-check --sandbox read-only -o "$OUT" {prompt} '
            f'< /dev/null > /dev/null 2>"$ERR"; RC=$?; '
            f'if [ "$RC" -eq 0 ]; then cat "$OUT" 2>/dev/null; '
            f'else cat "$ERR" >&2; fi; exit "$RC"'
        )
    if provider == "agy":
        # Sem prompt e sem `-p`/`--print`: `agy models` e um subcomando REAL
        # (nao uma flag inventada) que nao envia mensagem alguma ao modelo.
        # `--print-timeout` existe na versao fixada mas sua aplicabilidade a
        # `models` (em vez de `-p`) nao foi confirmada sem uma chamada real
        # — o orcamento de tempo usa APENAS o `timeout` externo do bash.
        return (f"{setup}timeout {_VERIFY_PROVIDER_TIMEOUT} "
                "asb-agy models < /dev/null")
    raise ValueError(
        f"provedor invalido para verificacao real: {provider!r} "
        "(use 'claude', 'codex' ou 'agy')")


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

# Evidencia PROPRIA de cada fornecedor de que a credencial e invalida. Um
# 401/403 puro NAO entra aqui de proposito: ele tambem e a assinatura de uma
# negativa de ACL do proxy, e o brief exige a evidencia do FORNECEDOR — nunca
# o codigo de um intermediario.
_AUTH_EVIDENCE_MARKERS: dict[str, tuple[str, ...]] = {
    "claude": (
        "invalid x-api-key", "authentication_error", "not logged in",
        "please run /login", "invalid bearer token",
    ),
    "codex": (
        "not logged in", "invalid_api_key", "incorrect api key provided",
        "no codex credentials were found",
    ),
    "agy": ("authentication required", "authentication failed"),
}

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

    `verify_client` monta `combined = f"{stdout}\\n{stderr}"`, entao a prosa
    de stderr chega DEPOIS das linhas de modelo. Por `podman exec` ela aparece
    antes. As duas ordens sao toleradas; o que nao e tolerado e prosa NO MEIO.

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


def classify_verification(provider: str, returncode: int, output: str,
                          network_ok: bool) -> AuthResult:
    """Classifica o RESULTADO de uma chamada real (ou a decisao de nao
    faze-la). Pura: nenhum I/O, nenhum podman, nenhuma chamada.

    Ordem das checagens, deliberada: rede primeiro (nunca vira logout),
    depois categorias de resposta do fornecedor que TAMBEM nunca podem
    apagar credencial (limite de taxa, erro de servico), so entao a
    evidencia PROPRIA de credencial invalida — e so quando o fornecedor
    fala, nunca a partir de um 401/403 generico que um proxy tambem emite.

    A evidencia devolvida e sempre texto enlatado (categoria), nunca o
    `output` bruto: e ali que apareceriam tokens e codigos OAuth.
    """
    checked_at = _now_iso()
    text = (output or "").lower()

    if not network_ok:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="rede indisponivel antes da chamada; nenhuma chamada "
                     "foi contada no orcamento",
            remediation="asb-agent doctor")

    if returncode == 124:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="chamada ao fornecedor atingiu o limite interno de "
                     "tempo (codigo 124); nunca interpretado como logout",
            remediation="tente novamente mais tarde")

    if any(marker in text for marker in _NETWORK_MARKERS):
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="chamada ao fornecedor falhou por rede (timeout ou "
                     "conexao); nunca interpretado como logout",
            remediation="asb-agent doctor")

    if _contains_code(text, _RATE_LIMIT_CODES) or any(
            marker in text for marker in _RATE_LIMIT_TEXT_MARKERS):
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence="fornecedor respondeu limite de taxa (429); rate limit "
                     "nunca apaga a credencial",
            remediation="aguarde e tente novamente mais tarde; nao repita a "
                       "chamada agora")

    if _contains_code(text, _SERVICE_ERROR_CODES) or any(
            marker in text for marker in _SERVICE_ERROR_TEXT_MARKERS):
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence="fornecedor reportou erro de servico (5xx); "
                     "indisponibilidade nunca apaga a credencial",
            remediation="tente novamente mais tarde")

    markers = _AUTH_EVIDENCE_MARKERS.get(provider, ())
    if any(marker in text for marker in markers):
        return AuthResult(
            provider=provider, state="unauthenticated", checked_at=checked_at,
            evidence=f"o proprio fornecedor {provider} reportou credencial "
                     "invalida (nao um 401/403 generico de proxy)",
            remediation="asb-agent login")

    normalized = " ".join((output or "").split())
    success_format = (
        _agy_models_output_valid(output)
        if provider == "agy"
        else normalized == _VERIFY_EXPECTED_RESPONSE
    )
    if returncode == 0 and success_format:
        return AuthResult(
            provider=provider, state="authenticated", checked_at=checked_at,
            evidence=("'agy models' retornou uma lista de nomes de modelos "
                      "com codigo 0; prova acesso a lista, nao geracao"
                      if provider == "agy" else
                      "chamada real ao fornecedor respondeu no formato "
                      "solicitado, com codigo 0"),
            remediation="")

    if returncode == 0:
        return AuthResult(
            provider=provider, state="unknown", checked_at=checked_at,
            evidence="chamada real retornou codigo 0, mas a resposta nao "
                     "bateu com o formato esperado (erro de formato, "
                     "registrado separado de erro de credencial)",
            remediation=f"asb-agent auth verify --agent {provider}")

    return AuthResult(
        provider=provider, state="unknown", checked_at=checked_at,
        evidence=f"saida nao reconhecida da chamada real ao fornecedor "
                 f"(codigo {returncode})",
        remediation=f"asb-agent auth verify --agent {provider}")


# Orcamento OBSERVAVEL: quantas chamadas REAIS cada fornecedor recebeu
# nesta execucao do processo. Existe para o piloto real (fora do escopo
# desta tarefa, ver brief) registrar a contagem exigida — nunca para
# decidir estado algum aqui.
_CALL_BUDGET: dict[str, int] = {}


def call_budget() -> dict[str, int]:
    """Copia do contador de chamadas reais por fornecedor."""
    return dict(_CALL_BUDGET)


def reset_call_budget() -> None:
    """Zera o contador. Uso exclusivo de testes: a producao nunca zera."""
    _CALL_BUDGET.clear()


def _spend_call(provider: str) -> None:
    _CALL_BUDGET[provider] = _CALL_BUDGET.get(provider, 0) + 1


def verify_client(provider: str, container: str, *,
                  proxy_container: str | None = None) -> AuthResult:
    """Faz UMA chamada real via SSH e wrapper do fornecedor no WORKSPACE.

    `proxy_container` e contexto explicito para o chamador canonico
    (`verify`, que usa `lifecycle.names(ws)`). O parametro e opcional apenas
    para preservar a interface publica de dois argumentos do brief e seus
    consumidores antigos; nesse fallback, a derivacao legada fica isolada
    aqui e nao e usada pelo caminho top-level.

    Orcamento: no maximo uma chamada por fornecedor por invocacao, sem retry.
    Quatro etapas de infraestrutura rodam ANTES e podem devolver um resultado
    sem gastar orcamento: container em execucao, proxy alcancavel, porta/chave
    SSH existentes e gate do transporte. Falhar qualquer uma delas e sempre
    infraestrutura, nunca `unauthenticated` — rede ruim nao pode virar logout.
    """
    if provider not in _INDIVIDUAL_PROVIDERS:
        raise ValueError(
            f"provedor invalido para verificacao: {provider!r} "
            "(use 'claude', 'codex' ou 'agy')")

    checked_at = _now_iso()
    ws_hint = container.removeprefix("asb-").removesuffix("-agent")

    try:
        container_running = podman.running(
            container, timeout=_RUNNING_CHECK_HOST_TIMEOUT)
    except (podman.PodmanError, subprocess.TimeoutExpired) as exc:
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence=f"falha ao verificar se o container {container} esta "
                     f"em execucao: {exc}",
            remediation="asb-agent doctor")

    if not container_running:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence=f"container {container} nao esta em execucao; nenhuma "
                     "chamada foi tentada",
            remediation=f"asb-agent resume --workspace {ws_hint}")

    if proxy_container is None:
        proxy_container = f"asb-{ws_hint}-proxy"
    probe = readiness.probe_proxy(
        agent_container=container, proxy_container=proxy_container)
    network_ok = probe.state == "healthy"
    if not network_ok:
        return replace(
            classify_verification(provider, 1, "", network_ok=False),
            checked_at=checked_at)

    try:
        mapping = podman.out("port", container, "22",
                             timeout=_RUNNING_CHECK_HOST_TIMEOUT)
        ssh_port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
        if not ssh_port:
            raise ValueError("porta SSH ausente")
        ssh_port_number = int(ssh_port)
        if not 1 <= ssh_port_number <= 65535:
            raise ValueError("porta SSH fora do intervalo valido")
        ssh_key = lifecycle.SSH_KEY
        if not ssh_key.is_file():
            raise ValueError("identidade SSH existente nao encontrada")
        ssh_user = getpass.getuser()
    except (podman.PodmanError, subprocess.TimeoutExpired, OSError,
            ValueError, IndexError):
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence="falha de infraestrutura ao preparar SSH para a "
                     "verificacao real",
            remediation="asb-agent doctor")

    ssh_base = [
        "ssh", "-p", str(ssh_port_number), "-i", str(ssh_key),
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR",
        f"{ssh_user}@127.0.0.1",
    ]

    # Gate observacional: prova o MESMO transporte (usuario, porta, chave e
    # opcoes) antes de gastar uma chamada. `true` roda no shell remoto sem
    # alcancar fornecedor algum.
    try:
        transport = subprocess.run(
            [*ssh_base, "true"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
            timeout=_RUNNING_CHECK_HOST_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="gate de transporte SSH excedeu o limite de tempo; "
                     "nenhuma chamada ao fornecedor foi tentada",
            remediation="asb-agent doctor")
    except OSError:
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence="falha local ao executar o gate de transporte SSH; "
                     "nenhuma chamada ao fornecedor foi tentada",
            remediation="asb-agent doctor")

    if transport.returncode != 0:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="gate de transporte SSH falhou; nenhuma chamada ao "
                     "fornecedor foi tentada",
            remediation="asb-agent doctor")

    command = _verify_command(provider)
    _spend_call(provider)
    try:
        result = subprocess.run(
            [*ssh_base, command], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=_VERIFY_EXEC_HOST_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="chamada real ao fornecedor excedeu o orcamento de "
                     f"tempo ({_VERIFY_PROVIDER_TIMEOUT}s); nunca "
                     "interpretado como logout",
            remediation="tente novamente mais tarde")
    except OSError:
        return AuthResult(
            provider=provider, state="provider_error", checked_at=checked_at,
            evidence="falha local de infraestrutura ao executar a "
                     "verificacao real",
            remediation="asb-agent doctor")

    stdout = result.stdout or ""
    stderr = getattr(result, "stderr", "") or ""
    returncode = result.returncode
    combined = f"{stdout}\n{stderr}"

    # 255 e reservado pelo cliente OpenSSH para falhas do proprio transporte.
    # O comando remoto ja foi contado porque o gate havia passado, mas sua
    # saida nunca e tratada como resposta do fornecedor.
    if returncode == 255:
        return AuthResult(
            provider=provider, state="unreachable", checked_at=checked_at,
            evidence="transporte SSH caiu durante a chamada ao fornecedor; "
                     "nunca interpretado como logout",
            remediation="asb-agent doctor")

    return replace(
        classify_verification(provider, returncode, combined, network_ok=True),
        checked_at=checked_at)


def verify(ws: str, provider: str, *, json_output: bool) -> int:
    """`asb-agent auth verify`: UMA chamada real por fornecedor, dentro do
    container do workspace, provando que o servidor aceitou a credencial —
    nao apenas que o cliente local acha que esta logado. Nunca muta estado.

    Mesmo schema de relatorio de `status()`, deliberado: um unico formato
    para o operador e para automacao consumirem, independente de qual
    metade (diagnostico ou verificacao) o gerou.
    """
    if provider not in _PUBLIC_PROVIDERS:
        raise ValueError(
            f"provedor invalido: {provider!r} (use claude, codex, agy ou all)")

    providers = ("claude", "codex", "agy") if provider == "all" else (provider,)
    n = lifecycle.names(ws)
    container = n["agent"]
    budget_before = call_budget()
    results = [verify_client(p, container, proxy_container=n["proxy"])
               for p in providers]
    budget_after = call_budget()
    invocation_budget = {
        p: budget_after.get(p, 0) - budget_before.get(p, 0)
        for p in providers
    }
    checked_at = _now_iso()

    if json_output:
        report = {
            "schemaVersion": 1,
            "workspace": ws,
            "checkedAt": checked_at,
            "callBudget": invocation_budget,
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
        print(f"agent-sandbox auth verify ({ws})", file=sys.stderr)
        for r in results:
            marker = "ok   " if r.state == "authenticated" else "FALTA"
            line = f"  {marker} {r.provider}: {r.state} ({r.evidence})"
            if r.remediation:
                line += f"  ->  {r.remediation}"
            print(line, file=sys.stderr)
        print(f"  chamadas gastas: {invocation_budget}", file=sys.stderr)

    return _aggregate_exit_code(results)
