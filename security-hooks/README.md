# security-hooks

Blocking rules for Claude Code that prevent accidental secret exposure, and `grep` and `rg` that skip secret files (the names in `shim/secret-globs`) and `.git/`.

## Requirements

The rules need the **hookify-plus** plugin from this same marketplace. Without the engine, the rule files are inert markdown with no effect. The grep and rg part below works on its own.

## Rules (32)

| Rule                          | Blocks                                                  |
| ----------------------------- | ------------------------------------------------------- |
| block-age-decrypt             | `age -d` / `age --decrypt`                              |
| block-declare-dump            | `declare -p` / `declare -x`                             |
| block-echo-s3crets            | `echo $SECRET` / `echo $TOKEN`                          |
| block-echo-subshell-s3crets   | `echo $(sops ...)` / `echo $(gpg ...)`                  |
| block-env-dump                | `env` / `printenv` bare commands                        |
| block-env-grep                | `env \| grep` / `printenv \| grep`                      |
| block-export-dump             | `export -p`                                             |
| block-gh-auth-token           | `gh auth token` / `gh auth status --show-token`         |
| block-gpg-decrypt             | `gpg --decrypt` / `gpg -d`                              |
| block-huge-glob               | Globs and braces past 256 words or 20k entries          |
| block-heredoc-s3crets         | heredocs containing secret variables                    |
| block-indirect-s3crets        | `${!x}`, `${x@P}` and namerefs to secret variables      |
| block-ip-in-commits           | Private IPs in git commit messages                      |
| block-ip-in-github            | Private IPs in gh issue/pr commands                     |
| block-message-s3crets         | Secret variables in commit, issue and PR messages       |
| block-openssl-decrypt         | `openssl enc -d` / `openssl smime -decrypt`             |
| block-powershell-env-dump     | `Get-ChildItem Env:` / `GetEnvironmentVariables()`      |
| block-powershell-secret-vars  | `$env:` reads of secret-looking names                   |
| block-printenv                | `printenv VAR`                                          |
| block-proc-environ            | `cat /proc/*/environ` / `ps e`                          |
| block-read-cloud-creds        | AWS/GCP/Azure credential files                          |
| block-read-encrypted-stores   | SOPS/Vault/GPG stores                                   |
| block-read-env-files          | `.env` / `.env.*` files                                 |
| block-read-package-creds      | `.npmrc` / `.pypirc` / `.netrc` / `.git-credentials`    |
| block-read-proc-environ       | Opening `/proc/*/environ` with a file tool              |
| block-read-secrets-generic    | Generic secret/token/key files                          |
| block-read-ssh-keys           | SSH private keys                                        |
| block-s3cret-as-command       | A secret variable run as a command: `eval $TOKEN`       |
| block-set-dump                | `set` bare command                                      |
| block-shell-read-secret-files | Shell reads of the files the `block-read-*` rules guard |
| block-sops-decrypt            | `sops -d` / `sops --decrypt` / `sops exec-*`            |
| block-sops-read               | `sops` file reads without encrypt flag                  |

## grep and rg skip secret files

In Claude sessions, `grep` skips secret files (the names in `shim/secret-globs`) and `.git/`, and so does `rg` when it searches a folder, whatever `-g`, `--glob` or `--iglob` you pass it. Everything else about them is as usual.

- `shim/secret-globs` is the one list: a glob per line, and a glob ending in `/` is a directory. It holds `*.sops.*`, `.env`, `.env.*`, `.envrc`, secret and token files, key and certificate files, cloud, package-manager, GitHub CLI and Terraform Cloud credential files, Terraform state, Talos config and `.git/`.
- A SessionStart hook (every source, `compact` included) copies a `grep` wrapper, an `rg` wrapper (only when a real rg is on PATH), the helper both source and the list to `${CLAUDE_PLUGIN_DATA}/shim`, which survives plugin updates, writes an rg config from the list next to them, then adds them to the Bash tool's shell through `CLAUDE_ENV_FILE`.
- The wrapper runs the real grep with an `--exclude=` (file) or `--exclude-dir=` (directory) for each entry, placed after your options so that a later `--include` does not undo it. If it cannot tell where the options end (an option it does not know, together with `--` or `POSIXLY_CORRECT`), it exits 2 with an error instead of guessing. It also exits 2 when it cannot read the list.
- The rg wrapper runs the real rg with a `--glob=!<glob>` for each entry, and the same with `**/<dir>/**` for a directory, so a directory you name on its command line is skipped too. They come after your options and before a `--` that ends them, so your own `-g`, `--glob` or `--iglob` does not undo them. rg applies every `--iglob` after every `--glob`, so when you pass `--iglob` the wrapper adds an `--iglob=!` for each of them too; those match names case-insensitively, and so do the skips in that call. It exits 2 when it cannot read the list.
- The rg config has the `--glob=!<glob>` lines, and an rg started by its full path gets the same `--glob=!` lines. If you set `RIPGREP_CONFIG_PATH` yourself, copy the lines of `${CLAUDE_PLUGIN_DATA}/shim/ripgreprc` into that file.
- It needs GNU grep. Without one the hook installs nothing.
- Only Claude sessions are affected. Your own terminal is unchanged.
- Set `SECURITY_HOOKS_GREP_SHIM=0` to turn all of it off.

## Installation

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
# Then enable security-hooks and hookify-plus
```
