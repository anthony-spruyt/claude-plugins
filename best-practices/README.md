# best-practices

Warning rules for Claude Code that nudge toward better patterns without blocking.

## Requirements

Requires the **hookify-plus** plugin to be installed from this same marketplace.
Without the engine, these rule files are inert markdown with no effect.

## Rules (6)

| Rule | Warns About |
|------|-------------|
| warn-conventional-commits | Non-conventional commit messages |
| warn-shell-wrappers | Using `./lint.sh` etc. instead of native tools |
| warn-use-edit-tool | Using `sed`/`awk` instead of Edit tool |
| warn-use-glob-tool | Using `find`/`ls` instead of Glob tool |
| warn-use-grep-tool | Using `grep` instead of Grep tool |
| warn-use-read-tool | Using `cat`/`head`/`tail` instead of Read tool |

## Installation

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
# Then enable best-practices and hookify-plus
```
