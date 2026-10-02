---
name: warn-use-edit-tool
enabled: true
event: bash
tool_matcher: Bash|PowerShell
conditions:
  - field: command
    operator: command_match
    pattern: '^(?:sed|gsed)(?: (?!\|)\S+)* (?:-[a-zA-Z]*i\S*|--in-place\S*)(?: |$)|^g?awk(?: (?!\|)\S+)* (?:-i inplace|--in-place)(?: |$)|^perl(?: (?!\|)\S+)* -[a-zA-Z]*i\S*(?: |$)'
    fallback: '(^|\s|&&|\|\||;|\(|`)(sed|awk)\s+([^;&|\n]*\s)?(-[a-zA-Z]*i|--in-place)'
mask_data: true
action: warn
warn_once: true
---

⚠️ **Use the Edit tool instead**

The **Edit tool** is preferred over `sed -i` or `awk -i` for file edits:

- Better security (respects file permission controls)
- Atomic replacements with validation
- Shows clear before/after context
- Supports replace_all for bulk changes

```
Edit(file_path="/path/to/file", old_string="before", new_string="after")
Edit(file_path="/path/to/file", old_string="old", new_string="new", replace_all=true)
```
