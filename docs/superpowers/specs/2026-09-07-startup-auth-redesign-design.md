# Redesenho de inicialização e autenticação

Data: 2026-09-07. Status: proposta para revisão; implementação não iniciada.

## 1. Objetivo e limites

Fazer os workspaces voltarem utilizáveis depois do login no desktop e manter
autenticação verificável entre sessões, workspaces e partidas da máquina.
O resultado será demonstrado em um piloto antes de migrar o ambiente diário.

Premissas preservadas do projeto: Podman rootless, Orca por SSH, mesmo usuário
e caminhos, login uma vez por fornecedor compartilhado entre workspaces,
execução simultânea de agentes, isolamento de rede e de arquivos do host.
Autenticação expirada/revogada pelo fornecedor pode exigir novo login;
reboot e troca de workspace não devem ser motivos para isso.

Não fazem parte deste trabalho: VM, Kubernetes, linguagem nova, servidor
próprio de OAuth, troca de assinatura por cobrança de API, ampliação da
allowlist, novas integrações ou reescrita do provisionamento de skills.

## 2. Evidência e incertezas

Diagnóstico desta máquina, neste dia:

- Os containers foram restaurados entre 10:18:14 e 10:18:15; a configuração
  IPv4 do host chegou às 10:18:18 e a conectividade global às 10:18:19.
- Os dois proxies retornaram `Network is unreachable`; Squid retornou 503
  com `ERR_CONNECT_FAIL 101`. Uma requisição do host a GitHub retornou 200.
- Há um processo pasta em execução, identificado como `passt.avx2`.
  Portanto, ausência de um processo chamado literalmente pasta não é diagnóstico.
- Codex reconhece login nos dois workspaces; Claude retorna `loggedIn: false`
  e seu arquivo compartilhado está vazio. Antigravity não foi validado.
- O keyring responde. O forwarder perdeu o listener da porta 80, mas seu
  processo principal continua vivo.
- 191 testes unitários passaram. Não foi executado reboot durante a análise.

A corrida entre rede do host e inicialização rootless é uma hipótese forte,
não uma causa encerrada por teste controlado. A origem do arquivo vazio do
Claude permanece desconhecida. Não atribuir a falha a symlinks, escrita
atômica, concorrência ou keyring sem observar o fornecedor real.

## 3. Alternativas e decisão proposta

| Alternativa | Benefício | Custo/risco | Decisão |
|---|---|---|---|
| Mais um ajuste no restore/login atuais | Mudança pequena | Mantém sucesso sem prontidão e diagnóstico ambíguo | Rejeitada |
| systemd supervisiona os containers persistentes | Dependências e supervisão explícitas; preserva IDs, portas e camada gravável | Pequenas unidades e sondas sob nossa manutenção | Recomendada para este escopo |
| Quadlet recria todos os containers | Configuração declarativa recomendada pelo Podman | Exige externalizar estado de agentes e serviços, preservar portas e migrar dados | Candidata se o piloto reprovar a alternativa anterior; requer revisão do desenho |

A escolha não usa `podman generate systemd`, que está depreciado.
Usa o comando suportado `podman start --attach` em unidades systemd.
Esse comando também se conecta a um container já em execução. A semântica de
supervisão, sinais e falhas será validada antes de adotar a solução.

## 4. Contratos globais

- Python >= 3.11; biblioteca padrão no CLI; Podman >= 6.1; systemd de usuário
  com `Type=exec`; plataforma inicialmente validada: Arch/Omarchy desta máquina.
- Início automático após login do usuário; `Linger=no` permanece. Iniciar antes
  de qualquer login é uma necessidade diferente e não será habilitado aqui.
- Containers, redes, nomes, portas SSH e diretórios de trabalho existentes são
  preservados na adoção da nova supervisão.
- Apenas systemd reinicia recursos adotados: política Podman desses containers
  passa a `no`. Não desabilitar `podman-restart.service` globalmente, pois pode
  servir a containers alheios ao projeto.
- Nenhum caminho do checkout em unidades instaladas. Helpers são instalados
  em `~/.local/lib/agent-sandbox/runtime/<revisao>/`, fora dos mounts dos agentes.
- Configuração, manifesto operacional e locks ficam fora do mount do workspace.
- Não montar HOME do host, credenciais do host, socket Docker irrestrito ou
  passphrase do keyring nos agentes. Manter a rede interna e o proxy filtrado.
- `up` e `resume`: uma linha JSON de conexão em stdout somente após prontidão;
  falha retorna código diferente de zero e diagnóstico em stderr.
- Não matar pasta, apagar namespace rootless, parar containers não inventariados
  ou reiniciar todos os containers do usuário como recuperação automática.
- Testes automáticos usam exclusivamente recursos com prefixo `asb-test-`,
  diretórios temporários e credenciais sintéticas; não usam volumes de produção.

## 5. Inicialização: responsabilidades e estado

`lifecycle.py` mantém criação, identidade e teardown. `supervisor.py` instala
unidades e pede start/stop ao systemd. `readiness.py` observa prontidão e
classifica falhas. O systemd mantém processos vivos; não criar daemon Python
de reconciliação nem uma segunda fila de reinícios.

Cada workspace adotado tem um target e unidades por container. Um manifesto
`state/<ws>/runtime.json`, schema 1, registra nomes E IDs dos containers,
políticas anteriores, porta SSH, revisão do helper e unidades pertencentes
ao workspace. Nomes iguais com IDs diferentes exigem reconciliação explícita.
Não persistir ambientes completos, tokens ou conteúdo de `podman inspect`.

O target habilitado é a fonte de verdade para restaurar o workspace no próximo
login. `suspend` desabilita e para o target; `resume` habilita e inicia. Parar
a sessão do usuário no desligamento não desabilita o target. Não manter um
segundo booleano de autostart que possa divergir do systemd.

Sequência de admissão:

```text
rede do host pronta -> proxy acessível e CONNECT permitido
                    -> dependências opcionais configuradas prontas
keyring pronto -----+-> agente iniciado -> SSH executa comando -> JSON ao Orca
```

Usar `Wants`/`After` para ordenar e sondas para comprovar prontidão. Uma falha
posterior do proxy não deve matar a sessão do agente; a sonda periódica não
reinicia o agente. `PartOf` liga os containers do workspace ao seu target para
stop explícito. O keyring é global, sem `PartOf` de workspace.

### 5.1 Sondas e limites

| Sonda | Evidência necessária | Limite |
|---|---|---|
| Host | rota utilizável + TCP/TLS ao destino de controle declarado | 90 s, tentativas espaçadas em 1 s, chamadas individuais <= 5 s |
| Proxy | CONNECT do agente ao proxy para um domínio já permitido | 30 s |
| Keyring | bus e Secret Service respondem como uid 1000 | 10 s |
| SSH | chave conhecida executa `true` via porta persistida | 30 s |
| Forwarder | cada porta configurada tem listener e alcança o destino declarado | 10 s por conjunto, concorrência limitada |
| Serviço de projeto | healthcheck da imagem quando existe; caso contrário apenas estado de processo, explicitamente rotulado | 30 s |

O domínio de controle inicial é `github.com:443`, já permitido. Torná-lo
configurável pelo operador, não pelo clone gravável. Falha nesse destino é
`probe_failed`, não prova de falta de internet global. Distinguir ausência de
rota, resolução, TCP, TLS, CONNECT negado, timeout e serviço ausente.

Toda partida de proxy reavalia o host, inclusive após o primeiro boot.
Uma unidade `network-online` previamente ativa não substitui a sonda.
`podman unshare --rootless-netns true` pode preparar o namespace após a rede,
mas seu exit code não comprova que a saída externa funciona.

Unidades: `Restart=always`, `RestartSec=5s`, `StartLimitIntervalSec=600s`,
`StartLimitBurst=3`, `TimeoutStartSec=150s`, `TimeoutStopSec=20s`.
Stop explícito do systemd não é reinício automático. Esgotado o limite,
diagnóstico deve indicar a unidade e o comando `resume`; não há loop infinito.
Queda de rede em execução é reportada sem logout e sem destruir containers.

### 5.2 Forwarder e criação transacional

Cada listener deve ser supervisionado pelo processo principal do forwarder.
Se algum filho encerrar, encerrar os demais e falhar; não manter `sh ... wait`
mascarando a perda de uma porta. Permitir bind baixo somente dentro do
namespace desse container (`net.ipv4.ip_unprivileged_port_start=0`), sem
alterar o host ou executar o encaminhador como root.

Uma falha de `up` remove somente recursos criados nessa invocação. Uma chamada
sobre workspace existente nunca executa a varredura destrutiva atual como
consequência de falha de prontidão. `resume` nunca remove recursos.

## 6. Autenticação: contratos por fornecedor

Mover gestão do keyring para `keyring.py` e login/checks para `auth.py`,
preservando temporariamente exports usados pelos testes e pelo CLI.
Não criar abstração extensível de plugins de autenticação.

| Fornecedor | Comando de login candidato | Estado local | Persistência a comprovar |
|---|---|---|---|
| Claude | `claude auth login` | `claude auth status` JSON | arquivo `.credentials.json` no Linux |
| Codex | `codex login --device-auth` | `codex login status` | armazenamento nativo efetivamente configurado |
| Antigravity | `agy` interativo | sem status presumido; usar `unknown` quando não verificável localmente | Secret Service observado na versão instalada |

O fluxo web é o oficial de cada fornecedor. Para Claude, suportar colagem do
código quando o callback não alcança o container; não inventar um device-auth
comum aos três. Não imprimir links com código OAuth em logs persistentes.

Comandos públicos:

```text
asb-agent login [--agent claude|codex|agy|all]       # default all, compatível
asb-agent auth status --workspace ID [--agent ...] [--json]
asb-agent auth verify --workspace ID [--agent ...] [--json]
```

`status` é observacional, não inicia login nem chama modelo. `verify` é uma
ação explícita com chamadas mínimas reais, timeout de 60 s por fornecedor e
sem retry automático. A ausência de autenticação não impede abrir SSH para
trabalhar ou fazer login. Prontidão de infraestrutura e de fornecedor são
estados separados.

Estados: `authenticated`, `unauthenticated`, `unknown`, `unreachable`,
`expired`, `provider_error`. Somente evidência explícita permite `expired`.
Exit code 1 sozinho não permite concluir logout. `status` não declara token
aceito pelo servidor; essa garantia pertence ao `verify` com data registrada.
Nunca inferir autenticação de `--version` ou da existência do arquivo.

### 6.1 Persistência e concorrência: gate obrigatório

Antes de mudar mounts ou credenciais, observar cada CLI real em ambiente de
teste: caminho de escrita, comportamento sobre symlink, troca por `rename`,
leitura em cliente novo e renovação concorrente em dois workspaces.
Registrar metadados/resultados, jamais valores de tokens.

O contrato atual de arquivos compartilhados só permanece se passar nesses
testes. Se um fornecedor substituir o symlink ou renovar tokens de maneira
incompatível com uso concorrente, encerrar essa etapa com evidência e revisar
o layout antes de executar a implementação de persistência. Não improvisar
um sincronizador de tokens, copiar snapshots cegamente ou serializar todas as
sessões de trabalho para manter a promessa de um login global.

Isso é um ponto de decisão deliberado: ainda não sabemos a causa do login
perdido. O plano não transforma uma hipótese em implementação obrigatória.

Logins interativos usam lock de operador por fornecedor, sem bloquear outros
fornecedores. O lock não é anunciado como solução de concorrência dos refreshes
das CLIs. Nunca remover um `asb-login` alheio: nomes de sessões são únicos.
Validar credencial em segundo cliente após encerrar o container de login;
uma checagem apenas no container que autenticou não basta.

### 6.2 Versões, logs e keyring

Registrar e fixar as versões verificadas: referência inicial Claude 2.1.263,
Codex 0.153.4 e Antigravity 1.1.27. Se o instalador do agy não permitir versão
fixa, usar artefato versionado verificável; sem isso, reprovar o gate de build.
Não alterar ferramentas não envolvidas nesta tarefa.

Não inventar chaves de configuração: conferir o modo de armazenamento do
Codex na versão fixada e a precedência da configuração provisionada.
Keyring é infraestrutura; sua indisponibilidade não deve mandar fazer login
novamente. Autenticação de Claude/Codex deve ser reportada independentemente
do estado do keyring quando não o utilizarem.

Logs de aplicação do projeto guardam etapa, duração, código do processo,
categoria e remediação. Não persistir stdout/stderr bruto de autenticação.
Detalhes interativos ficam no terminal do operador; diagnósticos persistentes
usam campos permitidos. Preservar volumes de credenciais e passphrase.

## 7. Migração e retorno

Primeiro o piloto sintético, depois um piloto com contas reais consentido pelo
operador, depois adoção de um workspace existente. Inventariar IDs, políticas,
portas, imagem e mounts antes de mudar supervisão. Preparar unidades desativadas
e validar sintaxe. Não parar `podman-restart.service`: seu ExecStop para todos
os containers do usuário.

Com os recursos exatos registrados, trocar política Podman para `no`, iniciar
as unidades e comprovar prontidão. Adoção é retomável sob lock por workspace.
Falha restaura políticas e habilitação anteriores, sem recriar containers.
A adoção do keyring global é uma transação separada e coordenada, com janela
registrada; não executá-la implicitamente pelo primeiro workspace.

Remover o drop-in antigo somente após inventário confirmar que foi criado
pelo projeto e que os recursos ASB foram adotados. Preservar alterações alheias.
Não alterar o serviço de restauração de outros containers.

O namespace rootless é compartilhado: aguardar rede em uma unidade não repara
um namespace já inicializado cedo por outra. Inventariar todos os produtores
antes do piloto de boot. Em janela acordada, suspender temporariamente apenas
workspaces ASB legados inventariados, registrando seu estado anterior, para
provar a partida com os pilotos gerenciados. Restaurá-los ao terminar a janela.
Se um workload alheio continuar inicializando a rede prematuramente, registrar
interferência e reprovar a validação do desenho nesta configuração; não
desabilitá-lo nem alegar que a ordenação local resolveu o sistema inteiro.

A adoção de supervisão não recria containers. O forwarder pode precisar de
recriação específica para receber novo comando/sysctl; tratar essa alteração
como migração separada, sem recriar o agente ou os containers de dados.

Se credenciais exigirem layout novo, preparar destino sem alterar a origem,
parar escritores em janela explícita e validar migração e rollback antes de
adotá-lo. Nunca substituir credenciais renovadas por uma cópia antiga.
Não usar `git pull` como backup de trabalho não commitado.

## 8. Aceitação e regras para parar

Aceitar a entrega somente com relatório que relacione requisito, comando,
resultado, versão e boot ID, sem credenciais:

1. Três boots reais distintos, incluindo rede disponível com atraso de 60 s;
   workspace pronto sem comando corretivo depois do login.
2. Workspace suspenso permanece suspenso no reboot; retomado preserva porta,
   container ID, trabalho não commitado e dados de serviço existentes.
3. Login real nos três fornecedores; cliente novo e dois workspaces simultâneos
   utilizáveis; renovação real observada ou marcada pendente, nunca simulada
   como comprovação final.
4. Queda temporária de rede não apaga credenciais; indisponibilidade de API não
   vira indicação de logout. Recuperação automática validada no piloto; caso
   exija reset global de rootless, não promover essa solução para produção.
5. Proxy ausente, porta 80 sem listener e keyring indisponível são detectados;
   falhas de admissão não emitem JSON de sucesso ao Orca.
6. Bloqueios de rede continuam válidos, com controles positivos de SSH e proxy.
7. Rollback de supervisão ensaiado sem perda de dados ou troca de porta.
8. Dois dias de uso real sem reparo manual, após os testes controlados.

Gate reprovado interrompe expansão/migração, não autoriza uma VM nem nova
reescrita. Registrar evidência e revisar somente a decisão que falhou.
Uma correção relacionada exige repetir os cenários afetados; testes verdes
isolados não liberam a etapa seguinte.

## 9. Fontes e relação com documentos anteriores

Este documento propõe substituir os contratos de inicialização e login dos
designs v2, rootless-uplink-recovery e singleton-secret-service. Enquanto não
aprovado/implementado, não declara esses documentos já substituídos.

- [Podman start: attach e sinais](https://docs.podman.io/en/latest/markdown/podman-start.1.html).
- [Quadlet: criação, rede e habilitação](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html).
- [Depreciação do gerador systemd e conflito de restart policies](https://docs.podman.io/en/latest/markdown/podman-generate-systemd.1.html).
- [Claude: login em containers e armazenamento Linux](https://code.claude.com/docs/en/authentication).
- Código local: `cli/asb/lifecycle.py`, `cli/asb/doctor.py`, `cli/asb/install.py`,
  `image/entrypoint.sh`, `image/start-keyring.sh`, `recipes/` e `tests/`.
