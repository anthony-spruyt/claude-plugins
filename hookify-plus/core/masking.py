#!/usr/bin/env python3
"""Blank text in a shell command that is data, not code.

Heredoc bodies fed to non-interpreters and gh/git message arguments are prose.
Quoted text is removed; expansions that the shell would run are kept.
"""

import re

INTERPRETER = re.compile(
    r'\b(?:python[0-9.]*|node|deno|bun|bash|sh|zsh|dash|ksh|fish|ruby|perl|php|pwsh|awk'
    r'|exec|eval|source|ssh|xargs)\b|(?:^|[;&|(]\s*)\.\s')
MESSAGE_CMD = re.compile(r'(?:^|[;&|(]\s*)(?:gh|git|glab)\s')
MESSAGE_ARG = re.compile(
    r'(?<=\s)(--body|--title|--message|--notes|--subject|-m)([\s=]+)("(?:[^"\\]|\\.)*"|\'[^\']*\')'
    r'(?=\s|$|[;&|)])')
EXPANSION = re.compile(r'\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*')
HEREDOC = re.compile(
    r'<<-?[^\S\n]*([\'"]?)(\w+)\1([^\n]*)\n(.*?)(\n[^\S\n]*\2[^\S\n]*)(?=\n|$|\))', re.S)


def _line_before(text: str, pos: int) -> str:
    return text[text.rfind('\n', 0, pos) + 1:pos]


def mask_data(command: str) -> str:
    def heredoc(m):
        quote, delim, rest, body, end = m.groups()
        if INTERPRETER.search(_line_before(command, m.start()) + rest):
            return m.group(0)
        kept = '' if quote else ' '.join(EXPANSION.findall(body))
        return f'<<{quote}{delim}{quote}{rest}\n{kept}{end}'

    masked = HEREDOC.sub(heredoc, command)

    def message(m):
        flag, sep, value = m.groups()
        if not MESSAGE_CMD.search(_line_before(masked, m.start())):
            return m.group(0)
        if value.startswith("'"):
            return f"{flag}{sep}''"
        return f'{flag}{sep}"' + ' '.join(EXPANSION.findall(value[1:-1])) + '"'

    return MESSAGE_ARG.sub(message, masked)
