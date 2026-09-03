#!/usr/bin/env bash
# image/firewall/apply.sh
# Roda no INIT CONTAINER, com NET_ADMIN, e termina. O container do agente entra
# no pod DEPOIS e SEM NET_ADMIN — por isso ele nao consegue desfazer nada disso.
set -euo pipefail

nft add table inet asb
nft add chain inet asb out '{ type filter hook output priority 0; policy drop; }'

# respostas de conexoes que ja passaram pelo crivo
nft add rule inet asb out ct state established,related accept

# o agente alcanca o proxy pelo loopback (mesmo netns)
nft add rule inet asb out oif lo accept

# SOMENTE o uid do proxy fala com o mundo. O agente (uid 1000) nao emite
# nenhum pacote para fora — nem consulta DNS.
nft add rule inet asb out meta skuid 900 accept

echo "asb: firewall aplicado"
nft list ruleset
