"""cli/asb/interfaces/ui.py — `asb-agent ui`: abre a interface web.

Espec 8.2. Le porta e token pela MESMA convencao de `keyring.CONFIG` (via
`install.server_token_path`). Com `--print-url`, imprime a URL e para ali —
NENHUMA chamada de rede, para que o comando funcione so lendo o token, sem
exigir um daemon de pe (a "Acceptance" da Tarefa 7 pede exatamente isso).
Sem `--print-url`, confere `GET /api/health` uma unica vez e, se o daemon
nao responder, reporta a unidade como inativa e nomeia o comando
`systemctl --user start` — nunca tenta subir o daemon sozinho. Saudavel,
abre a URL em modo app no primeiro de `chromium`, `google-chrome-stable`,
`brave` encontrado no PATH, com `xdg-open` como fallback e a URL impressa se
nada abrir (espec 12).

Emenda E, absoluta: o token so aparece na FRAGMENT da URL
(`#token=...`), nunca numa query string nem numa linha impressa isolada —
a fragment nunca sai no request line, entao nunca chega a um log do
servidor.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

from .. import install

_BROWSERS = ("chromium", "google-chrome-stable", "brave")


def _find_browser(which: Callable[[str], str | None]) -> str | None:
    for name in _BROWSERS:
        path = which(name)
        if path:
            return path
    return None


def _open_url(
    url: str,
    *,
    which: Callable[[str], str | None],
    popen: Callable[..., object],
) -> bool:
    """Tenta abrir `url`: primeiro navegador encontrado em modo app, senao
    `xdg-open`. Devolve False (sem levantar) quando nada abriu — o chamador
    imprime a URL nesse caso, como a espec 12 pede."""
    browser = _find_browser(which)
    if browser is not None:
        try:
            popen([browser, f"--app={url}"])
            return True
        except OSError:
            pass

    xdg = which("xdg-open")
    if xdg is not None:
        try:
            popen([xdg, url])
            return True
        except OSError:
            pass

    return False


def ui(
    *,
    print_url: bool = False,
    check_health: Callable[[str], bool] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    popen: Callable[..., object] = subprocess.Popen,
    out=sys.stdout,
    err=sys.stderr,
) -> int:
    port = install.server_port()
    token_path = install.server_token_path()
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"nao foi possivel ler o token em {token_path}: {exc}", file=err)
        return 1

    url = f"http://127.0.0.1:{port}/#token={token}"

    # `--print-url` so imprime: nenhuma chamada de rede, nada aberto. E o
    # unico jeito de a acao "imprime a URL" ficar verificavel sem depender
    # de o daemon estar de pe (a Emenda G pede evidencia disso sem um
    # daemon real).
    if print_url:
        print(url, file=out)
        return 0

    checker = check_health or install.default_health_check
    if not checker(install.server_health_url(port)):
        print(
            f"asb-server nao respondeu; se a unidade estiver inativa, rode: "
            f"systemctl --user start {install.SERVER_UNIT_NAME}",
            file=err,
        )
        return 1

    if _open_url(url, which=which, popen=popen):
        return 0

    print(url, file=out)
    return 0
