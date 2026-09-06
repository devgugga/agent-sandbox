# Secret Service singleton para credenciais dos agentes

## Contexto

O volume `asb-credentials` é compartilhado por todos os workspaces, mas cada
container inicia seu próprio `dbus-daemon` e `gnome-keyring-daemon` sobre o
mesmo diretório `keyrings/`. O container temporário de `asb-agent login` valida
as credenciais contra o daemon que acabou de gravá-las e então é removido.
Containers de workspace abrem outros daemons concorrentes sobre os mesmos
arquivos.

Essa arquitetura produz um falso sucesso: o login passa no container
temporário, mas Claude Code e Antigravity não encontram a sessão depois. Um
teste controlado com dois daemons concorrentes confirmou que uma gravação feita
por um daemon não é vista pelo outro e não sobrevive de forma confiável ao
próximo daemon. Codex funciona porque seu token é persistido diretamente em
`codex-auth.json`.

Claude Code atual também usa o Secret Service/libsecret no Linux quando ele
está disponível. Portanto, tratar somente `~/.claude/.credentials.json` como a
fonte canônica não cobre as versões atuais.

## Objetivo

Ter exatamente um proprietário do keyring por instalação do usuário, acessível
por todos os containers de login e workspace por um socket D-Bus compartilhado.
O login deve ser feito uma vez e continuar válido em clientes novos e depois de
reiniciar o serviço.

## Decisão de arquitetura

Criar um container global chamado `asb-keyring` e um volume de runtime chamado
`asb-keyring-runtime`.

```text
host keyring.pass (ro) ─┐
asb-credentials/keyrings├─> asb-keyring
asb-keyring-runtime     ┘       │
                               │ unix:/run/asb-keyring/bus
                ┌──────────────┼──────────────┐
                │              │              │
             asb-login     workspace A    workspace B
```

Somente `asb-keyring` inicia `dbus-daemon` e `gnome-keyring-daemon`. Ele:

- roda como o usuário 1000 em user namespace `keep-id`;
- não possui rede (`--network none`);
- monta a passphrase do host como arquivo somente leitura, nunca como variável
  visível em `podman inspect`;
- monta `asb-credentials` para os arquivos cifrados do keyring;
- publica apenas o socket Unix no volume `asb-keyring-runtime`;
- usa `--restart unless-stopped`.

Containers clientes:

- não recebem `ASB_KEYRING_PASS`;
- não iniciam D-Bus nem gnome-keyring;
- não montam/symlinkam o diretório `keyrings` em seus homes;
- montam `asb-keyring-runtime` e recebem
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus`;
- continuam montando `asb-credentials` para `codex-auth.json` e para o fallback
  legado `claude.json`.

Volumes compartilhados entre containers devem usar rótulo SELinux compartilhado
(`:z`); o runtime pode ser somente leitura nos clientes.

## Ciclo de vida

`ensure_keyring_service()` é o único ponto de criação/inicialização. Ele:

1. garante os volumes e a passphrase;
2. cria o container global se ausente;
3. inicia-o se estiver parado;
4. espera, com timeout curto e explícito, pelo socket D-Bus e por uma resposta
   de `org.freedesktop.secrets`;
5. falha com uma correção exata se o serviço não ficar saudável.

`up()` e `login()` chamam esse helper antes de criar o cliente. `resume()` o
chama antes de restaurar o proxy/agente. `down`, `suspend` e `purge` nunca
removem o serviço global nem seus volumes.

O container temporário de login valida os três agentes pelo mesmo Secret
Service consumido por clientes futuros. Depois da validação, ele é removido,
mas o serviço permanece.

O `doctor` verifica separadamente:

- existência do volume de credenciais;
- existência/execução do container global;
- existência do socket;
- resposta do Secret Service.

A correção indicada para serviço ausente ou inválido é `asb-agent login`.

## Segurança

- O keyring continua cifrado em repouso.
- A passphrase permanece `0600` no host e só é montada no container global,
  somente leitura.
- O container global não recebe rede, projeto, SSH, proxy, Docker socket nem
  configuração dos workspaces.
- O socket D-Bus fica em volume Podman privado à instalação do usuário; não é
  publicado no host por porta TCP.
- Nenhuma credencial real aparece em testes ou logs.

## Compatibilidade e migração

- `codex-auth.json` permanece inalterado.
- `claude.json` permanece como fallback compatível, embora versões atuais
  possam preferir Secret Service.
- O diretório cifrado já existente em `asb-credentials/keyrings` é reutilizado
  pelo singleton.
- Não há migração destrutiva de credenciais.
- Um cliente criado antes dessa mudança deve ser recriado para receber o socket
  compartilhado; `resume` não consegue adicionar mounts a containers antigos.
  A documentação deve dizer claramente que workspaces antigos exigem
  `pull`/`down`/`up`, preservando antes qualquer trabalho não integrado.

## Critérios de aceitação

- Há apenas um daemon de Secret Service escrevendo no keyring persistente.
- Dois clientes simultâneos enxergam o mesmo item de teste.
- Um cliente novo enxerga o item depois que o container de login é removido.
- O item continua disponível depois de reiniciar somente `asb-keyring`.
- Argumentos de containers clientes não contêm a passphrase.
- `asb-agent login` só imprime sucesso se os checks reais passarem usando o
  serviço compartilhado.
- A suíte nunca modifica o volume real `asb-credentials` nem credenciais reais.

## Fora de escopo

- Mudar os fluxos OAuth/device-auth dos fornecedores.
- Armazenar tokens fora dos mecanismos oficiais das CLIs.
- Compartilhar o socket com processos fora dos containers do projeto.
- Corrigir falhas de rede; isso pertence ao plano de uplink rootless.

