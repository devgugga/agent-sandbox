# Integração project-scoped do Graphify no agent-sandbox

**Data:** 2026-09-06  
**Status:** Desenho aprovado nas seções do brainstorming; aguardando revisão final da especificação  
**Escopo:** Tooling de engenharia, governança de agentes, grafo de conhecimento e convenções de commit  

---

## 1. Objetivo e Contexto

O `agent-sandbox` cresceu significativamente, englobando componentes em Python (`cli/asb`, `cli/asb-guard`, `cli/asb-agent`), scripts de ciclo de vida em Bash (`recipes/`, `image/*.sh`), infraestrutura de proxy Squid (`image/squid/`), perfis TOML (`profiles/`) e testes automatizados (`tests/unit/`, `tests/*.sh`).

O objetivo desta integração é equipar o repositório com o **Graphify 0.9.51** em escopo de projeto (project-scoped), espelhando o padrão já consolidado e validado no **BlackICE**, garantindo que:
1. Antigravity, Claude Code e Codex compartilhem um grafo de conhecimento portável e persistente do repositório.
2. Arquivos operacionais e de infraestrutura (`Containerfile`, scripts shell, templates Squid e perfis TOML) sejam compreendidos e indexados semanticamente como parte da arquitetura do projeto.
3. O grafo seja mantido por tooling de engenharia versionado no Git sem se tornar dependência de runtime do sandbox ou dos contêineres de agentes.
4. O princípio de SSoT (Single Source of Truth) e a governança de commits sejam rigorosamente respeitados sem modificações manuais invasivas nos prompts de subagentes.

---

## 2. Decisões Arquiteturais

### 2.1 Baseline e Tooling Local
- **Versão:** Pinar a baseline oficial em `graphifyy==0.9.51`, gerenciada de forma isolada via `uv tool`.
- **Instalador Linux Nativo (`.graphify/setup.sh`):**
  - Script Bash (`set -euo pipefail`) idempotente com suporte a `--verify-only`.
  - Valida o binário `uv` e instala/atualiza `graphifyy==0.9.51`.
  - Registra as skills em escopo de projeto para Claude Code, Antigravity (`.agents/skills/`) e Codex.
  - Instala o hook oficial de Git (`graphify hook install`) e configura o merge driver.
- **Isolamento de Runtime:** O Graphify **não** é injetado dentro das imagens de contêiner do `agent-sandbox` (`asb-agent`, `asb-proxy`, etc.). Permanece estritamente como ferramenta de repositório e contexto no host.

### 2.2 Adaptador de Domínio (`.graphify/project.py`)
O detector nativo do Graphify identifica apenas linguagens de programação convencionais e markdown. Para o `agent-sandbox`, criamos um adaptador de projeto customizado que roteia arquivos operacionais para a pipeline semântica como documentos:
- **Formatos e Arquivos Incluídos**:
  - Scripts e automações: `.sh`, `.bash`, `cli/asb-guard`, `cli/asb-agent`.
  - Contêineres e imagens: `image/Containerfile`, `image/Containerfile.proxy`.
  - Configurações do Squid: `image/squid/squid.conf.tmpl`, `image/squid/allowlist-base.txt`.
  - Serviços e perfis: `broker/*.service.tmpl`, `profiles/*.toml`.
- **Filtros de Segurança e Exclusões Ativas**:
  - Exclusão rigorosa de segredos e credenciais: `.env*`, `.agent-sandbox.toml`, chaves SSH (`id_ed25519*`), passphrases (`*.pass`, `keyring.pass`).
  - Exclusão de diretórios de build/runtime/voláteis: `.git/`, `graphify-out/`, `state/`, `scratch/`, `dist/`, `.venv/`, `__pycache__/`, `.pytest_cache/`.
  - Limite de tamanho máximo seguro por arquivo: 1 MB (`_MAX_CONFIG_BYTES = 1_000_000`).

### 2.3 Governança de Agentes e SSoT
- **Subagentes:** **Nenhum subagente terá seu arquivo de prompt alterado diretamente.**
  - Subagentes como o `commit-curator` são propositalmente finos e delegam suas regras inteiramente para `docs/domains/git/commit-conventions.md`.
  - As diretrizes gerais e de consulta ao grafo vivem canonicamente em `AGENTS.md`.
- **Governança de Commits e Gitmoji (`docs/domains/git/commit-conventions.md`):**
  - Inclusão do Gitmoji literal `🕸️` para sincronização do grafo de conhecimento.
  - **Fluxo de dois commits:**
    1. **1º Commit (Feature/Código):** Commita as alterações de produto/infraestrutura sem incluir `graphify-out/**`, cumprindo o formato com corpo estruturado obrigatório.
    2. **2º Commit (Sincronização do Grafo):** Commita exclusivamente `graphify-out/**` com a mensagem `🕸️ sync knowledge graph`. Este commit dedicado é a única exceção permitida à exigência de corpo estruturado.
  - **Momento da Atualização:** A atualização semântica do grafo (`graphify update .` ou `--update`) é executada **uma única vez**, quando a implementação, testes e revisões estiverem estáveis, imediatamente antes de criar o commit.

### 2.4 Integração de Skills e Git
- **Sincronização de Skills (`scripts/sync-skills.mjs`):**
  - O script já declara `const VENDOR = new Set(['graphify'])`, tratando a skill como fornecedor externo e evitando remoção acidental ou falsos positivos de drift.
  - As skills residirão em:
    - `.claude/skills/graphify/` (Claude Code)
    - `.agents/skills/graphify/` (Google Antigravity)
    - `.codex/skills/graphify/` (OpenAI Codex)
- **Git Attributes (`.gitattributes`):**
  - Define o merge driver oficial: `graphify-out/graph.json merge=graphify`.
- **Git Ignore (`.gitignore`):**
  - Ignora estados locais e caches voláteis: `graphify-out/cost.json`, `graphify-out/cache/`, `*.graphify-bak`, `*.graphify.log`, `.claude/settings.json`, `.codex/hooks.json` e intermediários `graphify-out/.graphify_*.json`.
  - Preserva e versiona os artefatos portáveis: `graphify-out/graph.json`, `graphify-out/graph.html` e `graphify-out/GRAPH_REPORT.md`.

---

## 3. Arquitetura de Arquivos

```text
agent-sandbox/
├── AGENTS.md                            # Adiciona seção canônica de uso e protocolo do Graphify
├── CLAUDE.md                            # Aponta para AGENTS.md e docs/architecture/graphify.md
├── GEMINI.md                            # Aponta para AGENTS.md e docs/architecture/graphify.md
├── .gitattributes                       # graphify-out/graph.json merge=graphify
├── .gitignore                           # Ignora custos, caches locais e hooks com paths da máquina
├── .graphifyignore                      # Exclui graphify-out/, logs e .claude/skills/graphify/
├── .graphify/
│   ├── setup.sh                         # Script de instalação, verificação e integridade
│   └── project.py                       # Adaptador de detecção customizado para o agent-sandbox
├── tests/unit/
│   └── test_project.py                  # Testes automatizados pytest para o project.py
├── docs/
│   ├── architecture/
│   │   └── graphify.md                  # Documentação operacional canônica do Graphify
│   └── domains/git/
│       └── commit-conventions.md        # Adiciona 🕸️ e a regra do commit de sincronização
├── .claude/skills/graphify/             # Skill project-scoped para Claude Code
├── .agents/skills/graphify/             # Skill project-scoped para Antigravity
├── .codex/skills/graphify/              # Skill project-scoped para Codex
└── graphify-out/                        # Grafo de conhecimento versionado
    ├── graph.json                       # Grafo consultável e portável
    ├── graph.html                       # Visualização interativa
    └── GRAPH_REPORT.md                  # Relatório consolidado da arquitetura e comunidades
```

---

## 4. Estratégia de Testes e Validação

1. **Testes Unitários (`tests/unit/test_project.py`):**
   - Testar inclusão de `Containerfile`, `.sh`, `.toml`, `squid.conf.tmpl`.
   - Testar exclusão rigorosa de `.env`, `*.pass`, chaves SSH e diretórios voláteis (`graphify-out/`, `.git/`, `__pycache__/`).
   - Testar detecção incremental com novos arquivos e arquivos removidos.
2. **Validação do Sincronizador de Skills:**
   - `node scripts/sync-skills.mjs --check` deve executar com saída 0 (sem drift).
3. **Validação do Setup e Hooks:**
   - Executar `.graphify/setup.sh`.
   - `graphify hook status` deve reportar hook de commit e merge driver ativos.
4. **Validação do Grafo e Consultas:**
   - Gerar `graphify-out/` completo via extração.
   - Validar parse JSON de `graphify-out/graph.json`.
   - Executar `graphify query "how does squid proxy filter egress traffic?"` e `graphify explain "Containerfile"`.
   - `git status` deve mostrar apenas arquivos rastreáveis intencionais.

---

## 5. Limites Deliberados e Fora de Escopo

- Não será configurado servidor MCP background/daemon compartilhado.
- Graphify não será adicionado aos contêineres de runtime nem ao build de imagens do sandbox.
- Não serão ativadas exportações para Neo4j, FalkorDB ou Obsidian.
- O modo estrito do Claude (`--strict`) não será ativado inicialmente (mantendo soft-nudge não intrusivo).
