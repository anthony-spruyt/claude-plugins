# security-hooks

Blocking rules for Claude Code that prevent accidental secret exposure.

## Requirements

Requires the **hookify-plus** plugin to be installed from this same marketplace. Without the engine, these rule files are inert markdown with no effect.

## Rules (23)

| Rule                        | Blocks                                       |
| --------------------------- | -------------------------------------------- |
| block-age-decrypt           | `age -d` / `age --decrypt`                   |
| block-declare-dump          | `declare -p` / `declare -x`                  |
| block-echo-s3crets          | `echo $SECRET` / `echo $TOKEN`               |
| block-echo-subshell-s3crets | `echo $(sops ...)` / `echo $(gpg ...)`       |
| block-env-dump              | `env` / `printenv` bare commands             |
| block-env-grep              | `env \| grep` / `printenv \| grep`           |
| block-export-dump           | `export -p`                                  |
| block-gpg-decrypt           | `gpg --decrypt` / `gpg -d`                   |
| block-heredoc-s3crets       | heredocs containing secret variables         |
| block-ip-in-commits         | Private IPs in git commit messages           |
| block-ip-in-github          | Private IPs in gh issue/pr commands          |
| block-openssl-decrypt       | `openssl enc -d` / `openssl smime -decrypt`  |
| block-printenv              | `printenv VAR`                               |
| block-proc-environ          | `/proc/*/environ` reads                      |
| block-read-cloud-creds      | AWS/GCP/Azure credential files               |
| block-read-encrypted-stores | SOPS/Vault/GPG stores                        |
| block-read-env-files        | `.env` / `.env.*` files                      |
| block-read-package-creds    | `.npmrc` / `.pypirc` / `.netrc`              |
| block-read-secrets-generic  | Generic secret/token/key files               |
| block-read-ssh-keys         | SSH private keys                             |
| block-set-dump              | `set` bare command                           |
| block-sops-decrypt          | `sops -d` / `sops --decrypt` / `sops exec-*` |
| block-sops-read             | `sops` file reads without encrypt flag       |

## Installation

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
# Then enable security-hooks and hookify-plus
```
