"""cli/asb/network_gate.py — espera unica por conectividade real do host.

ExecStart de `asb-network.service` (Emenda A §4): `Type=oneshot`,
`TimeoutStartSec=infinity`. Sai 0 somente quando `probe_host()` devolve
`healthy`; qualquer outro resultado, inclusive `tls_failed` de um portal
cativo, e continuar esperando.

Nunca inicia processo, nunca cria o namespace rootless. Criar o namespace aqui
reproduziria o defeito do drop-in antigo, que o inicializava antes de a rede
funcionar e o deixava sem egresso ate o proximo boot.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

from .readiness import ProbeResult, probe_host

DEFAULT_TARGET = "github.com:443"
INTERVAL_SECONDS = 5.0
SUMMARY_SECONDS = 60.0


def gate_target() -> str:
    """Destino sondado; `ASB_NETWORK_GATE_TARGET` o substitui em ambiente isolado."""
    return os.environ.get("ASB_NETWORK_GATE_TARGET") or DEFAULT_TARGET


def _log_stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def wait_for_network(
    target: str,
    *,
    probe: Callable[..., ProbeResult] = probe_host,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = _log_stderr,
    interval: float = INTERVAL_SECONDS,
    summary_every: float = SUMMARY_SECONDS,
) -> int:
    """Bloqueia ate o host alcancar `target`; devolve 0.

    O journal recebe so mudancas de estado e um resumo a cada `summary_every`
    segundos: horas offline nao geram uma linha a cada `interval`.
    """
    started = clock()
    last_code: str | None = None
    last_log = started
    attempts = 0
    while True:
        attempts += 1
        result = probe(target=target, timeout=interval)
        if result.state == "healthy":
            log(f"asb-network: conectividade real confirmada ({target}) "
                f"apos {attempts} tentativa(s) e {int(clock() - started)}s")
            return 0
        if result.code != last_code:
            log(f"asb-network: aguardando conectividade real ({target}): {result.code}")
            last_code = result.code
            last_log = clock()
        elif clock() - last_log >= summary_every:
            log(f"asb-network: ainda aguardando ({target}): {result.code}, "
                f"{attempts} tentativa(s), {int(clock() - started)}s")
            last_log = clock()
        sleep(interval)


def main() -> int:
    return wait_for_network(gate_target())


if __name__ == "__main__":
    sys.exit(main())
