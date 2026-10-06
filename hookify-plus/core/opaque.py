"""Spot commands that run code the shell parser can't see into.

When a command is opaque, command_match also checks the rule's raw-command fallback.
"""

import re
from typing import List

from core.shell_parse import SHELLS, SimpleCommand, _base, _Group

STDIN_READERS = SHELLS | frozenset(["su", "xargs", "ssh", "source", "."])
PRODUCERS = frozenset(["echo", "printf"])
WRITE_OPS = (">", ">>", ">|", "&>", "&>>")
RUNNABLE_FILE = re.compile(r"(?:rc|profile|login|\.(?:ba|da|k|z)?sh|/bin/[^/]+|crontab)$")
PASS_THROUGH = frozenset(
    [
        "cat",
        "tee",
        "head",
        "tail",
        "sed",
        "awk",
        "tr",
        "sort",
        "uniq",
        "base64",
        "xxd",
        "rev",
        "gzip",
        "zcat",
        "gunzip",
        "openssl",
    ]
)
CODE_BUILTINS = frozenset(
    [
        "source",
        ".",
        "trap",
        "let",
        "hash",
        "complete",
        "compgen",
        "fc",
        "history",
        "enable",
        "mapfile",
        "readarray",
        "exec",
    ]
)
RUNNERS = frozenset(
    [
        "busybox",
        "toybox",
        "tmux",
        "screen",
        "byobu",
        "gdb",
        "docker",
        "podman",
        "nerdctl",
        "kubectl",
        "oc",
        "flatpak",
        "flatpak-spawn",
        "distrobox",
        "toolbox",
        "lxc",
        "incus",
        "machinectl",
        "vagrant",
        "vim",
        "nvim",
        "vi",
        "ex",
        "less",
        "more",
        "parallel",
        "expect",
        "make",
    ]
)
CODE_VAR = re.compile(r'(?:^|[\s;&|(){}\'"])(?:PS[0-4]|PROMPT_COMMAND|BASH_ENV|ENV|BASH_FUNC_\S*)\+?=')
STDIN_PATH = re.compile(r"/dev/(?:stdin|fd/\d+)$|/proc/[^/]+/fd/\d+$|[<>]\(")
EVAL_EXPANSION = re.compile(r"@[PE]\}|\[\$\(|\[`")
STDIN_OPS = ("<", "<<", "<<-", "<<<", "<&", "<>")
SHELL_ALIAS = re.compile(r"alias\.[^=\s]*[= ]?!|^!")


def _name(cmd: SimpleCommand) -> str:
    return _base(cmd.name) or cmd.name


def _stdin_op(op: str) -> str:
    return op.lstrip("0123456789")


def _runs_hidden_code(cmd: SimpleCommand) -> bool:
    name = _name(cmd)
    if name in CODE_BUILTINS or name in RUNNERS or "{}" in cmd.name:
        return True
    words = cmd.args + [target for _, target in cmd.redirects]
    if any(EVAL_EXPANSION.search(w) for w in words):
        return True
    if name == "git" and any(SHELL_ALIAS.search(a) for a in cmd.args):
        return True
    if name == "find":
        return any(
            cmd.args[i] in ("-exec", "-execdir", "-ok", "-okdir") and "{}" in cmd.args[i + 1]
            for i in range(len(cmd.args) - 1)
        )
    if name in STDIN_READERS:
        if any(STDIN_PATH.match(a) for a in cmd.args):
            return True
        for op, target in cmd.redirects:
            fd = op[: len(op) - len(_stdin_op(op))]
            if _stdin_op(op) in STDIN_OPS and (fd not in ("", "0") or op.endswith("&") or STDIN_PATH.match(target)):
                return True
    return False


def _saves_code(cmd: SimpleCommand) -> bool:
    """echo/printf text written to a script or rc file runs later."""
    return _name(cmd) in PRODUCERS and any(
        op.lstrip("0123456789") in WRITE_OPS and op[:1] in "1>&" and RUNNABLE_FILE.search(target)
        for op, target in cmd.redirects
    )


def _group_reads_stdin(cmd: SimpleCommand) -> bool:
    parent = cmd.parent
    while parent is not None:
        if isinstance(parent, _Group) and any(_stdin_op(op) in STDIN_OPS for op, _ in parent.redirects):
            return True
        parent = parent.parent
    return False


def _unparsed_heredoc(commands: List[SimpleCommand]) -> bool:
    """Heredoc text saved to a file can run later; text a reader only prints can't."""
    fed = {c.feed for c in commands if c.feed is not None}
    return any(
        _stdin_op(op) in ("<<", "<<-") and (op, target) not in fed and _saves(c)
        for c in commands
        for op, target in c.redirects
    )


def _saves(cmd: SimpleCommand) -> bool:
    stage = cmd
    while stage is not None:
        if _name(stage) != "cat" or any(op.lstrip("0123456789") in WRITE_OPS for op, _ in stage.redirects):
            return True
        stage = stage.pipe_to
    return False


def opaque(command: str, commands: List[SimpleCommand], functions=()) -> bool:
    if functions or CODE_VAR.search(command):
        return True
    # Heredoc text can be saved and run later; the parser only reads it when a shell runs it now
    if _unparsed_heredoc(commands):
        return True
    upstream = {}
    for cmd in commands:
        if cmd.pipe_to is not None:
            upstream[id(cmd.pipe_to)] = cmd
    for cmd in commands:
        if _runs_hidden_code(cmd) or _group_reads_stdin(cmd) or _saves_code(cmd):
            return True
        if _name(cmd) == "xargs" and (
            id(cmd) in upstream or any(_stdin_op(op) in STDIN_OPS for op, _ in cmd.redirects)
        ):
            return True
        prev = upstream.get(id(cmd))
        if _name(cmd) in STDIN_READERS and prev is not None and (_name(prev) in PASS_THROUGH or id(prev) in upstream):
            return True
        # ssh with only a host runs its stdin as a remote script
        if _name(cmd) == "ssh" and prev is not None and len([a for a in cmd.args if not a.startswith("-")]) <= 1:
            return True
    return False
