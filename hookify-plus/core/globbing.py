#!/usr/bin/env python3
"""Expand a word's braces and globs the way bash would, against the current directory.

Patterns mark quoted characters with a backslash. Expansion gives up (None) rather
than spend more than MAX_WORDS results or MAX_ENTRIES directory entries.
"""

import itertools
import os
import re
from typing import List, Optional

MAX_WORDS = 256
MAX_ENTRIES = 20000
MAX_NESTING = 8
MAX_CHARS = 320000

SEQUENCE = re.compile(r"(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(?:\.\.(-?\d+))?$")
GLOB = re.compile(r"\\.|([*?\[])", re.DOTALL)
UNESCAPE = re.compile(r"\\(.)", re.DOTALL)
CLASSES = {
    "alpha": "a-zA-Z",
    "digit": "0-9",
    "alnum": "a-zA-Z0-9",
    "upper": "A-Z",
    "lower": "a-z",
    "space": r" \t\n\r\f\v",
    "blank": r" \t",
    "xdigit": "0-9A-Fa-f",
    "word": r"\w",
    "punct": r"!-/:-@\[-`{-~",
    "print": r" -~",
    "graph": r"!-~",
    "cntrl": r"\x00-\x1f\x7f",
}


class _TooMuchError(Exception):
    pass


def expand(pattern: str, budget: Optional[List[int]] = None, cwd: str = "") -> Optional[List[str]]:
    """Words bash makes of `pattern` in `cwd`, or None when that costs more than `budget` entries allows."""
    budget = [MAX_ENTRIES] if budget is None else budget
    try:
        out = []
        for word in _braces(pattern):
            matches = _glob(word, budget, cwd) if _has_glob(word) else []
            # An unmatched glob stays as written, as bash leaves it without nullglob
            out.extend(matches or [UNESCAPE.sub(r"\1", word)])
            if len(out) > MAX_WORDS:
                raise _TooMuchError
        return out
    except (_TooMuchError, RecursionError):
        return None


def _has_glob(word: str) -> bool:
    return any(m.group(1) for m in GLOB.finditer(word))


def _braces(word: str, depth: int = 0) -> List[str]:
    if depth > MAX_NESTING:
        raise _TooMuchError
    choices, last = [], 0
    for start, end, items in _groups(word):
        choices.append([word[last:start]])
        choices.append([w for item in items for w in _braces(item, depth + 1)])
        last = end + 1
    if not choices:
        return [word]
    choices.append([word[last:]])
    count = 1
    for choice in choices:
        count *= len(choice)
        if count > MAX_WORDS:
            raise _TooMuchError
    if count * len(word) > MAX_CHARS:
        raise _TooMuchError
    return ["".join(parts) for parts in itertools.product(*choices)]


def _groups(word: str):
    """Outermost `{...}` groups bash expands, as (start, end, items). One pass, so `{{{{...` stays linear."""
    stack, closed, i = [], {}, 0
    while i < len(word):
        c = word[i]
        if c == "\\":
            i += 1
        elif c == "{":
            stack.append((i, []))
        elif c == "," and stack:
            stack[-1][1].append(i)
        elif c == "}" and stack:
            start, commas = stack.pop()
            closed[start] = (i, commas)
        i += 1
    groups, covered = [], -1
    for start in sorted(closed):
        if start < covered:
            continue
        end, commas = closed[start]
        if commas:
            cuts = [start, *commas, end]
            items = [word[a + 1 : b] for a, b in zip(cuts, cuts[1:])]
        else:
            items = _sequence(word, start + 1, end)
        if items:
            groups.append((start, end, items))
            covered = end
    return groups


def _sequence(word: str, start: int, end: int) -> Optional[List[str]]:
    m = SEQUENCE.match(word, start, end)
    if not m or m.group(1).isalpha() != m.group(2).isalpha():
        return None
    letters = m.group(1).isalpha()
    first, last = (ord(m.group(1)), ord(m.group(2))) if letters else (int(m.group(1)), int(m.group(2)))
    step = abs(int(m.group(3) or 1)) or 1
    if abs(last - first) // step >= MAX_WORDS:
        raise _TooMuchError
    values = range(first, last + 1, step) if first <= last else range(first, last - 1, -step)
    return [chr(v) if letters else str(v) for v in values]


def _glob(word: str, budget: List[int], cwd: str) -> List[str]:
    if word.startswith("~/"):
        word = os.path.expanduser("~") + word[1:]
    parts = word.split("/")
    paths = ["/" if word.startswith("/") else ""]

    def on_disk(path):
        return os.path.join(cwd, path) if cwd else path

    for n, part in enumerate(parts):
        if not part:
            continue
        last = n == len(parts) - 1 or not any(parts[n + 1 :])
        if not _has_glob(part):
            paths = [p + UNESCAPE.sub(r"\1", part) + ("" if last else "/") for p in paths]
            continue
        regex, dotted = _segment(part), part.lstrip("\\").startswith(".")
        found = []
        for path in paths:
            for name in _entries(on_disk(path or "."), budget):
                if (dotted or not name.startswith(".")) and regex.fullmatch(name):
                    full = path + name
                    if last or os.path.isdir(on_disk(full)):
                        found.append(full + ("" if last else "/"))
            if len(found) > MAX_WORDS:
                raise _TooMuchError
        paths = found
    if word.endswith("/"):
        paths = [p.rstrip("/") + "/" for p in paths if os.path.isdir(on_disk(p))]
    return sorted(p for p in paths if os.path.lexists(on_disk(p)))


def _entries(path: str, budget: List[int]) -> List[str]:
    try:
        with os.scandir(path) as it:
            names = []
            for entry in it:
                budget[0] -= 1
                if budget[0] < 0:
                    raise _TooMuchError
                names.append(entry.name)
            return names
    except OSError:
        return []


def _segment(part: str) -> "re.Pattern":
    out, i = [], 0
    while i < len(part):
        c = part[i]
        if c == "\\":
            out.append(re.escape(part[i + 1 : i + 2]))
            i += 2
        elif c == "*":
            out.append(".*")
            i += 1
        elif c == "?":
            out.append(".")
            i += 1
        elif c == "[":
            cls, i = _bracket(part, i)
            out.append(cls)
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def _bracket(part: str, start: int):
    i = start + 1
    negate = i < len(part) and part[i] in "!^"
    i += negate
    body, first = [], True
    while i < len(part):
        c = part[i]
        if c == "]" and not first:
            return ("[^" if negate else "[") + "".join(body) + "]", i + 1
        first = False
        if c == "[" and part.startswith(":", i + 1):
            end = part.find(":]", i + 2)
            name = part[i + 2 : end] if end > 0 else ""
            if name in CLASSES:
                body.append(CLASSES[name])
                i = end + 2
                continue
        if c == "\\" and i + 1 < len(part):
            body.append(re.escape(part[i + 1]))
            i += 2
        elif c == "-" and body and i + 1 < len(part) and part[i + 1] != "]":
            body.append("-")
            i += 1
        else:
            body.append(re.escape(c))
            i += 1
    return re.escape("["), start + 1
