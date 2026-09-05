"""cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf.

A normalizacao NAO e cosmetica. Em ACL dstdomain do Squid, ".dominio.com" ja
casa "dominio.com" e todos os subdominios; declarar os dois no mesmo ACL e
erro FATAL de configuracao ("ERROR: '.github.com' is a subdomain of
'github.com'" seguido de "FATAL: Bungled"). O squid nao sobe, e o sintoma
observado e o sandbox sem egresso.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .profile import Profile

# Necessarios apenas quando o agente roda containers dentro do sandbox: os
# pulls saem pelo proxy. Ficam fora da base para nao abrir registries em
# workspaces que nao os usam.
NESTED_REGISTRIES = (
    "registry-1.docker.io",
    "auth.docker.io",
    "production.cloudflare.docker.com",
    "production.cloudfront.docker.com",
    "quay.io",
    "cdn.quay.io",
    "ghcr.io",
)


class SquidError(Exception):
    pass


def read_base(path: Path) -> list[str]:
    domains = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(line)
    return domains


def normalize_domains(domains: Iterable[str]) -> list[str]:
    clean = {d.strip() for d in domains if d.strip()}
    result = []
    for domain in clean:
        redundant = False
        for other in clean:
            if other == domain or not other.startswith("."):
                continue
            parent = other[1:]
            # Comparar por rotulo: "notgithub.com" termina em "github.com"
            # como texto, mas nao e subdominio dele.
            if domain == parent or domain.endswith("." + parent):
                redundant = True
                break
        if not redundant:
            result.append(domain)
    return sorted(result)


def render(profile: Profile, base: Path, template: Path) -> str:
    domains = read_base(base)
    domains.extend(profile.allow)
    if profile.container_mode == "nested":
        domains.extend(NESTED_REGISTRIES)

    ordered = normalize_domains(domains)
    if not ordered:
        raise SquidError(
            "allowlist vazia: o sandbox subiria sem egresso algum e o sintoma "
            "nao apontaria para a causa")
    return Path(template).read_text().replace("__ALLOWLIST__",
                                              " ".join(ordered))
