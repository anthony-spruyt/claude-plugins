"""Maps Claude Code tool names to hookify rule events."""

from typing import Optional

TOOL_EVENTS = {
    'Bash': 'bash',
    'PowerShell': 'bash',
    'Monitor': 'bash',
    'Edit': 'file',
    'Write': 'file',
    'NotebookEdit': 'file',
    'Read': 'read',
    'Glob': 'read',
    'Grep': 'read',
}


def event_for_tool(tool_name: str) -> Optional[str]:
    """Return the rule event for a tool, or None if no event covers it."""
    return TOOL_EVENTS.get(tool_name)
