#!/usr/bin/env bash
set -uo pipefail

if (($# == 0)); then
  echo "Error: at least one port must be specified" >&2
  exit 1
fi

for port in "$@"; do
  if ! [[ "$port" =~ ^[1-9][0-9]*$ ]] || ((${#port} > 5)) || ((10#$port < 1 || 10#$port > 65535)); then
    echo "Error: invalid port: $port (must be integer between 1 and 65535)" >&2
    exit 1
  fi
done

pids=()
stop_children() {
  trap '' TERM INT
  if ((${#pids[@]})); then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap 'stop_children; exit 0' TERM INT

for port in "$@"; do
  socat "TCP-LISTEN:${port},fork,reuseaddr" "TCP:host.containers.internal:${port}" &
  pids+=("$!")
done

wait -n "${pids[@]}"
result=$?
stop_children
((result != 0)) || result=1
exit "$result"
