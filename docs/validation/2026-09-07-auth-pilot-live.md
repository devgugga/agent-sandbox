# Piloto assistido de autenticação — 2026-09-07

## Escopo e estado

Operador autorizou preparar o piloto e informou que os workspaces existentes
são testes descartáveis. Mesmo assim, nenhum deles foi alterado ou removido.
Não importar credenciais do host. Não registrar tokens, códigos OAuth ou saída
bruta de login. Não executar chamadas de modelo nesta preparação.

**Estado (atualizado 2026-09-07 22:49 BRT): os três fornecedores têm login
humano realizado. Codex é o único validado sob a topologia fiel (rede interna
+ proxy). Antigravity deixou de ser falha de autenticação. Claude permanece
deslogado no ambiente normal, por causa de armazenamento já estabelecida.
Gate A1 continua ABERTO: renovação natural não observada.**
Este é um experimento de A1 com diretório montado, não a implementação A3 nem
aprovação do gate. A configuração do ambiente normal continua inalterada.

## Recursos efetivamente criados

- Imagem local fixada: `409bc7c31795efe28aa9c323811a3dd290a830e737fbd16b36b8dd39ef72c952`.
- Container: `asb-test-auth-20260907-claude-login`.
- Volume exclusivo inicialmente vazio: `asb-test-auth-20260907-claude`.
- Mount: volume acima em `/home/v/.claude`, opções `U,z,nocopy`.
- UID/GID `1000:1000`, user namespace `keep-id:uid=1000,gid=1000`.
- Entrypoint `/bin/sleep infinity`, sem passar pelo entrypoint de produção.
- Rede `pasta`, sem proxy, portas publicadas, mounts de host ou keyring de produção.
- Restart `no`, capabilities removidas, `no-new-privileges` habilitado.

Não reutilizar esses nomes para outros testes. Os recursos permanecem para
validação posterior; não remover o volume antes de decidir sobre as credenciais.
Não há restauração automática deste piloto após reboot.

## Evidência anterior ao login

- `id`: UID/GID 1000, usuário `v`.
- `/run/asb-credentials` ausente; `.claude` não é symlink e é gravável.
- `.claude/.credentials.json` ausente, em vez de precriado vazio.
- CLI: Claude Code `2.1.263`.
- Ajuda local confirma `claude auth login --claudeai` para assinatura Claude;
  não usar `--console`, que seleciona faturamento de API.
- `claude auth status --json`: exit 1, `loggedIn=false`, `authMethod=none`.
- Sondas HTTPS sem credenciais: `https://claude.ai` retornou 403;
  `https://console.anthropic.com` retornou 301. Há resposta HTTPS, mas isso
  **não comprova** que todos os endpoints OAuth estejam acessíveis.

## Login Claude — executado pelo operador

No terminal do host:

```bash
podman exec -it --user 1000:1000 asb-test-auth-20260907-claude-login claude auth login --claudeai
```

Seguir o fluxo no navegador. Se houver código para colar, colar somente no
terminal desse comando, nunca na conversa ou em um arquivo do repositório.
Se o callback local falhar, não repetir logins às cegas: relatar apenas o erro
sanitizado, sem URL com parâmetros OAuth. Não enviar prompts ao modelo.

Avisar quando o comando encerrar. O agente verificará apenas o booleano de
autenticação e metadados do arquivo, sem imprimir email ou conteúdo da credencial.

### Resultado observado após o login (2026-09-07, aproximadamente 20:11 BRT)

- No cliente de login: `loggedIn=true`, exit 0, `authMethod=claude.ai`.
- Credencial regular, não symlink, não vazia, UID 1000 e modo `0600`.
- Cliente de login parado. Seu PID 1 era `sleep` sem init; após 5 segundos
  sem encerrar com SIGTERM, Podman usou SIGKILL (exit 137). Isso ocorreu após
  o login e não representa teste de encerramento gracioso do runtime normal.
- Outro container, `asb-test-auth-20260907-claude-fresh`, montou somente o
  mesmo volume `.claude`: `loggedIn=true`, exit 0, `authMethod=claude.ai`.
  O container efêmero foi removido automaticamente; o volume foi preservado.
- Não foram feitas chamadas de modelo. O resultado comprova reconhecimento
  local no cliente novo, não aceitação pelo servidor, refresh ou concorrência.

## Login Antigravity — executado pelo operador

Preparação isolada, mesma imagem e UID/GID do piloto Claude:

- Keyring `asb-test-auth-20260907-keyring`, rede `none`, restart `no`.
- Dados: volume `asb-test-auth-20260907-keyring-data`.
- Socket: volume `asb-test-auth-20260907-keyring-runtime`.
- Passphrase exclusiva gerada pela função existente `ensure_keyring_pass`,
  em `/tmp/asb-test-auth-20260907/keyring.pass`, montada somente no keyring,
  read-only. Não foi copiada da configuração de produção. Não remover esse
  arquivo durante o piloto; `/tmp` não é armazenamento durável após reboot.
- Cliente `asb-test-auth-20260907-agy-login`, com `--init`, rede `pasta`, sem
  portas publicadas, somente socket do keyring montado read-only e variável
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus`.
- Ambos sem capabilities, com `no-new-privileges`, usuário 1000 e sem o
  entrypoint de produção. Nenhum mount de credenciais/configuração do host.
- Secret Service respondeu **a partir do cliente** e a coleção `login`
  reportou `Locked=false`. Isso não comprova conta Google autenticada.
- CLI `agy` 1.1.27; ajuda confirma TUI sem subcomando `login`/`auth status`.
- Variáveis `SSH_CONNECTION`, `SSH_CLIENT`, `SSH_TTY` ausentes.
- Sonda HTTPS sem credenciais: `accounts.google.com` retornou 302;
  não comprova acesso a todos os endpoints OAuth.

No terminal do host:

```bash
podman exec -it --user 1000:1000 asb-test-auth-20260907-agy-login agy
```

Concluir o login Google, sem enviar prompts ao modelo. Avisar ao chegar à
interface autenticada ou relatar apenas erro sanitizado. Não colar códigos,
tokens nem URLs OAuth na conversa. Manter o container: qualquer estado local
adicional necessário ainda precisa ser caracterizado antes do cliente novo.

### Resultado observado (2026-09-07, aproximadamente 20:14–20:16 BRT)

- Após login humano, a coleção `login` contém um identificador de item.
  Somente o caminho do objeto foi consultado; nenhum segredo, atributo de
  conta ou conteúdo de arquivo de autenticação foi impresso.
- `podman diff` identificou estado local em `.gemini/antigravity-cli` e
  `.gemini/config`. Esse estado **não foi copiado** para os clientes novos.
- A ajuda da CLI confirma `agy models` como listagem de modelos. Usado
  explicitamente no piloto, com stdin fechado e timeout de 20 segundos,
  sem prompt. Saída bruta capturada apenas em memória e reduzida a indicadores:
  exit, número de linhas, presença de nomes de modelos, erro e pedido de login.

| Experimento | Resultado de `agy models` |
| --- | --- |
| Cliente original após login | exit 0; 16 linhas; nomes de modelos presentes; sem marcador de erro/login |
| Cliente novo `asb-test-auth-20260907-agy-fresh`, apenas socket compartilhado | mesmo resultado positivo, sem copiar home |
| Controle novo `asb-test-auth-20260907-agy-control`, sem socket/keyring | exit 1; nenhum nome de modelo; pedido de autenticação e erro |
| Outro cliente novo `asb-test-auth-20260907-agy-afterrestart`, após parar o cliente de login e reiniciar o keyring | mesmo resultado positivo, sem copiar home |

A coleção voltou desbloqueada após o restart. Os containers `agy-control` e
`agy-afterrestart` foram removidos automaticamente; seus dados efêmeros não
foram preservados. Volumes com credenciais e os clientes de login foram
preservados; os clientes de login estão parados.

Conclusão limitada: nas condições desse piloto, o keyring compartilhado foi
suficiente para a listagem autenticada em clientes novos e sobreviveu ao
restart do serviço. Não houve chamada de geração ao modelo. Não reproduzimos
a falha original do Antigravity no caminho Orca/SSH/proxy; portanto não há
evidência para alterar seu armazenamento ou declarar o problema original
resolvido. `agy models` também não foi promovido a status automático/offline.

## Verificações ainda pendentes

Substituídas pelo [Adendo de 2026-09-07 22:00–22:50 BRT](#adendo--2026-09-07-2200-2250-brt);
ver §A8 para as pendências vigentes.

---

# Adendo — 2026-09-07, 22:00–22:50 BRT

Ambiente do adendo: boot ID `fee948a6-3b2b-4aeb-8478-a5ffb4527207`;
Podman 6.1.0; imagem fixada
`409bc7c31795efe28aa9c323811a3dd290a830e737fbd16b36b8dd39ef72c952`;
Claude Code 2.1.263, Codex CLI 0.153.4, Antigravity 1.1.27.

## A1. Correção de escopo: a topologia do piloto anterior não era fiel

Os quatro clientes usados nas seções acima (`claude-login`, `agy-login`,
`agy-fresh`, `codex-login`) foram criados com `NetworkMode=pasta` e **sem
variáveis de proxy**. Verificado por inspeção e por teste: um container nesse
modo alcança `github.com:443` diretamente. O proxy do piloto
(`asb-test-auth-20260907-proxy`) e suas duas redes foram criados e **nunca
foram usados por nenhum cliente**.

Consequência sobre o que já estava registrado:

- Os achados de **persistência** de Claude e Antigravity **permanecem
  válidos**. São propriedades de armazenamento em disco e de IPC via socket do
  Secret Service; não dependem da rota de saída.
- Nenhum resultado anterior caracteriza **login sob a topologia com proxy e
  allowlist**, que é a topologia dos workspaces reais. Essa lacuna não estava
  declarada e é corrigida aqui.

## A2. Achado bloqueante: namespace rootless sem uplink

Ao preparar um cliente fiel, constatou-se que **nenhum container em rede bridge
tinha egresso**, incluindo os workspaces de produção.

Evidência, com IP puro `4.228.31.150:443` para descartar DNS:

| Alvo | Resultado |
|---|---|
| Proxy do piloto | `Network is unreachable` |
| Proxy de produção `asb-orca-44b95c8d-…-proxy` | `Network is unreachable` |
| Container novo e descartável na rede `-out` | `Network is unreachable` |
| Controle: container em `pasta` | conexão bem-sucedida |

Dentro de `podman unshare --rootless-netns`: todas as bridges presentes e UP,
**sem rota default** e **sem processo `pasta`/`slirp4netns`**. O namespace
existia sem uplink; cada rede bridge era uma ilha.

**Achado contra o plano `2026-09-06-rootless-uplink-recovery`:** o helper que
ele entregou, `ensure_rootless_netns()` = `podman unshare --rootless-netns
true`, **não recupera esse estado**. Foi executado; um container recém-criado
continuou sem saída. Ele se anexa ao namespace existente em vez de reconstruir
um com uplink.

**Recuperação, com autorização explícita do operador:** parar os 8 containers
em bridge (sem remover nenhum), deixando os dois keyrings de pé por usarem
`--network none`; o namespace quebrado foi destruído; religar na ordem
proxy → agente → forwarder. Preservação verificada contra snapshot anterior:
IDs `301fb7e28e38`, `601de1242cd1`, `288a6aa04968`, `50ae9ac49b83`,
`664cdc9044af` idênticos; portas SSH `45311` e `44533` inalteradas; nenhum
volume tocado. Após religar, o agente de produção alcança `github.com:443`
**via Squid**, e o egresso direto continua `Network is unreachable` — o
isolamento foi preservado.

## A3. Antigravity: reclassificado, não era falha de autenticação

Com o uplink restaurado, `agy models` no workspace **real**
`orca-44b95c8d-…` retornou **rc 0** com a lista de modelos.

O timeout de 20 s registrado antes era ausência de egresso, não sessão
expirada. A hipótese de keyring/SSH fica descartada para este sintoma. A
credencial do Antigravity persiste normalmente.

## A4. Codex: login sob topologia fiel — PASS

Cliente `asb-test-auth-20260907-codex-proxied`: rede interna
`asb-test-auth-20260907-net`, `HTTP_PROXY`/`HTTPS_PROXY` para o Squid do
piloto, sem egresso direto, uid 1000, volume exclusivo em `/home/v/.codex`.

Primeira tentativa **falhou** com `Permission denied (os error 13)`: o `_data`
do volume pertencia a uid 0 enquanto o container roda como uid 1000. Corrigido
com `podman unshare chown -R 1000:1000` — escolhido em vez de `:U` para não
alterar ownership sem avaliação. O volume estava vazio. O resultado passa a
coincidir com produção, onde `~/.codex` dentro do agente real é `1000:1000`.

Comando executado pelo operador:

```bash
podman exec -it --user 1000:1000 \
  asb-test-auth-20260907-codex-proxied codex login --device-auth
```

Resultados observados:

| Verificação | Resultado |
|---|---|
| `auth.json` | arquivo **regular**, não symlink, modo `600`, `1000:1000`, 3876 bytes |
| `codex login status` (cliente de login) | `Logged in using ChatGPT`, rc 0 |
| Cliente novo `codex-fresh`, só o volume compartilhado | logado, rc 0 |
| Concorrência: dois clientes simultâneos | ambos rc 0 |
| Cliente de login **parado** → cliente novo | logado, rc 0 |
| Metadados após concorrência | inalterados, sem corrupção |

Nenhum home ou configuração foi copiado entre containers. Nenhuma chamada de
geração foi feita.

## A5. Claude: causa confirmada também por inspeção direta

Com a rede plenamente funcional, `auth status` no workspace real continua
reportando `unauthenticated` (`loggedIn=false`) — o sintoma é independente de
rede.

O volume de produção `asb-credentials/_data` contém:

```
-rw------- 1 0 0    0 claude.json        <- zero bytes
-rw------- 1 0 0 3876 codex-auth.json
```

O arquivo de 0 bytes previsto pela análise de A1 está literalmente em disco, ao
lado de uma credencial saudável do Codex. É a razão de o Codex aparecer
autenticado e o Claude não.

## A6. Correção de redação sobre a cobertura dos testes

Os testes de `rename`/`replace` em `tests/integration/test_credential_writers.py`
são **simulações em Python** do padrão de escrita atômica. Eles não observam o
escritor real de cada fornecedor. O registro anterior sugeria cobertura maior
do que a obtida; a conclusão sobre o Claude sustenta-se na análise do binário
somada ao arquivo de 0 bytes observado, não nesses testes isoladamente.

## A7. Situação por fornecedor, com as quatro separações exigidas

| Fornecedor | Caracterização A1 | Mecanismo aprovado | Problema original resolvido | Aceitação final |
|---|---|---|---|---|
| Codex | **PASS**, topologia fiel | sim, para diretório montado | n/a (não estava quebrado) | não — renovação pendente |
| Claude | **PASS** (causa estabelecida) | diretório montado validado no piloto, em egresso direto | **não** — conserto é A3 | não |
| Antigravity | **PASS**, reclassificado | persistência via socket do keyring | **sim**, era rede | não — renovação pendente |

## A8. Pendências que impedem fechar o gate

1. **Renovação natural não observada** para nenhum dos três. Não será forçada
   por alteração de relógio ou de token. Permanece `pending` e, por si só,
   impede a aceitação final.
2. **Claude e Antigravity não foram validados sob a topologia com proxy.** Só o
   Codex foi. A persistência já demonstrada não depende de rede, mas o
   comportamento de *login* sob allowlist não foi caracterizado para esses dois.
3. **Claude pelo caminho SSH/wrapper do workspace** ainda não foi comparado com
   o cliente direto.
4. **Nenhuma chamada real de geração** foi executada, em nenhum fornecedor.

Este adendo caracteriza A1. **Não aprova o gate, não autoriza A3 e não declara
o problema original resolvido para o Claude.**
