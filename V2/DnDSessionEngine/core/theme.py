from rich.console import Console
from rich.theme import Theme

CUSTOM_THEME = Theme(
    {
        # Structural
        "rule.header": "bold green",
        "rule.section": "bold magenta",
        "rule.sub": "dim white",
        # UI Elements
        "menu.key": "bold yellow",
        "menu.label": "white",
        "hint": "dim white",
        # Status & Feedback
        "success": "bold green",
        "warning": "bold yellow",
        "danger": "bold red",
        "empty": "bold red italic",
        "highlight": "cyan",
        # Tables
        "table.title": "bold cyan",
        "table.border": "dim",
        "table.header": "bold magenta",
        "table.column1": "yellow",
        "table.column2": "green",
    }
)

con = Console(theme=CUSTOM_THEME)
