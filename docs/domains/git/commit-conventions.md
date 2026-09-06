# Git Commit Conventions

This document is the canonical source of truth for agents authoring and curating local Git commits.

## 1. Authority and Branching Rules

1. Inspect the active branch before taking action (`git status`, `git branch --show-current`).
2. On a dedicated working branch, author the local commit upon completing a verified task with versionable changes.
3. On the `main` or `master` branch, **never** create a commit without explicit human authorization in the active session context.
4. Do not create branches, rewrite historical commits (`git commit --amend`, `git rebase`), or execute `git push` without explicit authorization.

## 2. Safe Scope Selection (Surgical Changes)

1. Inspect `git status` and diffs before selecting and staging files (`git add`).
2. Stage strictly the changes directly related to the completed task.
3. Never mix unrelated edits or foreign work into a shared working directory.
4. If it is impossible to separate the scope safely, stop and explain why; never produce ambiguous or partial commits.

## 3. Prerequisites & Empirical Verification

1. Run relevant automated checks and log verified outputs (build, lint, test).
2. Evidence must precede assertions of completion.

## 4. Commit Message Format

1. Select the Gitmoji directly from the table below.
2. Use the **literal emoji character** (`✨`), never the colon shortcode (`:sparkles:`).
3. Commit directly without asking for message confirmation once authorization is granted.
4. Title format:
   ```text
   <gitmoji> <verb in imperative/infinitive> <outcome>: <context>
   ```
   Example:
   ```text
   ✨ add subagent and skill infrastructure: agent architecture
   ```
5. Never claim features, tests, or guarantees unsupported by the diff.

### Gitmoji Selection

| Gitmoji | When to Use |
| :--- | :--- |
| `📝` | Any documentation-only change (`.md` docs, specs, plans, domain packs, agent instructions). |
| `✨` | New capability or feature in executable code. |
| `🐛` | Bugfix. |
| `♻️` | Refactoring without observable behavioral change. |
| `🔧` | Tooling, configuration, infrastructure scripts, `.gitignore`. |
| `🔐` | Auth, credentials, permissions, and security. |
| `✅` | Adding or correcting automated tests. |
| `🚚` | Moving or renaming files and directories. |
| `⬆️` | Upgrading dependencies or toolchain baselines. |
| `🕸️` | Graphify knowledge graph synchronization. |

### Commit Body (Mandatory)

The body is **mandatory** for every commit touching code,
configuration, infrastructure, or structural documentation.

**Two-Commit Knowledge Graph Workflow & Exception:**
The dedicated commit carrying strictly `graphify-out/**` with title
`🕸️ sync knowledge graph` is the **sole exception** where the mandatory
structured body is omitted. In this two-commit workflow:
1. First commit: Product code, infrastructure, tests, or documentation
   changes with the standard mandatory structured body.
2. Second commit: Strictly `graphify-out/**` artifacts with title
   `🕸️ sync knowledge graph` and no body.

Use the structured sections in this order:

| Section | When to Use |
| :--- | :--- |
| `### ✅ New features` | When new capabilities are added. |
| `### 💡 Architecture improvements` | Structural changes, boundaries, design decisions. |
| `### 🧼 Best practices & validations` | Code hygiene, tests, healthchecks, linting. |
| `### 🔐 Security & Access Control` | Auth, roles, permissions, secrets. |
| `### 🚀 Outcome` | **Always present.** Summary of repository state and next steps. |

Wrap all lines at **76 columns**.

## 5. Attribution

It is strictly forbidden to append `Co-authored-by` or similar co-authorship trailers to commits.
