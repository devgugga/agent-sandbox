#!/usr/bin/env bash
# image/start-keyring.sh — serviço singleton de Secret Service para agent-sandbox.
#
# Executado como processo principal (PID 1) do container `asb-keyring`.
# Gerencia dbus-daemon de sessão e gnome-keyring-daemon (componente secrets),
# expondo o socket fixo em /run/asb-keyring/bus para containers clientes.
#
# Nunca emite passphrases, tokens sensíveis ou conteúdos de segredos.
set -euo pipefail

# 1. Validar usuário de execução (uid 1000)
if [ "$(id -u)" != "1000" ]; then
  echo "start-keyring: processo deve rodar como uid 1000" >&2
  exit 1
fi

# 2. Exigir arquivo de passphrase legível
pass_file=/run/asb-keyring-pass
if [ ! -r "$pass_file" ]; then
  echo "start-keyring: $pass_file nao encontrado ou ilegivel" >&2
  exit 1
fi

# 3. Garantir persistência do diretório de keyrings no volume dedicado de dados
keyring_data_dir="/run/asb-keyring-data/keyrings"
migration_marker="/run/asb-keyring-data/.migration_done"
if [ -d /run/asb-keyring-data ]; then
  mkdir -p "$keyring_data_dir"
  chmod 0700 "$keyring_data_dir"

  # Migração transacional e retomável de dados legados do volume de credenciais.
  # Protegida por staging e marcador de conclusão: se interrompida antes do fim,
  # o próximo início retoma a sincronização de onde parou sem apagar a origem.
  if [ -d /run/asb-credentials/keyrings ] && [ ! -f "$migration_marker" ]; then
    if [ -n "$(ls -A /run/asb-credentials/keyrings 2>/dev/null)" ]; then
      staging_dir="/run/asb-keyring-data/.staging_keyrings"
      rm -rf "$staging_dir"
      mkdir -p "$staging_dir"
      chmod 0700 "$staging_dir"
      cp -a /run/asb-credentials/keyrings/. "$staging_dir/"
      cp -a "$staging_dir/." "$keyring_data_dir/"
      rm -rf "$staging_dir"
      touch "$migration_marker"
      chmod 0600 "$migration_marker" 2>/dev/null || true
      chmod 0700 "$keyring_data_dir"
    fi
  fi

  mkdir -p "$HOME/.local/share"
  if [ ! -L "$HOME/.local/share/keyrings" ] || [ "$(readlink "$HOME/.local/share/keyrings")" != "$keyring_data_dir" ]; then
    rm -rf "$HOME/.local/share/keyrings"
    ln -sfn "$keyring_data_dir" "$HOME/.local/share/keyrings"
  fi
else
  mkdir -p "$HOME/.local/share/keyrings"
  chmod 0700 "$HOME/.local/share/keyrings"
fi

# 4. Preparar runtime dir e remover socket stale
runtime_dir="/run/asb-keyring"
mkdir -p "$runtime_dir"
rm -f "$runtime_dir/bus"

# 5. Iniciar dbus-daemon no endereço fixo
dbus-daemon --config-file=/usr/share/dbus-1/session.conf \
  --address="unix:path=$runtime_dir/bus" --nofork &
dbus_pid=$!

# Aguardar criação do socket do bus
while [ ! -S "$runtime_dir/bus" ]; do
  if ! kill -0 "$dbus_pid" 2>/dev/null; then
    echo "start-keyring: dbus-daemon falhou ao iniciar" >&2
    exit 1
  fi
  sleep 0.02
done

export DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus"

# 6. Desbloquear e iniciar gnome-keyring-daemon (apenas secrets) em foreground
gnome-keyring-daemon --unlock --foreground --components=secrets \
  < "$pass_file" >/dev/null &
gkd_pid=$!

# Aguardar registro do Secret Service no bus
gkd_ready=0
for _ in $(seq 1 50); do
  if ! kill -0 "$gkd_pid" 2>/dev/null; then
    echo "start-keyring: gnome-keyring-daemon falhou ao iniciar" >&2
    exit 1
  fi
  if dbus-send --session --dest=org.freedesktop.DBus --type=method_call \
      --print-reply /org/freedesktop/DBus org.freedesktop.DBus.GetNameOwner \
      string:org.freedesktop.secrets >/dev/null 2>&1; then
    gkd_ready=1
    break
  fi
  sleep 0.05
done

if [ "$gkd_ready" -ne 1 ]; then
  echo "start-keyring: timeout aguardando org.freedesktop.secrets no bus" >&2
  kill -TERM "$gkd_pid" "$dbus_pid" 2>/dev/null || true
  exit 1
fi

# 7. Tratar sinais TERM/INT para desligamento gracioso dos processos filhos
cleanup() {
  trap - TERM INT
  kill -TERM "$gkd_pid" "$dbus_pid" 2>/dev/null || true
  wait "$gkd_pid" "$dbus_pid" 2>/dev/null || true
  exit 0
}
trap cleanup TERM INT

# 8. Permanecer em foreground e propagar falha de processos filhos
wait -n "$dbus_pid" "$gkd_pid"
child_status=$?
echo "start-keyring: processo filho encerrou inesperadamente (status $child_status)" >&2
kill -TERM "$gkd_pid" "$dbus_pid" 2>/dev/null || true
wait "$gkd_pid" "$dbus_pid" 2>/dev/null || true
[ "$child_status" -eq 0 ] && exit 1 || exit "$child_status"
