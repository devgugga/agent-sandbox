# Orca Reboot Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restaurar sandboxes Orca após reboot sem perder conectividade,
isolamento, login percebido ou configuração dos agentes.

**Architecture:** O lifecycle permanece Podman rootless e fail-closed. O host
aguarda rota antes do restore; cada pod prova rota, DNS e CONNECT pelo Squid
antes de iniciar o agente. Configurações duráveis são copiadas por manifesto
explícito, e o `agy` corrige hooks reinjetados pelo Orca no momento do launch.

**Tech Stack:** Bash, Python 3.11+, Podman 6.1, pasta/netavark, nftables, Squid,
systemd user service.

**Spec:**
`docs/superpowers/specs/2026-09-04-orca-reboot-persistence-design.md`

### Task 1: readiness de rede e proxy

**Files:** `tests/test-readiness.sh`, `cli/lib/pod.sh`, `cli/agent-sandbox`

- [x] Escrever testes unitários shell para espera com sucesso tardio, timeout,
      prova do proxy e fail-closed.
- [x] Confirmar RED.
- [x] Implementar espera de rota do host e prova de rota/DNS/CONNECT no pod.
- [x] Fazer `restore-all` aguardar rede apenas quando há pods restauráveis.
- [x] Configurar retry da unidade systemd e confirmar GREEN.

### Task 2: criação transacional e imagem autenticada obrigatória

**Files:** `tests/test-transaction.sh`, `cli/lib/pod.sh`

- [x] Testar ausência da imagem auth e rollback após falha de provisionamento.
- [x] Confirmar RED.
- [x] Transformar `asb_up` em transação com cleanup em `EXIT`.
- [x] Tornar toda cópia de provisionamento obrigatória quando planejada.
- [x] Confirmar ausência de pod/estado parcial e GREEN.

### Task 3: estado completo do Antigravity

**Files:** `tests/test-provision.sh`, `tests/test-guard.sh`,
`profiles/provision.toml`, `cli/lib/provision.py`, `cli/asb-agent`,
`image/asb-agent`

- [x] Criar fixtures para plugins, skills, MCP e hooks com path do host.
- [x] Confirmar RED.
- [x] Adicionar entradas explícitas e filtro JSON para hooks portáveis.
- [x] Normalizar hooks novamente antes do launch de `agy`.
- [x] Confirmar que denylist e configurações Claude/Codex continuam verdes.

### Task 4: autenticação verificável e diagnóstico

**Files:** `tests/test-auth.sh`, `tests/test-doctor.sh`, `cli/lib/auth.sh`,
`cli/lib/doctor.sh`, `cli/agent-sandbox`

- [x] Testar espera do Secret Service e recusa se `agy` falhar.
- [x] Testar doctor saudável e cada falha crítica com comandos simulados.
- [x] Confirmar RED, implementar o mínimo e confirmar GREEN.

### Task 5: integração Orca e documentação

**Files:** `tests/test-recipe.sh`, `recipes/shim.template.sh`,
`docs/domains/sandbox/{authentication,lifecycle,troubleshooting}.md`

- [x] Fixar em teste o contrato dos quatro hooks do consumidor.
- [x] Documentar instalação/migração, modelo de persistência e diagnóstico.
- [x] Rodar shell syntax, suite completa aplicável, diff e static recipe doctor.
- [x] Deixar o self-test `--provision` e a recriação auth para o gate humano.
