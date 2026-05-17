# claude-plugins

Plugin monorepo for Claude Code by [@anthony-spruyt](https://github.com/anthony-spruyt).

## Plugins

| Plugin | Description |
|--------|-------------|
| [hookify-plus](./hookify-plus/) | Rule engine with convention-based discovery |
| [security-hooks](./security-hooks/) | 23 blocking rules preventing secret exposure |
| [best-practices](./best-practices/) | 6 warning rules for better tool usage |

## Installation

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
```

Then enable desired plugins in your Claude Code settings.

## How It Works

The **hookify-plus** engine scans sibling plugins for `hookify-plus/` directories containing rule files (`.md` with YAML frontmatter). Install the engine plus any combination of rule plugins.

## License

MIT
