#!/usr/bin/env python3
"""Unit tests for the command_match operator and its fallback."""

import os
import shutil
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core import rule_engine
from core.config_loader import Condition, Rule, extract_frontmatter
from core.globbing import MAX_ENTRIES
from core.rule_engine import RuleEngine
from core.shell_parse import normalise

PATTERN = r"^(env|printenv)( -\S+)*$"
NASTY = r"""(?:^|[;&|]\s*)(?:env|printenv)\b(?![:#])[^'"\\|]*(?:\\.|'[^']*'|"x")*$ # not:a comment|---"""


def _yaml_single(text):
    return "'" + text.replace("'", "''") + "'"


def _frontmatter(conditions_yaml):
    content = "---\nname: r\nevent: bash\naction: block\nconditions:\n" + conditions_yaml + "---\nmsg"
    return Rule.from_dict(*extract_frontmatter(content))


class TestFrontmatter:
    def test_fallback_round_trips(self):
        rule = _frontmatter(
            "  - field: command\n"
            "    operator: command_match\n"
            f"    pattern: {_yaml_single(PATTERN)}\n"
            f"    fallback: {_yaml_single(NASTY)}\n"
        )
        cond = rule.conditions[0]
        assert cond.operator == "command_match"
        assert cond.pattern == PATTERN
        assert cond.fallback == NASTY

    def test_quoted_pattern_with_comma_on_dash_line(self):
        rule = _frontmatter(f"  - pattern: {_yaml_single('x{1,3}: y')}\n    field: command\n")
        assert rule.conditions[0].pattern == "x{1,3}: y"
        assert rule.conditions[0].field == "command"

    def test_missing_fallback_is_none(self):
        rule = _frontmatter("  - field: command\n    operator: command_match\n    pattern: x\n")
        assert rule.conditions[0].fallback is None

    def test_double_quoted_value_keeps_backslashes(self):
        rule = _frontmatter('  - field: command\n    pattern: "a\\\\s#b"\n')
        assert rule.conditions[0].pattern == "a\\\\s#b"


def _rule(pattern=PATTERN, fallback=None, mask=False, operator="command_match", field="command"):
    return Rule(
        name="r",
        enabled=True,
        event="bash",
        action="block",
        mask_data=mask,
        conditions=[Condition(field, operator, pattern, fallback)],
    )


def _matches(rule, command, tool="Bash"):
    return RuleEngine()._rule_matches(rule, {"tool_name": tool, "tool_input": {"command": command}})


class TestCleanLines:
    @pytest.mark.parametrize("cmd", ["env", "e''nv", "sudo -E e''nv", "bash -c 'printenv -0'"])
    def test_matches_after_quote_removal(self, cmd):
        assert _matches(_rule(), cmd)

    def test_clean_lines_keep_pipes(self):
        assert not _matches(_rule(), "e''nv | wc -l")
        assert _matches(_rule(pattern=r"^env( \| .*)?$"), "sudo -E e''nv | wc -l")

    @pytest.mark.parametrize("cmd", ["cd env", 'grep -E "(export|import)" f', "echo env"])
    def test_ignores_non_invocations(self, cmd):
        assert not _matches(_rule(), cmd)

    def test_regex_is_case_insensitive(self):
        assert _matches(_rule(), "ENV")


class TestUnparseable:
    CMD = "$X env"

    def test_command_really_is_unparseable(self):
        assert normalise(self.CMD) is None

    def test_uses_fallback(self):
        assert _matches(_rule(fallback=r"\$X\s+env\b"), self.CMD)
        assert not _matches(_rule(fallback=r"printenv"), self.CMD)

    def test_without_fallback_uses_pattern_on_raw_command(self):
        assert not _matches(_rule(), self.CMD)
        assert _matches(_rule(pattern=r"\benv$"), self.CMD)


class TestUnparseableSegments:
    @pytest.mark.parametrize(
        "cmd",
        [
            "n=$((1)); env",
            "n=$((1)) && sudo env -0",
            "case x in x) env;; esac",
            "n=$((1)); if true; then e''nv; fi",
            "n=$((1)); echo x | env",
        ],
    )
    def test_block_rule_matches_pattern_on_each_segment(self, cmd):
        assert normalise(cmd) is None
        assert _matches(_rule(fallback=r"nomatch"), cmd)

    def test_block_rule_reads_heredoc_ended_mid_line(self):
        cmd = "git commit -F - $(cat <<'X'\nX)z .x${T}"
        assert normalise(cmd) is None
        assert _matches(_rule(pattern=r"^git .*\$\{T\}", fallback=r"nomatch"), cmd)

    def test_warn_rule_keeps_fallback_only(self):
        rule = _rule(fallback=r"nomatch")
        rule.action = "warn"
        assert not _matches(rule, "n=$((1)); env")

    def test_segments_share_one_glob_budget(self, tmp_path, monkeypatch):
        for n in range(MAX_ENTRIES // 4):
            (tmp_path / str(n)).touch()
        monkeypatch.chdir(tmp_path)
        rule_engine.segment_lines.cache_clear()
        _, overflow = rule_engine.segment_lines("n=$((1)); " + "; ".join(["ls 7?"] * 8), str(tmp_path))
        assert overflow

    @pytest.mark.parametrize("cmd", ["n=$((1)); echo env", "case x in x) cd env;; esac"])
    def test_segments_keep_the_pattern_anchor(self, cmd):
        assert not _matches(_rule(fallback=r"nomatch"), cmd)


class TestMasking:
    def test_command_match_sees_quote_removed_command(self):
        assert _matches(_rule(pattern=r"--body env$"), 'gh pr create --body "e""nv"')

    def test_masked_rule_does_not_see_message_text(self):
        assert not _matches(_rule(pattern=r"--body env$", mask=True), 'gh pr create --body "env"')

    def test_prose_does_not_match_invocation_pattern(self):
        assert not _matches(_rule(mask=True), 'gh pr create --body "env"')

    def test_fallback_sees_masked_command(self, monkeypatch):
        # No real command is both maskable and unparseable, so force the parser to give up.
        monkeypatch.setattr(rule_engine, "normalise", lambda command: None)
        rule_engine.clean_lines.cache_clear()
        cmd = 'gh pr create --body "env"'
        assert not _matches(_rule(fallback=r"\benv\b", mask=True), cmd)
        assert _matches(_rule(fallback=r"\benv\b", mask=False), cmd)
        rule_engine.clean_lines.cache_clear()


class TestParserCrash:
    def test_exception_uses_fallback(self, monkeypatch):
        def boom(command):
            raise IndexError

        monkeypatch.setattr(rule_engine, "normalise", boom)
        rule_engine.clean_lines.cache_clear()
        try:
            assert _matches(_rule(fallback=r"\bboom\b"), "x; boom")
            assert not _matches(_rule(fallback=r"nomatch"), "x; boom")
        finally:
            rule_engine.clean_lines.cache_clear()


class TestOpaqueAlsoUsesFallback:
    FALLBACK = r"\bprintenv\b"

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo printenv | cat | sh",
            "bash < <(echo printenv)",
            "echo printenv | xargs nice",
            "xargs nice < printenv",
            "cat printenv | sh",
            "echo printenv | cut -d: -f1 | sh",
            "trap printenv EXIT",
            "busybox printenv",
            "docker exec c printenv",
            "kubectl exec p -- printenv",
            "tmux new printenv",
            "find /usr/bin -name printenv -exec {} \\;",
            "PS4='$(printenv)' bash -xc :",
            "source ./printenv.sh",
            "git -c alias.x='!f(){ eval \"$2\"; }; f' x -m printenv",
            "git -c 'alias.y=!printenv' y",
            "git config alias.z '!printenv'",
            "cat <<'EOF' | ash\nprintenv\nEOF",
            "cat > s <<'EOF'\nprintenv\nEOF\nbash s",
            "cat <<'EOF' >> ~/.bashrc\nprintenv\nEOF",
            "echo printenv > run.sh",
            "printf 'printenv' >> ~/.bashrc",
            "echo printenv | ssh host",
            "echo printenv | ssh -t host",
            "echo printenv | tee x | bash",
            "parallel ::: printenv",
            "cat > /tmp/r.md <<'EOF'\nprintenv\nEOF\nbash /tmp/r.md",
            "cat > notes.md <<'EOF'\nprintenv\nEOF",
            "cat > /tmp/../etc/r.md <<'EOF'\nprintenv\nEOF",
            "cat > /tmp/r.sh <<'EOF'\nprintenv\nEOF",
            "cat <<'EOF' | tee /tmp/r.md | sh\nprintenv\nEOF",
            "cat > /tmp/r.md <<'EOF'\nprintenv\nEOF\ncat /tmp/r.md > ~/.bashrc",
            "python3 - <<'PY'\nprintenv\nPY",
        ],
    )
    def test_opaque_command_also_checks_fallback(self, cmd):
        assert normalise(cmd) is not None
        assert _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat > /tmp/r.md <<'EOF'\nran printenv;\nEOF",
            "cat <<'EOF' > /tmp/r.txt\n(printenv)\nEOF",
            "tee /tmp/r.md >/dev/null <<'EOF'\n(printenv)\nEOF",
            "cat > /tmp/qa/r.md <<'EOF'\n(printenv)\nEOF\ngh issue comment 5 --body-file /tmp/qa/r.md",
            "cd /repo && cat > /tmp/r.md <<'EOF'\n(printenv)\nEOF",
        ],
    )
    def test_heredoc_saved_as_report_skips_fallback(self, cmd):
        assert not _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.fixture
    def tmp_dir(self):
        path = tempfile.mkdtemp(dir="/tmp")
        yield path
        shutil.rmtree(path)

    def _report(self, path):
        rule_engine.clean_lines.cache_clear()
        return f"cat > {path} <<'EOF'\nprintenv\nEOF"

    def test_regular_report_file_skips_fallback(self, tmp_dir):
        path = os.path.join(tmp_dir, "r.md")
        open(path, "w").close()
        assert not _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), self._report(path))

    def test_symlinked_report_file_checks_fallback(self, tmp_dir):
        path = os.path.join(tmp_dir, "r.md")
        os.symlink(os.path.join(tmp_dir, "rc"), path)
        assert _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), self._report(path))

    def test_report_in_symlinked_dir_checks_fallback(self, tmp_dir):
        os.mkdir(os.path.join(tmp_dir, "real"))
        os.symlink(os.path.join(tmp_dir, "real"), os.path.join(tmp_dir, "link"))
        path = os.path.join(tmp_dir, "link", "r.md")
        assert _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), self._report(path))

    def test_hard_linked_report_file_checks_fallback(self, tmp_dir):
        other = os.path.join(tmp_dir, "rc")
        open(other, "w").close()
        path = os.path.join(tmp_dir, "r.md")
        os.link(other, path)
        assert _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), self._report(path))

    @pytest.mark.parametrize(
        "cmd", ["echo printenv", "mkdir -p printenv # x", "git log printenv", "echo printenv | ssh host ls"]
    )
    def test_plain_commands_skip_fallback(self, cmd):
        assert not _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)


class TestOpaqueFallbackPerCommand:
    FALLBACK = r"kubectl\b(?=.*\ssecrets?\b)(?=.*\s-o\s*(?:json|yaml)\b)"

    def _blocks(self, cmd, fallback=FALLBACK):
        return _matches(_rule(pattern=r"^nomatch$", fallback=fallback), cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get secret demo-creds; kubectl get pods -o json",
            "kubectl get secret demo-creds && kubectl get pods -o json",
            "kubectl get secret demo-creds || kubectl get pods -o json",
            "kubectl get secret demo-creds\nkubectl get pods -o json",
        ],
    )
    def test_flags_of_another_command_do_not_match(self, cmd):
        assert not self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get secret demo -o json",
            "kubectl get secret demo -o json; kubectl get pods",
            "kubectl get pods; kubectl get secret demo -o json",
            "kubectl get pods && kubectl get secret demo -o json",
            "kubectl get secret x $(true; echo) -o json",
            "kubectl get secret x `true; echo` -o json",
            "kubectl get secret x \\\n -o json",
            "kubectl get secret x '; ' -o json",
        ],
    )
    def test_one_command_still_matches(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "n=$((1)); kubectl get secret demo; kubectl get pods -o json",
            "kubectl get secret demo # note\nkubectl get pods -o json",
            "kubectl get secret demo; kubectl get pods -o json <<EOF\nx\nEOF",
        ],
    )
    def test_unparsed_or_unsplittable_command_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            'kc() { kubectl -n x "$@"; }; kc get secret db -o yaml',
            'function kc { kubectl get secret x "$@"; }; kc -o json',
            "hash -p /usr/local/bin/kubectl k; k get secret x -o json",
            "echo 'kubectl get secret x \"$@\"' > /tmp/a.sh; bash /tmp/a.sh -o json",
            "echo 'kubectl get secret x' > /tmp/a.sh; source /tmp/a.sh -o json",
            "printf 'kubectl get secret x' > ./a.env; . ./a.env -o json",
            "f() { kubectl \"$@\"; }; export -f f; bash -c 'f get secret x -o json'",
            "alias k=kubectl; k get secret x -o json",
            "alias k='kubectl get secret'; k x -o json",
        ],
    )
    def test_code_defined_in_one_command_and_run_in_another_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    def test_function_defined_and_called_in_separate_commands_is_matched_whole(self):
        commit_ip = r"git\s+commit\b.*\b\d{1,3}(?:\.\d{1,3}){3}\b"
        assert self._blocks('f() { git commit -m "$1"; }; f "host 192.0.2.5"', commit_ip)


class TestOpaqueFallbackScope:
    """Per command only when the code a command hides cannot be set up by another command."""

    FALLBACK = r"\bfirst\b.*\bsecond\b"

    def _blocks(self, cmd):
        return _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get first; echo second",
            "kubectl exec p -- first && echo second",
            "docker exec c first || echo second",
            "podman run first\necho second",
            "oc get first; echo second",
            "kubectl get first >/dev/null 2>&1; echo second",
            "kubectl get first 2>&1 | head; echo second",
            "kubectl get first >&2; echo second",
            "kubectl get first; sed s/a/b/ f; echo second",
            "kubectl get first; curl -s -H x url; echo second",
            "kubectl get first; echo MYPATH=x PYTHONPATH=y; echo second",
        ],
    )
    def test_runner_keeping_its_code_in_one_command_is_matched_per_command(self, cmd):
        assert not self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "busybox first; echo second",
            "toybox first; echo second",
            "flatpak-spawn --host first; echo second",
            "distrobox enter c -- first; echo second",
            "toolbox run first; echo second",
        ],
    )
    def test_runner_that_can_run_a_script_file_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get first; echo x > /tmp/f; echo second",
            "kubectl get first > /tmp/f; echo second",
            "kubectl get first >> /tmp/f; echo second",
            "kubectl get first 2> /tmp/f; echo second",
            "kubectl get first &> /tmp/f; echo second",
            "kubectl get first >& /tmp/f; echo second",
            "kubectl get first >| /tmp/f; echo second",
            "kubectl get first; { echo x; } > /tmp/f; echo second",
            "kubectl get first; (echo x) >> /tmp/f; echo second",
            "kubectl get first; bash -c 'echo x > /tmp/f'; echo second",
            "kubectl get first; echo $(echo x > /tmp/f); echo second",
            "kubectl get first; echo x | tee /tmp/f; echo second",
            "kubectl get first; cp a b; echo second",
            "kubectl get first; mv a b; echo second",
            "kubectl get first; ln -s a b; echo second",
            "kubectl get first; install a b; echo second",
            "kubectl get first; dd if=a of=b; echo second",
            "kubectl get first; sed -i s/a/b/ f; echo second",
            "kubectl get first; sed -ni p f; echo second",
            "kubectl get first; sed --in-place s/a/b/ f; echo second",
            "kubectl get first; curl -o f url; echo second",
            "kubectl get first; curl -sSO url; echo second",
            "kubectl get first; curl --output f url; echo second",
            "kubectl get first; curl --remote-name url; echo second",
            "kubectl get first; wget url; echo second",
            "kubectl get first; tar xf a.tar; echo second",
            "kubectl get first; unzip a.zip; echo second",
            "kubectl get first; rsync a b; echo second",
            "kubectl get first; scp a b; echo second",
            "kubectl get first; patch f p; echo second",
            "kubectl get first; python3 -c 'print(1)'; echo second",
            "kubectl get first; perl -e 'print 1'; echo second",
            "kubectl get first; awk 'BEGIN{print 1}'; echo second",
            "kubectl cp first p:/tmp/f; echo second",
            "docker cp first c:/tmp/f; echo second",
            "oc cp first p:/tmp/f; echo second",
        ],
    )
    def test_command_that_can_write_a_file_next_to_a_runner_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "PATH=/tmp/p:$PATH kubectl get first; echo second",
            "kubectl get first; PATH=/tmp/p:$PATH echo second",
            "PATH=/tmp/p; kubectl get first; echo second",
            "PATH+=:/tmp/p; kubectl get first; echo second",
            "export PATH=/tmp/p:$PATH; kubectl get first; echo second",
            "declare -x PATH=/tmp/p; kubectl get first; echo second",
            "env PATH=/tmp/p kubectl get first; echo second",
            "kubectl get first; env 'PATH=/tmp/p' echo second",
            "kubectl get first; read PATH; echo second",
            "kubectl get first; printf -v PATH x; echo second",
        ],
    )
    def test_path_change_next_to_a_runner_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get first; c=x; echo second",
            "c=x; kubectl get first; echo second",
            "kubectl get first && c=x; echo second",
            "kubectl get first\nc=x\necho second",
            "kubectl get first; (c=x); echo second",
            "kubectl get first; { c=x; }; echo second",
            "kubectl get first; c+=x; echo second",
            "kubectl get first; a[1]=x; echo second",
            "kubectl get first; export c=x; echo second",
            "kubectl get first; declare c=x; echo second",
            "kubectl get first; local c=x; echo second",
            "kubectl get first; readonly c=x; echo second",
            "kubectl get first; read c; echo second",
            "kubectl get first; mapfile c; echo second",
            "kubectl get first; getopts a c; echo second",
            "kubectl get first; printf -v c x; echo second",
            "kubectl get first; set -- a b; echo second",
            "kubectl get first; set a b; echo second",
            "kubectl get first; set -e a b; echo second",
            "kubectl get first; : ${c:=x}; echo second",
            "kubectl get first; : ${c=x}; echo second",
            "kubectl get first; echo $_; echo second",
            "kubectl get first; echo ${_}; echo second",
            "eval 'c=x'; kubectl get first; echo second",
        ],
    )
    def test_variable_set_next_to_a_runner_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get first -l app=web; echo second",
            "kubectl get first --selector app=web; echo second",
            "docker run -e A=b first; echo second",
            "KUBECONFIG=/x kubectl get first; echo second",
            "kubectl get first; export KUBECONFIG; echo second",
            "kubectl get first; echo a=b; echo second",
            'kubectl get first; echo "a=b"; echo second',
            "kubectl get first; set -e; echo second",
            "kubectl get first; set -euo pipefail; echo second",
            "kubectl get first; set -o pipefail; echo second",
            "kubectl get first; echo _x $_x ${_x}; echo second",
        ],
    )
    def test_arguments_that_only_look_like_a_variable_set_are_matched_per_command(self, cmd):
        assert not self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "f() { first; }; f second",
            "function f { first; }; f second",
            "source first; echo second",
            ". first; echo second",
            "trap first EXIT; echo second",
            "hash first; echo second",
            "exec first; echo second",
            "PS4=first bash -xc :; echo second",
            "echo first > run.sh; echo second",
            'echo "${first@P}"; echo second',
            "git -c alias.x='!first' x; echo second",
            "find first -exec {} \\; ; echo second",
            "bash < <(echo first); echo second",
            "echo first | cat | sh; echo second",
            "echo first | xargs nice; echo second",
            "echo first | ssh host; echo second",
            "{ first; } < f; echo second",
            "tmux send-keys first; tmux send-keys second",
            "make first; echo second",
            "parallel first ::: x; echo second",
            "vim -c first; echo second",
            "kubectl get x; trap first EXIT; echo second",
            "kubectl get first; . ./x.sh; echo second",
        ],
    )
    def test_code_that_can_reach_another_command_is_matched_whole(self, cmd):
        assert self._blocks(cmd)


class TestOpaqueFallbackKeepsPipes:
    FALLBACK = r"\benv\s*\|\s*grep\b"

    def _blocks(self, cmd):
        return _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get pods; env | grep TOKEN",
            "kubectl get pods && env | grep TOKEN",
            "env | grep TOKEN; docker ps",
            "docker ps\nenv | grep TOKEN",
            "docker ps | env | grep TOKEN",
        ],
    )
    def test_pipe_inside_one_command_matches(self, cmd):
        assert self._blocks(cmd)


class TestOpaqueFallbackAcrossCommands:
    """The text a fallback needs sits in two commands, so only the whole command can match it."""

    FALLBACK = r"kubectl\s+get\b.*\bsecrets?\b.*\s-o\s*(?:json|yaml)\b"

    def _blocks(self, cmd):
        return _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "printf 'exec kubectl get \"$@\"' > /tmp/p/kubectl-g; PATH=/tmp/p:$PATH kubectl g secret db -o yaml",
            "printf 'exec kubectl get \"$@\"' > /tmp/p/oc-g; PATH=/tmp/p:$PATH oc g secret db -o yaml",
            "printf 'exec kubectl get \"$@\"' > ~/.docker/cli-plugins/docker-g; docker g secret db -o yaml",
            "printf 'exec kubectl get \"$@\"' > /tmp/p/kubectl-g; kubectl g secret db -o yaml",
            "printf 'exec kubectl get \"$@\"' | tee /tmp/p/kubectl-g; kubectl g secret db -o yaml",
            "kubectl get cm x > /tmp/p/g; sh /tmp/p/g secret db -o yaml",
            "kubectl version; echo 'kubectl get \"$@\"' > /tmp/x; sh /tmp/x secret db -o yaml",
        ],
    )
    def test_code_saved_by_one_command_and_run_by_another_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "c='kubectl get'; kubectl exec p -- sh -c \"$c secret db -o yaml\"",
            "c='kubectl get'; docker exec p sh -c \"$c secret db -o yaml\"",
            "export c='kubectl get'; docker exec p sh -c \"$c secret db -o yaml\"",
            'c=$(echo kubectl get); docker exec p sh -c "$c secret db -o yaml"',
            'set -- kubectl get; docker exec p sh -c "$* secret db -o yaml"',
            "echo 'kubectl get'; docker exec p sh -c \"$_ secret db -o yaml\"",
            ": ${c:='kubectl get'}; docker exec p sh -c \"$c secret db -o yaml\"",
            'eval "c=\'kubectl get\'"; docker exec p sh -c "$c secret db -o yaml"',
        ],
    )
    def test_code_held_in_a_variable_and_run_by_another_command_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get x; busybox sh /tmp/x secret db -o yaml",
            "kubectl get x; toybox sh /tmp/x secret db -o yaml",
        ],
    )
    def test_runner_of_script_files_is_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "for i in 1 2; do kubectl get $@; set -- secret db -o yaml; done",
            "for i in 1 2\ndo\n  kubectl get $@\n  set -- secret db -o yaml\ndone",
            "for ((i=0; i<2; i++)); do kubectl get $@; set -- secret db -o yaml; done",
            "while true; do kubectl get $@; set -- secret db -o yaml; done",
            "until false; do kubectl get $@; set -- secret db -o yaml; done",
            "select i in a b; do kubectl get $@; set -- secret db -o yaml; done",
            "until false; do kubectl exec p -- kubectl get $c; c='secret db -o yaml'; done",
            "echo a | while read i; do kubectl get $@; set -- secret db -o yaml; done",
            "! while true; do kubectl get $@; set -- secret db -o yaml; done",
            "true && for i in 1 2; do kubectl get $@; set -- secret db -o yaml; done",
            "if true; then for i in 1 2; do kubectl get $@; set -- secret db -o yaml; done; fi",
        ],
    )
    def test_commands_in_a_loop_are_matched_whole(self, cmd):
        assert self._blocks(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "kubectl get pods; echo secret db -o yaml",
            "kubectl get pods; kubectl wait --for=condition=Ready pod/x; echo secret db -o yaml",
            "kubectl get pods 2>&1 | head -n 5; echo secret db -o yaml",
        ],
    )
    def test_commands_with_no_write_path_change_or_loop_are_matched_per_command(self, cmd):
        assert not self._blocks(cmd)


class TestMaskedCleanLines:
    NAME = r"\.npmrc\b"

    def test_message_text_is_masked_in_clean_lines(self):
        rule = _rule(pattern=self.NAME, fallback=self.NAME, mask=True)
        assert not _matches(rule, 'git commit -m "docs: ignore .npmrc"')

    def test_unwrapped_message_is_masked(self):
        rule = _rule(pattern=r"^git .*\.npmrc\b", mask=True)
        assert not _matches(rule, "bash -c 'git commit -m \"docs: ignore .npmrc\"'")

    def test_real_reads_still_match(self):
        rule = _rule(pattern=self.NAME, fallback=self.NAME, mask=True)
        assert _matches(rule, "c''at ~/.np''mrc")
        assert _matches(rule, 'git commit -m "x" && cat ~/.npmrc')

    def test_unmasked_rule_sees_message_text(self):
        assert _matches(_rule(pattern=self.NAME), 'git commit -m "docs: ignore .npmrc"')


class TestPowerShell:
    def test_uses_fallback_not_bash_parser(self):
        rule = _rule(pattern=r"^cat ", fallback=r"\bGet-Content\b")
        assert _matches(rule, "Get-Content secrets.txt", tool="PowerShell")
        assert not _matches(rule, "cat x", tool="PowerShell")


class TestOtherFields:
    def test_non_command_field_is_plain_regex(self):
        rule = _rule(pattern=r"\.env$", field="file_path")
        data = {"tool_name": "Read", "tool_input": {"file_path": "/a/.env"}}
        assert RuleEngine()._rule_matches(rule, data)


def test_unknown_operator_still_false():
    assert not _matches(_rule(pattern="env", operator="no_such_op"), "env")


def test_regex_condition_without_fallback_arg():
    assert Condition("command", "regex_match", "x").fallback is None


class TestGlobOverflow:
    def _rule(self):
        return _rule(pattern="", operator="glob_overflow")

    @pytest.mark.parametrize("cmd", ["echo {1..300}", "n=$((1)); echo {1..300}", "bash -c 'echo {1..300}'"])
    def test_matches_word_past_the_limits(self, cmd):
        assert _matches(self._rule(), cmd)

    @pytest.mark.parametrize("cmd", ["echo {1..3}", "echo '{1..300}'", "n=$((1)); echo x"])
    def test_ignores_small_or_quoted_words(self, cmd):
        assert not _matches(self._rule(), cmd)

    def test_other_tools_never_match(self):
        assert not _matches(self._rule(), "echo {1..300}", tool="PowerShell")
