#!/usr/bin/env python3
"""Find every simple command bash would run, after quote removal.

Fail closed: anything the parser cannot read the way bash would returns None,
so callers fall back to matching the raw command string.
"""

import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_LENGTH = 20000
MAX_DEPTH = 8
# Rendered pipelines repeat their tails, so output can grow quadratically in input.
OUTPUT_LIMIT = 16 * MAX_LENGTH

EXPANDED, GLOB, QUOTED = 1, 2, 4

PLAIN = re.compile(r'[^ \t\n;&|()<>\'"\\$`*?\[{}]+')
BLANK = re.compile(r'(?:[ \t]+|\\\n)+')
DQ_PLAIN = re.compile(r'[^"\\$`]+')
PARAM_PLAIN = re.compile(r'[^}\'"\\$`]+')
VARIABLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-]')
UNDERSCORE = re.compile(r'_(?![A-Za-z0-9_])')
BACKTICK = re.compile(r'`((?:[^`\\]|\\.)*)`', re.S)
BACKTICK_ESCAPE = re.compile(r'\\([\\`$])')
BACKTICK_DQ_ESCAPE = re.compile(r'\\([\\`$"])')
ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
ANSI_ESCAPE = re.compile(r'\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|.)', re.S)
ANSI_SIMPLE = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r',
               't': '\t', 'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}
REDIRECT = re.compile(r'([0-9]*)(<<<|<<-|<<|<>|<&|>&|>>|>\||<|>)|&>>|&>')
PROC_SUB = re.compile(r'[<>]\(')
DELIM = re.compile(r'(?=[ \t\n;&|()<>]|$)')
RESERVED = re.compile(r'(?:[a-z]+|[{}!]|\[\[)(?=[ \t\n;&|()<>]|$)')
TERMINATORS = frozenset(['then', 'elif', 'else', 'fi', 'do', 'done', 'esac', '}'])
UNSUPPORTED = frozenset(['case', 'select', 'coproc'])
KEYWORDS = TERMINATORS | UNSUPPORTED | frozenset(['!', '{', '[[', 'if', 'while', 'until', 'for',
                                                  'function', 'time'])
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
FUNCNAME = re.compile(r'[^ \t\n;&|()<>\'"\\$`]+(?:[ \t]*\([ \t]*\))?')
FUNCDEF = re.compile(r'[^ \t\n;&|()<>\'"\\$`]+[ \t]*\([ \t]*\)')
ASSIGN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]$`\s;&|()<>]*\])?\+?=')


@dataclass
class SimpleCommand:
    name: str
    args: List[str] = field(default_factory=list)
    redirects: List[Tuple[str, str]] = field(default_factory=list)
    pipe_to: Optional['SimpleCommand'] = None
    # Set when this command is part of the whole program of `parent`, so it inherits the
    # parent's redirects and pipe_to, except `feed`: the parent redirect that carried the code.
    parent: Optional['SimpleCommand'] = field(default=None, repr=False, compare=False)
    feed: Optional[Tuple[str, str]] = field(default=None, repr=False, compare=False)


class _Group(SimpleCommand):
    """Context of a compound command: its body inherits these redirects and pipe_to."""


class FunctionDef(str):
    """Name of a function defined in the command; kept out of the returned commands."""


class _Unsure(Exception):
    pass


class _Expansion(str):
    """Word piece bash expands, as opposed to literal text."""


LITERAL = re.compile(r'[\\$`]')


class Word(str):
    """Word text; `shown` escapes literal `\\`, `$` and backticks so rules can tell them from an expansion."""

    shown = ''


def _word_text(buf) -> str:
    text = ''.join(buf)
    if '$' not in text and '`' not in text:
        return text
    word = Word(text)
    word.shown = ''.join(p if isinstance(p, _Expansion) else LITERAL.sub(r'\\\g<0>', p) for p in buf)
    return word


PLAIN_CODE = re.compile(r'[ \t]*[A-Za-z0-9_./:@%+,-][A-Za-z0-9_./:@%+, \t-]*$')
LEADING_TABS = re.compile(r'^\t+', re.M)
SHELLS = frozenset(['bash', 'sh', 'zsh', 'dash', 'ksh'])
ECHO_OPTS = re.compile(r'-[neE]+$')
STDIN_REDIRECT = re.compile(r'0?(?:<|<<|<<-|<<<|<>|<&)$')
ENV_ASSIGN = re.compile(r'[^=$`]+=')
SPLIT_UNSURE = re.compile(r'[\'"\\$#{`]')
GLOB_CHARS = re.compile(r'[*?\[]')
# name: (short options taking a value, long options taking a value, short options whose
# value can only be attached, operands before the command)
WRAPPERS = {
    'sudo': ('ugCDprtTUaRc', ('user', 'group', 'close-from', 'chdir', 'host', 'prompt', 'role',
                              'type', 'command-timeout', 'other-user', 'auth-type', 'chroot',
                              'login-class'), 'h', 0),
    'doas': ('uCa', (), '', 0),
    'nohup': ('', (), '', 0),
    'nice': ('n', ('adjustment',), '', 0),
    'time': ('fo', ('format', 'output'), '', 0),
    'command': ('', (), '', 0),
    'builtin': ('', (), '', 0),
    'exec': ('a', (), '', 0),
    'timeout': ('sk', ('signal', 'kill-after'), '', 1),
    'stdbuf': ('ioe', ('input', 'output', 'error'), '', 0),
    'xargs': ('adEILnPs', ('arg-file', 'delimiter', 'max-args', 'max-procs', 'max-chars',
                           'process-slot-var'), 'eil', 0),
    'watch': ('nq', ('interval', 'equexit'), '', 0),
    'ssh': ('BbcDEeFIiJLlmOopQRSWw', (), '', 1),
    'chroot': ('', ('userspec', 'groups'), '', 1),
    'unbuffer': ('', (), '', 0),
    'script': ('cEIOBTm', ('command', 'log-in', 'log-out', 'log-io', 'log-timing',
                           'logging-format', 'echo'), 't', 0),
    'su': ('csgGw', ('command', 'session-command', 'shell', 'group', 'supp-group',
                     'whitelist-environment'), '', 0),
    'flock': ('wE', ('timeout', 'conflict-exit-code'), '', 1),
}
# Like WRAPPERS plus (flag-only short, flag-only long, operand patterns, options that mean no
# command runs); any option not listed might take a value, so it fails closed.
NUM = re.compile(r'[0-9]+$')
CPUS = re.compile(r'[0-9a-fA-Fx,:-]+$')
ANY = re.compile(r'')
STRICT = {
    'ionice': ('cnpPu', ('class', 'classdata', 'pid', 'pgid', 'uid'), '', 't', ('ignore',), (),
               {'p', 'P', 'u', 'pid', 'pgid', 'uid'}),
    'taskset': ('', (), '', 'acp', ('all-tasks', 'cpu-list', 'pid'), (CPUS,), {'p', 'pid'}),
    'setsid': ('', (), '', 'cfw', ('ctty', 'fork', 'wait'), (), set()),
    'strace': ('oepsuabEIOPSXU', ('output', 'trace', 'attach', 'string-limit', 'user', 'columns',
                                  'signal', 'status', 'env', 'path', 'summary-sort-by'),
               '', 'AcCdDfFiknqrtTvwxyYzZ', ('follow-forks', 'output-separately', 'quiet',
                                              'summary-only', 'summary', 'verbose', 'decode-fds',
                                              'decode-pids', 'no-abbrev', 'seccomp-bpf'), (),
               {'p', 'attach'}),
    'ltrace': ('aAeFlnopsuwxD', ('output', 'align', 'library', 'indent'), '', 'bcCfiLrStT',
               ('demangle',), (), {'p'}),
    'unshare': ('SGRw', ('setuid', 'setgid', 'root', 'wd', 'propagation', 'setgroups',
                         'load-interp', 'monotonic', 'boottime', 'map-user', 'map-group',
                         'map-users', 'map-groups'),
                'muinpUCT', 'frc', ('mount', 'uts', 'ipc', 'net', 'pid', 'user', 'cgroup', 'time',
                                    'fork', 'map-root-user', 'map-current-user', 'map-auto',
                                    'mount-proc', 'kill-child', 'keep-caps'), (), set()),
    'nsenter': ('tSG', ('target', 'setuid', 'setgid'), 'muinpUCTrwW', 'aeFZ',
                ('all', 'mount', 'uts', 'ipc', 'net', 'pid', 'user', 'cgroup', 'time', 'root',
                 'wd', 'preserve-credentials', 'keep-caps', 'follow-context'), (), set()),
    'chrt': ('TPD', ('sched-runtime', 'sched-period', 'sched-deadline'), '', 'frobidepamRv',
             ('fifo', 'rr', 'other', 'batch', 'idle', 'deadline', 'ext', 'all-tasks', 'pid', 'max',
              'reset-on-fork', 'verbose'), (NUM,), {'p', 'pid', 'm', 'max'}),
    'prlimit': ('po', ('pid', 'output'), 'cdefilmnqrstuvxy', '',
                ('noheadings', 'raw', 'verbose', 'core', 'data', 'nice', 'fsize', 'sigpending',
                 'memlock', 'rss', 'nofile', 'msgqueue', 'rtprio', 'stack', 'cpu', 'nproc', 'as',
                 'locks', 'rttime'), (), {'p', 'pid'}),
    'setpriv': ('', ('ruid', 'euid', 'rgid', 'egid', 'reuid', 'regid', 'groups', 'inh-caps',
                     'ambient-caps', 'bounding-set', 'securebits', 'pdeathsig', 'selinux-label',
                     'apparmor-profile', 'landlock-access', 'landlock-rule', 'seccomp-filter',
                     'ptracer'),
                '', 'd', ('clear-groups', 'keep-groups', 'init-groups', 'no-new-privs',
                          'reset-env', 'dump', 'list-caps'), (), {'d', 'dump', 'list-caps'}),
    'firejail': ('', (), '', '', ('noprofile', 'quiet', 'private', 'seccomp', 'nonewprivs',
                                  'nosound', 'novideo', 'noroot', 'caps', 'nogroups', 'no3d',
                                  'nodvd', 'notv', 'nou2f', 'private-dev', 'private-tmp',
                                  'machine-id'), (), set()),
    'systemd-run': ('puEMHC', ('property', 'unit', 'description', 'slice', 'setenv', 'machine',
                               'host', 'uid', 'gid', 'nice', 'working-directory', 'service-type',
                               'on-active', 'on-boot', 'on-startup', 'on-unit-active',
                               'on-unit-inactive', 'on-calendar', 'timer-property',
                               'path-property', 'socket-property', 'capsule'),
                    '', 'tPqrGdS', ('user', 'system', 'scope', 'pty', 'pipe', 'quiet',
                                    'remain-after-exit', 'collect', 'wait', 'shell', 'no-block',
                                    'no-ask-password', 'same-dir', 'send-sighup',
                                    'expand-environment', 'ignore-failure'), (), set()),
    'catchsegv': ('', (), '', '', (), (), set()),
    'valgrind': ('', (), '', 'qv', ('quiet', 'verbose'), (), set()),
    'torsocks': ('uapP', ('user', 'pass', 'address', 'port'), '', 'idq',
                 ('isolate', 'debug', 'quiet'), (), set()),
    'proxychains': ('f', (), '', 'q', (), (), set()),
    'proxychains4': ('f', (), '', 'q', (), (), set()),
    'tsocks': ('', (), '', '', (), (), set()),
    'faketime': ('p', ('date-prog',), '', 'mf', ('exclude-monotonic',), (ANY,), set()),
    'fakeroot': ('lsib', ('lib', 'faked'), '', 'u', ('unknown-is-real',), (), set()),
    'numactl': ('imNCpPwb', ('interleave', 'membind', 'cpunodebind', 'physcpubind', 'preferred',
                             'preferred-many', 'weighted-interleave', 'balancing'),
                '', 'laHst', ('localalloc', 'all', 'hardware', 'show'), (),
                {'H', 's', 'hardware', 'show'}),
    'cgexec': ('g', (), '', '', ('sticky',), (), set()),
    'pkexec': ('', ('user',), '', '', ('disable-internal-agent', 'keep-cwd'), (), set()),
}
PERMUTE = frozenset(['su', 'script'])
SHELL_OPTS = frozenset(['s', 'i', 'shell', 'login'])
# Read stdin as code to run later, so the text never reaches this parser's caller
SCHEDULERS = frozenset(['crontab', 'at', 'batch'])
FIND_ACTIONS = frozenset(['-exec', '-execdir', '-ok', '-okdir'])
INNER = (SHELLS | SCHEDULERS | frozenset(WRAPPERS) | frozenset(STRICT)
         | frozenset(['eval', 'env', 'runuser', 'sg']))


def _base(name: str) -> str:
    return name.rsplit('/', 1)[-1]


def _globbing(text: str) -> bool:
    if GLOB_CHARS.search(text):
        return True
    start = text.find('{')
    if start < 0:
        return False
    last = text.rfind('}')
    comma, dots = text.find(',', start), text.find('..', start)
    return 0 <= comma < last or 0 <= dots < last - 1


def _plain(word: Tuple[str, int]) -> str:
    text, flags = word
    if flags & EXPANDED or (flags & GLOB and _globbing(text)):
        raise _Unsure
    return text


def _options(words, i, short, long, attached='', permute=False, stop=frozenset(), flags=None):
    opts = {}
    known_short = None if flags is None else short + attached + flags[0]
    while i < len(words):
        w = _plain(words[i]) if words[i][0][:1] == '-' else words[i][0]
        if w == '--':
            return i + 1, opts
        if len(w) < 2 or w[0] != '-':
            if not permute:
                break
            _plain(words[i])
            i += 1
            continue
        i += 1
        if w.startswith('--'):
            key, eq, value = w[2:].partition('=')
            if flags is not None and not eq and key not in long and key not in flags[1]:
                raise _Unsure
            if not eq and key in long and i < len(words):
                value, i = _plain(words[i]), i + 1
            opts[key] = value
            if key in stop:
                break
            continue
        for j in range(1, len(w)):
            if known_short is not None and w[j] not in known_short:
                raise _Unsure
            if w[j] in attached or (w[j] in short and j + 1 < len(w)):
                opts[w[j]] = w[j + 1:]
                break
            if w[j] in short:
                if i < len(words):
                    opts[w[j]], i = _plain(words[i]), i + 1
                break
            opts[w[j]] = ''
        if stop & opts.keys():
            break
    return i, opts


def _code(words, i):
    if i >= len(words):
        return None
    text = ' '.join(_plain(w) for w in words[i:])
    # No shell syntax: the words are the split, which keeps eval chains linear
    if PLAIN_CODE.match(text) and text.split()[0] not in KEYWORDS:
        return _wrapped([(w, 0) for w in text.split()], 0)
    return 'code', text


def _shell(words):
    i, code, stdin = 1, False, False
    while i < len(words):
        if words[i][0][:1] not in ('-', '+'):
            break
        w = _plain(words[i])
        i += 1
        if w in ('-', '--'):
            break
        if w in ('--rcfile', '--init-file'):
            i += 1
        elif w[1:2] != '-':
            code = code or (w[0] == '-' and 'c' in w)
            stdin = stdin or (w[0] == '-' and 's' in w)
            i += w.count('o') + w.count('O')
    if code:
        return ('code', _plain(words[i])) if i < len(words) else None
    return ('stdin',) if stdin or i >= len(words) else None


def _produced(words) -> Optional[str]:
    name, args = _base(words[0][0]), words[1:]
    if name == 'printf' and args:
        fmt = _plain(args[0])
        if '%' in fmt or fmt.startswith('-'):
            raise _Unsure
        return ANSI_ESCAPE.sub(_ansi_escape, fmt)
    if name != 'echo':
        return None
    while args and ECHO_OPTS.match(args[0][0]):
        args = args[1:]
    text = ' '.join(_plain(w) for w in args)
    # Whether echo expands backslash escapes depends on the shell and xpg_echo
    if '\\' in text:
        raise _Unsure
    return text


def _stdin_redirect(cmd: 'SimpleCommand') -> Optional[Tuple[str, str]]:
    for redirect in reversed(cmd.redirects):
        if STDIN_REDIRECT.match(redirect[0]):
            return redirect
    return None


def _split(text):
    if SPLIT_UNSURE.search(text):
        raise _Unsure
    return [(w, 0) for w in text.split()]


ENV_CLEAN = ('ignore-environment', 'help', 'version')


def _env_parts(words):
    """(index of the command env runs, whether env starts from an empty environment)."""
    i, splits, clean = 1, 0, False
    while True:
        i, opts = _options(words, i, 'uCSaf', ('unset', 'chdir', 'split-string', 'argv0',
                                               'env0-from', 'quoting-style', 'file'),
                           stop=frozenset(['S', 'split-string']))
        # GNU env accepts any unique prefix of a long option
        clean = clean or 'i' in opts or any(
            len(k) >= 3 and any(full.startswith(k) for full in ENV_CLEAN) for k in opts)
        text = opts.get('S', opts.get('split-string'))
        if text is None:
            break
        splits += 1
        if splits > MAX_DEPTH:
            raise _Unsure
        words = words[:i] + _split(text) + words[i:]
    while i < len(words) and (words[i][0] == '-' or ENV_ASSIGN.match(words[i][0])):
        clean = clean or words[i][0] == '-'
        _plain(words[i])
        i += 1
    return words, i, clean


def _env(words):
    words, i, _ = _env_parts(words)
    return _wrapped(words, i)


def _args(name, words) -> List[str]:
    return _env_summary(words) if _base(name) == 'env' else [w for w, _ in words[1:]]


def _env_summary(words) -> List[str]:
    words, i, clean = _env_parts(words)
    if i < len(words):
        return [w for w, _ in words[i:]]
    return ['-i'] if clean else []


def _wrapped(words, i):
    # `{}` as a wrapped name is the find -exec / xargs -I placeholder, filled in at run time
    if i >= len(words) or words[i][0] == '{}':
        return None
    return 'words', words[i:]


def _find_actions(words):
    # An expanded word could become `-exec` or `;` and move where an action starts or ends
    for word in words[1:]:
        _plain(word)
    i = 1
    while i < len(words):
        if words[i][0] not in FIND_ACTIONS:
            i += 1
            continue
        start = i = i + 1
        # `+` only ends the command straight after `{}`; elsewhere it is an argument
        while i < len(words) and words[i][0] != ';' and (words[i][0], words[i - 1][0]) != ('+', '{}'):
            i += 1
        if i == start:
            raise _Unsure
        if start < len(words) and words[start][0] != '{}':
            yield words[start:i]
        i += 1


def _strict(words, spec):
    short, long, attached, flag_short, flag_long, operands, stop = spec
    i, opts = _options(words, 1, short, long, attached, flags=(flag_short, flag_long))
    if stop & opts.keys():
        return None
    for pattern in operands:
        if i >= len(words) or not pattern.match(_plain(words[i])):
            raise _Unsure
        i += 1
    return _wrapped(words, i)


def _runuser(words):
    short, long = 'ugGscw', ('user', 'group', 'supp-group', 'shell', 'command', 'session-command',
                             'whitelist-environment')
    i, opts = _options(words, 1, short, long, flags=('lmpP', ('login', 'preserve-environment',
                                                              'pty')))
    if 'u' in opts or 'user' in opts:
        return _wrapped(words, i)
    i, opts = _options(words, 1, short, long, permute=True,
                       flags=('lmpP', ('login', 'preserve-environment', 'pty')))
    code = opts.get('c', opts.get('command', opts.get('session-command')))
    return ('stdin',) if code is None else ('code', code)


def _sg(words):
    i = 1
    if i < len(words) and words[i][0] == '-':
        i += 1
    if i >= len(words):
        return ('stdin',)
    _plain(words[i])
    i += 1
    if i < len(words) and words[i][0] == '-c':
        i += 1
    return _code(words, i) if i < len(words) else ('stdin',)


def _inner(words):
    name = _base(words[0][0])
    if name in SHELLS:
        return _shell(words)
    if name == 'eval':
        return _code(words, 2 if words[1:2] and words[1][0] == '--' else 1)
    if name == 'env':
        return _env(words)
    if name in SCHEDULERS:
        return ('stdin',)
    if name in STRICT:
        return _strict(words, STRICT[name])
    if name == 'runuser':
        return _runuser(words)
    if name == 'sg':
        return _sg(words)
    if name not in WRAPPERS:
        return None
    short, long, attached, operands = WRAPPERS[name]
    i, opts = _options(words, 1, short, long, attached, name in PERMUTE)
    if name in PERMUTE:
        code = opts.get('c', opts.get('command', opts.get('session-command')))
        if code is None:
            return ('stdin',) if name == 'su' else None
        return 'code', code
    if name == 'command' and ('v' in opts or 'V' in opts):
        return None
    if name == 'xargs':
        placeholder = opts.get('I', opts.get('replace', '{}' if 'i' in opts else None))
        if placeholder and i < len(words) and placeholder in words[i][0]:
            raise _Unsure
    if name == 'sudo':
        while i < len(words) and ASSIGN.match(words[i][0]):
            _plain(words[i])
            i += 1
    for word in words[i:i + operands]:
        _plain(word)
    i += operands
    if name == 'ssh':
        return _code(words, _options(words, i, short, long)[0])
    if name == 'watch' and 'x' not in opts and 'exec' not in opts:
        return _code(words, i)
    if name == 'flock' and i + 1 < len(words) and words[i][0] in ('-c', '--command'):
        return 'code', _plain(words[i + 1])
    if i >= len(words) and (name == 'chroot' or SHELL_OPTS & opts.keys() and name in ('sudo', 'doas')):
        return ('stdin',)
    return _wrapped(words, i)


def _ansi_escape(m) -> str:
    code = m.group(1)
    if code in ANSI_SIMPLE:
        return ANSI_SIMPLE[code]
    if code[0] in 'xuU' and len(code) > 1:
        value = int(code[1:], 16)
    elif code[0] in '01234567':
        value = int(code, 8) & 0xFF
    else:
        raise _Unsure
    # NUL truncates the word in bash; surrogates and > U+10FFFF are not text
    if value == 0 or 0xD800 <= value < 0xE000 or value > 0x10FFFF:
        raise _Unsure
    return chr(value)


class _Parser:
    def __init__(self, s: str, out: list, depth: int, subst: int,
                 parent: Optional[SimpleCommand] = None, feed: Optional[Tuple[str, str]] = None):
        self.s, self.i, self.out = s, 0, out
        self.depth, self.subst = depth, subst
        self.parent, self.fed_by, self.base = parent, feed, subst
        self.pending, self.readers, self.words, self.heredocs = [], {}, {}, {}
        self.bodies_out = _BODIES
        self.registered = 0

    def at(self, prefix: str) -> bool:
        return self.s.startswith(prefix, self.i)

    def blank(self, newlines: bool = False) -> None:
        s = self.s
        while self.i < len(s):
            if s[self.i] not in ' \t\\#\n':
                return
            m = BLANK.match(s, self.i)
            if m:
                self.i = m.end()
            elif s[self.i] == '#':
                end = s.find('\n', self.i)
                self.i = len(s) if end < 0 else end
            elif s[self.i] == '\n' and newlines:
                self.i += 1
                if self.pending:
                    self.bodies()
            else:
                return

    def enter(self, subst: int = 0) -> None:
        self.depth += 1
        self.subst += subst
        if self.depth > MAX_DEPTH:
            raise _Unsure

    def leave(self, subst: int = 0) -> None:
        self.depth -= 1
        self.subst -= subst

    def word(self) -> Tuple[str, int]:
        s, buf, flags = self.s, [], 0
        while self.i < len(s):
            m = PLAIN.match(s, self.i)
            if m:
                buf.append(m.group())
                self.i = m.end()
                continue
            c = s[self.i]
            if c in '<>' and s.startswith('(', self.i + 1):
                flags |= self.nested(buf, 2)
            elif c in ' \t\n;&|()<>':
                break
            elif c == "'":
                end = s.find("'", self.i + 1)
                if end < 0:
                    raise _Unsure
                buf.append(s[self.i + 1:end])
                self.i, flags = end + 1, flags | QUOTED
            elif c == '"' or self.at('$"'):
                self.i += 1 if c == '"' else 2
                flags |= QUOTED | self.double_quoted(buf)
            elif self.at("$'"):
                buf.append(self.ansi_c())
                flags |= QUOTED
            elif c == '$':
                flags |= self.dollar(buf, False)
            elif c == '`':
                flags |= self.backtick(buf, False)
            elif c == '\\':
                nxt = s[self.i + 1:self.i + 2]
                if not nxt:
                    raise _Unsure
                if nxt != '\n':
                    buf.append(nxt)
                self.i, flags = self.i + 2, flags | QUOTED
            else:
                buf.append(c)
                self.i, flags = self.i + 1, flags | GLOB
        return _word_text(buf), flags

    def double_quoted(self, buf: List[str], closing: bool = True) -> int:
        s, flags = self.s, 0
        while self.i < len(s):
            m = DQ_PLAIN.match(s, self.i)
            if m:
                buf.append(m.group())
                self.i = m.end()
                continue
            c = s[self.i]
            if c == '"':
                if closing:
                    self.i += 1
                    return flags
                buf.append(c)
                self.i += 1
            elif c == '$':
                flags |= self.dollar(buf, True)
            elif c == '`':
                flags |= self.backtick(buf, closing)
            else:
                nxt = s[self.i + 1:self.i + 2]
                if not nxt:
                    raise _Unsure
                if nxt in '$`\\' or (nxt == '"' and closing):
                    buf.append(nxt)
                elif nxt != '\n':
                    buf.append(c + nxt)
                self.i += 2
        if closing:
            raise _Unsure
        return flags

    def ansi_c(self) -> str:
        m = ANSI_C.match(self.s, self.i)
        if not m:
            raise _Unsure
        self.i = m.end()
        return ANSI_ESCAPE.sub(_ansi_escape, m.group(1))

    def dollar(self, buf: List[str], quoted: bool) -> int:
        s, start = self.s, self.i
        if self.at('$(('):
            raise _Unsure
        if self.at('$('):
            return self.nested(buf, 2)
        if self.at('${'):
            if s.startswith('!', self.i + 2) or UNDERSCORE.match(s, self.i + 2):
                raise _Unsure
            self.i += 2
            self.enter()
            self.brace_param(quoted)
            self.leave()
        else:
            m = VARIABLE.match(s, self.i + 1)
            if not m:
                buf.append('$')
                self.i += 1
                return 0
            if m.group() == '_':
                raise _Unsure
            self.i = m.end()
        buf.append(_Expansion(s[start:self.i]))
        return EXPANDED

    def brace_param(self, quoted: bool) -> None:
        s, scratch = self.s, []
        while self.i < len(s):
            m = PARAM_PLAIN.match(s, self.i)
            if m:
                self.i = m.end()
                continue
            c = s[self.i]
            if c == '}':
                self.i += 1
                return
            if c == "'" and not quoted:
                end = s.find("'", self.i + 1)
                if end < 0:
                    raise _Unsure
                self.i = end + 1
            elif c == '"':
                self.i += 1
                self.double_quoted(scratch)
            elif c == '$':
                self.dollar(scratch, quoted)
            elif c == '`':
                self.backtick(scratch, quoted)
            elif c == '\\':
                self.i += 2
            else:
                self.i += 1
        raise _Unsure

    def nested(self, buf: List[str], skip: int) -> int:
        start = self.i
        self.i += skip
        self.enter(1)
        outer, self.pending = self.pending, []
        self.compound_list(frozenset(')'))
        if self.pending or (outer and '\n' in self.s[start:self.i]):
            raise _Unsure
        self.pending = outer
        self.leave(1)
        buf.append(_Expansion(self.s[start:self.i]))
        return EXPANDED

    def backtick(self, buf: List[str], quoted: bool) -> int:
        m = BACKTICK.match(self.s, self.i)
        if not m or (self.pending and '\n' in m.group()):
            raise _Unsure
        self.i = m.end()
        unescape = BACKTICK_DQ_ESCAPE if quoted else BACKTICK_ESCAPE
        _run(unescape.sub(r'\1', m.group(1)), self.out, self.depth + 1, self.subst + 1)
        buf.append(_Expansion(m.group()))
        return EXPANDED

    def simple_command(self) -> Optional[SimpleCommand]:
        slot = len(self.out)
        self.out.append(None)
        s, words, redirects, assigned = self.s, [], [], False
        while True:
            self.blank()
            if self.i >= len(s):
                break
            proc = PROC_SUB.match(s, self.i)
            if not proc and self.redirect(redirects):
                continue
            if s[self.i] in '\n;&|()' or (s[self.i] in '<>' and not proc):
                break
            m = ASSIGN.match(s, self.i) if not words else None
            if m:
                self.i, assigned = m.end(), True
                self.array() if self.at('(') else self.word()
            else:
                words.append(self.word())
        if not words:
            if not (assigned or redirects):
                raise _Unsure
            # bash runs `$(< file)` as `cat file`
            if self.subst and not assigned and any(r[0] in ('<', '0<') for r in redirects):
                words = [('cat', 0)]
            else:
                return None
        name, flags = words[0]
        if flags & EXPANDED or (flags & GLOB and name != '['):
            raise _Unsure
        args = _args(name, words)
        cmd = self.out[slot] = SimpleCommand(name, args, redirects)
        if self.subst == self.base and self.parent:
            cmd.parent, cmd.feed = self.parent, self.fed_by
        self.words[id(cmd)] = words
        self.find_actions(cmd, words, self.depth)
        reader = self.analyse(cmd, words, self.depth) if _base(name) in INNER else None
        if reader:
            redirect = _stdin_redirect(cmd)
            if redirect is None:
                self.readers[id(cmd)] = reader
                self.registered += 1
            elif id(redirect) in self.heredocs:
                self.feed(self.heredocs[id(redirect)], reader, redirect)
        return cmd

    def analyse(self, cmd: SimpleCommand, words, depth: int) -> Optional[SimpleCommand]:
        result = _inner(words)
        if result is None:
            return None
        if result[0] == 'stdin':
            return cmd
        if depth >= MAX_DEPTH:
            raise _Unsure
        if result[0] == 'code':
            return _run(result[1], self.out, depth + 1, self.subst, cmd)
        words = result[1]
        name = words[0][0] if words[0][0] == '[' else _plain(words[0])
        args = _args(name, words)
        inner = SimpleCommand(name, args, parent=cmd)
        self.out.append(inner)
        self.find_actions(inner, words, depth + 1)
        return self.analyse(inner, words, depth + 1)

    def find_actions(self, cmd: SimpleCommand, words, depth: int) -> None:
        if _base(cmd.name) != 'find':
            return
        for action in _find_actions(words):
            name = action[0][0] if action[0][0] == '[' else _plain(action[0])
            inner = SimpleCommand(name, _args(name, action))
            self.out.append(inner)
            # Runs with find's stdin, which this parser cannot follow
            if _base(name) in INNER and self.analyse(inner, action, depth + 1) is not None:
                raise _Unsure

    def feed(self, entry: list, reader: SimpleCommand, redirect: Optional[Tuple[str, str]]) -> None:
        if _base(reader.name) in SCHEDULERS:
            raise _Unsure
        if entry[1] is None:
            entry[2].append((reader, redirect))
            return
        if entry[0]:
            raise _Unsure
        _run(entry[1], self.out, self.depth + 1, self.subst, reader, redirect)

    def feed_pipe(self, producer: SimpleCommand, reader: SimpleCommand) -> None:
        if _base(reader.name) in SCHEDULERS and _base(producer.name) in ('echo', 'printf', 'cat'):
            raise _Unsure
        text = _produced(self.words[id(producer)])
        if text is not None:
            _run(text, self.out, self.depth + 1, self.subst, reader)
            return
        redirect = _stdin_redirect(producer)
        if _base(producer.name) == 'cat' and not producer.args and redirect:
            if id(redirect) in self.heredocs:
                self.feed(self.heredocs[id(redirect)], reader, None)

    def redirect(self, redirects: List[Tuple[str, str]]) -> bool:
        m = REDIRECT.match(self.s, self.i)
        if not m:
            return False
        self.i = m.end()
        self.blank()
        if self.i >= len(self.s) or (self.s[self.i] in '\n;&|()<>' and not PROC_SUB.match(self.s, self.i)):
            raise _Unsure
        target, flags = self.word()
        redirect = (m.group(), target)
        if m.group(2) in ('<<', '<<-'):
            if flags & EXPANDED:
                raise _Unsure
            self.pending.append((target, m.group(2) == '<<-', bool(flags & QUOTED), redirect))
            self.heredocs[id(redirect)] = [None, None, [], redirect]
        elif m.group(2) == '<<<':
            self.heredocs[id(redirect)] = [flags & EXPANDED, target, [], redirect]
        redirects.append(redirect)
        return True

    def array(self) -> None:
        self.i += 1
        while True:
            self.blank(newlines=True)
            if self.at(')'):
                self.i += 1
                return
            if self.i >= len(self.s) or self.s[self.i] in ';&|(<>':
                raise _Unsure
            self.word()

    def bodies(self) -> None:
        s, pending, self.pending = self.s, self.pending, []
        for delim, strip, quoted, redirect in pending:
            start = i = self.i
            while True:
                if i >= len(s):
                    raise _Unsure
                nl = s.find('\n', i)
                nl = len(s) if nl < 0 else nl
                line = s[i:nl].lstrip('\t') if strip else s[i:nl]
                # Bash joins backslash-newline in an unquoted body before matching the delimiter
                if not quoted and (len(line) - len(line.rstrip('\\'))) % 2:
                    raise _Unsure
                if line == delim:
                    break
                # Inside $( bash also ends the heredoc at a line like `EOF)`
                if self.subst and line.startswith(delim):
                    raise _Unsure
                i = nl + 1
            body, flags = s[start:i], 0
            if strip:
                body = LEADING_TABS.sub('', body)
            if not quoted:
                # Quote removal turns \$X into $X, so a rule would see a variable that never expands
                if '\\$' in body:
                    raise _Unsure
                buf = []
                flags = _Parser(body, self.out, self.depth, self.subst).double_quoted(buf, closing=False)
                body = ''.join(buf)
            self.i = min(nl + 1, len(s))
            entry = self.heredocs[id(redirect)]
            entry[:2] = flags & EXPANDED, body
            if not quoted:
                self.bodies_out[id(redirect)] = body
            for reader, feed in entry[2]:
                self.feed(entry, reader, feed)

    def command(self) -> Optional[SimpleCommand]:
        self.blank()
        if self.at('(('):
            raise _Unsure
        if self.at('('):
            self.i += 1
            return self.group(self.compound, frozenset(')'))
        m = RESERVED.match(self.s, self.i)
        word = m.group() if m and m.group() in KEYWORDS else None
        if word in UNSUPPORTED or word in TERMINATORS:
            raise _Unsure
        if word:
            self.i = m.end()
        while word in ('!', 'time'):
            self.blank()
            if word == 'time' and self.at('-p') and DELIM.match(self.s, self.i + 2):
                self.i += 2
                self.blank()
            if word == 'time' and self.at('--') and DELIM.match(self.s, self.i + 2):
                self.i += 2
                self.blank()
            m = RESERVED.match(self.s, self.i)
            word = m.group() if m and m.group() in KEYWORDS else None
            if word in UNSUPPORTED or word in TERMINATORS:
                raise _Unsure
            if word:
                self.i = m.end()
            elif self.at('('):
                return self.command()
        if word == '{':
            return self.group(self.compound, frozenset('}'))
        if word == 'if':
            return self.group(self.if_clause)
        if word in ('while', 'until'):
            return self.group(self.while_clause)
        if word == 'for':
            return self.group(self.for_clause)
        if word == '[[':
            self.conditional()
        elif word == 'function' or (not ASSIGN.match(self.s, self.i) and FUNCDEF.match(self.s, self.i)):
            self.function(word == 'function')
        else:
            return self.simple_command()
        return self.trailing_redirects()

    def trailing_redirects(self, redirects: Optional[list] = None) -> None:
        while True:
            self.blank()
            if self.i >= len(self.s) or PROC_SUB.match(self.s, self.i):
                return None
            if not self.redirect([] if redirects is None else redirects):
                return None

    def group(self, body, *args) -> '_Group':
        frame, outer = _Group(''), (self.parent, self.fed_by, self.base)
        if self.subst == self.base:
            frame.parent, frame.feed = self.parent, self.fed_by
        self.parent, self.fed_by, self.base = frame, None, self.subst
        body(*args)
        self.parent, self.fed_by, self.base = outer
        self.trailing_redirects(frame.redirects)
        return frame

    def compound(self, ends: frozenset) -> str:
        self.enter()
        end = self.compound_list(ends)
        self.leave()
        return end

    def if_clause(self) -> None:
        end = 'elif'
        while end == 'elif':
            self.compound(frozenset(['then']))
            end = self.compound(frozenset(['elif', 'else', 'fi']))
        if end == 'else':
            self.compound(frozenset(['fi']))

    def while_clause(self) -> None:
        self.compound(frozenset(['do']))
        self.compound(frozenset(['done']))

    def for_clause(self) -> None:
        self.blank()
        m = NAME.match(self.s, self.i)
        if not m or not DELIM.match(self.s, m.end()):
            raise _Unsure
        self.i = m.end()
        self.blank(newlines=True)
        if self.at('in') and DELIM.match(self.s, self.i + 2):
            self.i += 2
            while True:
                self.blank()
                if self.i >= len(self.s) or self.s[self.i] in '\n;':
                    break
                if self.s[self.i] in '&|()<>':
                    raise _Unsure
                self.word()
            if self.at(';'):
                self.i += 1
        elif self.at(';'):
            self.i += 1
        self.blank(newlines=True)
        if not (self.at('do') and DELIM.match(self.s, self.i + 2)):
            raise _Unsure
        self.i += 2
        self.compound(frozenset(['done']))

    def conditional(self) -> None:
        s = self.s
        while True:
            self.blank(newlines=True)
            if self.i >= len(s) or s[self.i] in ';|':
                if not self.at('||'):
                    raise _Unsure
            if self.at(']]') and DELIM.match(s, self.i + 2):
                self.i += 2
                return
            if self.at('&&') or self.at('||'):
                self.i += 2
            elif PROC_SUB.match(s, self.i):
                self.word()
            elif s[self.i] in '()<>!&':
                self.i += 1
            else:
                self.word()

    def function(self, keyword: bool) -> None:
        self.blank()
        m = (FUNCNAME if keyword else FUNCDEF).match(self.s, self.i)
        if not m:
            raise _Unsure
        self.i = m.end()
        self.blank(newlines=True)
        if not (self.at('{') or self.at('(')):
            raise _Unsure
        self.out.append(FunctionDef(m.group().split('(')[0].strip()))
        self.enter()
        self.command()
        self.leave()

    def pipeline(self) -> None:
        left, feeds = self.command(), []
        while True:
            self.blank()
            if not self.at('|') or self.at('||'):
                for producer, reader in feeds:
                    self.feed_pipe(producer, reader)
                return
            self.i += 2 if self.at('|&') else 1
            self.blank(newlines=True)
            seen = self.registered
            stage = self.command()
            if left is not None and stage is not None and not isinstance(stage, _Group):
                left.pipe_to = stage
            producer = None if isinstance(left, _Group) else left
            right = None if isinstance(stage, _Group) else stage
            if right and id(right) in self.readers:
                reader = self.readers.pop(id(right))
                if not producer:
                    raise _Unsure
                feeds.append((producer, reader))
            elif not right and self.registered != seen:
                raise _Unsure
            left = stage

    def and_or(self) -> None:
        self.pipeline()
        while True:
            self.blank()
            if not (self.at('&&') or self.at('||')):
                return
            self.i += 2
            self.blank(newlines=True)
            self.pipeline()

    def compound_list(self, ends: frozenset = frozenset()) -> Optional[str]:
        s = self.s
        while True:
            self.blank(newlines=True)
            if self.i >= len(s):
                if ends:
                    raise _Unsure
                return None
            m = RESERVED.match(s, self.i)
            if m and m.group() in ends:
                self.i = m.end()
                return m.group()
            if s[self.i] == ')':
                if ')' not in ends:
                    raise _Unsure
                self.i += 1
                return ')'
            self.and_or()
            self.blank()
            if self.at(';;') or self.at(';&'):
                raise _Unsure
            if self.at(';') or self.at('&'):
                self.i += 1
            elif self.i < len(s) and s[self.i] not in '\n)':
                raise _Unsure


def _run(text: str, out: list, depth: int, subst: int, parent: Optional[SimpleCommand] = None,
         feed: Optional[Tuple[str, str]] = None) -> Optional[SimpleCommand]:
    if depth > MAX_DEPTH:
        raise _Unsure
    parser = _Parser(text, out, depth, subst, parent, feed)
    parser.compound_list()
    if parser.pending:
        raise _Unsure
    return next(iter(parser.readers.values()), None)


def parse_commands(command: str, functions: Optional[set] = None) -> Optional[List[SimpleCommand]]:
    if len(command) > MAX_LENGTH:
        return None
    out = []
    try:
        _run(command, out, 1, 0)
    except (_Unsure, RecursionError):
        return None
    if functions is not None:
        functions.update(c for c in out if isinstance(c, FunctionDef))
    commands = [c for c in out if c is not None and not isinstance(c, FunctionDef)]
    if any((_base(c.name) or c.name).startswith('-') for c in commands):
        return None
    # An alias can turn any later word into eval, so no line after it reads as written
    if any(_base(c.name) == 'alias' for c in commands):
        return None
    return commands


NEEDS_QUOTE = re.compile(r'[\s|&;<>()$`\\"\'#*?\[\]{}]')


def _word(arg: str) -> str:
    arg = getattr(arg, 'shown', arg) or arg
    return shlex.quote(arg) if not arg or NEEDS_QUOTE.search(arg) else arg


# Expanding heredoc bodies by redirect id, filled while parsing and read while rendering
_BODIES = {}


def _redirects(redirects, skip=None) -> str:
    return ''.join(' %s %s' % (op, _word(_BODIES.get(id(r), r[1]))) for r in redirects
                   for op in (r[0],) if r != skip)


def normalise(command: str) -> Optional[List[str]]:
    _BODIES.clear()
    commands = parse_commands(command)
    return None if commands is None else render(commands)


def render(commands: List[SimpleCommand]) -> Optional[List[str]]:
    rendered, inherited, budget = {}, {}, [OUTPUT_LIMIT]

    def spend(text):
        budget[0] -= len(text)
        if budget[0] < 0:
            raise _Unsure
        return text

    def pipeline(cmd):
        chain = []
        while cmd is not None and id(cmd) not in rendered:
            chain.append(cmd)
            cmd = cmd.pipe_to
        # Tail-first so a long pipeline costs a loop, not a recursion per stage.
        for stage in reversed(chain):
            text = ' '.join([_base(stage.name) or stage.name] + [_word(a) for a in stage.args])
            text += _redirects(stage.redirects)
            if stage.pipe_to is not None:
                text = spend(text + ' | ' + rendered[id(stage.pipe_to)])
            rendered[id(stage)] = text
        return rendered[id(chain[0] if chain else cmd)]

    def suffix(cmd):
        key = (id(cmd.parent), cmd.feed)
        if key not in inherited:
            parent = cmd.parent
            text = _redirects(parent.redirects, cmd.feed)
            if parent.pipe_to is not None:
                text += ' | ' + pipeline(parent.pipe_to)
            if parent.parent is not None:
                text += suffix(parent)
            inherited[key] = spend(text)
        return inherited[key]

    try:
        return [spend(pipeline(c) + (suffix(c) if c.parent is not None else '')) for c in commands]
    except (_Unsure, RecursionError):
        return None
