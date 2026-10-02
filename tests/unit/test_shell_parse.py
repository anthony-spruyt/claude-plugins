#!/usr/bin/env python3
"""Unit tests for shell_parse: finding every simple command bash would run."""

import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.shell_parse import MAX_LENGTH, normalise, parse_commands
from tests.unit.test_rule_performance import INPUTS


def pairs(command):
    result = parse_commands(command)
    assert result is not None, command
    return [(c.name, c.args) for c in result]


def names(command):
    return [name for name, _ in pairs(command)]


class TestQuoteRemoval:
    @pytest.mark.parametrize("command", [
        "env", "e''nv", '"env"', "\\env", "'env'", '"e"nv', "$'\\x65nv'", "$'\\145nv'",
        '$"env"', "e\\\nnv",
    ])
    def test_env_spellings(self, command):
        assert names(command) == ["env"]

    def test_backslash_inside_word(self):
        assert names("s\\et") == ["set"]

    def test_quoted_declare(self):
        assert pairs("'declare' -p") == [("declare", ["-p"])]

    def test_split_export(self):
        assert pairs("ex''port -p") == [("export", ["-p"])]

    def test_double_quote_backslash_only_escapes_specials(self):
        assert pairs('echo "a\\b\\$c\\"d"') == [("echo", ['a\\b$c"d'])]

    def test_variables_keep_source_text(self):
        assert pairs('echo "$HOME" ${USER} $1') == [("echo", ["$HOME", "${USER}", "$1"])]


class TestArgumentsAreNotCommands:
    @pytest.mark.parametrize("command", [
        "cd env", "ls env", "mkdir -p env # venv", "python3 -m venv env",
        'gh pr create --body "env and set are blocked"', 'git commit -m "export -p"',
        "echo if then env", "printf '%s\\n' env",
    ])
    def test_no_env_family_command(self, command):
        assert not {"env", "set", "export"} & set(names(command))

    def test_grep_pattern(self):
        assert pairs('grep -E "(export|import)" file') == [("grep", ["-E", "(export|import)", "file"])]

    def test_comment_is_dropped(self):
        assert pairs("mkdir -p env # venv; env") == [("mkdir", ["-p", "env"])]

    def test_hash_inside_word_is_not_comment(self):
        assert pairs("echo a#b") == [("echo", ["a#b"])]


class TestSeparators:
    def test_all_list_separators(self):
        assert names("a; b && c || d & e\nf") == ["a", "b", "c", "d", "e", "f"]

    def test_pipeline(self):
        env, wc = parse_commands("env | wc -l")
        assert (env.name, env.pipe_to) == ("env", wc)
        assert (wc.name, wc.args, wc.pipe_to) == ("wc", ["-l"], None)

    def test_pipe_with_stderr(self):
        env, cat = parse_commands("env |& cat")
        assert env.pipe_to is cat

    def test_newline_after_operator(self):
        assert names("env &&\n  set |\n  cat") == ["env", "set", "cat"]

    def test_line_continuation(self):
        assert pairs("echo a \\\n  b") == [("echo", ["a", "b"])]


class TestRedirects:
    def test_redirect_is_not_an_argument(self):
        (echo,) = parse_commands("echo export > f")
        assert (echo.name, echo.args, echo.redirects) == ("echo", ["export"], [(">", "f")])

    def test_dev_null(self):
        (cmd,) = parse_commands("printenv HOME >/dev/null")
        assert (cmd.args, cmd.redirects) == (["HOME"], [(">", "/dev/null")])

    def test_operators_anywhere(self):
        cmd = parse_commands("2>&1 env >>log <in a &>all b >|x 3<>y 4>&- c")[0]
        assert cmd.name == "env"
        assert cmd.args == ["a", "b", "c"]
        assert cmd.redirects == [("2>&", "1"), (">>", "log"), ("<", "in"), ("&>", "all"),
                                 (">|", "x"), ("3<>", "y"), ("4>&", "-")]

    def test_here_string(self):
        (cmd,) = parse_commands("cat <<<'env'")
        assert (cmd.name, cmd.args, cmd.redirects) == ("cat", [], [("<<<", "env")])

    def test_heredoc_body_is_consumed(self):
        assert names("cat <<EOF\nenv\nset\nEOF\necho done") == ["cat", "echo"]

    @pytest.mark.parametrize("command", [
        "cat <<'EOF'\nenv\nEOF", 'cat <<"EOF"\nenv\nEOF', "cat <<-EOF\n\tenv\n\tEOF",
        "cat << EOF\nenv\nEOF\n",
    ])
    def test_heredoc_forms(self, command):
        assert names(command) == ["cat"]

    def test_several_heredocs_on_one_line(self):
        assert names("cat <<A; cat <<'B'\nenv\nA\nset\nB\necho ok") == ["cat", "cat", "echo"]

    def test_heredoc_redirect_recorded(self):
        (cmd,) = parse_commands("cat <<-'EOF'\nx\nEOF")
        assert cmd.redirects == [("<<-", "EOF")]


class TestAssignments:
    def test_leading_assignment(self):
        assert pairs("FOO=1 env") == [("env", [])]

    def test_assignment_only_is_not_a_command(self):
        assert pairs("A=1 B=2") == []

    def test_array_assignment(self):
        assert names("a=(1 2 3); env") == ["env"]

    def test_assignment_substitution_runs(self):
        assert names("X=$(env)") == ["env"]

    def test_later_assignment_is_an_argument(self):
        assert pairs("echo A=1") == [("echo", ["A=1"])]


class TestKeywords:
    @pytest.mark.parametrize("command", [
        "if true; then env; fi",
        "if false\nthen :\nelif true; then :; else env; fi",
        "while false; do env; done",
        "until true; do env; done",
        "for i in 1 2; do env; done",
        "for i\ndo env\ndone",
        "(env)",
        "{ env; }",
        "f() { env; }",
        "function f { env; }",
        "! env",
        "time -p env",
        "(env) > f",
    ])
    def test_env_inside_construct(self, command):
        assert "env" in names(command)

    def test_for_loop_declare(self):
        assert pairs("for i in 1; do declare -p; done") == [("declare", ["-p"])]

    def test_keyword_words_in_for_list_are_arguments(self):
        assert names("for i in env set; do echo $i; done") == ["echo"]

    def test_conditional_expression(self):
        assert names('[[ -n "$(env)" && $x == y ]] && echo ok') == ["env", "echo"]

    def test_test_bracket_command(self):
        assert pairs("[ -f x ]") == [("[", ["-f", "x", "]"])]

    @pytest.mark.parametrize("command", [
        "case $x in a) env;; esac", "((x++))", "select x in a; do env; done", "coproc env",
    ])
    def test_unsupported_constructs(self, command):
        assert parse_commands(command) is None


class TestNestedCode:
    @pytest.mark.parametrize("command, inner", [
        ("bash -c 'env'", "env"),
        ('sh -c "set"', "set"),
        ("bash -lc 'env'", "env"),
        ("zsh -xc env", "env"),
        ("dash -e -c 'printenv'", "printenv"),
        ("ksh -o pipefail -c 'export -p'", "export"),
        ("eval env", "env"),
        ("eval 'export' -p", "export"),
        ("echo $(env)", "env"),
        ("echo `printenv`", "printenv"),
        ('echo "$(env)"', "env"),
        ('echo "`env`"', "env"),
        ("cat <(env)", "env"),
        ("tee >(env)", "env"),
        ("diff < <(env) f", "env"),
        ("echo ${X:-$(env)}", "env"),
        ("echo $(echo $(env))", "env"),
        ("echo `echo \\`env\\``", "env"),
    ])
    def test_inner_command_found(self, command, inner):
        assert inner in names(command)

    def test_order_outer_then_inner(self):
        assert pairs("bash -c 'env | wc'") == [("bash", ["-c", "env | wc"]), ("env", []), ("wc", [])]

    def test_shell_script_file_is_not_code(self):
        assert names("bash script.sh env") == ["bash"]

    def test_unquoted_heredoc_substitution_runs(self):
        assert names("cat <<EOF\n$(env)\nEOF") == ["cat", "env"]

    def test_quoted_heredoc_substitution_is_text(self):
        assert names("cat <<'EOF'\n$(env)\nEOF") == ["cat"]

    def test_heredoc_inside_substitution(self):
        assert names('git commit -F - <<<"$(cat <<\'EOF\'\nenv\nEOF\n)"') == ["git", "cat"]

    def test_heredoc_ambiguous_end_inside_substitution(self):
        assert parse_commands("x=$(cat <<'EOF'\nEOF)\nenv\nEOF\n)") is None

    def test_single_quoted_dollar_is_literal(self):
        assert names("echo '$(env)'") == ["echo"]


class TestWrappers:
    @pytest.mark.parametrize("command, expected", [
        ("sudo -E env", ["sudo", "env"]),
        ("sudo -u root -- env", ["sudo", "env"]),
        ("sudo FOO=1 env", ["sudo", "env"]),
        ("doas -u root env", ["doas", "env"]),
        ("nohup env", ["nohup", "env"]),
        ("nice -n 5 env", ["nice", "env"]),
        ("nice -10 env", ["nice", "env"]),
        ("'time' -p env", ["time", "env"]),
        ("command env", ["command", "env"]),
        ("command -p env", ["command", "env"]),
        ("command -v env", ["command"]),
        ("builtin export -p", ["builtin", "export"]),
        ("exec -a x env", ["exec", "env"]),
        ("timeout 5 env", ["timeout", "env"]),
        ("timeout -s KILL --preserve-status 5s env", ["timeout", "env"]),
        ("stdbuf -oL -e 0 env", ["stdbuf", "env"]),
        ("xargs -0 -n1 env", ["xargs", "env"]),
        ("xargs -I{} sh -c 'env {}'", ["xargs", "sh", "env"]),
        ("watch env", ["watch", "env"]),
        ("watch -n 1 'env | grep X'", ["watch", "env", "grep"]),
        ("watch -x env", ["watch", "env"]),
        ("ssh host env", ["ssh", "env"]),
        ("ssh -p 22 -o X=y host 'env | grep X'", ["ssh", "env", "grep"]),
        ("ssh host", ["ssh"]),
        ("chroot /mnt env", ["chroot", "env"]),
        ("unbuffer env", ["unbuffer", "env"]),
        ("script -qc 'env' /dev/null", ["script", "env"]),
        ("su -c 'env' root", ["su", "env"]),
        ("su - root -c env", ["su", "env"]),
        ("flock /tmp/l env", ["flock", "env"]),
        ("flock -n /tmp/l -c 'env'", ["flock", "env"]),
        ("sudo nohup nice env", ["sudo", "nohup", "nice", "env"]),
        ("/usr/bin/sudo env", ["/usr/bin/sudo", "env"]),
    ])
    def test_wrapped_command(self, command, expected):
        assert names(command) == expected

    def test_env_args_are_the_command_it_runs(self):
        assert pairs("env FOO=1 printenv") == [("env", ["printenv"]), ("printenv", [])]

    def test_env_options(self):
        assert names("env -i -0 -u X --unset=Y -C /tmp --chdir=/ - A=1 printenv") == [
            "env", "printenv"]

    def test_env_split_string(self):
        assert pairs("env -S 'FOO=1 printenv HOME' -0") == [
            ("env", ["printenv", "HOME", "-0"]), ("printenv", ["HOME", "-0"])]

    def test_sudo_wrapped_args(self):
        assert pairs("sudo -E env") == [("sudo", ["-E", "env"]), ("env", [])]


class TestMoreWrappers:
    @pytest.mark.parametrize("command, expected", [
        ("ionice -c3 env", ["ionice", "env"]),
        ("ionice -c 2 -n 7 env", ["ionice", "env"]),
        ("ionice -t -c3 env", ["ionice", "env"]),
        ("taskset -c 0 env", ["taskset", "env"]),
        ("taskset 0x1 env", ["taskset", "env"]),
        ("taskset --cpu-list 0-3 env", ["taskset", "env"]),
        ("taskset -a 3 env", ["taskset", "env"]),
        ("setsid env", ["setsid", "env"]),
        ("setsid -f -w env", ["setsid", "env"]),
        ("strace -o /dev/null env", ["strace", "env"]),
        ("strace -f -e trace=open -s 100 env", ["strace", "env"]),
        ("strace -ff -tt -u root env", ["strace", "env"]),
        ("ltrace -o /tmp/x -f env", ["ltrace", "env"]),
        ("unshare env", ["unshare", "env"]),
        ("unshare -m -u --map-root-user env", ["unshare", "env"]),
        ("unshare -S 0 -G 0 env", ["unshare", "env"]),
        ("nsenter -t 1 -m -u -i -n -p env", ["nsenter", "env"]),
        ("nsenter --target=1 -a env", ["nsenter", "env"]),
        ("chrt -f 10 env", ["chrt", "env"]),
        ("chrt --rr 5 env", ["chrt", "env"]),
        ("prlimit --nofile=1024 env", ["prlimit", "env"]),
        ("setpriv --reuid=1000 --init-groups env", ["setpriv", "env"]),
        ("runuser -u nobody env", ["runuser", "env"]),
        ("runuser -l nobody -c 'env'", ["runuser", "env"]),
        ("firejail --noprofile --net=none env", ["firejail", "env"]),
        ("systemd-run --user -p MemoryMax=1G --unit=x env", ["systemd-run", "env"]),
        ("systemd-run --scope -q env", ["systemd-run", "env"]),
        ("catchsegv env", ["catchsegv", "env"]),
        ("valgrind --leak-check=full -q env", ["valgrind", "env"]),
        ("torsocks env", ["torsocks", "env"]),
        ("proxychains -q -f /etc/p.conf env", ["proxychains", "env"]),
        ("proxychains4 env", ["proxychains4", "env"]),
        ("tsocks env", ["tsocks", "env"]),
        ("faketime '2020-01-01' env", ["faketime", "env"]),
        ("faketime -f '+1d' env", ["faketime", "env"]),
        ("fakeroot env", ["fakeroot", "env"]),
        ("fakeroot -- env", ["fakeroot", "env"]),
        ("numactl --cpunodebind=0 -m 0 env", ["numactl", "env"]),
        ("numactl -N 0 env", ["numactl", "env"]),
        ("cgexec -g cpu:grp env", ["cgexec", "env"]),
        ("sg wheel 'env'", ["sg", "env"]),
        ("sg wheel -c 'env'", ["sg", "env"]),
        ("pkexec --user root env", ["pkexec", "env"]),
        ("/usr/bin/time -f %e -o /tmp/t env", ["/usr/bin/time", "env"]),
        ("/usr/bin/time -v env", ["/usr/bin/time", "env"]),
        ("/bin/nice env", ["/bin/nice", "env"]),
        ("/usr/sbin/chroot /mnt env", ["/usr/sbin/chroot", "env"]),
    ])
    def test_wrapped_command(self, command, expected):
        assert names(command) == expected

    def test_normalise_gives_wrapped_line(self):
        assert normalise("ionice -c3 env") == ["ionice -c3 env", "env"]

    @pytest.mark.parametrize("command", [
        "strace -j env",
        "unshare --frobnicate x env",
        "valgrind --tool memcheck env",
        "firejail --profile x env",
        "chrt env",
        "taskset env",
        "nsenter -Q 1 env",
    ])
    def test_unknown_options_fail_closed(self, command):
        assert parse_commands(command) is None


class TestFindExec:
    @pytest.mark.parametrize("command, expected", [
        ("find /tmp -exec env \\;", ["find /tmp -exec env ';'", "env"]),
        ("find . -name x -execdir printenv HOME {} + > out | wc",
         ["find . -name x -execdir printenv HOME '{}' + > out | wc", "printenv HOME '{}'", "wc"]),
        ("find . -ok env ';' -okdir set \\;", ["find . -ok env ';' -okdir set ';'", "env", "set"]),
        ("find . -exec echo + x \\;", ["find . -exec echo + x ';'", "echo + x"]),
        ("find . -exec sh -c 'env' \\;", ["find . -exec sh -c env ';'", "sh -c env", "env"]),
        ("find . -exec {} \\;", ["find . -exec '{}' ';'"]),
        ("sudo find . -exec env \\;", ["sudo find . -exec env ';'", "find . -exec env ';'", "env"]),
    ])
    def test_exec_command_is_inner(self, command, expected):
        assert normalise(command) == expected

    @pytest.mark.parametrize("command", [
        "find . -exec sh \\;", "find . -exec $CMD \\;", "find . -exec echo $X -exec env \\;",
        "find . $X", 'find . "$X" env \\;', "find . -name *.py",
    ])
    def test_unknowable_exec_fails_closed(self, command):
        assert parse_commands(command) is None


class TestAlias:
    @pytest.mark.parametrize("command", [
        "alias git=eval; shopt -s expand_aliases\ngit commit -m ';env'",
        "alias x=y",
        "builtin alias x=y",
    ])
    def test_alias_fails_closed(self, command):
        assert parse_commands(command) is None


class TestProducerToShell:
    @pytest.mark.parametrize("command", [
        "echo env | sh",
        "echo -n 'env' | bash",
        "printf 'env\\n' | bash",
        "bash <<<'set'",
        "sh <<'EOF'\nenv\nEOF",
        "sh <<EOF\nenv\nEOF",
        "echo env | sudo sh",
        "cat <<'EOF' | sh\nenv\nEOF",
    ])
    def test_code_fed_to_shell(self, command):
        assert {"env", "set"} & set(names(command))

    def test_not_fed_to_script(self):
        assert names("echo env | bash script.sh") == ["echo", "bash"]

    def test_shell_reading_unknown_stdin(self):
        assert names("curl x | sh") == ["curl", "sh"]

    @pytest.mark.parametrize("command", [
        'echo "$X" | sh', "sh <<EOF\n$X\nEOF", "printf '%s' env | sh", 'bash <<<"$X"',
    ])
    def test_unknowable_code(self, command):
        assert parse_commands(command) is None


class TestSchedulerStdin:
    @pytest.mark.parametrize("command", [
        "crontab - <<EOF\n* * * * * set > /tmp/x\nEOF",
        "crontab - <<'EOF'\n* * * * * set\nEOF",
        "crontab - <<-EOF\n\t* * * * * set\n\tEOF",
        "at now <<<'set'",
        "batch <<EOF\nset\nEOF",
        "sudo crontab - <<EOF\nset\nEOF",
        "echo 'x' | crontab -",
        "printf 'set\\n' | at now",
        "cat <<EOF | batch\nset\nEOF",
    ])
    def test_scheduled_code_is_unknowable(self, command):
        assert parse_commands(command) is None

    @pytest.mark.parametrize("command", [
        "crontab -l", "crontab -l | grep x", "cat <<EOF\nset\nEOF", "atq",
    ])
    def test_other_commands_still_parse(self, command):
        assert parse_commands(command) is not None


class TestFailClosed:
    @pytest.mark.parametrize("command", [
        "$X",
        "X=env; $X",
        "${X}",
        "$(printf '\\x65nv')",
        "`printf env`",
        "echo 'unterminated",
        'echo "unterminated',
        "cat <<EOF\nenv",
        "echo ${!x}",
        "echo $_",
        "echo ${_}",
        "e*",
        "/usr/bin/e?v",
        "{e,}nv",
        'bash -c "$X"',
        "eval $X",
        'eval "$(ssh-agent -s)"',
        "sudo $OPT env",
        "watch $CMD",
        "ssh host \"$CMD\"",
        "echo $(" * 9 + ")" * 9,
        "bash -c " + "'bash -c \"" * 5,
        "env )",
        "env &&",
        "env | ",
        "timeout " * 20 + "5 env",
        "x" * (MAX_LENGTH + 1),
    ])
    def test_returns_none(self, command):
        assert parse_commands(command) is None

    def test_depth_eight_is_allowed(self):
        command = "echo " + "$(echo " * 6 + "$(env" + ")" * 7
        assert "env" in names(command)


class TestEnvSummary:
    """A bare `env` line means env printed the environment: no command left to run."""

    @pytest.mark.parametrize("cmd", [
        "env", "env -0", "env -u HOME", "env --unset=HOME", "env -C /", "env --chdir /",
        "env --debug", "env --ignore-signal=INT", "env --nul", "env FOO=1", "env -S '-u X -0'",
        "env -S'A=1'", "env -- ", "env -a x", "env -f vars.txt", "env --file=vars.txt",
    ])
    def test_dump_renders_bare(self, cmd):
        assert normalise(cmd)[0] == "env"

    @pytest.mark.parametrize("cmd, first", [
        ("env | wc -l", "env | wc -l"),
        ("env > f", "env > f"),
        ("env -0 | cut -d= -f1", "env | cut -d= -f1"),
    ])
    def test_dump_keeps_redirects_and_pipes(self, cmd, first):
        assert normalise(cmd)[0] == first

    @pytest.mark.parametrize("cmd", ["env -i", "env --ignore-environment", "env -i FOO=1",
                                     "env --help", "env --version", "env --ignore-env"])
    def test_clean_env_renders_as_env_i(self, cmd):
        assert normalise(cmd)[0] == "env -i"

    def test_find_exec_env_is_summarised(self):
        assert normalise("find . -execdir /usr/bin/env -0 ';'")[1] == "env"

    def test_env_running_a_command_keeps_the_command(self):
        assert normalise("env FOO=1 python3 x.py") == ["env python3 x.py", "python3 x.py"]


class TestHeredocBodies:
    """Expanding heredoc bodies render after `<<` so rules can see the $VARs that expand."""

    def test_unquoted_body_is_shown(self):
        assert normalise("cat <<EOF\nhi $USER\nEOF") == ["cat << 'hi $USER\n'"]

    @pytest.mark.parametrize("cmd", ["cat <<'EOF'\nhi $USER\nEOF", 'cat <<"EOF"\nhi $USER\nEOF',
                                     "cat <<\\EOF\nhi $USER\nEOF", "cat <<E'O'F\nhi $USER\nEOF"])
    def test_quoted_delimiter_shows_only_the_delimiter(self, cmd):
        assert normalise(cmd) == ["cat << EOF"]

    def test_escaped_dollar_is_unsure(self):
        assert normalise("cat <<EOF\nhi \\$USER\nEOF") is None

    def test_expanding_here_string_keeps_its_variable(self):
        assert normalise('cat <<< "x $USER"') == ["cat <<< 'x $USER'"]

    def test_literal_here_string_escapes_its_dollar(self):
        assert normalise("cat <<< 'x $USER'") == ["cat <<< 'x \\$USER'"]

    def test_second_heredoc(self):
        line = normalise("cat <<'A' <<B\nx $X\nA\ny $Y\nB")[0]
        assert "$Y" in line
        assert "$X" not in line



class TestLiteralDollar:
    """A `$` that bash will not expand renders as `\\$` so rules can tell it from an expansion."""

    @pytest.mark.parametrize("cmd", ["echo '$X'", "echo \\$X", 'echo "\\$X"', "echo $'\\x24X'"])
    def test_literal_dollar_is_escaped(self, cmd):
        assert normalise(cmd) == ["echo '\\$X'"]

    def test_expansion_is_bare(self):
        assert normalise("echo $X") == ["echo '$X'"]

    def test_mixed_word(self):
        assert normalise("echo \"$A\"'$B'") == ["echo '$A\\$B'"]

    def test_literal_backslash_before_expansion(self):
        assert normalise("echo \\\\$X") == ["echo '\\\\$X'"]

    def test_literal_backtick_is_escaped(self):
        assert normalise("echo 'a `b`'") == ["echo 'a \\`b\\`'"]

    def test_here_string_escapes_its_backslash(self):
        assert normalise("cat <<< 'a\\$X'") == ["cat <<< 'a\\\\\\$X'"]

    def test_redirect_only_substitution_reads_like_cat(self):
        assert "cat < f" in normalise('echo "$(< f)"')

    def test_shell_c_code_still_expands(self):
        assert "echo '$X'" in normalise("bash -c 'echo $X'")



class TestAsciiNames:
    """Bash names and fd numbers are ASCII; Unicode letters and digits are literal text."""

    def test_unicode_letter_is_not_a_variable(self):
        assert normalise("echo $\u00e9") == ["echo '\\$\u00e9'"]

    def test_unicode_letter_is_not_an_assignment(self):
        assert normalise("\u00e9=1 ls") == ["\u00e9=1 ls"]

    def test_unicode_digit_is_not_an_fd(self):
        assert normalise("cat \u0663<f") == ["cat \u0663 < f"]

    def test_underscore_then_unicode_is_last_argument(self):
        assert normalise("echo $_\u00e9") is None


class TestNormalise:
    def test_none_when_unparsable(self):
        assert normalise("$X") is None

    def test_plain(self):
        assert normalise("env") == ["env"]

    def test_wrapper_inherits_pipe(self):
        assert normalise("sudo -E e''nv | wc -l") == ["sudo -E env | wc -l", "env | wc -l", "wc -l"]

    def test_shell_code_inherits_redirect(self):
        assert normalise("bash -c 'env' > f") == ["bash -c env > f", "env > f"]

    def test_substitution_does_not_inherit(self):
        assert normalise("echo $(env) | wc") == ["echo '$(env)' | wc", "env", "wc"]

    def test_redirect_format(self):
        assert normalise("printenv HOME >/dev/null 2>&1") == ["printenv HOME > /dev/null 2>& 1"]

    def test_args_quoted_only_when_needed(self):
        assert normalise("""grep -E "(export|import)" 'a b' x.txt""") == [
            "grep -E '(export|import)' 'a b' x.txt"]

    def test_empty_arg_is_quoted(self):
        assert normalise("echo ''") == ["echo ''"]

    def test_inner_pipeline_inherits_at_tail(self):
        assert normalise("bash -c 'env | grep X' > f") == [
            "bash -c 'env | grep X' > f", "env | grep X > f", "grep X > f"]

    def test_compound_context(self):
        assert normalise("(env; set) | wc") == ["env | wc", "set | wc", "wc"]

    def test_here_string_code_drops_feeding_redirect(self):
        assert normalise("bash <<<'env' > f") == ["bash <<< env > f", "env > f"]

    def test_producer_code_inherits_consumer(self):
        assert normalise("echo env | sh | wc") == ["echo env | sh | wc", "sh | wc", "wc", "env | wc"]

    def test_heredoc_redirect_rendered_with_delimiter(self):
        assert normalise("cat <<'EOF'\nenv\nEOF") == ["cat << EOF"]

    @pytest.mark.parametrize("command, expected", [
        ("/usr/bin/printenv HOME", ["printenv HOME"]),
        ("./set", ["set"]),
        ("/bin/env | grep KEY", ["env | grep KEY", "grep KEY"]),
        ("sudo /usr/bin/printenv", ["sudo /usr/bin/printenv", "printenv"]),
        ("echo x | /bin/sh", ["echo x | sh", "sh", "x"]),
    ])
    def test_command_name_is_basename(self, command, expected):
        assert normalise(command) == expected


ADVERSARIAL = dict(INPUTS, **{
    "many-pipes": "a|" * 9999 + "a",
    "many-evals": "eval " * 4000,
    "many-bash-c": "bash -c " * 2500,
    "many-backticks": "`" * 20000,
    "many-escaped-backticks": "echo `" + "\\`" * 9000,
    "many-ansi": "$'\\x" * 5000,
    "many-semicolons": "env;" * 5000,
    "many-wrappers": "sudo nohup " * 1800,
    "many-brace-groups": "{ " * 10000,
    "many-ifs": "if true; then " * 1400,
    "many-params": "${a:-" * 4000,
    "many-heredocs-bodies": "cat <<A\nA\n" * 1800,
    "many-dquote-subst": 'echo "$(echo "' * 1400,
})


# Linear parsing takes ~40ms on 20k chars here and ~75ms on CI; quadratic takes seconds
BUDGET = 0.2


@pytest.mark.parametrize("name", ADVERSARIAL)
def test_parse_commands_is_fast(name):
    command = ADVERSARIAL[name]
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        parse_commands(command)
        timings.append(time.perf_counter() - start)
    assert min(timings) < BUDGET, f"{name} took {min(timings) * 1000:.0f}ms"


@pytest.mark.parametrize("name", ADVERSARIAL)
def test_parse_is_fast(name):
    command = ADVERSARIAL[name]
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        normalise(command)
        timings.append(time.perf_counter() - start)
    assert min(timings) < BUDGET, f"{name} took {min(timings) * 1000:.0f}ms"


PE = "print" + "e" + "nv"
E = "e" + "nv"


class TestReviewFixes:
    @pytest.mark.parametrize("command", [
        "find . -exec \\; ; " + E, "find . -ok \\; ; " + E, "find . -execdir \\; ; " + E,
        "find . -exec >x \\; ; " + E, "find . -ok<< x \\;",
    ])
    def test_empty_find_action_fails_closed(self, command):
        assert normalise(command) is None

    @pytest.mark.parametrize("command, expected", [
        ("time -- " + PE, [PE]),
        ("time -p -- " + PE, [PE]),
        ("eval -- " + PE, ["eval -- " + PE, PE]),
    ])
    def test_double_dash_is_not_the_command(self, command, expected):
        assert normalise(command) == expected

    @pytest.mark.parametrize("command", ["! -- " + PE, "find . -exec -- " + PE + " \\;", "./-x"])
    def test_line_never_starts_with_dash(self, command):
        assert normalise(command) is None

    @pytest.mark.parametrize("command", [
        "env -a x " + PE, "env --argv0 x " + PE, "env --argv0=x " + PE,
        "sudo -R /d " + PE, "sudo --chroot /d " + PE, "sudo -a pam " + PE,
        "sudo -c cls " + PE, "sudo --login-class cls " + PE, "sudo --auth-type pam " + PE,
        "sudo -hhost " + PE, "doas -a style " + PE,
    ])
    def test_value_options(self, command):
        assert normalise(command)[-1] == PE

    def test_process_substitution_in_conditional(self):
        assert PE + " >& 2" in normalise("[[ -n <(" + PE + " >&2) ]]")

    @pytest.mark.parametrize("command", [
        "cat <<EOF\nx\\\nEOF\ncat <<'Y'\nEOF\n" + PE + "\nY",
        "cat <<EOF\nhi\nEO\\\nF\n" + PE + "\nEOF",
        "cat <<-EOF\n\tx\\\nEOF\n" + PE,
    ])
    def test_heredoc_line_continuation_fails_closed(self, command):
        assert normalise(command) is None

    def test_heredoc_even_backslashes_still_parse(self):
        assert normalise("cat <<EOF\nx\\\\\nEOF\n" + PE) == ["cat << 'x\\\n'", PE]

    def test_quoted_heredoc_backslash_is_literal(self):
        assert normalise("cat <<'EOF'\nx\\\nEOF\n" + PE) == ["cat << EOF", PE]


@pytest.mark.parametrize("command", [
    "find " + "{.." * 6000,
    *["find " + "{.." * n + "; " + PE for n in (10, 100, 1000, 3000, 6000)],
])
def test_brace_glob_check_is_linear(command):
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        normalise(command)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.05, f"took {min(timings) * 1000:.0f}ms"


def test_eval_skips_only_one_double_dash():
    assert normalise("eval -- -- " + PE) is None
