#!/usr/bin/env bash
# tests/assert.sh — helper mínimo de asserção. Fonte: source tests/assert.sh
_pass=0; _fail=0

assert_eq() {
  local expected="$1" actual="$2" msg="$3"
  if [ "$expected" = "$actual" ]; then
    _pass=$((_pass+1)); echo "  ok: $msg"
  else
    _fail=$((_fail+1)); echo "  FALHOU: $msg"; echo "    esperado: [$expected]"; echo "    obtido:   [$actual]"
  fi
}

assert_contains() {
  local needle="$1" haystack="$2" msg="$3"
  case "$haystack" in
    *"$needle"*) _pass=$((_pass+1)); echo "  ok: $msg" ;;
    *) _fail=$((_fail+1)); echo "  FALHOU: $msg"; echo "    nao encontrou [$needle] em: $haystack" ;;
  esac
}

# Sucesso = o comando FALHAR. Usado para provar que algo esta bloqueado.
assert_fails() {
  local msg="$1"; shift
  if "$@" >/dev/null 2>&1; then
    _fail=$((_fail+1)); echo "  FALHOU: $msg (comando teve sucesso, deveria falhar)"
  else
    _pass=$((_pass+1)); echo "  ok: $msg"
  fi
}

report() {
  echo "---"; echo "passou: $_pass  falhou: $_fail"
  [ "$_fail" -eq 0 ] || return 1
}
