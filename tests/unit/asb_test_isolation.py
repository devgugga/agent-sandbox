"""Isolamento IMPOSTO da suite unitaria: nenhum teste fala de volume real.

Nao e um teste. E o guarda que os testes importam na primeira linha, e ha um
teste em `test_login_flow.py` que reprova qualquer `tests/unit/test_*.py` que
esqueca de importa-lo.

Por que ele existe: duas vezes um teste desta suite mockou apenas
`lifecycle.ensure_credentials_volume` e deixou a chamada SEGUINTE chegar a um
`podman volume inspect asb-credentials` de verdade, resolvendo o mountpoint do
volume de credenciais de PRODUCAO do operador e criando diretorios dentro
dele. O que existia contra isso era uma docstring pedindo cuidado, e uma
docstring nao impede nada.

Onde o guarda entra, e por que ai: `subprocess.run` e o unico ponto por onde
TODA invocacao real do podman passa. Guardar o invólucro `podman` nao serviria
— `asb.podman` (via o sys.path de `cli/`) e `cli.asb.podman` (via o pacote
`cli`) sao dois objetos de modulo distintos na MESMA execucao da suite, e
guardar um deixaria o outro aberto. `subprocess` e um so para os dois.

A regra e deliberadamente mais forte que a propriedade pedida pela revisao
("nenhum `podman volume inspect` real de volume sem prefixo `asb-test-`"):

    nenhuma invocacao REAL de podman vinda de um teste unitario pode NOMEAR
    um volume, com prefixo ou sem.

Mais forte de proposito. Sob uma regra de prefixo, um
`podman volume create asb-test-unit-credentials` real PASSARIA — e deixaria
recurso para tras numa suite que tem de terminar sem nenhum. Um teste que
precisa de comportamento de podman mocka podman; um teste que nao mocka nao
chega ao host.

Por que NAO ha tambem um default de `ASB_CREDENTIALS_VOLUME` na suite (a
revisao sugeriu isso como "a rota mais barata", e pediu para conferir contra
os testes que asserem a string literal): conferido, e ele nao paga. O que a
variavel muda e o NOME que `ensure_credentials_volume()` devolve — e sob a
regra acima nenhum teste consegue levar nome algum de volume ate o podman, de
producao ou de teste. Em compensacao ela quebra os testes que legitimamente
afirmam que o `doctor` imprime `volume asb-credentials` para o operador
(test_doctor, test_auth), trocando uma asercao de contrato por uma de nome
sintetico. Guarda de comportamento vale mais que renomear o alvo proibido.
"""
from __future__ import annotations

import os
import subprocess

_GUARD_MARK = "_asb_unit_isolation_guard"


class RealPodmanVolumeAccess(AssertionError):
    """Um teste unitario tentou nomear um volume para o podman de verdade."""


# Verbos de `podman volume ...` que recebem NOME de volume como argumento
# posicional. `ls` fica de fora: nao nomeia volume nenhum.
_VOLUME_VERBS_WITH_NAMES = frozenset(
    {"create", "inspect", "exists", "rm", "remove", "mount", "unmount"})

# Flags de `podman volume ...` cujo ARGUMENTO seguinte nao e nome de volume.
_FLAGS_THAT_TAKE_A_VALUE = frozenset({"--format", "--driver", "--opt", "--label"})


def _mount_volume_source(spec: str) -> str | None:
    """Nome do volume citado num `--mount type=volume,src=...`."""
    fields: dict[str, str] = {}
    for field in spec.split(","):
        key, _, value = field.partition("=")
        fields[key.strip()] = value.strip()
    if fields.get("type") != "volume":
        return None
    return fields.get("src") or fields.get("source") or None


def named_volumes(argv: list[str]) -> list[str]:
    """Volumes que esta linha de comando do podman nomeia."""
    found: list[str] = []

    if len(argv) >= 4 and argv[1] == "volume" \
            and argv[2] in _VOLUME_VERBS_WITH_NAMES:
        skip_next = False
        for token in argv[3:]:
            if skip_next:
                skip_next = False
                continue
            if token.startswith("-"):
                # Uma flag NAO encerra a lista: `podman volume rm -f <nome>`
                # poe o nome depois dela. Parar na primeira flag deixava
                # justamente a remocao forcada passar batida.
                skip_next = token in _FLAGS_THAT_TAKE_A_VALUE
                continue
            found.append(token)

    for index, token in enumerate(argv):
        if index + 1 >= len(argv):
            break
        value = argv[index + 1]
        if token == "-v" or token == "--volume":
            source = value.split(":", 1)[0]
            # Origem absoluta e bind de diretorio do host, nao volume nomeado.
            if source and not source.startswith(("/", ".", "~")):
                found.append(source)
        elif token == "--mount":
            source = _mount_volume_source(value)
            if source:
                found.append(source)

    return found


def _install() -> None:
    real_run = subprocess.run
    if getattr(real_run, _GUARD_MARK, False):
        return

    def guarded_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)) and argv:
            parts = [str(part) for part in argv]
            if os.path.basename(parts[0]) == "podman":
                volumes = named_volumes(parts)
                if volumes:
                    raise RealPodmanVolumeAccess(
                        "teste unitario tentou executar podman de verdade "
                        f"nomeando volume(s) {volumes}: {' '.join(parts)}. "
                        "Mocke o podman (ou a funcao do lifecycle que o "
                        "chama): a suite unitaria nunca toca volume do host.")
        return real_run(*args, **kwargs)

    setattr(guarded_run, _GUARD_MARK, True)
    subprocess.run = guarded_run


_install()
