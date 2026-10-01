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


@dataclass(frozen=True)
class Spec:
    message: frozenset
    stdin: frozenset
    value: frozenset = frozenset()
    boolean: frozenset = frozenset()
    positionals: int = 0
    short_cluster: str = ''


def _spec(message, stdin, value='', boolean='', positionals=0, short_cluster=''):
    return Spec(frozenset(message.split()), frozenset(stdin.split()), frozenset(value.split()),
                frozenset(boolean.split()), positionals, short_cluster)


GH_REPO = '-R --repo '
PR_EDIT_VALUES = ('--add-label --remove-label --add-assignee --remove-assignee --add-reviewer '
                  '--remove-reviewer --add-project --remove-project -m --milestone ')
# Every word of a masked segment must be listed here, so the scanner parses it as gh/git would
SPECS = {
    ('gh', 'pr', 'create'): _spec('-t --title -b --body', '-F --body-file',
                                  GH_REPO + '-B --base -H --head -l --label -a --assignee -r --reviewer '
                                  '-m --milestone -p --project -T --template',
                                  '-d --draft -f --fill --fill-first --fill-verbose --no-maintainer-edit --dry-run'),
    ('gh', 'pr', 'comment'): _spec('-b --body', '-F --body-file', GH_REPO,
                                   '--edit-last --create-if-none', 1),
    ('gh', 'pr', 'edit'): _spec('-t --title -b --body', '-F --body-file', GH_REPO + '-B --base ' + PR_EDIT_VALUES,
                                '--remove-milestone', 1),
    ('gh', 'pr', 'review'): _spec('-b --body', '-F --body-file', GH_REPO,
                                  '-a --approve -c --comment -r --request-changes', 1),
    ('gh', 'pr', 'close'): _spec('-c --comment', '', GH_REPO, '-d --delete-branch', 1),
    ('gh', 'pr', 'reopen'): _spec('-c --comment', '', GH_REPO, '', 1),
    ('gh', 'pr', 'merge'): _spec('-t --subject -b --body', '-F --body-file',
                                 GH_REPO + '-A --author-email --match-head-commit',
                                 '-s --squash -m --merge -r --rebase --auto --admin -d --delete-branch', 1),
    ('gh', 'issue', 'create'): _spec('-t --title -b --body', '-F --body-file',
                                     GH_REPO + '-a --assignee -l --label -m --milestone -p --project -T --template'),
    ('gh', 'issue', 'comment'): _spec('-b --body', '-F --body-file', GH_REPO,
                                      '--edit-last --create-if-none', 1),
    ('gh', 'issue', 'edit'): _spec('-t --title -b --body', '-F --body-file', GH_REPO + PR_EDIT_VALUES,
                                   '--remove-milestone', 1),
    ('gh', 'issue', 'close'): _spec('-c --comment', '', GH_REPO + '-r --reason', '', 1),
    ('gh', 'issue', 'reopen'): _spec('-c --comment', '', GH_REPO, '', 1),
    # Positionals after the tag are uploaded as assets, so only the tag is allowed
    ('gh', 'release', 'create'): _spec('-t --title -n --notes', '-F --notes-file',
                                       GH_REPO + '--target --discussion-category --notes-start-tag',
                                       '-d --draft -p --prerelease --latest --generate-notes --verify-tag', 1),
    ('gh', 'release', 'edit'): _spec('-t --title -n --notes', '-F --notes-file',
                                     GH_REPO + '--tag --target --discussion-category',
                                     '--draft --prerelease --latest --verify-tag', 1),
    ('git', 'commit'): _spec('-m --message', '-F --file', '',
                             '-a --all -q --quiet -s --signoff --amend --no-edit --allow-empty '
                             '--allow-empty-message --no-verify -n -v --verbose', 0, 'aqsnv'),
    ('git', 'tag'): _spec('-m --message', '-F --file', '', '-a --annotate -s --sign -f --force', 2, 'asf'),
}
# Any other command could redefine git or gh before the message segment runs
SEGMENT_COMMANDS = {'git', 'gh', 'cd'}

UNQUOTED = re.compile(r'[A-Za-z0-9_./:=@%+,~-]+')
HEREDOC = re.compile(r'<<[ \t]*([\'"])(\w+)\1')
CAT_HEREDOC = re.compile(r'\$\(cat <<[ \t]*([\'"])(\w+)\1\n')
VARIABLE = re.compile(r'\$[A-Za-z_]\w*|\$\{[A-Za-z_]\w*\}')
# $_ and ${!x} re-expand text from an earlier, masked argument
REEXPAND = re.compile(r'\$\{?(?:_\b|!)')
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


def _message_spec(words: List[str]) -> Tuple[Optional[Spec], int]:
    if words[:1] == ['git']:
        k = 3 if words[1:2] == ['-C'] else 1
        if len(words) > k:
            return SPECS.get(('git', words[k])), k + 1
    if words[:1] == ['gh'] and len(words) > 2:
        return SPECS.get(('gh', words[1], words[2])), 3
    return None, 0


def _replacement(kept: List[str]) -> str:
    return '"' + ' '.join(kept) + '"' if kept else "''"


def _plain(word: str) -> bool:
    return UNQUOTED.fullmatch(word) is not None and not word.startswith('-')


def _edits(cmd: str, segment: Segment) -> Optional[List[Tuple[int, int, str]]]:
    words = segment.words
    if not words:
        return []
    raw = [cmd[w.start:w.end] for w in words]
    if raw[0] == 'cd':
        return []
    spec, k = _message_spec(raw)
    if spec is None:
        return None if segment.heredocs or '-c' in raw else []
    edits = []
    reads_stdin = False
    positionals = 0
    while k < len(words):
        word = raw[k]
        name, eq, value = word.partition('=')
        following = raw[k + 1] if k + 1 < len(words) else None
        cluster = re.fullmatch(rf'-([{spec.short_cluster}]+)(m?)', word) if spec.short_cluster else None
        if word in spec.message or (cluster and cluster.group(2)):
            if following is None:
                return None
            k += 1
            edits.append((words[k].start, words[k].end, _replacement(words[k].kept)))
        elif eq and name.startswith('--') and name in spec.message:
            edits.append((words[k].start + len(name) + 1, words[k].end, _replacement(words[k].kept)))
        elif word in spec.stdin and following == '-':
            reads_stdin = True
            k += 1
        elif eq and name.startswith('--') and name in spec.stdin and value == '-':
            reads_stdin = True
        elif word in spec.value and following is not None and _plain(following):
            k += 1
        elif eq and name.startswith('--') and name in spec.value and UNQUOTED.fullmatch(value):
            pass
        elif word in spec.boolean or cluster:
            pass
        elif _plain(word) and positionals < spec.positionals:
            positionals += 1
        elif _plain(word) and spec is SPECS[('git', 'commit')]:
            pass
        else:
            return None
        k += 1
    if len(segment.heredocs) > 1 or (segment.heredocs and not reads_stdin):
        return None
    if segment.heredocs:
        start, end = segment.heredocs[0]
        edits.append((start, end, ''))
    return edits


def mask_data(command: str) -> str:
    if len(command) > MAX_LENGTH or REEXPAND.search(command):
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
