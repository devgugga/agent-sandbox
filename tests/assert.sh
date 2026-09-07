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

assert_not_contains() {
  local needle="$1" haystack="$2" msg="$3"
  case "$haystack" in
    *"$needle"*) _fail=$((_fail+1)); echo "  FALHOU: $msg"; echo "    encontrou indevidamente [$needle] em: $haystack" ;;
    *) _pass=$((_pass+1)); echo "  ok: $msg" ;;
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


# Espera uma condicao ficar verdadeira. Substitui `sleep N` fixo, que sob carga
# e a primeira coisa a quebrar.
#   wait_for <segundos> <comando...>
wait_for() {
  local limit="$1"; shift
  local i=0
  while [ "$i" -lt "$limit" ]; do
    "$@" >/dev/null 2>&1 && return 0
    i=$((i+1)); sleep 1
  done
  return 1
}

# CONTROLE POSITIVO. Asserção negativa ("X esta bloqueado") passa de graça quando
# o container nem subiu: o comando falha e o teste conclui "bloqueado". Um falso
# verde numa asserção de seguranca e pior que uma falha. Portanto: antes de
# confiar em qualquer "bloqueado", prove que o ambiente responde — e ABORTE se
# nao responder, em vez de seguir e reportar verde.
require() {
  local msg="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  controle positivo ok: $msg"
    return 0
  fi
  echo "  ABORTADO: controle positivo falhou -> $msg"
  echo "  As assercoes de bloqueio nao sao confiaveis sem ele (falso verde)."
  exit 1
}

report() {
  echo "---"; echo "passou: $_pass  falhou: $_fail"
  [ "$_fail" -eq 0 ] || return 1
}
