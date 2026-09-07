# Autenticação por fornecedor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar login, persistência e diagnóstico confiáveis para Claude,
Codex e Antigravity, mantendo login compartilhado entre workspaces.

**Architecture:** Adaptadores pequenos por fornecedor usam os fluxos nativos;
keyring é infraestrutura separada. Persistência só muda após caracterização
do escritor real; verificação acontece também em um cliente novo.

**Tech Stack:** Python >= 3.11/stdlib, Podman >= 6.1, CLIs reais versionadas,
GNOME Keyring/Secret Service existente, SSH e fixtures isoladas de I1.

**Spec:** [Desenho §6–8](../specs/2026-09-07-startup-auth-redesign-design.md).

## Global Constraints

- Proposta; A1 é gate obrigatório antes de alterar armazenamento em A3.
- Python >= 3.11; biblioteca padrão no CLI; Podman >= 6.1; systemd de usuário
  com `Type=exec`; plataforma inicialmente validada: Arch/Omarchy desta máquina.
- Login uma vez por fornecedor, compartilhado entre workspaces, com execução
  simultânea. Lock de operador não resolve refresh concorrente de CLIs.
- Não importar tokens do host, criar broker OAuth, trocar assinatura por API,
  ampliar allowlist ou apagar credenciais para recuperar rede.
- Testes automáticos somente em recursos `asb-test-` com dados sintéticos.
- Login real e chamadas aos fornecedores ocorrem somente no piloto explícito;
  uma sessão interativa é do operador, não um token obtido pelo agente.
- Referência inicial: Claude 2.1.263; Codex 0.153.4; Antigravity 1.1.27.
- Nunca persistir saída bruta de auth, tokens ou códigos de device login.
- Cada tarefa termina em diff e commit curado em branch, seguindo a governança
  Git e atualização única de Graphify do plano coordenador.

## A1 — Caracterizar o login real antes de escolher a correção

**Files:** criar `docs/validation/2026-09-07-provider-auth-contracts.md` na
execução; criar `tests/integration/test_credential_writers.py`; usar fixture I1.

**Interfaces:** relatório por fornecedor com versão, comando nativo, destino
real, tipo de arquivo antes/depois, status local, resultado em cliente novo,
concorrência, renovação e conclusão `pass`, `fail` ou `pending`.
Nenhum campo contém o valor de uma credencial.

- [ ] Conferir `--help` nas versões da imagem e configuração efetiva do Codex,
  filtrando apenas campos de armazenamento. Não imprimir config/env completos.
  Conferir documentação primária e a divergência do design antigo sobre Claude
  usar libsecret no Linux. Documento antigo não é evidência do binário atual.
- [ ] Provar a limitação do teste sintético atual em TemporaryDirectory:

```python
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    stored, link, temporary = root / "stored", root / "auth", root / "next"
    stored.write_text("old")
    link.symlink_to(stored)
    temporary.write_text("new")
    temporary.replace(link)
    self.assertEqual(stored.read_text(), "old")
    self.assertFalse(link.is_symlink())
```

Esse teste demonstra uma possibilidade de falha do contrato, não prova que
Claude ou Codex fazem esse tipo de escrita. Não recomendar trocar symlinks
por bind mounts de arquivos: rename também precisa ser testado nesse caso.
- [ ] Em containers de teste, reproduzir permissões e paths atuais e verificar
  leitura/escrita sintéticas como uid 1000. Adicionar casos de destino ausente,
  arquivo vazio, arquivo malformado e symlink substituído.
- [ ] Planejar com o operador uma sessão de login real em volume exclusivo do
  piloto. Observar somente metadados de escrita, status do fornecedor e exit
  codes. Não copiar sua credencial de produção para testes automáticos.
- [ ] Encerrar container de login, abrir cliente novo, comparar apenas validade
  observada. Testar pelo SSH/wrapper do workspace para incluir ambiente PAM e
  a remoção de SSH_* do agy. Login que funciona apenas no primeiro cliente falha.
- [ ] Executar dois clientes simultâneos e observar uma renovação real quando
  ela ocorrer; não adulterar token real ou relógio da máquina para provocá-la.
  Se não observada, marcar pending e manter esse critério aberto.
- [ ] Documentar a causa do Claude vazio ou a evidência que ainda falta.
  Distinguir login abortado, caminho diferente, erro de persistência, token
  rejeitado e conectividade. Não implementar A3 por adivinhação.
- [ ] Decisão: se mecanismo nativo escreve corretamente no contrato atual,
  preservá-lo e corrigir a causa encontrada. Se exige layout diferente ou
  compartilhamento conflita com refresh, registrar reprovação e revisar §6.1
  antes de A3. Não completar o restante por meio de cópia periódica de tokens.

## A2 — Separar status de conta, rede e infraestrutura

**Files:** criar `cli/asb/auth.py`, `cli/asb/keyring.py`,
`tests/unit/test_auth_status.py`; modificar `cli/asb/lifecycle.py`,
`cli/asb/doctor.py`, `cli/asb-agent`, `tests/unit/test_auth.py`.

**Interfaces:**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AuthResult:
    provider: str
    state: str
    checked_at: str
    evidence: str
    remediation: str
```

Produzir `check_status(provider: str, container: str) -> AuthResult`,
`parse_claude_status(returncode: int, stdout: str) -> AuthResult`,
`parse_codex_status(returncode: int, stdout: str, stderr: str) -> AuthResult`,
`status(ws: str, provider: str, *, json_output: bool) -> int`.
`provider` aceita claude/codex/agy/all na fronteira pública; check individual
rejeita all. `keyring.py` recebe funções e constantes de keyring existentes,
com reexports temporários em lifecycle para compatibilidade.

- [ ] Escrever casos para authenticated, unauthenticated, JSON inválido,
  comando ausente e saída inesperada. Exemplo:

```python
result = auth.parse_claude_status(1, '{"loggedIn": false}')
self.assertEqual(result.state, "unauthenticated")
unexpected = auth.parse_claude_status(124, "")
self.assertEqual(unexpected.state, "unknown")
```

- [ ] Rodar `python3 -B -m unittest discover -s tests/unit -p 'test_auth_status.py' -v`
  e confirmar RED. Para Codex, saída explícita negativa prevalece sobre
  substring positiva; formato desconhecido retorna unknown, não authenticated.
- [ ] Implementar execução como uid 1000, ambiente igual ao workspace e timeout
  de 10 s por status. Status não inicia login, faz logout ou envia prompt.
  Sem comando local comprovado para agy, responder unknown e indicar verify.
- [ ] Adicionar parser `auth status --workspace ID --agent all --json`.
  Relatório schema 1 contém lista de resultados sanitizados e timestamp UTC.
  Retorno agregado: 0 se todos authenticated; 1 se conta ausente/expirada;
  2 se algum unknown/unreachable/provider_error, com precedência sobre 1.
- [ ] Mover keyring sem mudar seu armazenamento; doctor apresenta erro de
  infraestrutura como tal, não remediação `login` universal. Não classificar
  Claude como deslogado porque dbus está parado.
- [ ] Executar unitários existentes e novos, revisar chamadas reais para provar
  que status não modifica recursos. Preparar documentação dos estados, sem
  anunciar `status` como prova de uma chamada aceita pelo servidor.

## A3 — Login seletivo, persistência comprovada e versões

**Files:** modificar `cli/asb/auth.py`, `cli/asb/lifecycle.py:login`,
`cli/asb-agent`, `image/entrypoint.sh`, `image/Containerfile`;
criar `tests/unit/test_login_flow.py`; atualizar `tests/test-auth.sh`
para fixtures isoladas, sem passar a usar contas reais.

**Interfaces:** `login(root: Path, provider: str = "all") -> int`;
`login_command(provider: str) -> tuple[str, ...]`;
`operator_lock(provider: str)` context manager com flock não bloqueante;
`verify_fresh_client(provider: str) -> AuthResult`, usando cliente efêmero
próprio e o armazenamento aprovado em A1. Reexportar lifecycle.login até
atualizar seu único consumidor e testes.

- [ ] Confirmar A1 aprovado para o mecanismo de persistência. Escrever teste
  da causa específica observada, além do contrato seletivo:

```python
self.assertEqual(auth.login_command("claude"), ("claude", "auth", "login"))
self.assertEqual(auth.login_command("codex"), ("codex", "login", "--device-auth"))
self.assertEqual(auth.login_command("agy"), ("agy",))
with patch("asb.auth.verify_fresh_client") as verify:
    verify.return_value = AuthResult("claude", "unauthenticated", "2026-09-07T00:00:00Z", "native_status", "login")
    # A fixture do teste simula término bem-sucedido do login interativo.
    self.assertNotEqual(auth.login(root, "claude"), 0)
    verify.assert_called_once_with("claude")
```

Montar mocks do subprocesso, lock e criação/remoção do cliente para que esse
teste nunca inicie login real. Segundo cliente deslogado reprova o fluxo.
- [ ] Confirmar RED. Trocar loop indiscriminado por seleção explícita. Default
  all permanece, mas cada fornecedor tem resultado separado e erros preservados.
  Login interativo herda TTY; invocação sem TTY falha com orientação, sem travar.
- [ ] Nomes de clientes são únicos e cleanup só remove o próprio ID. Lock por
  fornecedor retorna erro de sessão ocupada imediatamente; cancelamento retorna
  130 e mantém dados. Não remover asb-login de outra execução.
- [ ] Aplicar apenas a correção de persistência demonstrada em A1. Remover
  criação de arquivos vazios ou relink destrutivo somente se esses passos
  forem a causa confirmada ou violarem o contrato testado. Não apagar uma
  credencial nativa nova para reinstalar o link de uma cópia antiga no boot.
- [ ] Encerrar o cliente de login e verificar outro cliente antes de declarar
  persistência válida. Falha não inicia novo OAuth automaticamente. Para agy,
  sem status nativo, usar o mesmo `verify_client` limitado de A4 no cliente novo;
  a validação faz parte do login solicitado. Até A4 estar integrado, o resultado
  é explicitamente pendente e não autoriza anunciar login completo de all.
- [ ] Fixar versões da imagem pelo mecanismo suportado por cada instalador.
  Claude/Codex usam versões npm exatas; agy usa artefato versionado com
  checksum ou instalador com seleção comprovada. Se indisponível, interromper
  o gate de build, sem usar latest como se estivesse fixado. Labels de versões
  são validados contra os binários, não apenas declarados no Containerfile.
- [ ] Testar cancelamento, login parcial, segundo login concorrente, fonte
  vazia/malformada e persistência após restart. Rodar integrações sintéticas
  sem acessar keyring/passphrase reais; depois repetir somente os cenários
  reais necessários no piloto do operador.

## A4 — Verificação real e orçamento explícito

**Files:** modificar `cli/asb/auth.py`, `cli/asb-agent`,
`tests/test-agents-behind-proxy.sh`; criar `tests/unit/test_auth_verify.py`,
`tests/integration/test_provider_auth.py`.

**Interfaces:** `verify(ws: str, provider: str, *, json_output: bool) -> int`,
`verify_client(provider: str, container: str) -> AuthResult`,
`classify_verification(provider: str, returncode: int, output: str,
                       network_ok: bool) -> AuthResult`.
SandboxFixture recebe `provider_client(provider: str, fresh: bool) -> str`,
que retorna nome de cliente próprio. Chamadas reais exigem seleção explícita
de `test_provider_auth.py` e `ASB_LIVE_AUTH=1`; ausência desse opt-in é SKIP
e não serve como evidência de aprovação.

- [ ] Escrever teste impedindo rede ruim de virar logout:

```python
result = auth.classify_verification("claude", 1, "connection timed out", network_ok=False)
self.assertEqual(result.state, "unreachable")
self.assertNotEqual(result.remediation, "login")
rate_limited = auth.classify_verification("claude", 1, "HTTP 429", network_ok=True)
self.assertEqual(rate_limited.state, "provider_error")
```

- [ ] Confirmar RED. Implementar checks de infraestrutura antes da chamada,
  comandos reais via SSH e wrappers configurados, diretório sintético sem
  projeto ou secrets, stdin fechado e 60 s por fornecedor. Conferir flags
  disponíveis na versão fixada antes de usar print/exec ou restringir ferramentas.
  Não usar flag imaginária do agy nem um prompt como teste de login local.
- [ ] Limitar uma chamada por fornecedor por verify, sem retry; no piloto,
  limitar a três por fornecedor por cenário (login, novo cliente, simultaneidade)
  e registrar contagem. 401/403 só significa credencial inválida com evidência
  do fornecedor, não erro de ACL do proxy. Rate limit/serviço fora nunca apagam token.
- [ ] Evidência de sucesso exige resposta de modelo no formato solicitado e
  exit code zero. Não usar grep de `ok`, strings de help ou mensagem de login
  como prova de execução. Normalizar whitespace e comparar resposta completa
  de um prompt sintético, registrando erro de formato separadamente.
- [ ] Testes de log verificam que fixtures com token, bearer e código OAuth
  não aparecem no JSON/diagnóstico persistente. Usar campos permitidos e
  categorias, não regex que promete remover todo segredo de saída arbitrária.
- [ ] No piloto real, executar após login, em cliente novo, simultaneamente e
  após boot. Observar refresh sem manipular relógio/token real. Pendência de
  refresh não é preenchida por um teste de `secret-tool store/lookup`.
- [ ] Rodar unitários, integrações sintéticas e relatório real separado. Remover
  a prática de pular silenciosamente fornecedores deslogados e ainda declarar
  validação completa; SKIP fica explícito no relatório final.

## Saída desta frente

Status e erros previsíveis por fornecedor, login seletivo e persistência
comprovada no contrato aprovado. A aceitação depende do piloto T2: unitários,
arquivo existente e keyring saudável não provam que as contas funcionam.
