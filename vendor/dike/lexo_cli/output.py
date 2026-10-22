"""Output formatting for the CLI."""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import print as rprint

# Lo que el abogado pidió va a stdout; los diagnósticos, a stderr.
#
# Todo salía por stderr, incluidas las tablas de resultados: `dike buscar
# "lesión enorme" | less` no mostraba nada y `> resultados.txt` guardaba un
# archivo vacío. Y al revés, `2>/dev/null` para silenciar avisos borraba
# también los resultados. La única salida que ya estaba bien era `--json`.
console = Console()
err_console = Console(stderr=True)


def output_json(data: Any) -> None:
    """Output data as JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def output_text(text: str, verbose: bool = False) -> None:
    """Output text to stdout."""
    print(text)


def output_error(message: str) -> None:
    """Output error to stderr."""
    err_console.print(f"[bold red]ERROR:[/bold red] {message}")


def output_warning(message: str) -> None:
    """Output warning to stderr."""
    err_console.print(f"[bold yellow]⚠[/bold yellow] {message}")


def output_success(message: str) -> None:
    """Output success to stderr."""
    err_console.print(f"[bold green]✓[/bold green] {message}")


def output_info(message: str) -> None:
    """Output info to stderr."""
    err_console.print(f"[dim]{message}[/dim]")


def format_verdict(verdict: str, rating: float | None = None) -> str:
    """Format a verdict with color/emoji."""
    colors = {
        "Aprobado": "green",
        "Aprobado con reservas": "yellow",
        "Necesita revisión": "orange3",
        "Rechazado": "red",
        "ABSTENCIÓN": "bold red",
    }
    color = colors.get(verdict, "white")
    rating_str = f" (rating: {rating:.1f}/10)" if rating is not None else ""
    return f"[bold {color}]{verdict}[/bold {color}]{rating_str}"


def format_nif_summary(nif_data: dict) -> Table:
    """Format NIF data as a Rich table."""
    table = Table(title="Normative Interaction Frame (NIF)", show_lines=True)
    table.add_column("Campo", style="bold")
    table.add_column("Contenido")

    for key, value in nif_data.items():
        if isinstance(value, list):
            content = ", ".join(str(v) for v in value[:5])
            if len(value) > 5:
                content += f" ... (+{len(value) - 5})"
        elif isinstance(value, dict):
            content = json.dumps(value, ensure_ascii=False)[:100]
        else:
            content = str(value)[:200] if value else "—"
        table.add_row(key, content)

    return table
