# Recuperação do uplink rootless do Podman

## Contexto

Depois de reiniciar a máquina, containers restaurados pelo
`podman-restart.service` podem continuar marcados como `running` enquanto o
namespace rootless compartilhado está sem um processo `pasta` funcional. Nesse
estado, o Squid aceita a conexão local, mas responde `503` porque não consegue
alcançar a Internet. Claude Code, Codex e Antigravity então apresentam sintomas
de timeout que parecem falhas de autenticação.

O `asb-agent doctor` já distingue esse estado de um bloqueio da allowlist e
indica a recuperação manual:

```bash
podman unshare --rootless-netns true
```

Falta executar a mesma inicialização automaticamente antes de restaurar ou
criar containers que dependem de egresso.

## Objetivo

Garantir que o namespace de rede rootless esteja inicializado:

1. antes de criar o proxy em `asb-agent up`;
2. antes de iniciar o proxy em `asb-agent resume`;
3. antes do `podman-restart.service` restaurar containers no login do usuário.

## Decisão de arquitetura

Adicionar `podman.ensure_rootless_netns()` como um invólucro explícito para:

```text
podman unshare --rootless-netns "$(command -v true)"
```

O helper deve falhar claramente se `true` não estiver disponível ou se o
Podman retornar erro. Não haverá retry oculto.

`install.podman_restart()` criará um drop-in do usuário em:

```text
~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf
```

com um `ExecStartPre` que executa o mesmo helper por linha de comando. O projeto
continua usando a unidade fornecida pela distribuição; não cria uma cópia nem
grava o caminho do checkout no systemd.

## Invariantes

- A topologia `agent -> Squid -> uplink` não muda.
- A allowlist não é ampliada.
- O projeto não mata processos `pasta` e não reinicia workspaces como parte da
  correção.
- `up` e `resume` falham visivelmente se não conseguirem preparar o uplink.
- O drop-in usa caminhos absolutos dos binários encontrados no host e é
  idempotente.
- O `doctor` continua sendo o detector; a mensagem manual existente permanece
  útil para instalações ainda não atualizadas.

## Critérios de aceitação

- O helper produz exatamente uma chamada Podman com `unshare`,
  `--rootless-netns` e o binário `true` absoluto.
- `up` chama o helper antes de criar/iniciar o proxy.
- `resume` chama o helper antes de iniciar o proxy.
- `podman_restart()` escreve o drop-in esperado, executa
  `systemctl --user daemon-reload` e habilita a unidade da distribuição.
- Os testes unitários não alteram o namespace rootless real.
- O teste manual controlado confirma que um workspace previamente afetado
  volta a alcançar um host permitido depois de `resume`.

## Fora de escopo

- Alterar a política de domínios do Squid.
- Resolver falhas específicas de MCP ou de cada fornecedor.
- Reinventar a unidade `podman-restart.service` da distribuição.
- Automatizar reboot da máquina durante a suíte de testes.
