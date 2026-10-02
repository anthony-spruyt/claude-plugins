---
name: block-openssl-decrypt
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: '^openssl (?:enc(?!(?:(?: (?:-d|-a|-A|-base64|-in \S+|-out \S+))+(?: (?:\d*|&)[<>].*| \|.*)?$))|(?:aes|aria|bf|camellia|cast|chacha20|des|idea|rc[245]|seed|sm4)\S*)(?: (?!\|)\S+)* --?d(?: |$)|^openssl pkcs12\b|^openssl (?:smime|cms|pkeyutl|rsautl)(?: (?!\|)\S+)* --?decrypt(?: |$)'
    fallback: 'openssl\s+(enc\s+-d|pkcs12)'
action: block
mask_data: true
---

🚫 **Blocked: OpenSSL decryption/extraction**

**What was blocked:** `openssl enc -d` or `openssl pkcs12`

**Why:** These commands decrypt files or extract private keys from certificates, exposing sensitive material.

**If you need decrypted content:**

1. Ask the user: "Can you decrypt this and share the specific non-sensitive portion?"
2. For PKCS12: Ask user to extract and share only the public certificate if needed

**Safe alternatives:**

- View certificate info: `openssl x509 -in cert.pem -text -noout`
- Check certificate dates: `openssl x509 -in cert.pem -dates -noout`
- Generate keys (not extract): `openssl genrsa -out key.pem 2048`
- Create CSR: `openssl req -new -key key.pem -out cert.csr`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-openssl-decrypt" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
