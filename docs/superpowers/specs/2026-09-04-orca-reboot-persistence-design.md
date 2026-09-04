# Design: persistência profissional do sandbox no Orca

**Data:** 2026-09-04
**Status:** Aprovado pelo usuário em 2026-09-04
**Escopo:** Restauração após reboot, fail-closed, autenticação e configuração dos
agentes em workspaces Orca.

## Problema confirmado

O serviço de restauração pode executar antes de o host possuir rota padrão. O
`pasta` copia esse estado incompleto para o namespace de rede do pod; o Squid
fica sem rota e sem DNS, mas o código considera o proxy saudável apenas porque
o processo está rodando. O Antigravity então carrega o token válido do keyring,
falha ao consultar o Google e apresenta o sintoma enganoso de logout.

Separadamente, o manifesto de provisionamento copia apenas
`~/.gemini/antigravity-cli/settings.json`. Plugins, skills, configuração de MCP
e hooks em `~/.gemini/config` não entram no sandbox. Quando o Orca injeta hooks,
ele também pode gravar caminhos absolutos do host, inválidos no container.

## Decisões

1. A restauração aguarda conectividade real do host, com timeout configurável.
   A unidade systemd usa `Restart=on-failure`, transformando atraso de rede em
   retry, não em um sandbox falsamente saudável.
2. Depois de subir o Squid, o lifecycle valida dentro do próprio namespace:
   rota padrão, DNS no processo autorizado e um CONNECT a domínio permitido.
   O agente só sobe depois dessas provas. Falha sempre para o pod inteiro.
3. `up` passa a ser transacional para recursos novos. Qualquer falha remove pod
   e estado parciais; um workspace existente nunca é substituído implicitamente.
   A imagem `agent-sandbox-auth` é obrigatória; não há fallback silencioso para
   uma imagem sem login.
4. O provisionamento inclui plugins, skills, hooks e MCP do Antigravity por
   lista explícita. Hooks são normalizados para o home do container tanto na
   cópia inicial quanto imediatamente antes de lançar `agy`, cobrindo a
   reinjeção feita pelo Orca.
5. O fluxo `auth` espera o Secret Service ficar pronto e testa os três agentes,
   incluindo uma chamada real do Antigravity, antes de gerar a imagem.
6. Um comando `doctor` expõe pré-requisitos e saúde dos pods sem modificar o
   ambiente.
7. Consumidores Orca devem declarar os quatro hooks da receita: `create`,
   `destroy`, `suspend` e `resume`. O projeto compartilhado continua sendo a
   fonte única da implementação.

## Limites deliberados

- Não será criado volume persistente para todo `/home/agent`: ele misturaria
  estado e credenciais entre workspaces. Configuração durável vem do manifesto;
  login durável vem da imagem autenticada e do keyring cifrado.
- Esta implementação não recria a imagem autenticada nem executa o doctor
  destrutivo `--provision` do Orca automaticamente. Ambos exigem interação ou
  podem destruir/recriar o workspace ativo.
- Uma allowlist de rede limita destinos, mas não impede exfiltração para um
  domínio já permitido.

## Critérios de aceitação

- Boot sem rota não restaura pods até a conectividade aparecer; timeout retorna
  falha para que o systemd tente novamente.
- Processo Squid sem DNS/CONNECT não é considerado saudável e o agente fica
  parado.
- Falha durante `up` não deixa pod nem diretório de estado.
- `up` sem `agent-sandbox-auth` falha antes de criar recursos.
- Plugins, skills, MCP e hooks sintéticos do Antigravity chegam ao destino;
  credenciais negadas continuam bloqueadas.
- Hook absoluto do host é convertido para `/home/agent/.orca/agent-hooks` no
  sandbox.
- Symlinks de origem fora das raízes de skills aprovadas são recusados; symlinks
  de destino controlados pelo agente nunca são atravessados até o repo montado.
- SSH só fica disponível depois do provisionamento terminar com um token único
  daquele start.
- `auth` recusa commit se qualquer um dos três agentes não estiver autenticado.
- `doctor` retorna zero apenas quando pré-requisitos e pods estão saudáveis.
- Suite anterior continua verde e novos testes cobrem as regressões.
