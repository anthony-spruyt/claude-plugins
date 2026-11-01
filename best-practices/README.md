# best-practices

Rules for Claude Code that nudge toward better patterns and block commands that stall on a permission prompt.

## Requirements

Requires the **hookify-plus** plugin to be installed from this same marketplace. Without the engine, these rule files are inert markdown with no effect.

## Rules (5)

| Rule                      | Action | Covers                                                                                             |
| ------------------------- | ------ | -------------------------------------------------------------------------------------------------- |
| block-rm-unchecked-target | Block  | `rm`/`rmdir` of `*` or `dir/*`, `"$VAR"/`, a bare `$(...)`, `/`, `~`, `.` or a top-level directory |
| warn-conventional-commits | Warn   | Non-conventional commit messages                                                                   |
| warn-shell-wrappers       | Warn   | `sh -c` / `bash -c` / `eval` instead of dedicated tools                                            |
| warn-use-edit-tool        | Warn   | Using `sed`/`awk` instead of Edit tool                                                             |
| warn-use-read-tool        | Warn   | Using `cat`/`head`/`tail` instead of Read tool                                                     |

## Installation

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
# Then enable best-practices and hookify-plus
```
