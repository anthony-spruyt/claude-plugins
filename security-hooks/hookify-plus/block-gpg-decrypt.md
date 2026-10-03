---
name: block-gpg-decrypt
enabled: true
event: bash
# Second branch: with no command option gpg runs its default action, which decrypts
conditions:
  - field: command
    operator: command_match
    pattern: '^gpg2?(?: (?!\|)\S+)* (?:-[a-zA-Z]*d[a-zA-Z]*|--decr[a-z-]*)(?: |$)|^gpg2?(?!(?: (?!\|)\S+)*? (?:-[a-zA-Z]*[sbeckKh][a-zA-Z]*(?: |$)|--(?:sign|clear|clearsign|detach|encrypt|symmetric|store|verify|list|check|fingerprint|show-keys|gen|generate|full|quick|delete|edit|lsign|export|import|send|recv|receive|search|refresh|fetch|locate|update|fix-trustdb|rebuild|card|change|passwd|print|server|tofu|dearmor|enarmor|desig|gpgconf|dump|help|version|warranty|apropos)(?:-[a-z-]*)?(?<!-options)(?<!-filter)(?<!-to)(?:=| |$)))(?: (?!\|)\S+)*(?: \||$)'
    fallback: 'gpg\s+(-d|--decrypt)'
action: block
mask_data: true
---

🚫 **Blocked: GPG decryption**

**What was blocked:** `gpg -d` or `gpg --decrypt`

**Why:** GPG-encrypted files typically contain sensitive secrets, keys, or credentials.

**If you need the decrypted content:**

1. Ask the user: "Can you decrypt this file and share the specific portion you'd like me to work with?"
2. User can decrypt manually: `gpg -d filename.gpg`
3. User shares only the non-sensitive parts needed

**Safe alternatives:**

- List recipients: `gpg --list-packets file.gpg`
- Verify signature: `gpg --verify file.sig`
- Encrypt (not decrypt): `gpg -e -r recipient file`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-gpg-decrypt" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
