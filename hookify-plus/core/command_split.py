"""Split a shell command into the commands it runs one after another.

Anything it cannot read with certainty returns None, so the caller keeps the whole command.
"""

import re
from functools import lru_cache
from typing import List, Optional, Tuple

UNSPLITTABLE = re.compile(r"<<|\$'|(?<![\w-])case(?![\w-])")
COMMENT_BEFORE = frozenset(" \t\r\n;&|()<>`")
PARAM = "${"


class _UnsplittableError(Exception):
    pass


class _Splitter:
    def __init__(self, command: str):
        self.command = command
        self.stack: List[str] = []
        self.pieces: List[str] = []
        self.current: List[str] = []

    def run(self) -> Optional[Tuple[str, ...]]:
        i = 0
        try:
            while i < len(self.command):
                i += self._step(i)
        except _UnsplittableError:
            return None
        if self.stack:
            return None
        self._cut()
        return tuple(p for p in (piece.strip() for piece in self.pieces) if p)

    def _cut(self) -> None:
        self.pieces.append("".join(self.current))
        self.current = []

    def _step(self, i: int) -> int:
        """Handle the text at i and return how many characters it used."""
        c = self.command[i]
        pair = self.command[i : i + 2]
        top = self.stack[-1] if self.stack else ""
        if c == "\\" and top != "'":
            # A backslash-newline is gone before the shell reads the line
            self.current.append("" if pair == "\\\n" else pair)
            return 2
        if top == "'":
            self._single(c)
        elif top == PARAM:
            return self._param(c, pair)
        elif pair in ("$(", "${"):
            self.stack.append(")" if pair == "$(" else PARAM)
            self.current.append(pair)
            return 2
        elif top == '"':
            self._double(c)
        else:
            return self._command(i, c, pair, top)
        self.current.append(c)
        return 1

    def _single(self, c: str) -> None:
        if c == "'":
            self.stack.pop()

    def _double(self, c: str) -> None:
        if c == '"':
            self.stack.pop()
        elif c == "`":
            self.stack.append(c)

    def _param(self, c: str, pair: str) -> int:
        """Inside ${..} only the closing brace matters; anything fancier is not worth reading."""
        if c in "'\"`" or pair in ("$(", "${"):
            raise _UnsplittableError
        if c == "}":
            self.stack.pop()
        self.current.append(c)
        return 1

    def _command(self, i: int, c: str, pair: str, top: str) -> int:
        if c == "`" and top == "`":
            self.stack.pop()
        elif c in "'\"`":
            self.stack.append(c)
        elif c in "({":
            self.stack.append(")" if c == "(" else "}")
        elif c in ")}":
            if top != c:
                raise _UnsplittableError
            self.stack.pop()
        elif c == "#" and (i == 0 or self.command[i - 1] in COMMENT_BEFORE):
            raise _UnsplittableError
        elif not self.stack and (c in ";\n" or pair in ("&&", "||")):
            self._cut()
            return 1 if c in ";\n" else 2
        self.current.append(c)
        return 1


@lru_cache(maxsize=64)
def split_commands(command: str) -> Optional[Tuple[str, ...]]:
    """Top-level commands split on ; && || and newlines, or None when it cannot be split safely."""
    if UNSPLITTABLE.search(command):
        return None
    return _Splitter(command).run()
