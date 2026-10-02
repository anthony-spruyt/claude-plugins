#!/usr/bin/env python3
"""Blank prose in gh/git message arguments before rules match.

Allowlist: only message flags on known gh/git subcommands are masked. Any
command the scanner cannot fully parse is returned unchanged, so rules still
see every byte of it.
"""

import re
import sys
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

    def option(self, word: str) -> Tuple[Optional[str], int]:
        name, eq, _ = word.partition('=')
        if eq and name.startswith('--'):
            kinds = ('message', 'stdin', 'value')
            return next((k for k in kinds if name in getattr(self, k)), None), len(name) + 1
        kinds = ('message', 'stdin', 'value', 'boolean')
        kind = next((k for k in kinds if word in getattr(self, k)), None)
        cluster = self.short_cluster and re.fullmatch(rf'-([{self.short_cluster}]+)(m?)', word)
        if kind is None and cluster:
            kind = 'message' if cluster.group(2) else 'boolean'
        return kind, 0


def _spec(message, stdin, value='', boolean='', positionals=0, short_cluster=''):
    return Spec(frozenset(message.split()), frozenset(stdin.split()), frozenset(value.split()),
                frozenset(boolean.split()), positionals, short_cluster)


GH_REPO = '-R --repo '
TITLE_BODY = '-t --title -b --body'
BODY = '-b --body'
BODY_FILE = '-F --body-file'
COMMENT = '-c --comment'
PR_EDIT_VALUES = ('--add-label --remove-label --add-assignee --remove-assignee --add-reviewer '
                  '--remove-reviewer --add-project --remove-project -m --milestone ')
# Every word of a masked segment must be listed here, so the scanner parses it as gh/git would
SPECS = {
    ('gh', 'pr', 'create'): _spec(TITLE_BODY, BODY_FILE,
                                  GH_REPO + '-B --base -H --head -l --label -a --assignee '
                                  '-r --reviewer -m --milestone -p --project -T --template',
                                  '-d --draft -f --fill --fill-first --fill-verbose '
                                  '--no-maintainer-edit --dry-run'),
    ('gh', 'pr', 'comment'): _spec(BODY, BODY_FILE, GH_REPO,
                                   '--edit-last --create-if-none', 1),
    ('gh', 'pr', 'edit'): _spec(TITLE_BODY, BODY_FILE, GH_REPO + '-B --base ' + PR_EDIT_VALUES,
                                '--remove-milestone', 1),
    ('gh', 'pr', 'review'): _spec(BODY, BODY_FILE, GH_REPO,
                                  '-a --approve ' + COMMENT + ' -r --request-changes', 1),
    ('gh', 'pr', 'close'): _spec(COMMENT, '', GH_REPO, '-d --delete-branch', 1),
    ('gh', 'pr', 'reopen'): _spec(COMMENT, '', GH_REPO, '', 1),
    ('gh', 'pr', 'merge'): _spec('-t --subject -b --body', BODY_FILE,
                                 GH_REPO + '-A --author-email --match-head-commit',
                                 '-s --squash -m --merge -r --rebase --auto --admin '
                                 '-d --delete-branch', 1),
    ('gh', 'issue', 'create'): _spec(TITLE_BODY, BODY_FILE,
                                     GH_REPO + '-a --assignee -l --label -m --milestone '
                                     '-p --project -T --template'),
    ('gh', 'issue', 'comment'): _spec(BODY, BODY_FILE, GH_REPO,
                                      '--edit-last --create-if-none', 1),
    ('gh', 'issue', 'edit'): _spec(TITLE_BODY, BODY_FILE, GH_REPO + PR_EDIT_VALUES,
                                   '--remove-milestone', 1),
    ('gh', 'issue', 'close'): _spec(COMMENT, '', GH_REPO + '-r --reason', '', 1),
    ('gh', 'issue', 'reopen'): _spec(COMMENT, '', GH_REPO, '', 1),
    # Positionals after the tag are uploaded as assets, so only the tag is allowed
    ('gh', 'release', 'create'): _spec('-t --title -n --notes', '-F --notes-file',
                                       GH_REPO + '--target --discussion-category --notes-start-tag',
                                       '-d --draft -p --prerelease --latest --generate-notes '
                                       '--verify-tag', 1),
    ('gh', 'release', 'edit'): _spec('-t --title -n --notes', '-F --notes-file',
                                     GH_REPO + '--tag --target --discussion-category',
                                     '--draft --prerelease --latest --verify-tag', 1),
    ('git', 'commit'): _spec('-m --message', '-F --file', '',
                             '-a --all -q --quiet -s --signoff --amend --no-edit --allow-empty '
                             '--allow-empty-message --no-verify -n -v --verbose',
                             sys.maxsize, 'aqsnv'),
    ('git', 'tag'): _spec('-m --message', '-F --file', '', '-a --annotate -s --sign -f --force',
                          2, 'asf'),
}
# Any other command could redefine git or gh before the message segment runs
SEGMENT_COMMANDS = {'git', 'gh', 'cd'}
# Other git/gh segments could run masked text (rebase --exec, aliases, --upload-pack), and git
# accepts abbreviated long options, so their flags are an exact allowlist too
SAFE_GIT = {sub: frozenset(flags.split()) for sub, flags in {
    'add': '-A --all -u --update -N --intent-to-add -v --verbose --',
    'push': '-u --set-upstream -f --force --force-with-lease --force-if-includes --tags '
            '--follow-tags -q --quiet -v --verbose -d --delete -n --dry-run --no-verify',
    'status': '-s --short -b --branch -sb --porcelain -uno -unormal -uall',
    'log': '--oneline -1 -2 -3 -5 -10 -20 -n --stat --graph --decorate --all',
    'diff': '--stat --cached --staged --name-only --name-status --check',
    'show': '--stat --name-only --oneline -s --no-patch',
    'fetch': '--all --prune -p --tags -q --quiet',
    'pull': '-r --rebase --no-rebase --ff-only -q --quiet',
    'switch': '-c --create',
    'checkout': '-b -B',
    'branch': '--show-current -a --all -v -vv --list',
    'rev-parse': '--abbrev-ref --show-toplevel --short',
}.items()}
SAFE_GH = {('pr', 'view'), ('pr', 'list'), ('pr', 'status'), ('pr', 'checks'), ('pr', 'diff'),
           ('issue', 'view'), ('issue', 'list'), ('run', 'list'), ('run', 'view'),
           ('run', 'watch'), ('repo', 'view')}

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


def _substitution_end(cmd: str, j: int) -> Optional[int]:
    m = CAT_HEREDOC.match(cmd, j)
    end = _terminator(cmd, m.group(2), m.end())
    close = end and CLOSE_SUBSTITUTION.match(cmd, end.end())
    if not close:
        return None
    # Inside $( bash also ends the heredoc at a line like `EOF)`
    if re.search(rf'^{re.escape(m.group(2))}', cmd[m.end():end.start()], re.M):
        return None
    return close.end()


def _dollar(cmd: str, j: int, word: Word) -> Optional[int]:
    if CAT_HEREDOC.match(cmd, j):
        return _substitution_end(cmd, j)
    m = VARIABLE.match(cmd, j)
    if not m:
        return None
    word.kept.append(m.group())
    return m.end()


def _double_quoted(cmd: str, i: int, word: Word) -> Optional[int]:
    j = i + 1
    while j is not None and j < len(cmd):
        c = cmd[j]
        if c == '"':
            return j + 1
        if c == '`' or (c == '\\' and j + 1 >= len(cmd)):
            return None
        if c == '\\':
            j += 2
        elif c == '$':
            j = _dollar(cmd, j, word)
        else:
            j += 1
    return None


def _part_end(cmd: str, i: int, word: Word) -> Optional[int]:
    if cmd[i] == "'":
        end = cmd.find("'", i + 1)
        return end + 1 if end >= 0 else None
    if cmd[i] == '"':
        return _double_quoted(cmd, i, word)
    m = UNQUOTED.match(cmd, i)
    return m.end() if m else None


def _word_end(cmd: str, i: int, word: Word) -> Optional[int]:
    while i is not None and i < len(cmd) and cmd[i] not in ' \t\n;&|<':
        i = _part_end(cmd, i, word)
    if i is None or cmd.startswith(('&&', '||'), i):
        return i
    return None if i < len(cmd) and cmd[i] in '&|<' else i


def _heredoc_bodies(cmd: str, i: int, pending: List[Tuple[Segment, str]]) -> Optional[int]:
    for segment, delim in pending:
        end = _terminator(cmd, delim, i)
        if not end:
            return None
        segment.heredocs.append((i, end.start()))
        i = end.end()
    return i


def _heredoc_start(cmd: str, i: int, segment: Segment,
                   pending: List[Tuple[Segment, str]]) -> Optional[int]:
    m = HEREDOC.match(cmd, i)
    # Bash joins glued quoting into one delimiter: <<'E'"OF" ends at EOF
    if not m or (m.end() < len(cmd) and cmd[m.end()] not in ' \t\n;&|'):
        return None
    pending.append((segment, m.group(2)))
    return m.end()


def _separator_end(cmd: str, i: int, pending: List[Tuple[Segment, str]]) -> Optional[int]:
    if cmd[i] != '\n':
        return i + (1 if cmd[i] == ';' else 2)
    i = _heredoc_bodies(cmd, i + 1, pending)
    pending.clear()
    return i


def _scan(cmd: str) -> Optional[List[Segment]]:
    segments = [Segment()]
    pending: List[Tuple[Segment, str]] = []
    i = 0
    while i is not None and i < len(cmd):
        if cmd[i] in ' \t':
            i += 1
        elif cmd[i] == '<':
            i = _heredoc_start(cmd, i, segments[-1], pending)
        elif cmd.startswith(('\n', '&&', '||', ';'), i):
            segments.append(Segment())
            i = _separator_end(cmd, i, pending)
        else:
            word = Word(start=i)
            i = _word_end(cmd, i, word)
            word.end = i
            segments[-1].words.append(word)
    if i is None or pending:
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


def _safe(raw: List[str]) -> bool:
    if raw[0] == 'gh':
        return tuple(raw[1:3]) in SAFE_GH and all(UNQUOTED.fullmatch(w) for w in raw[3:])
    k = 3 if raw[1:2] == ['-C'] else 1
    flags = SAFE_GIT.get(raw[k]) if len(raw) > k else None
    return flags is not None and all(w in flags or _plain(w) for w in raw[k + 1:])


def _replacement(kept: List[str]) -> str:
    return '"' + ' '.join(kept) + '"' if kept else "''"


def _plain(word: str) -> bool:
    return UNQUOTED.fullmatch(word) is not None and not word.startswith('-')


def _inline_step(word: Word, value: str, kind: Optional[str], inline: int, k: int):
    if kind == 'message':
        return k + 1, (word.start + inline, word.end, _replacement(word.kept)), False
    if kind == 'stdin' and value == '-':
        return k + 1, None, True
    if kind == 'value' and UNQUOTED.fullmatch(value):
        return k + 1, None, False
    return None


def _step(raw: List[str], words: List[Word], spec: Spec, k: int):
    kind, inline = spec.option(raw[k])
    if inline:
        return _inline_step(words[k], raw[k][inline:], kind, inline, k)
    following = raw[k + 1] if k + 1 < len(raw) else None
    if kind == 'message' and following is not None:
        value = words[k + 1]
        return k + 2, (value.start, value.end, _replacement(value.kept)), False
    if kind == 'stdin' and following == '-':
        return k + 2, None, True
    if kind == 'value' and following is not None and _plain(following):
        return k + 2, None, False
    if kind == 'boolean':
        return k + 1, None, False
    return None


def _parse(raw: List[str], words: List[Word], spec: Spec, k: int) -> Optional[Tuple[list, bool]]:
    edits = []
    reads_stdin = False
    positionals = 0
    while k < len(words):
        if _plain(raw[k]) and positionals < spec.positionals:
            positionals += 1
            k += 1
            continue
        step = _step(raw, words, spec, k)
        if step is None:
            return None
        k, edit, stdin = step
        edits += [edit] if edit else []
        reads_stdin = reads_stdin or stdin
    return edits, reads_stdin


def _edits(cmd: str, segment: Segment) -> Optional[List[Tuple[int, int, str]]]:
    words = segment.words
    raw = [cmd[w.start:w.end] for w in words]
    if raw[:1] in ([], ['cd']):
        return []
    spec, k = _message_spec(raw)
    if spec is None:
        return [] if not segment.heredocs and _safe(raw) else None
    parsed = _parse(raw, words, spec, k)
    if parsed is None:
        return None
    edits, reads_stdin = parsed
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
