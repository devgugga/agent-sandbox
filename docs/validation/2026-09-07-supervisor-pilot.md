# Relatório de Validação: Piloto de Supervisão via systemd Type=exec

- **Data:** 2026-09-07
- **Ambiente:** Linux x86_64 (Arch Linux / Omarchy)
- **Componentes:** Podman 6.1.0 (rootless), systemd 257.3 (`systemd --user`)
- **Status da Tarefa I1:** APROVADO

---

## 1. Objetivo e Escopo

Validar empiricamente a premissa central da Etapa 0 do plano de redesenho
de inicialização e autenticação (`docs/superpowers/plans/2026-09-07-startup-supervision.md`):
a capacidade do systemd em modo usuário (`--user`) supervisionar containers
persistentes do Podman usando `Type=exec` com `podman start --attach`,
garantindo recuperação de falhas, preservação de portas, preservação de
camada gravável e ausência de processos órfãos, sem recorrer a daemons
adicionais e sem alterar código de produção.

---

## 2. Artefatos Desenvolvidos

1. **`tests/integration/sandbox_fixture.py`**:
   - Context manager `SandboxFixture(label: str)` com isolamento estrito.
   - Geração de UUID determinístico por execução (`test-<label>-<uuid>`).
   - Todos os recursos criados obrigatoriamente prefixados com `asb-test-<label>-<uuid>-*`.
   - Volumes isolados de credenciais, toolcache e keyring (`asb-test-...`).
   - Chave SSH dedicada gerada em raiz temporária (`~/.local/state/` ou `tmpfs`).
   - Validação e registro obrigatório de recursos antes do teardown: qualquer
     nome fora do prefixo ou caminho fora da raiz temporária dispara `IsolationError`.
   - Teardown com `systemctl --user stop/reset-failed`, remoção do arquivo de
     unidade, `daemon-reload`, `podman rm -f`, `podman volume rm -f`,
     `podman network rm -f` e limpeza de diretórios temporários.

2. **`tests/integration/test_supervisor_pilot.py`**:
   - Suíte de testes de integração com 6 casos empíricos reais.

---

## 3. Resultados dos Ensaios Empíricos

Todos os 6 testes foram executados via:
```bash
python3 -B -m unittest discover -s tests/integration -p 'test_supervisor_pilot.py' -v
```
Resultado: **6 testes executados, 6 aprovados (OK)** em ~58s.

### Detalhamento por Cenário:

### 3.1. Recuperação após Falha e Preservação de Identidade
- **Caso:** `test_supervision_restart_and_identity_preservation`
- **Comportamento observado:**
  1. Container criado (`docker.io/library/alpine:latest`) com mapeamento dinâmico de porta (`127.0.0.1::8080`).
  2. Unidade iniciada com `systemctl --user start <unit>`.
  3. Identidade original inspecionada: Container ID (64 caracteres hex) e Porta de host (ex: `127.0.0.1:38155`).
  4. Sentinela gravada na camada de escrita do container (`/sentinel.txt`).
  5. Container encerrado forçadamente via `podman kill` (SIGKILL).
  6. O processo anexado `podman start --attach` encerrou com status 137.
  7. O systemd detectou imediatamente a saída do processo principal e escalonou job de reinício (`RestartSec=5s`).
  8. O container foi reiniciado com sucesso pelo systemd.
  9. A identidade pós-reinício foi verificada e coincide exatamente com a original (mesmo Container ID e mesma porta de host).
  10. O arquivo sentinela `/sentinel.txt` permaneceu íntegro e legível no container.
  11. `systemctl --user stop <unit>` encerrou o serviço e o container de forma limpa.
  12. Verificação de ausência de órfãos (`assert_no_orphans`): zero processos `podman` ou `conmon` residuais.

### 3.2. Saída Limpa Inesperada (Código 0)
- **Caso:** `test_supervision_unexpected_zero_exit`
- **Comportamento observado:**
  1. Container encerrado com código 0 (via `podman stop -t 2`).
  2. A diretiva `Restart=always` instruiu o systemd a reiniciar o serviço mesmo perante saída zero.
  3. Reinício concluído com sucesso e identidade preservada.

### 3.3. Falha em `ExecStartPost` e Limpeza por `ExecStopPost`
- **Caso:** `test_supervision_exec_start_post_failure_cleans_up_via_stop_post`
- **Comportamento observado:**
  1. Configurada diretiva `ExecStartPost=/usr/bin/false`.
  2. Tentativa de inicialização falhou conforme esperado (`CalledProcessError`).
  3. Como a unidade não atingiu o estado `active`, o systemd não executou `ExecStop`.
  4. No entanto, o systemd executou `ExecStopPost=/usr/bin/podman stop --ignore --time=10 ...`.
  5. O container foi parado imediatamente e nenhum processo órfão permaneceu ativo.
  6. **Conclusão:** `ExecStopPost` é indispensável para evitar vazamento de containers quando hooks de admissão falharem.

### 3.4. Reconexão a Container em Execução
- **Casos:**
  - `test_supervision_reconnect_to_running_container_with_launcher`
  - `test_supervision_literal_reconnect_bounces_via_stop_post_and_restarts`
- **Descoberta Empírica Crítica:**
  - No Podman 6.1.0 rootless, invocar literalmente `podman start --attach` sobre um container que *já está em execução* resulta em erro imediato do runc (`exit status 125: cannot start an already running container`).
  - Na unidade literal pura: a saída 125 dispara `ExecStopPost`, que para o container; em seguida, o `Restart=always` aguarda 5s e reinicia com `podman start --attach`, o que agora tem sucesso porque o container foi parado. Isso causa um ciclo indesejado de parada/reinício (bounce de 5s).
  - Com o launcher helper (que inspeciona o estado do container e executa `podman attach` se já estiver `running`, ou `podman start --attach` caso contrário): a reconexão ocorre instantaneamente sem interrupção do container, mantendo o serviço ativo de forma transparente.
  - **Recomendação para Tarefa I3:** O supervisor em `supervisor.py` e o helper de runtime devem usar essa lógica de despacho para garantir adoção limpa de workspaces sem reiniciar containers em execução.

### 3.5. Proteção de Isolamento
- **Caso:** `test_isolation_guards_refuse_foreign_names_and_paths`
- **Comportamento observado:**
  - Tentativas de registrar recursos com nomes de produção (`asb-keyring`, `asb-toolcache`, etc.) ou sem o prefixo exato da fixture foram barradas com `IsolationError`.
  - Tentativas de validar caminhos fora do diretório temporário foram recusadas com `IsolationError`.

---

## 4. Avaliação dos Critérios de Parada / Reprovação da Tarefa I1

| Critério do Brief | Resultado Observado | Status |
| :--- | :--- | :--- |
| Detecção de saída | Detectou tanto SIGKILL quanto exit 0 | APROVADO |
| Ausência de loops infinitos | `StartLimitBurst=3` e `StartLimitIntervalSec=600s` contêm repetições | APROVADO |
| Preservação de dados e identidade | Container ID, porta e sentinela na camada gravável intactos | APROVADO |
| Independência de daemons extras | Operou exclusivamente com `systemd --user` nativo | APROVADO |
| Ausência de órfãos | Nenhum container ou processo conmon/podman órfão após stop | APROVADO |
| Não regressão em testes unitários | 191/191 testes unitários aprovados | APROVADO |

---

## 5. Conclusão e Próximos Passos

A premissa da supervisão via systemd `Type=exec` sobre Podman rootless está **empiricamente comprovada**.
A transição para a Tarefa I2 (diagnósticos tipados e sondas de prontidão) e Tarefa I3 (instalação versionada com launcher helper) está liberada conforme o plano arquitetural.
