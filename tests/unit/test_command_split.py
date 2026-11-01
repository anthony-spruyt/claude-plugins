#!/usr/bin/env python3
"""Unit tests for splitting a command into its top-level commands."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.command_split import split_commands


class TestSeparators:
    @pytest.mark.parametrize(
        "cmd",
        ["a; b", "a;b", "a && b", "a&&b", "a || b", "a||b", "a\nb", "a ;\n b"],
    )
    def test_splits_on_list_operators_and_newlines(self, cmd):
        assert split_commands(cmd) == ("a", "b")

    def test_keeps_pipes_and_background_together(self):
        assert split_commands("a | b; c & d |& e") == ("a | b", "c & d |& e")

    def test_drops_empty_pieces(self):
        assert split_commands("a;; b;\n\n; ") == ("a", "b")

    def test_no_separator_is_one_piece(self):
        assert split_commands("kubectl get pods") == ("kubectl get pods",)


class TestQuotesAndEscapes:
    @pytest.mark.parametrize(
        "cmd",
        [
            "a 'x; y' b",
            'a "x; y" b',
            "a 'x && y' b",
            'a "x\ny" b',
            'a "it\'s; ok" b',
            "a 'say \"hi\"; ok' b",
            'a "x \\" ; y" b',
            "a x\\;y b",
            "a x\\&&y b",
        ],
    )
    def test_does_not_split_inside_quotes_or_after_a_backslash(self, cmd):
        assert split_commands(cmd) == (cmd,)

    def test_single_quote_ends_at_the_next_quote_whatever_precedes_it(self):
        assert split_commands("a 'x\\'; b") == ("a 'x\\'", "b")

    def test_joins_backslash_newline(self):
        assert split_commands("a \\\n  b; c") == ("a   b", "c")
        assert split_commands("kub\\\nectl x") == ("kubectl x",)
        assert split_commands('a "x\\\ny" b') == ('a "xy" b',)

    def test_backslash_newline_stays_inside_single_quotes(self):
        assert split_commands("a 'x\\\ny'") == ("a 'x\\\ny'",)

    @pytest.mark.parametrize("cmd", ["a 'x; b", 'a "x; b', 'a "x\\"; b', "a 'x\"; b"])
    def test_unclosed_quote_gives_up(self, cmd):
        assert split_commands(cmd) is None


class TestNesting:
    @pytest.mark.parametrize(
        "cmd",
        [
            "a $(b; c) d",
            "a $(b && c) d",
            "a (b; c) d",
            "(a; b)",
            "a $((1; 2)) b",
            "a $(b $(c; d); e) f",
            "a $(b 'x)' ; c) d",
            'a $(b "x)" ; c) d',
            "a `b; c` d",
            "a { b; c; } d",
            "a ${b:-c;d} e",
            'a "x $(b; c) y" d',
            'a "x `b; c` y" d',
            'a "x `b "c; d"` y" e',
            'a "x ${b:-c;d} y" d',
            'a "$(b "c; d")" e',
            "a <(b; c) d",
            "a >(b; c) d",
            "a $(b\nc) d",
            "a (b\nc) d",
        ],
    )
    def test_does_not_split_inside_groups_and_substitutions(self, cmd):
        assert split_commands(cmd) == (cmd,)

    def test_splits_around_a_group(self):
        assert split_commands("(a; b); c && { d; e; }") == ("(a; b)", "c", "{ d; e; }")

    def test_splits_after_a_quoted_substitution(self):
        assert split_commands('a "$(b)"; c') == ('a "$(b)"', "c")

    @pytest.mark.parametrize(
        "cmd",
        ["a $(b; c", "a (b; c", "a { b; c", "a ${b; c", "a `b; c", 'a "$(b; c"', "a $(b 'x); c)"],
    )
    def test_unclosed_group_gives_up(self, cmd):
        assert split_commands(cmd) is None

    @pytest.mark.parametrize("cmd", ["a b); c", "a b}; c", "a (b}; c", "a {b); c", "a $(b}); c"])
    def test_unmatched_closer_gives_up(self, cmd):
        assert split_commands(cmd) is None


class TestGivesUp:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat <<EOF; a\nb\nEOF",
            "cat <<'EOF'\nx\nEOF\na",
            "cat <<-EOF\nx\nEOF",
            "a <<< b; c",
            "a $'\\';'' b",
            "a # it's; b",
            "a; # note\nb",
            "a (# x\n) b",
            "case x in a) b;; esac; c",
            "case x in (a) b;; (c) d;; esac",
            "a $(case x in a) b;; esac); c",
            "a ${b:-'c;d'}; e",
            'a ${b:-"c;d"}; e',
            "a ${b:-`c;d`}; e",
            "a ${b:-$(c;d)}; e",
            "a ${b:-${c};d}; e",
            "# x\na",
            "a\n# x\nb",
            "a\t# x\nb",
            "a;# x\nb",
            "a&# x\nb",
            "a|# x\nb",
            "(a)# x\nb",
            "a ># x\nb",
            "a <# x\nb",
            "a `# x\n` b",
            "cat <\\\n<EOF\nx\nEOF",
            "a $\\\n'x;y'; b",
            "ca\\\nse x in (a) b;; esac",
            "for i in 1 2; do a; b; done",
            "for ((i=0; i<2; i++)); do a; done",
            "while a; do b; c; done",
            "until a; do b; c; done",
            "select i in x y; do a; b; done",
            "a && for i in 1; do b; done",
            "a | while read i; do b; done",
            "! while a; do b; done",
            "if a; then for i in 1; do b; done; fi",
            "{ for i in 1; do a; done; }; b",
            "fo\\\nr i in 1; do a; done",
        ],
    )
    def test_gives_up_on_what_it_cannot_read_with_certainty(self, cmd):
        assert split_commands(cmd) is None

    @pytest.mark.parametrize("cmd", ["a $#; b", "a x#y; b", "a 'x #'; b", 'a "x #"; b', "a ${#b}; c", "a \\#b; c"])
    def test_a_hash_inside_a_word_is_not_a_comment(self, cmd):
        assert split_commands(cmd) is not None

    @pytest.mark.parametrize("cmd", ["showcase a; b", "a --case-file x; b", "a case_x; b"])
    def test_other_words_containing_case_split(self, cmd):
        assert split_commands(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "a --for=x; b",
            "a --while x; b",
            "a format; b",
            "a forward; b",
            "a for_each; b",
            "a for-each; b",
            "a unlike; b",
            "a selected; b",
            "a until_x; b",
        ],
    )
    def test_other_words_containing_a_loop_keyword_split(self, cmd):
        assert split_commands(cmd) is not None
