---
name: replay-logs
description: Use when the user wants to check the hookify rules against real Claude Code session logs or fuzz them - find false positives (rules firing on harmless calls), misses (secret leaks no rule blocked), slow rules or parser crashes, "mine the logs", "use our transcripts as training data", "run the fuzzer", or turn real-world rule behavior into test cases and fixes.
---

# Replay session logs and fuzz the rules

Real session logs in `~/.claude/projects/**/*.jsonl` are the training data. Every tool call in them is replayed through the rules in this repo. The fuzzers then hunt for what real use never tried. Each surprise becomes a test case and, if needed, a rule fix.

## 1. Run the replay

```bash
python3 tests/helpers/replay_transcripts.py --exclude-project claude-plugins
python3 tests/helpers/replay_transcripts.py --project claude-plugins --out /tmp/hookify-replay-dev
```

The first run is real-world use. The second is this repo's own dev sessions: they are full of deliberate attack strings written while testing rules, so treat their hits as low-signal. Other flags: `--project <text>` (repeatable), `--since YYYY-MM-DD`, `--rules <dir>` (repeatable; loads another repo's `.claude/hookify-plus` on top of this repo's rules).

Output: a summary table on stdout, then `/tmp/hookify-replay/report.md` and `report.json`, readable only by you. Common token shapes and secret-named values are redacted, but redaction is best-effort: treat the report as sensitive, never commit it, and never echo secret values from it.

The report also lists **PreToolUse timeouts**: calls where the hook ran past its 10 s limit, so no block rule ran. Each one is a speed bug; reproduce it with the `speed` fuzzer or time the rule on that command.

## 2. Read the columns

- **hits** - tool calls the rule matches today.
- **started** - matches today, did not fire when the session ran.
- **stopped** - fired when the session ran, does not match today.

Drift has innocent causes. Check these before calling something a bug:

- Warn rules with `warn_once` only fire once per agent, so warn **started** is mostly expected. Warn drift is left out for calls a block rule stopped, since PostToolUse never ran on them.
- The session may have run an older plugin version, or in a project without the plugin enabled.
- **stopped** on a block rule is either a deliberate false-positive fix or a regression. Find which with `git log -S` on the rule file.

## 3. Fuzz

```bash
python3 tests/helpers/fuzz_rules.py speed --seconds 240 --seed 1
python3 tests/helpers/fuzz_rules.py crash --from-logs --count 200000 --seed 1
python3 tests/helpers/fuzz_rules.py bypass --count 3000 --seed 1
```

They are independent; run them in parallel. Each exits 1 when it finds something. Change `--seed` between runs to explore new inputs; keep it to reproduce one.

- **speed** repeats a random unit up to 20,000 characters and times every rule on Bash commands (file-content rules are not covered). `SLOW` lines name the rule and unit; a rule still running at 15 s is cut off and reported at 15 s. A rule past the 10 s hook timeout fails open, so every block rule is skipped: treat it as a bypass. Trial count depends on wall-clock time, so a seed alone does not reproduce a run; rerun the reported unit instead.
- **crash** mutates commands from the YAML suites (plus real log commands with `--from-logs`) and runs the shell parser. `CRASH` lines give the error, the `file:line` of the deepest frame and the smallest input (redacted); a parse running past 5 s is reported as `Timeout`.
- **bypass** runs random commands for real with stub `git`/`gh` executables first on `PATH` and a canary `SECRET_TOKEN` in the environment and in `.env`. When `bwrap` works it runs inside it: read-only root, writable temp dir only, no network. Without it a warning prints and only the stubs protect you. It reports commands that leak the canary while no block rule matches: `dump` (name=value output, the serious kind), `persist` (the value reached git/gh arguments or stdin, i.e. a commit, PR or release), `print` (bare value on stdout), `error` (value only in a shell error, e.g. run as a command name - lowest priority).

## 4. Triage

Sort every finding into one bucket:

| Bucket | Means | Signal |
| --- | --- | --- |
| False positive | Rule fires on a harmless call | A block or warn **hit** a human would not want stopped |
| Miss | A leak no rule caught | A **suspect**, a block rule **stopped** on a call that still leaks, a `BYPASS`, a `SLOW` rule, or a PreToolUse timeout |
| Crash | Parser throws | A `CRASH` line |
| Fine | Working as intended | Everything else |

Suspects are a broad keyword net (`token`, `secret`, `sops`, `.env`...). Most are harmless. A real miss prints a secret value into the transcript: dumping env, decrypting, catting a key, `kubectl get secret -o yaml`, and so on.

When the report is large, fan the triage out with one subagent per rule family (env-dump family, file reads, decrypt, warn rules, suspects). Give each one the `report.json` path and ask for findings as `{rule, command, bucket, why}`.

Show the user the triage before writing code. They decide what counts as a false positive.

## 5. Fix, red-green

For each agreed finding:

1. **Red**: write the failing test in the place that fits:
   - Rule behavior: a case in the suite file for that rule family in `tests/hooks/` (`warn_rules.yaml`, `secret_file_reads.yaml`, `decrypt_rules.yaml`, ...; `review_regressions.yaml` when nothing fits).
   - `SLOW`: an entry in `INPUTS` in `tests/unit/test_rule_performance.py`.
   - `CRASH`: a case in `tests/unit/test_shell_parse.py` or `tests/unit/test_fail_closed.py`.

   Shrink the command to the smallest form that shows the problem, and swap any real value for an obvious fake. Run it and watch it fail:

   ```bash
   python3 tests/helpers/run_hookify_tests.py tests/hooks/<suite>.yaml --verbose
   ```

2. **Green**: fix the rule's `pattern` or `fallback` in `<plugin>/hookify-plus/<rule>.md`, or the engine in `hookify-plus/core/` when the bug is in parsing.
3. Run everything:

   ```bash
   for f in tests/hooks/*.yaml; do python3 tests/helpers/run_hookify_tests.py "$f" | tail -1; done
   python3 -m pytest tests/unit/ -q
   bats tests/hooks/
   ```

4. Re-run the replay and the fuzzer that found it (same `--seed`). Confirm the finding is gone and no new **started** rows appeared for that rule.

## 6. Ship

Bump the version of every plugin you touched, in both `<plugin>/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (see `CLAUDE.md`). Patch for false-positive fixes, minor when a rule now catches a new kind of leak.
