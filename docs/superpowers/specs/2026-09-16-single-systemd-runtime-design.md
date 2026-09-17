# Emenda A — runtime único systemd e espera única por rede

Data: 2026-09-16. Status: desenho aprovado pelo operador em sessão, seção por
seção; aguarda revisão da versão escrita. Implementação não iniciada.

Emenda a: [Redesenho de inicialização e autenticação](2026-09-07-startup-auth-redesign-design.md).
Onde esta emenda e a spec original divergirem, vale esta emenda.

---

## 1. Motivo

A spec original tratou o ambiente diário como produção a migrar: manteve o
caminho antigo (`legacy`, restauração por `podman-restart.service` e
`--restart unless-stopped`) ao lado do novo (systemd de usuário), com adoção
sem recriar containers e rollback. O piloto real de T2
([`startup-auth-pilot.md`](../../validation/startup-auth-pilot.md)) mostrou
que essa coexistência é a causa das falhas de boot, e que ela não protegia
nada:

- **Não havia o que migrar.** No início do piloto, `asb-agent list` devolvia
  "nenhum workspace". Os diretórios `orca-*` em `~/asb-agent/` são clones sem
  containers e sem estado.
- **O `up` legacy reinstala o drop-in**
  `podman-restart.service.d/agent-sandbox.conf`, cujo
  `ExecStartPre=podman unshare --rootless-netns true` cria o namespace rootless
  em todo boot, 1 s após o `network-online.target` (boots 1 e 3).
- **Containers legacy criam o namespace cedo e o mantêm aberto.** Nos boots 1
  e 3 o workspace adotado herdou um namespace sem egresso e atingiu
  `start-limit-hit`; no boot 2, sem drop-in e sem produtor legacy, recuperou no
  primeiro reinício.
- **O caminho legacy falha em silêncio.** No boot 3 o workspace legacy do Orca
  tinha SSH saudável e egresso morto (`CONNECT tunnel failed, response 503`).
  O caminho legacy não tem sonda de prontidão.
- **O Orca cria workspaces legacy** (`recipes/create.sh` chama `up` sem
  `--runtime`), então o runtime systemd nunca era exercitado no uso real.

O projeto está em desenvolvimento ativo. O operador decidiu eliminar o runtime
legacy.

## 2. Decisões do operador

| Decisão | Escolha | Alternativas rejeitadas |
| :--- | :--- | :--- |
| Passagem para o runtime único | **Recriar** (`down` + `up`), sem adoção nem rollback | manter só a adoção; manter adoção e rollback |
| Rede que nunca chega | **Esperar sem limite** | esperar até um limite e falhar, exigindo `resume` |
| Mecanismo de espera | **Unidade dedicada** `asb-network.service` | `ExecStartPre` por unidade; recuperação por reinício global |

A recuperação por reinício global foi descartada porque equivale ao reset de
namespace que a §8.4 da spec original proíbe promover, e porque dependeria da
hipótese não comprovada do namespace preso.

## 3. Arquitetura

**Runtime único: systemd de usuário.** Deixa de existir escolha de runtime.
Todo container ASB é criado com `--restart=no`, e quem o inicia, reinicia e
para é sempre o systemd de usuário.

| Unidade | Papel | Depende de |
| :--- | :--- | :--- |
| `asb-network.service` | espera única por conectividade real do host | nada |
| `asb-keyring.service` | Secret Service compartilhado, singleton | nada — o container roda com `--network none` |
| `asb-<ws>-*.service` e `asb-<ws>.target` | um workspace: `proxy`, `agent` e, quando existirem, `fwd`, `docker` e containers de serviço | **todas** com `Requires=` e `After=asb-network.service`; o agente também `Wants=` e `After=asb-keyring.service`, como já é gerado hoje |

**`podman-restart.service` sai do caminho do ASB.** Ele continua habilitado —
a spec original proíbe desativá-lo globalmente, e containers alheios podem
usá-lo —, mas nenhum container ASB depende dele: com `--restart=no`, o filtro
`should-start-on-boot=true` não os seleciona. O drop-in do projeto deixa de
existir.

**Ordem de boot.** A sessão do usuário inicia; `asb-keyring` e `asb-network`
partem em paralelo; nenhum workspace parte antes de `asb-network` concluir.
Logo nenhum produtor ASB cria o namespace rootless antes de haver conexão
real. Por isso a dependência de `asb-network` vale para **toda** unidade de
container de workspace, não só para o proxy: qualquer container em rede
bridge que partisse antes da espera criaria o namespace cedo.

## 4. A espera por rede

**Implementação.** Um script `network_gate.py`, instalado pelo mesmo
`install_runtime()` que instala `launcher.sh` e `runtime_check.py` em
`~/.local/lib/agent-sandbox/runtime/<revisão>/`, chama
`readiness.probe_host()` a cada 5 s até obter TCP e TLS até `github.com:443`,
e então sai com código 0.

**Unidade.**

```ini
[Unit]
Description=Agent Sandbox: espera por conectividade real

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=infinity
Restart=on-failure
ExecStart=<runtime>/network_gate.py
```

- `TimeoutStartSec=infinity` implementa "esperar sem limite".
- `RemainAfterExit=yes` mantém a espera `active (exited)`: workspaces
  iniciados depois não esperam de novo.
- `Restart=on-failure` cobre apenas falha do próprio script. Ausência de rede
  não é falha; é continuar esperando.

**Todo resultado diferente de `healthy` significa continuar esperando**,
inclusive `tls_failed` e `connection_refused`: um portal cativo aceita TCP e
falha no TLS, e ali não há internet real.

**A espera nunca** chama Podman, **nunca cria o namespace rootless** e nunca
executa `unshare`. É uma sonda do host. Criar o namespace a partir dela
reproduziria o defeito do drop-in.

**Registro.** O journal recebe apenas mudanças de estado e um resumo por
minuto enquanto espera, para que horas offline não gerem uma linha a cada 5 s.

**Visibilidade.** `systemctl --user status asb-network` mostra se espera e
desde quando; `systemctl --user list-jobs` mostra os workspaces aguardando; o
`doctor` informa o estado da espera.

**Chamadas manuais.** `up` e `resume` iniciam o target pelo systemd e passam
pela mesma espera; com rede disponível ela conclui imediatamente.

**Correção associada.** `probe_host()` recomenda
`podman unshare --rootless-netns true` quando não há rota. O piloto mostrou
que isso não recupera um namespace quebrado, e o próprio `unshare` no boot era
o produtor do defeito. A recomendação é substituída.

## 5. Keyring e troca

**Keyring sob systemd como caminho normal.** `ensure_keyring_service()` deixa
de criar o container com `--restart unless-stopped`. Passa a criá-lo com
`--restart=no` e a instalar `asb-keyring.service` a partir de
`_render_keyring_unit`, que sai do código de adoção e vai para o núcleo do
supervisor.

A unidade do keyring ganha sonda de prontidão —
`ExecStartPost=<runtime>/runtime_check.py --role keyring`, sobre o
`readiness.probe_keyring()` existente. Sem ela, `After=asb-keyring.service`
no agente esperaria apenas o início do processo, não o D-Bus pronto; hoje essa
espera é feita em Python dentro de `ensure_keyring_service()`. O keyring não
depende de `asb-network`.

**Credenciais preservadas.** Os volumes `asb-credentials`, `asb-keyring-data`
e `asb-keyring-runtime`, e a passphrase `~/.config/agent-sandbox/keyring.pass`,
não são tocados. Recriar o container do keyring não apaga login.

**Troca, uma vez, nesta ordem:**

1. **Remover o drop-in do projeto** com a verificação existente
   (`read_project_dropin` / `_is_project_dropin`): remove só se o conteúdo for
   exatamente o do projeto; drop-ins de terceiros ficam intactos. Depois,
   `systemctl --user daemon-reload`.
2. **Recriar o keyring** sob systemd, antes dos workspaces, porque o agente
   depende dele.
3. **Recriar cada workspace** com `down` e `up`. O trabalho vive no clone, e o
   `up` nunca clona de novo (`prepare_clone` é idempotente). O ID do container
   e a porta SSH mudam uma vez.

**Limpeza idempotente.** O `up` remove o drop-in do projeto sempre que o
encontrar, pela mesma verificação. Isso impede que ele volte por um caminho
esquecido, como voltou pelo `up` legacy do Orca.

**Orca.** A receita não passa `--runtime`; workspaces criados pelo Orca passam
a nascer sob systemd sem alteração na receita. A validação pelo Orca continua
bloqueada pelo defeito do Orca na reidratação do terminal após reboot.

**Diretórios `orca-*` antigos.** Não têm containers nem estado; nada migra.
São recriados quando usados.

## 6. O que sai e o que muda

A lista é por interface e arquivo. A confirmação de cada remoção é feita no
plano, lendo os chamadores; nada é removido por suposição.

**CLI**

- a opção `up --runtime`;
- os comandos `adopt-runtime` e `rollback-runtime`.

**Código**

| Arquivo | Sai | Fica ou muda |
| :--- | :--- | :--- |
| `cli/asb/lifecycle.py` | ramo legacy de `up`, incluindo a chamada a `install.podman_restart()`, e a escolha de `--restart unless-stopped` | todo container com `--restart=no`; limpeza idempotente do drop-in |
| `cli/asb/supervisor.py` | bloco de adoção e rollback (aproximadamente da linha 648 ao fim): diário, paridade de ID, baselines, fases, `adopt_workspace`, `rollback_workspace`, `adopt_keyring`, `rollback_keyring` | `_render_keyring_unit` vai para o núcleo; unidades de workspace ganham a dependência de `asb-network` |
| `cli/asb/install.py` | `podman_restart()`, que instala o drop-in | funções que reconhecem o drop-in (`read_project_dropin`, `_is_project_dropin`), usadas na limpeza; `install_runtime()` passa a instalar `network_gate.py` |
| `cli/asb/keyring.py` | `--restart unless-stopped` | inicia pelo systemd |
| `cli/asb/doctor.py` | checagem de `podman-restart.service` | checagem de `asb-network` e das unidades |
| `cli/asb/readiness.py` | recomendação `podman unshare --rootless-netns true` | orientação coerente com o piloto |
| `cli/asb-agent` | parser de `--runtime`, `adopt-runtime`, `rollback-runtime` | — |

**Decisões tomadas no desenho:**

- `_netns_producers` permanece, como diagnóstico do `doctor` que aponta
  produtores do namespace rootless **que não são unidades ASB**. Foi ele que
  sinalizou o drop-in no piloto, e drop-ins e containers de terceiros ainda
  podem inicializar o namespace cedo.
- O manifesto `runtime.json` permanece no schema 1, com `runtime_type` sempre
  `"systemd"`. Remover o campo exigiria mudar o schema consumido por
  `runtime_check.py` e pelo coletor de evidência; isso fica fora desta emenda.

**Testes** (candidatos; confirmação no plano)

- saem: `tests/integration/test_adoption.py`,
  `tests/unit/test_id_swap_protection.py`, `tests/unit/test_journal_schema.py`,
  e as partes de rollback de `tests/unit/test_systemd_status_and_rollback.py`
  e de `tests/test-transaction.sh`;
- mudam: `tests/integration/test_workspace_supervision.py` (deixa de passar
  `--runtime`), `tests/unit/test_install.py` (instalação do drop-in vira
  remoção), `tests/unit/test_doctor.py`.

**Spec original**

| Seção | Mudança |
| :--- | :--- |
| Restrições globais | "preservar containers, dados, portas SSH" passa a "preservar **dados e credenciais**"; ID de container e porta SSH podem mudar **uma vez**, na troca |
| "Apenas systemd reinicia recursos adotados" | vale para todo recurso ASB, não só adotados |
| §7 Migração e retorno | substituída pela §5 desta emenda |
| §8 critério 7 (rollback ensaiado) | **removido** |
| §8 critério 2 (suspenso permanece suspenso; retomado preserva porta, ID, trabalho e dados) | **mantido**: suspender e retomar dentro do runtime continua precisando preservar porta e ID |

## 7. Verificação

### 7.1. Testes automatizados

Escritos antes da implementação.

- **Espera:** sai com 0 apenas em `healthy`; continua em `dns_failed`,
  `timeout`, `no_route`, `tls_failed` e `connection_refused`; nunca invoca
  Podman; registra apenas mudanças de estado.
- **Unidades geradas:** **toda** unidade de container de workspace (proxy,
  agent, fwd, docker e serviços) contém `Requires=asb-network.service` e
  `After=asb-network.service`; a unidade do
  keyring não depende de `asb-network` e tem `ExecStartPost` de prontidão; a
  espera tem `Type=oneshot`, `RemainAfterExit=yes` e
  `TimeoutStartSec=infinity`.
- **Política de reinício:** nenhum container ASB criado com
  `unless-stopped`; todos com `--restart=no`.
- **Drop-in:** `up` remove o drop-in do projeto quando presente, nunca o
  instala, e preserva drop-ins de terceiros.
- **CLI:** `--runtime`, `adopt-runtime` e `rollback-runtime` não existem.
- **Integração isolada** (fixture de isolamento, sem volumes reais): com a
  sonda forçada a falhar, o workspace não inicia; quando a sonda passa, ele
  inicia sem intervenção.

### 7.2. Validação real

A §8 da spec original determina que uma correção relacionada exige repetir os
cenários afetados. Repetem-se os boots:

| Boot | O que prova |
| :--- | :--- |
| Normal, **dois workspaces systemd simultâneos** | a corrida entre vários workspaces, ainda não testada |
| Rede atrasada 60 s (cabo desconectado no boot) | a espera segura os workspaces e eles iniciam sem comando corretivo |
| Um workspace ativo e outro suspenso | critério 2 |

Em cada boot, obrigatoriamente:

1. **Medida decisiva:** o `pasta` do namespace rootless nasce **depois** de
   `ActiveEnterTimestamp` de `asb-network.service`. Se nascer antes, algum
   produtor ainda cria o namespace cedo.
2. **Prontidão pelo caminho real**, não pelo estado `active` do systemd:
   agente → proxy → `github.com` com HTTP 200, e `example.com` com 403.
3. Boot real comprovado por troca de `boot_id`; nenhum comando corretivo.

E, na troca:

4. Credenciais preservadas: `auth status` antes e depois da recriação do
   keyring.
5. Drop-in do projeto ausente depois do `up`.

### 7.3. Regra de parada

Se um boot com a espera **ainda** perder o egresso, com o `pasta` nascido
**depois** da espera, a premissa da §8 desta emenda estava errada. Nesse caso
parar, registrar e rever o desenho, sem expandir nem migrar, conforme a regra
de parada da spec original.

## 8. Premissa não comprovada

Esta emenda só resolve o defeito de boot **se um namespace rootless criado
depois de o host ter conectividade real tiver egresso funcional**.

A favor: no boot 2 o namespace em uso nasceu cerca de 40 s após o
`network-online.target`, depois de uma primeira tentativa falhar, e o egresso
funcionou.

Não comprovado: não se determinou por que o uplink capturado logo após o
`network-online.target` não funcionava, nem se observou diretamente a
destruição e recriação do namespace — apenas foi inferida pelos carimbos de
tempo. A validação da §7.2 é o que confirma ou refuta a premissa.

## 9. Limites e fora de escopo

- **Queda de rede depois do boot.** A espera protege só a ordem de partida;
  uma perda de rede posterior não a dispara de novo. É o cenário do critério 4
  e da fase (d) do piloto, medido separadamente.
- **Limite de reinícios.** As unidades mantêm `StartLimitBurst=3`. Com a
  espera, a primeira sonda de egresso deve passar; se não passar, a §7.3 se
  aplica. Rever o limite fica fora desta emenda.
- **Schema do manifesto:** mantido (§6).
- **Validação pelo Orca:** bloqueada por defeito do Orca.
- **Produtores de terceiros:** a espera não impede um workload alheio de
  inicializar o namespace cedo. O `doctor` passa a apontá-los (§6), mas não os
  controla.

## 10. Evidência

- Relatório do piloto: [`docs/validation/startup-auth-pilot.md`](../../validation/startup-auth-pilot.md),
  §6.2 (boot 1), §6.4 (boot 2), §6.5 a §6.7 (Orca e boot 3).
- Evidência bruta por boot: `~/.local/state/agent-sandbox/t2-evidence/`
  (`pre-boot*`, `post-boot*`, journals das unidades).
