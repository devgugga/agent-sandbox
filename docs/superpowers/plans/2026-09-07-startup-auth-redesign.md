# Inicialização e autenticação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar inicialização e autenticação confiáveis, comprovadas no uso
real antes de migrar os workspaces de trabalho.

**Architecture:** systemd supervisiona containers persistentes; o CLI cria e
remove recursos e só publica conexão após sondas explícitas. Autenticação tem
contratos e diagnóstico por fornecedor, com persistência validada nas CLIs
reais antes de alterar seu armazenamento.

**Tech Stack:** Python >= 3.11/stdlib, Podman >= 6.1 rootless, systemd de usuário
com Type=exec, Bash, Squid, OpenSSH, Secret Service existente.

**Spec:** [Desenho proposto](../specs/2026-09-07-startup-auth-redesign-design.md).

As falhas de login a corrigir incluem Claude Code e Antigravity, conforme
relato do operador. O diagnóstico técnico já constatou Claude deslogado;
Antigravity ainda precisa de reprodução. Codex permanece na validação de
regressão, sem presumir que as três CLIs falham pela mesma causa.

## Global Constraints

- Proposta para revisão; nenhuma tarefa de implementação foi executada.
- Python >= 3.11; biblioteca padrão no CLI; Podman >= 6.1; systemd de usuário
  com `Type=exec`; plataforma inicialmente validada: Arch/Omarchy desta máquina.
- Início automático após login do usuário; `Linger=no` permanece.
- Login uma vez por fornecedor, compartilhado entre workspaces, com execução
  simultânea. Não trocar esse requisito silenciosamente por login por workspace.
- Preservar containers, dados, portas SSH, isolamento, contas e integração Orca.
- Não mudar o backend de VM, a linguagem ou o escopo da allowlist.
- Não reiniciar todos os containers, matar pasta ou usar volumes reais em testes.
- Apenas systemd reinicia recursos adotados: política Podman desses containers
  passa a `no`. Não desabilitar `podman-restart.service` globalmente.
- Helpers instalados fora do checkout; logs não contêm credenciais.
- Ler AGENTS.md e o domain pack sandbox. Na execução, usar branch de trabalho,
  respeitar a gestão de worktrees do ambiente e preservar alterações alheias.
- Commits por commit-curator, conforme `docs/domains/git/commit-conventions.md`.
  Não commitar em main/master nem fazer push sem autorização. Graphify update
  somente quando implementação, testes e revisão estiverem estáveis; grafo em
  commit separado. Esta entrega de planejamento não instala nem commita nada.

## Ordem e pontos de decisão

| Etapa | Documento/tarefas | Saída exigida |
|---|---|---|
| 0 | I1 e parte sintética/documental de A1 | Supervisão provada em fixtures; hipóteses de autenticação delimitadas |
| Gate 0 | Revisão desses resultados | Decisão de seguir com o desenho ou revisar somente a parte reprovada |
| 1 | I2–I5 e A2 | Inicialização sintética e diagnóstico de conta/rede separados |
| Gate de autenticação | Parte real de A1, com rede do piloto funcional | Falhas de Claude e Antigravity investigadas separadamente; causa e persistência observadas antes de A3 |
| 2 | A3–A4 | Login seletivo e verificação real, armazenamento aprovado por A1 |
| 3 | T1 abaixo | Ciclo integrado em piloto isolado e contrato Orca preservado |
| 4 | I6 e T2 abaixo | Adoção de um workspace, ensaio de rollback e boots reais |
| 5 | T3 abaixo | Evidência de uso diário e atualização dos contratos operacionais |

Frentes detalhadas:

- [Plano de inicialização, I1–I6](2026-09-07-startup-supervision.md).
- [Plano de autenticação, A1–A4](2026-09-07-agent-authentication.md).

As frentes têm saídas próprias, mas ambas modificam `lifecycle.py` e o parser.
Executar essas alterações sequencialmente. Não despachar implementadores
concorrentes sobre os mesmos arquivos. Nenhum resultado futuro é presumido
aprovado por estar descrito neste plano.

A prova real de A1 não roda sobre a rede quebrada: avança depois da etapa 1,
ou antes somente se o piloto tiver conectividade comprovada. Observação de
renovação pode continuar até T2; sua pendência impede aceitação final, mas não
impede desenvolver diagnóstico ou supervisão que independem dessa observação.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `cli/asb/readiness.py` (novo) | Sondas tipadas, prazos e categorias de erro |
| `cli/asb/supervisor.py` (novo) | Manifestos, unidades e transações de adoção |
| `cli/asb/runtime_check.py` (novo) | Entry point instalado para sondas do systemd |
| `cli/asb/keyring.py` (novo) | Código existente de infraestrutura do keyring, extraído |
| `cli/asb/auth.py` (novo) | Login seletivo, status e verificação por fornecedor |
| `cli/asb/lifecycle.py`, `cli/asb-agent` | Integração, criação/teardown e parsing |
| `cli/asb/install.py`, `cli/asb/doctor.py` | Instalação versionada e diagnóstico |
| `image/forwarder.sh` (novo), `image/entrypoint.sh`, `image/Containerfile*` | Supervisão de listeners e contrato validado de credenciais/build |
| `tests/integration/` (novo) | Fixtures isoladas e gates de execução real |
| `docs/domains/sandbox/lifecycle.md`, `authentication.md` (novos) | Contratos operacionais finais, sem duplicar regras em wrappers |

## T1 — Integrar as frentes e provar o fluxo Orca

**Files:** criar `tests/integration/test_startup_auth.py`; modificar
`tests/test-recipe.sh`, `recipes/common.sh`, `recipes/resume.sh` somente onde
comentários/contratos mudarem; não editar projetos consumidores.

**Interfaces:** consome I5 (`up/resume` com readiness), A4 (`auth verify`) e
fixture `SandboxFixture` definida em I1. Produz relatório de piloto sintético.

- [ ] Escrever primeiro um teste de conexão sem falso sucesso. Exemplo dentro
  de `unittest.TestCase`, com fixture ativa:

```python
with SandboxFixture("integrated") as sandbox:
    sandbox.start()
    sandbox.break_proxy()
    result = sandbox.cli("resume", "--workspace", sandbox.workspace)
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(result.stdout.strip(), "")
    self.assertTrue(sandbox.worktree_exists())
```

- [ ] Rodar `python3 -B -m unittest discover -s tests/integration -p 'test_startup_auth.py' -v`
  no ambiente de teste preparado por I1. Confirmar a falha esperada antes da
  integração, não apenas falha por ausência do Podman.
- [ ] Integrar chamadas usando listas de argumentos, mantendo stdout somente
  para JSON. O adaptador do recipe continua consumindo `.port` e `.project_root`;
  o JSON externo continua schemaVersion 1, SSH em 127.0.0.1 e identitiesOnly.
- [ ] Acrescentar casos de conta ausente com infraestrutura pronta, proxy 403,
  proxy 503, keyring parado, lock de login ocupado e workspace já existente.
  Conta ausente aparece em auth status e não impede SSH; falha de infraestrutura
  impede emitir conexão. Os dados de projeto permanecem nos casos de falha.
- [ ] Executar testes unitários e a integração isolada; revisar diff e registrar
  resultados reais. Curar o commit da integração em branch, sem push.

## T2 — Piloto real, reboot e retorno

**Files:** criar `docs/validation/startup-auth-pilot.md` na execução e
`tests/integration/collect_boot_evidence.py`; usar I6 para adoção/rollback.

**Interfaces:** consome `doctor --json`, `auth status/verify --json`, manifesto
runtime schema 1 e comandos de adoção de I6. Produz evidência por boot ID via
`collect_boot_evidence.collect(workspace: str) -> dict`.

- [ ] Implementar coletor somente leitura, com allowlist de campos: boot ID,
  timestamp, versões, IDs dos containers, porta, estado systemd, etapas de rede,
  resultado agregado de autenticação. Nunca coletar env/inspect completo.
  Teste inicial da forma mínima do relatório:

```python
report = collect_boot_evidence.collect(workspace="test-pilot")
self.assertEqual(report["schema"], 1)
self.assertIn("boot_id", report)
self.assertNotIn("environment", report)
self.assertNotIn("credentials", report)
```

- [ ] Antes de cada ação disruptiva, identificar o workspace e a janela com o
  operador. Reboot, interrupção da rede do desktop e login humano não fazem
  parte da suíte automática. Não considerar espera sem resposta uma autorização.
- [ ] Executar um login por fornecedor no piloto real, verificar em cliente
  novo, depois em dois workspaces. Usar o orçamento explícito de A4. Se a
  renovação real não ocorrer na janela, registrá-la pendente; não encerrar o gate.
- [ ] Com I6 validado, adotar um workspace preservando ID, porta, alterações não
  commitadas e serviços. Ensaiar rollback; revalidar esses mesmos invariantes.
- [ ] Registrar três boots distintos: normal; rede atrasada 60 s; um workspace
  ativo e outro suspenso. Após login, verificar automaticamente prontidão e
  manualmente a reconexão do Orca, sem `resume` corretivo no cenário de autostart.
- [ ] Antes desses boots, aplicar a condição de coexistência da spec §7:
  registrar e suspender somente recursos legados ASB na janela acordada. Não
  confundir um piloto isolado aprovado com suporte a produtores externos que
  inicializem o mesmo namespace antes da rede. Restaurar estados ao fim.
- [ ] Exercitar perda temporária de rede com janela autorizada. Nenhum login
  deve ser apagado. Se houver recuperação somente por reset global, reprovar
  o gate e voltar à decisão de arquitetura, sem migrar os demais workspaces.

## T3 — Aceitar operação e atualizar documentação

**Files:** modificar `docs/domains/sandbox/README.md`, `failure-modes.md`,
`security.md`; criar `lifecycle.md` e `authentication.md` nesse domain pack;
anotar supersessão nos três designs antigos citados pela spec.

**Interfaces:** consome relatório T2 aprovado e dois dias de uso sem reparo;
produz runbook coerente com a implementação e decisão de promover o runtime.

- [ ] Conferir todos os oito critérios da spec §8 contra evidência com data.
  Falta de teste real, renovação pendente ou reboot simulado mantém o item aberto.
- [ ] Consolidar comandos de recuperação por categoria: rede, proxy, serviço,
  SSH, keyring, login ausente, conta expirada e erro do fornecedor. Remover a
  orientação universal de fazer login para reparar infraestrutura.
- [ ] Atualizar a documentação de armazenamento usando os resultados A1/A3;
  preservar explicitamente o que é cifrado, compartilhado e legível ao agente.
- [ ] Executar unitários, integrações isoladas aplicáveis, sintaxe dos scripts
  alterados e `git diff --check`. Registrar testes e cenários reais separadamente.
- [ ] Fazer revisão de código somente leitura com foco em falso sucesso,
  ownership systemd/Podman, tokens e perda de dados; resolver achados antes de
  promover. Seguir revisão/commit-curator e atualização única do Graphify.
- [ ] Migrar outros workspaces somente depois desse gate e do inventário por
  workspace. A migração não é consequência automática de instalar o novo CLI.

## Investimento e critério de interrupção

O primeiro investimento termina no Gate 0: validar supervisão e delimitar as
hipóteses de persistência. Não há estimativa responsável de uma correção de
autenticação antes dessa evidência. O trabalho restante é uma sequência
revisável, não uma autorização aberta para insistir indefinidamente.

Se I1 exigir novo daemon, se A1 exigir servidor de tokens próprio, ou se T2
exigir resets globais frequentes, parar expansão e apresentar o resultado.
Reavaliar Quadlet com persistência explícita ou VM exige novo desenho, mantendo
os dados e o ambiente atual disponíveis para retorno.
