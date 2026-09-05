"""cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado.

O padrao de TODO campo e o fechado: arquivo ausente equivale a arquivo vazio,
que equivale a sandbox isolado sem acesso algum ao Docker do host.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONTAINER_MODES = ("none", "nested")
HOST_API_LEVELS = ("none", "read")

# Nome de servico vira parte de nome de container (asb-<ws>-svc-<nome>), entao
# so aceita o que o podman aceita.
SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

# Chaves do esquema v1 que deixaram de existir. Recusar em vez de ignorar: um
# perfil antigo aceito em silencio produz um sandbox que nao faz o que o
# arquivo diz, e o operador so descobre quando algo nao alcanca o que deveria.
REMOVED_KEYS = {
    ("sandbox", "mode"):
        'o modo "attached" virou [docker] host_ports, que declara QUAIS portas',
    ("proxy", "java"):
        "removido: era um ajuste pontual que nunca foi exercitado",
    ("tools", "extra"):
        "declare ferramentas no mise.toml do projeto, ou em mise.local.toml "
        "para as que so voce quer",
}


class ProfileError(Exception):
    """Perfil invalido. A mensagem sempre nomeia o campo e o que fazer."""


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    allow: tuple[str, ...] = ()
    host_ports: tuple[int, ...] = ()
    publish_ports: tuple[tuple[int, int], ...] = ()
    container_mode: str = "none"
    host_api: str = "none"
    services: tuple[Service, ...] = ()


def _reject_removed(raw: dict) -> None:
    for (table, key), advice in REMOVED_KEYS.items():
        if key in raw.get(table, {}):
            raise ProfileError(
                f"[{table}] {key} nao existe mais neste esquema: {advice}")


def _strings(raw: dict, table: str, key: str) -> tuple[str, ...]:
    value = raw.get(table, {}).get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ProfileError(f"[{table}] {key} precisa ser uma lista de strings")
    return tuple(value)


def _ports(raw: dict) -> tuple[int, ...]:
    value = raw.get("docker", {}).get("host_ports", [])
    if not isinstance(value, list):
        raise ProfileError("[docker] host_ports precisa ser uma lista")
    ports = []
    for port in value:
        # bool e subclasse de int em Python; `true` numa lista de portas e
        # quase certamente engano do operador.
        if not isinstance(port, int) or isinstance(port, bool):
            raise ProfileError(
                f"[docker] host_ports: {port!r} nao e um numero de porta")
        if not 1 <= port <= 65535:
            raise ProfileError(f"[docker] host_ports: {port} fora de 1-65535")
        ports.append(port)
    return tuple(ports)


def _publish_ports(raw: dict) -> tuple[tuple[int, int], ...]:
    value = raw.get("docker", {}).get("publish_ports", [])
    if not isinstance(value, list):
        raise ProfileError("[docker] publish_ports precisa ser uma lista")
    pairs = []
    for item in value:
        if isinstance(item, bool):
            raise ProfileError(
                f"[docker] publish_ports: {item!r} nao e uma porta valida")
        if isinstance(item, int):
            if not 1 <= item <= 65535:
                raise ProfileError(
                    f"[docker] publish_ports: {item} fora de 1-65535")
            pairs.append((item, item))
        elif isinstance(item, str):
            parts = item.split(":")
            if len(parts) == 2:
                try:
                    host_p = int(parts[0])
                    cont_p = int(parts[1])
                except ValueError:
                    raise ProfileError(
                        f"[docker] publish_ports: {item!r} formato invalido (esperado host:container)")
                if not (1 <= host_p <= 65535 and 1 <= cont_p <= 65535):
                    raise ProfileError(
                        f"[docker] publish_ports: {item!r} portas fora de 1-65535")
                pairs.append((host_p, cont_p))
            elif len(parts) == 1:
                try:
                    p = int(parts[0])
                except ValueError:
                    raise ProfileError(
                        f"[docker] publish_ports: {item!r} formato invalido")
                if not 1 <= p <= 65535:
                    raise ProfileError(
                        f"[docker] publish_ports: {item!r} porta fora de 1-65535")
                pairs.append((p, p))
            else:
                raise ProfileError(
                    f"[docker] publish_ports: {item!r} formato invalido (esperado host:container)")
        else:
            raise ProfileError(
                f"[docker] publish_ports: item {item!r} precisa ser inteiro ou string")
    return tuple(pairs)


def _choice(raw: dict, key: str, allowed: tuple[str, ...], default: str) -> str:
    value = raw.get("docker", {}).get(key, default)
    if value not in allowed:
        raise ProfileError(
            f"[docker] {key} = {value!r}; valores aceitos: "
            + ", ".join(repr(a) for a in allowed))
    return value


def _services(raw: dict) -> tuple[Service, ...]:
    services = []
    for name, body in raw.get("services", {}).items():
        if not SERVICE_NAME.match(name):
            raise ProfileError(
                f"[services.{name}]: nome precisa casar {SERVICE_NAME.pattern} "
                "(vira parte do nome do container)")
        if not isinstance(body, dict) or not isinstance(body.get("image"), str):
            raise ProfileError(f"[services.{name}] exige image = \"...\"")
        env = body.get("env", {})
        if not isinstance(env, dict) or any(
                not isinstance(v, str) for v in env.values()):
            raise ProfileError(
                f"[services.{name}] env precisa mapear string para string")
        services.append(Service(name=name, image=body["image"], env=dict(env)))
    return tuple(services)


def load_profile(repo: Path) -> Profile:
    """Le o perfil do repositorio. Ausente equivale a vazio."""
    candidate = Path(repo) / ".agent-sandbox.toml"
    if not candidate.is_file():
        return Profile()
    try:
        raw = tomllib.loads(candidate.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(f"{candidate}: TOML invalido: {error}") from error

    _reject_removed(raw)
    return Profile(
        allow=_strings(raw, "network", "allow"),
        host_ports=_ports(raw),
        publish_ports=_publish_ports(raw),
        container_mode=_choice(raw, "mode", CONTAINER_MODES, "none"),
        host_api=_choice(raw, "host_api", HOST_API_LEVELS, "none"),
        services=_services(raw),
    )
