"""Agent invoker — replaces Hermes subagent_profiles.

Resolves paths to subagent scripts without depending on ~/.hermes/profiles/.
Each subagent lives at: subagents/{agent_id}/scripts/{agent_id}.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from lexo_cli.config import subagents_root


# Map of agent_id → script filename (without .py)
AGENT_SCRIPTS: dict[str, str] = {
    "contradictor": "contradict",
    "juez": "evaluate_document",
    "case_designer": "design_case",
    "rhetoric_writer": "write_document",
    "procurador": "procurador_engine",
    "docs_assembler": "assemble_document",
    "benchmark_master": "benchmark",
}

# Agents that can be invoked as scripts (have argparse + __main__)
CLI_AGENTS = set(AGENT_SCRIPTS.keys())


def get_script_path(agent_id: str) -> Path:
    """Return the Path to a subagent's main script."""
    script_name = AGENT_SCRIPTS.get(agent_id)
    if not script_name:
        raise ValueError(
            f"Unknown agent: {agent_id}. Available: {', '.join(sorted(CLI_AGENTS))}"
        )
    script_path = subagents_root() / agent_id / "scripts" / f"{script_name}.py"
    if not script_path.exists():
        raise FileNotFoundError(
            f"Script not found: {script_path}. "
            f"Ensure subagents/{agent_id}/scripts/{script_name}.py exists."
        )
    return script_path


def invoke_cli_agent(agent_id: str, input_data: dict[str, Any], **kwargs) -> dict:
    """Invoke a subagent CLI with JSON input, return parsed JSON output.

    Args:
        agent_id: One of CLI_AGENTS.
        input_data: Dict to pass as JSON input (via temp file).
        **kwargs: Additional CLI flags (e.g., area="laboral").

    Returns:
        Parsed JSON output from the subagent.
    """
    import json
    import tempfile
    import os

    script_path = get_script_path(agent_id)

    # Write input to temp file — subagents expect --input as a file path
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
        encoding="utf-8",
    ) as tf:
        json.dump(input_data, tf, ensure_ascii=False)
        tmp_path = tf.name

    cmd = [sys.executable, str(script_path), "--input", tmp_path]

    # Pass extra kwargs as --key value
    for k, v in kwargs.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                cmd.append(flag)
        else:
            cmd.extend([flag, str(v)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Some agents (juez) use exit code 1 as a quality gate (rating < 6.0),
    # not as a crash. If stdout has valid JSON, accept it.
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Agent {agent_id} failed (exit {result.returncode}):\n"
        f"stderr: {result.stderr[:500]}\n"
        f"stdout: {result.stdout[:500]}"
    )


def resolve_document(arg: str) -> str:
    """Resuelve el argumento 'documento' a su texto.

    Un argumento con extensión de documento (.docx, .pdf, .txt…) es SIEMPRE
    una referencia a un archivo: si no se puede leer, es un error. Antes se
    devolvía la ruta como si fuera el contenido, y el juez terminaba
    puntuando el nombre del archivo —«demanda.docx», nota 2.1/10— como si
    fuera el escrito del abogado.
    """
    from lexo_cli.documento import DocumentoIlegible, looks_like_path, read_document

    if looks_like_path(arg):
        return read_document(arg)
    # Sin extensión reconocible: puede ser una ruta igualmente (un archivo sin
    # extensión) o el texto pegado directamente.
    if "\n" not in arg and len(arg) < 256:
        try:
            if Path(arg).is_file():
                return read_document(arg)
        except (OSError, DocumentoIlegible):
            pass
    return arg


def invoke_import_agent(agent_id: str, fn_name: str, *args, **kwargs):
    """Import and call a function from a subagent module directly.

    Faster than subprocess, but runs in the same process.
    """
    import importlib

    script_name = AGENT_SCRIPTS.get(agent_id)
    if not script_name:
        raise ValueError(f"Unknown agent: {agent_id}")

    module_path = f"subagents.{agent_id}.scripts.{script_name}"
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(f"Cannot import {module_path}: {exc}") from exc

    fn = getattr(mod, fn_name, None)
    if fn is None:
        raise AttributeError(
            f"{module_path} has no function '{fn_name}'. "
            f"Available: {[x for x in dir(mod) if not x.startswith('_')][:10]}..."
        )
    return fn(*args, **kwargs)
