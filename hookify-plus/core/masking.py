#!/usr/bin/env python3
"""Blank prose in gh/git message arguments before rules match.

Allowlist: only message flags on known gh/git subcommands are masked. Any
command the scanner cannot fully parse is returned unchanged, so rules still
see every byte of it.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_LENGTH = 20000

GH_SUBCOMMANDS = {
    ('pr', s) for s in ('create', 'comment', 'edit', 'review', 'close', 'merge', 'reopen')
} | {
    ('issue', s) for s in ('create', 'comment', 'edit', 'close', 'reopen')
} | {
    ('release', s) for s in ('create', 'edit')
}
GH_FLAGS = {'--body', '-b', '--title', '-t', '--notes', '--subject'}
GH_STDIN = {'--body-file', '-F', '--notes-file'}
GIT_SUBCOMMANDS = {'commit', 'tag'}
GIT_FLAGS = {'-m', '--message'}
GIT_STDIN = {'-F', '--file'}
# Any other command could redefine git or gh before the message segment runs
SEGMENT_COMMANDS = {'git', 'gh', 'cd'}

UNQUOTED = re.compile(r'[A-Za-z0-9_./:=@%+,~-]+')
HEREDOC = re.compile(r'<<[ \t]*([\'"])(\w+)\1')
CAT_HEREDOC = re.compile(r'\$\(cat <<[ \t]*([\'"])(\w+)\1\n')
VARIABLE = re.compile(r'\$[A-Za-z_]\w*|\$\{[^}"`$\\\n]*\}')
CLOSE_SUBSTITUTION = re.compile(r'\n[ \t]*\)')


@dataclass
class Word:
    start: int
    end: int = 0
    kept: List[str] = field(default_factory=list)


@dataclass
class Segment:
    words: List[Word] = field(default_factory=list)
    heredocs: List[Tuple[int, int]] = field(default_factory=list)


def _terminator(cmd: str, delim: str, pos: int) -> Optional[re.Match]:
    # Bash ends a heredoc at the first line equal to the delimiter
    return re.compile(rf'^{re.escape(delim)}$', re.M).search(cmd, pos)


def _double_quoted(cmd: str, i: int, word: Word) -> Optional[int]:
    j = i + 1
    while j < len(cmd):
        c = cmd[j]
        if c == '"':
            return j + 1
        if c == '\\':
            if j + 1 >= len(cmd):
                return None
            j += 2
        elif c == '`':
            return None
        elif c == '$':
            m = CAT_HEREDOC.match(cmd, j)
            if m:
                end = _terminator(cmd, m.group(2), m.end())
                close = end and CLOSE_SUBSTITUTION.match(cmd, end.end())
                if not close:
                    return None
                # Inside $( bash also ends the heredoc at a line like `EOF)`
                if re.search(rf'^{re.escape(m.group(2))}', cmd[m.end():end.start()], re.M):
                    return None
                j = close.end()
                continue
            m = VARIABLE.match(cmd, j)
            if not m:
                return None
            word.kept.append(m.group())
            j = m.end()
        else:
            j += 1
    return None


def _scan(cmd: str) -> Optional[List[Segment]]:
    segments = [Segment()]
    pending: List[Tuple[Segment, str]] = []
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in ' \t':
            i += 1
        elif c == '\n':
            segments.append(Segment())
            i += 1
            for segment, delim in pending:
                end = _terminator(cmd, delim, i)
                if not end:
                    return None
                segment.heredocs.append((i, end.start()))
                i = end.end()
            pending = []
        elif cmd.startswith(('&&', '||'), i):
            segments.append(Segment())
            i += 2
        elif c == ';':
            segments.append(Segment())
            i += 1
        elif c == '<':
            m = HEREDOC.match(cmd, i)
            # Bash joins glued quoting into one delimiter: <<'E'"OF" ends at EOF
            if not m or (m.end() < n and cmd[m.end()] not in ' \t\n;&|'):
                return None
            pending.append((segments[-1], m.group(2)))
            i = m.end()
        else:
            word = Word(start=i)
            while i < n and cmd[i] not in ' \t\n;&|<':
                if cmd[i] == "'":
                    end = cmd.find("'", i + 1)
                    if end < 0:
                        return None
                    i = end + 1
                elif cmd[i] == '"':
                    i = _double_quoted(cmd, i, word)
                    if i is None:
                        return None
                else:
                    m = UNQUOTED.match(cmd, i)
                    if not m:
                        return None
                    i = m.end()
            if i < n and cmd[i] in '&|' and not cmd.startswith(('&&', '||'), i):
                return None
            if i < n and cmd[i] == '<':
                return None
            word.end = i
            segments[-1].words.append(word)
    if pending:
        return None
    return segments


def _message_spec(words: List[str]):
    if words[:1] == ['git']:
        k = 3 if words[1:2] == ['-C'] else 1
        if len(words) > k and words[k] in GIT_SUBCOMMANDS:
            return GIT_FLAGS, GIT_STDIN, k + 1
    if words[:1] == ['gh'] and len(words) > 2 and (words[1], words[2]) in GH_SUBCOMMANDS:
        return GH_FLAGS, GH_STDIN, 3
    return None


def _replacement(kept: List[str]) -> str:
    return '"' + ' '.join(kept) + '"' if kept else "''"


def _edits(cmd: str, segment: Segment) -> Optional[List[Tuple[int, int, str]]]:
    words = segment.words
    raw = [cmd[w.start:w.end] for w in words]
    spec = _message_spec(raw)
    if not spec:
        return []
    flags, stdin_flags, first = spec
    edits = []
    reads_stdin = False
    k = first
    while k < len(words):
        name, eq, value = raw[k].partition('=')
        if raw[k] in flags and k + 1 < len(words):
            k += 1
            edits.append((words[k].start, words[k].end, _replacement(words[k].kept)))
        elif eq and name in flags:
            edits.append((words[k].start + len(name) + 1, words[k].end, _replacement(words[k].kept)))
        elif raw[k] in stdin_flags and raw[k + 1:k + 2] == ['-']:
            reads_stdin = True
            k += 1
        elif eq and name in stdin_flags and value == '-':
            reads_stdin = True
        k += 1
    if len(segment.heredocs) > 1:
        return None
    if segment.heredocs and reads_stdin:
        start, end = segment.heredocs[0]
        edits.append((start, end, ''))
    return edits


def mask_data(command: str) -> str:
    if len(command) > MAX_LENGTH:
        return command
    segments = _scan(command)
    if segments is None:
        return command
    if any(s.words and command[s.words[0].start:s.words[0].end] not in SEGMENT_COMMANDS
           for s in segments):
        return command
    edits = []
    for segment in segments:
        segment_edits = _edits(command, segment)
        if segment_edits is None:
            return command
        edits.extend(segment_edits)
    for start, end, text in sorted(edits, reverse=True):
        command = command[:start] + text + command[end:]
    return command
