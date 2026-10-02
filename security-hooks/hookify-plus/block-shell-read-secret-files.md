---
name: block-shell-read-secret-files
enabled: true
event: bash
action: block
mask_data: true
conditions:
  - field: command
    operator: command_match
    pattern: '^(?!(?:echo|printf) |(?:ba|z|da|k)?sh -[a-z]*c[a-z]* |eval )(?=.*?(?<!(?<!<)>)(?<!(?<!<)>\s)(?:^|(?<=[\s''"=<(:])|(?<=[\s''"=<(:]@))(?:[^\s''"`;|&<>()=:@]*/)?(?:[\w.-]*secrets?\.(?:ya?ml|json|txt)|[\w.-]*tokens?\.(?:json|txt)|[\w.-]*credentials\.json|[\w.-]*\.credentials|\.htpasswd|\.vault-token|\.env(?:\.[\w.-]+)?|\.(?:npmrc|pypirc|netrc)|id_(?:rsa|ed25519|ecdsa|dsa)|\.aws/credentials|\.kube/config|\.docker/config\.json|\.config/gh/hosts\.yml|\.(?:gnupg|password-store)/[^\s''"`;|&<>()]*|[\w.-]*\.sops\.(?:ya?ml|json))(?=$|[\s''"`;|&)>,]))'
    fallback: '(?<!(?<!<)>)(?<!(?<!<)>\s)(?:^|(?<=[\s''"=<(:])|(?<=[\s''"=<(:]@))(?:[^\s''"`;|&<>()=:@]*/)?(?:[\w.-]*secrets?\.(?:ya?ml|json|txt)|[\w.-]*tokens?\.(?:json|txt)|[\w.-]*credentials\.json|[\w.-]*\.credentials|\.htpasswd|\.vault-token|\.env(?:\.[\w.-]+)?|\.(?:npmrc|pypirc|netrc)|id_(?:rsa|ed25519|ecdsa|dsa)|\.aws/credentials|\.kube/config|\.docker/config\.json|\.config/gh/hosts\.yml|\.(?:gnupg|password-store)/[^\s''"`;|&<>()]*|[\w.-]*\.sops\.(?:ya?ml|json))(?=$|[\s''"`;|&)>,])'
  - field: command
    operator: not_regex_match
    pattern: ^\s*sops\s+(-e|--encrypt)\b
---

🚫 **Blocked: Shell command touching a secrets file**

**What was blocked:** A shell command that names a secrets file: `secrets.yaml`, `.env`, `.npmrc`, SSH private keys, cloud and kube credentials, `.sops.yaml` files, and the rest of the list the `block-read-*` rules guard for file tools.

**Why:** The `block-read-*` rules only see file tool paths. `cat`, `grep`, `head`, `python -c "open(...)"` and `< file` redirects read the same files through Bash.

**Still allowed:** appending or writing with `>>` / `>` (for example, adding a new key to `secrets.yaml` without printing it), `sops -e`, and public keys such as `id_ed25519.pub`.

**This rule matches file names, not folders.** `grep -r` or `rg` over a directory that holds a secrets file is not caught. Add a project rule for those directories.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-shell-read-secret-files" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
