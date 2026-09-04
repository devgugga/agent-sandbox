#!/usr/bin/env bash
# tests/test-resume.sh — o sandbox precisa VOLTAR ISOLADO depois de parar.
# Motivador: apos um reboot, `podman pod start` subia o agente com o netns
# recriado (regras nft perdidas) e o squid morto (config em /tmp, tmpfs).
# Resultado medido: curl direto para a internet respondendo 200 dentro do
# sandbox. Este teste existe para que isso nao volte a passar despercebido.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

WS=resume-test
POD="asb-$WS"
REPO=$(mktemp -d)
trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

key=~/.config/agent-sandbox/id_ed25519
ssh_agent() { ssh -o ConnectTimeout=5 -i "$key" -p "$1" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$2" 2>/dev/null; }
ssh_probe() { ssh -q -o ConnectTimeout=3 -i "$key" -p "$1" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null agent@127.0.0.1 true; }

echo "== resume: volta isolado depois do suspend =="
out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port)
wait_for 40 ssh_probe "$port"
require "SSH responde antes do suspend" ssh_probe "$port"

# Simula um workspace antigo, criado antes da correcao do guarda/config. O
# resume precisa sincronizar o estado versionado sem recriar a imagem auth.
podman exec --user 0 "asb-$WS-agent" sh -c \
  'printf "wrapper antigo\n" > /usr/local/bin/asb-agent; chmod 0755 /usr/local/bin/asb-agent'
podman exec --user agent "asb-$WS-agent" sh -c '
  mkdir -p /home/agent/workspace/config-trap
  printf "preservar\n" > /home/agent/workspace/config-trap/sentinel
  rm -rf /home/agent/.gemini/config
  ln -s /home/agent/workspace/config-trap /home/agent/.gemini/config
'

./cli/agent-sandbox suspend --workspace "$WS" >/dev/null 2>&1
assert_eq "" "$(podman ps --filter "name=asb-$WS-agent" --filter status=running -q)" \
  "suspend para o container do agente"

# A config do squid vivia em /tmp (tmpfs): depois de um reboot ela sumia e o
# `podman pod start` falhava so nela, subindo o agente sem proxy nem firewall.
assert_eq "ok" "$(test -f ~/.config/agent-sandbox/pods/asb-$WS/squid.conf && echo ok)" \
  "config do squid persiste fora de /tmp"

rout=$(./cli/agent-sandbox resume --workspace "$WS" 2>/dev/null)
rport=$(echo "$rout" | jq -r .port)
assert_eq "$port" "$rport" "resume preserva a porta SSH (o Orca guarda a antiga)"

wait_for 40 ssh_probe "$rport"
require "SSH responde depois do resume" ssh_probe "$rport"
assert_eq "$(sha256sum image/asb-agent | cut -c1-16)" \
          "$(ssh_agent "$rport" 'sha256sum /usr/local/bin/asb-agent | cut -c1-16')" \
  "resume sincroniza o guarda/config sem perder a imagem autenticada"
assert_eq "arquivo" "$(ssh_agent "$rport" 'test -f ~/workspace/config-trap/sentinel && test ! -e ~/workspace/config-trap/plugins && echo arquivo')" \
  "provisionamento nao segue symlink controlado ate o repo do host"
assert_eq "diretorio" "$(ssh_agent "$rport" 'test -d ~/.gemini/config && test ! -L ~/.gemini/config && echo diretorio')" \
  "resume substitui parent symlink por diretorio seguro"

# ESTA e a asserção que faltava. Sem controle positivo acima, ela passaria de
# graca com o container morto.
assert_fails "sem egresso direto depois do resume" \
  ssh -o ConnectTimeout=5 -i "$key" -p "$rport" -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null agent@127.0.0.1 \
    'curl -s -m 6 https://1.1.1.1'
assert_eq "" "$(ssh_agent "$rport" 'getent hosts example.com')" \
  "sem DNS depois do resume"
assert_contains "table inet asb" \
  "$(podman run --rm --pod "asb-$WS" --user 1000 --cap-add NET_ADMIN agent-sandbox-net nft list ruleset 2>/dev/null)" \
  "regras nft reaplicadas no netns recriado"
# Qualquer resposta HTTP prova que o proxy encaminhou; 404 e a resposta normal
# da raiz da api.anthropic.com. "000" seria o curl nao conseguindo conectar.
code=$(ssh_agent "$rport" 'curl -s -o /dev/null -w %{http_code} -m 15 https://api.anthropic.com')
case "$code" in ''|000) reached="" ;; *) reached="respondeu" ;; esac
assert_eq "respondeu" "$reached" "egresso permitido volta pelo proxy (HTTP $code)"

echo "== resume idempotente revalida pod que ainda aparece running =="
podman run --rm --pod "$POD" --user 1000 --cap-add NET_ADMIN \
  agent-sandbox-net ip route del default >/dev/null
running_out=$(./cli/agent-sandbox resume --workspace "$WS" 2>/dev/null)
assert_eq "$rport" "$(printf '%s' "$running_out" | jq -r .port)" \
  "resume recupera pod running cuja rede quebrou"
wait_for 40 ssh_probe "$rport"
require "SSH responde depois da recuperacao do fast path" ssh_probe "$rport"
code=$(ssh_agent "$rport" 'curl -s -o /dev/null -w %{http_code} -m 15 https://api.anthropic.com')
case "$code" in ''|000) reached="" ;; *) reached="respondeu" ;; esac
assert_eq "respondeu" "$reached" \
  "fast path so retorna depois de restaurar proxy (HTTP $code)"

echo "== resume e fail-closed: proxy vivo sem rota nao e saudavel =="
./cli/agent-sandbox suspend --workspace "$WS" >/dev/null 2>&1
infra=$(podman pod inspect "$POD" --format '{{.InfraContainerID}}')
podman start "$infra" >/dev/null
podman run --rm --pod "$POD" --user 1000 --cap-add NET_ADMIN \
  agent-sandbox-net ip route del default >/dev/null
assert_fails "resume falha quando o namespace nasce sem rota" \
  ./cli/agent-sandbox resume --workspace "$WS"
assert_eq "" "$(podman ps --filter "name=${POD}-agent" --filter status=running -q)" \
  "agente NAO fica no ar quando Squid nao alcanca a internet"

# O fail-closed acima para o pod. Um novo start da infra recria o namespace a
# partir da rede normal do host, permitindo que os cenarios seguintes rodem.
./cli/agent-sandbox resume --workspace "$WS" >/dev/null

echo "== resume e fail-closed: firewall que falha nao deixa agente no ar =="
./cli/agent-sandbox suspend --workspace "$WS" >/dev/null 2>&1
# Sabotagem cirurgica: um `podman` no PATH que reprova SO a chamada do firewall.
# Nada global e alterado.
sabo=$(mktemp -d)
cat > "$sabo/podman" <<'SABO'
#!/usr/bin/env bash
for a in "$@"; do [ "$a" = "/usr/local/bin/apply.sh" ] && exit 1; done
exec /usr/bin/podman "$@"
SABO
chmod +x "$sabo/podman"
PATH="$sabo:$PATH" ./cli/agent-sandbox resume --workspace "$WS" >/dev/null 2>&1
assert_eq "1" "$?" "resume falha quando o firewall nao sobe"
assert_eq "" "$(podman ps --filter "name=asb-$WS-agent" --filter status=running -q)" \
  "agente NAO fica no ar quando o firewall falha"
rm -rf "$sabo"

echo "== o caminho ingenuo (podman pod start) nao pode servir um sandbox falso =="
# Foi exatamente isto que aconteceu depois do reboot: `podman pod start` recria o
# netns (regras nft perdidas) e sobe o agente assim mesmo. O entrypoint precisa
# recusar. Exit 1 distingue "recusou" de "nem chegou a subir".
./cli/agent-sandbox suspend --workspace "$WS" >/dev/null 2>&1
podman pod start "asb-$WS" >/dev/null 2>&1 || true
agent_exited() { [ "$(podman inspect "asb-$WS-agent" --format '{{.State.Status}}' 2>/dev/null)" = exited ]; }
wait_for 30 agent_exited
assert_eq "exited" "$(podman inspect "asb-$WS-agent" --format '{{.State.Status}}' 2>/dev/null)" \
  "agente nao permanece no ar apos podman pod start cru"
assert_eq "1" "$(podman inspect "asb-$WS-agent" --format '{{.State.ExitCode}}' 2>/dev/null)" \
  "agente RECUSOU subir (exit 1) por detectar egresso direto"
assert_contains "EGRESSO DIRETO DETECTADO" "$(podman logs "asb-$WS-agent" 2>&1 | tail -5)" \
  "motivo da recusa registrado no log"
podman pod stop "asb-$WS" >/dev/null 2>&1

echo "== restore-all: o que a unidade do systemd chama no boot =="
./cli/agent-sandbox restore-all >/dev/null 2>&1
assert_eq "1" "$(podman ps --filter "name=asb-$WS-agent" --filter status=running -q | wc -l)" \
  "restore-all sobe o agente de volta"

echo "== proxy que nao sobe tambem e fail-closed =="
# Com firewall aplicado e sem squid o agente sobe sem egresso nenhum, e o
# sintoma vira "internet quebrada" em vez de erro de ciclo de vida.
./cli/agent-sandbox suspend --workspace "$WS" >/dev/null 2>&1
podman rm -f "asb-$WS-squid" >/dev/null 2>&1
./cli/agent-sandbox resume --workspace "$WS" >/dev/null 2>&1
assert_eq "1" "$?" "resume falha quando o proxy nao sobe"
assert_eq "" "$(podman ps --filter "name=asb-$WS-agent" --filter status=running -q)" \
  "agente NAO fica no ar sem proxy"

echo "== pod anterior ao estado persistido nao reprova o boot =="
# restore-all e o ExecStart da unidade do systemd. Um pod legado que nao da
# para restaurar nao pode marcar a unidade como failed — isso esconderia falhas
# de verdade em todos os outros pods.
rm -rf ~/.config/agent-sandbox/pods/asb-$WS
out=$(./cli/agent-sandbox restore-all 2>&1); code=$?
assert_eq "0" "$code" "restore-all sai com 0 apesar de um pod sem estado"
assert_contains "ignorado" "$out" "pod legado e reportado como ignorado, nao como falha"

echo "== down limpa o estado persistido =="
./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1
assert_fails "estado por pod removido no down" test -d ~/.config/agent-sandbox/pods/asb-$WS

report
