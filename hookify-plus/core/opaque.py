"""Spot commands that run code the shell parser can't see into.

When a command is opaque, command_match also checks the rule's raw-command fallback.
"""

import enum
import os
import re
import stat
from typing import Dict, List

from core.masking import _message_spec
from core.shell_parse import SHELLS, SimpleCommand, _base, _Group

STDIN_READERS = SHELLS | frozenset(["su", "xargs", "ssh", "source", "."])
PRODUCERS = frozenset(["echo", "printf"])
WRITE_OPS = (">", ">>", ">|", "&>", "&>>")
RUNNABLE_FILE = re.compile(r"(?:rc|profile|login|\.(?:ba|da|k|z)?sh|/bin/[^/]+|crontab)$")
# No segment starts with a dot, so no .. and no hidden config dirs
REPORT_FILE = re.compile(r"/dev/null$|/tmp(?:/[\w+-][\w.+-]*)+\.(?:md|txt)$")
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
# Run only the code in their own arguments, right away
ONE_SHOT_RUNNERS = frozenset(
    [
        "docker",
        "podman",
        "nerdctl",
        "kubectl",
        "oc",
        "flatpak",
        "lxc",
        "incus",
        "machinectl",
    ]
)
# Take code from a session, a script, a shell or a project file that another command may have written
STATEFUL_RUNNERS = frozenset(
    [
        "busybox",
        "toybox",
        "flatpak-spawn",
        "distrobox",
        "toolbox",
        "tmux",
        "screen",
        "byobu",
        "gdb",
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
# Put text in a file that a later command can run: a plugin, a script or a project file
FILE_WRITERS = frozenset(["tee", "cp", "mv", "ln", "install", "wget", "tar", "unzip", "rsync", "scp", "patch"])
INTERPRETERS = re.compile(r"(?:python[\d.]*|perl|ruby|node|deno|bun|php|lua[\d.]*|g?awk|mawk|pwsh|powershell)$")
SED_IN_PLACE = re.compile(r"-[A-Za-z]*i|--in-place")
CURL_OUTPUT = re.compile(r"-[A-Za-z]*[oO]|--(?:output|remote-name)")
DISCARD = re.compile(r"/dev/(?:null|stdout|stderr)$")
FD_TARGET = re.compile(r"(?:\d+-?|-)$")
PATH_ASSIGN = re.compile(r"(?<![\w$])PATH\+?=")
# Keep text in a variable that a later command reads back
DECLARERS = frozenset(["export", "declare", "typeset", "readonly", "local"])
VAR_ASSIGN_ARG = re.compile(r"[A-Za-z_]\w*(?:\[[^\]]*\])?\+?=")
SET_OPTION_ARG = re.compile(r"[-+]\w*o$")
VAR_EXPANSION = re.compile(r"\$_(?!\w)|\$\{_\W|\$\{[A-Za-z_]\w*(?:\[[^\]]*\])?:?=|BASH_REMATCH")
CODE_VAR = re.compile(r'(?:^|[\s;&|(){}\'"])(?:PS[0-4]|PROMPT_COMMAND|BASH_ENV|ENV|BASH_FUNC_\S*)\+?=')
STDIN_PATH = re.compile(r"/dev/(?:stdin|fd/\d+)$|/proc/[^/]+/fd/\d+$|[<>]\(")
EVAL_EXPANSION = re.compile(r"@[PE]\}|\[\$\(|\[`")
STDIN_OPS = ("<", "<<", "<<-", "<<<", "<&", "<>")
SHELL_ALIAS = re.compile(r"alias\.[^=\s]*[= ]?!|^!")


class Opacity(enum.IntEnum):
    """LOCAL: the hidden code sits in the one command that runs it. SHARED: another command may define it."""

    VISIBLE = 0
    LOCAL = 1
    SHARED = 2


def _name(cmd: SimpleCommand) -> str:
    return _base(cmd.name) or cmd.name


def _stdin_op(op: str) -> str:
    return op.lstrip("0123456789")


def _runs_hidden_code(cmd: SimpleCommand) -> bool:  # noqa: PLR0911  # one early return per independent check
    name = _name(cmd)
    if name in CODE_BUILTINS or name in STATEFUL_RUNNERS or "{}" in cmd.name:
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


def _writes_file(cmd: SimpleCommand) -> bool:  # noqa: PLR0911  # one early return per independent check
    name = _name(cmd)
    if name in FILE_WRITERS or INTERPRETERS.match(name):
        return True
    if name == "dd":
        return any(a.startswith("of=") for a in cmd.args)
    if name == "sed":
        return any(SED_IN_PLACE.match(a) for a in cmd.args)
    if name == "curl":
        return any(CURL_OUTPUT.match(a) for a in cmd.args)
    if name in ONE_SHOT_RUNNERS and "cp" in cmd.args:
        return True
    node = cmd
    while node is not None:
        if any(_writes_via(op, target) for op, target in node.redirects):
            return True
        node = node.parent
    return False


def _writes_via(op: str, target: str) -> bool:
    op = _stdin_op(op)
    if DISCARD.match(target) or (op == ">&" and FD_TARGET.match(target)):
        return False
    return op in (*WRITE_OPS, "<>", ">&")


def _sets_variable(cmd: SimpleCommand) -> bool:
    name = _name(cmd)
    if name in ("read", "getopts"):
        return True
    if name in DECLARERS:
        return any(VAR_ASSIGN_ARG.match(a) for a in cmd.args)
    if name == "printf":
        return any(a.startswith("-v") for a in cmd.args)
    return name == "set" and _sets_positionals(cmd.args)


def _sets_positionals(args: List[str]) -> bool:
    """`set -- a b` and `set a b` fill $1, $2 ...; `set -e` and `set -o pipefail` only flip options."""
    prev = ""
    for arg in args:
        if arg == "--" or (not arg.startswith(("-", "+")) and not SET_OPTION_ARG.fullmatch(prev)):
            return True
        prev = arg
    return False


def _group_reads_stdin(cmd: SimpleCommand) -> bool:
    parent = cmd.parent
    while parent is not None:
        if isinstance(parent, _Group) and any(_stdin_op(op) in STDIN_OPS for op, _ in parent.redirects):
            return True
        parent = parent.parent
    return False


def _writes_report(cmd: SimpleCommand) -> bool:
    name = _name(cmd)
    files = [t for op, t in cmd.redirects if op.lstrip("0123456789") in WRITE_OPS]
    if name == "tee":
        files += [a for a in cmd.args if a not in ("-a", "--append")]
    elif name != "cat":
        return False
    return all(f == "/dev/null" or (REPORT_FILE.match(f) and _plain_file(f)) for f in files)


def _plain_file(path: str) -> bool:
    """A link would carry the text to a file that runs."""
    if os.path.realpath(path) != os.path.realpath("/tmp") + path[len("/tmp") :]:
        return False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def _report_only(commands: List[SimpleCommand]) -> bool:
    """Text copied to a /tmp report and posted with gh or git never runs."""
    return all(
        _writes_report(c) or _name(c) == "cd" or _message_spec([c.name, *c.args])[0] is not None for c in commands
    )


def _unparsed_heredoc(commands: List[SimpleCommand]) -> bool:
    """Heredoc text saved to a file can run later; text a reader only prints can't."""
    if _report_only(commands):
        return False
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


def _upstream_of(commands: List[SimpleCommand]) -> Dict[int, SimpleCommand]:
    """Each command that pipes into another, keyed by the id of the command it feeds."""
    return {id(cmd.pipe_to): cmd for cmd in commands if cmd.pipe_to is not None}


def _runs_fed_code(cmd: SimpleCommand, upstream: Dict[int, SimpleCommand]) -> bool:
    """A command that runs the text another command pipes or redirects into it."""
    name = _name(cmd)
    prev = upstream.get(id(cmd))
    if name == "xargs" and (prev is not None or any(_stdin_op(op) in STDIN_OPS for op, _ in cmd.redirects)):
        return True
    if name in STDIN_READERS and prev is not None and (_name(prev) in PASS_THROUGH or id(prev) in upstream):
        return True
    # ssh with only a host runs its stdin as a remote script
    return name == "ssh" and prev is not None and len([a for a in cmd.args if not a.startswith("-")]) <= 1


def opaque(command: str, commands: List[SimpleCommand], functions=(), variables=()) -> Opacity:  # noqa: PLR0911  # one early return per independent check
    """LOCAL only when every command that hides code keeps it to itself and none writes a file or sets a variable."""
    if functions or CODE_VAR.search(command):
        return Opacity.SHARED
    # Heredoc text can be saved and run later; the parser only reads it when a shell runs it now
    if _unparsed_heredoc(commands):
        return Opacity.SHARED
    upstream = _upstream_of(commands)
    if any(
        _runs_hidden_code(c) or _group_reads_stdin(c) or _saves_code(c) or _runs_fed_code(c, upstream) for c in commands
    ):
        return Opacity.SHARED
    if not any(_name(cmd) in ONE_SHOT_RUNNERS for cmd in commands):
        return Opacity.VISIBLE
    # A written file, a new PATH or a variable lets one command run code another saved
    if variables or PATH_ASSIGN.search(command) or VAR_EXPANSION.search(command):
        return Opacity.SHARED
    if any(_writes_file(cmd) or _sets_variable(cmd) for cmd in commands):
        return Opacity.SHARED
    return Opacity.LOCAL
