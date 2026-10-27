"""Subprocess wrapper around the Diké CLI. Never reinterprets the verdict."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path

from shield.env import ROOT, load_env

VENDOR_DIKE = ROOT / "vendor" / "dike"
CORPUS_TAR = VENDOR_DIKE / "corpus" / "chile-base-af1422d66d1e6eee.tar.gz"
PACK_NAME = "chile-base"
USER = "shield"


def dike_paths(env: dict[str, str] | None = None) -> dict[str, Path]:
    cfg = env or load_env()
    home = Path(cfg.get("DIKE_HOME_DIR", ".local/dike-home"))
    if not home.is_absolute():
        home = ROOT / home
    users = home / "users"
    return {
        "home": home,
        "users": users,
        "pack": home / "pack-src" / PACK_NAME,
        "key": (
            Path(cfg.get("DIKE_SIGNING_KEY_PATH", ".local/keys/demo-content-signing-key.pem"))
            if Path(cfg.get("DIKE_SIGNING_KEY_PATH", "")).is_absolute()
            else ROOT / cfg.get("DIKE_SIGNING_KEY_PATH", ".local/keys/demo-content-signing-key.pem")
        ),
        "config": home / "config.yaml",
        "tmp": home / "tmp",
    }


def isolated_env(env: dict[str, str] | None = None) -> dict[str, str]:
    cfg = env or load_env()
    paths = dike_paths(cfg)
    home = str(paths["home"])
    key = paths["key"]
    merged = {
        **os.environ,
        "HOME": home,
        "LEXO_CONFIG": str(paths["config"]),
        "DIKE_USER": USER,
        "DIKE_USERS_ROOT": str(paths["users"]),
        "DIKE_HOME_DIR": home,
        "LEXO_CASES_ROOT": str(paths["home"] / "cases"),
        "DIKE_BINDING_CACHE_DIR": str(paths["home"] / "cache" / "binding"),
        "DIKE_ROOTS_CACHE_DIR": str(paths["home"] / "cache" / "roots"),
        "LEXO_BCN_CACHE_DIR": str(paths["home"] / "cache" / "bcn"),
    }
    if key.is_file():
        merged["LEXO_CONTENT_SIGNING_KEY_PATH"] = str(key)
        merged["DIKE_SIGNING_KEY_PATH"] = str(key)
    return merged


def dike_cmd() -> list[str]:
    return ["uv", "run", "--directory", str(VENDOR_DIKE), "dike"]


def ensure_cli() -> list[str]:
    cmd = dike_cmd()
    probe = subprocess.run(
        cmd + ["--help"],
        capture_output=True,
        text=True,
        env=isolated_env(),
        timeout=180,
    )
    if probe.returncode != 0:
        sync = subprocess.run(
            ["uv", "sync"],
            cwd=VENDOR_DIKE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if sync.returncode != 0:
            raise RuntimeError("uv sync vendor/dike failed")
    return cmd


def ensure_corpus(cmd: list[str] | None = None) -> Path:
    """Install chile-base into the isolated HOME if it is not already there."""
    cmd = cmd or ensure_cli()
    paths = dike_paths()
    paths["home"].mkdir(parents=True, exist_ok=True)
    paths["users"].mkdir(parents=True, exist_ok=True)
    marker = paths["users"] / USER / "starter" / PACK_NAME
    if (marker / "STATE.json").is_file():
        return marker
    pack = paths["pack"]
    if not pack.is_dir():
        pack.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(CORPUS_TAR) as tar:
            tar.extractall(pack.parent)
    install = subprocess.run(
        cmd
        + [
            "starter",
            "--user",
            USER,
            "--users-root",
            str(paths["users"]),
            "install",
            str(pack),
            "--name",
            PACK_NAME,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=isolated_env(),
        timeout=180,
    )
    if install.returncode != 0:
        raise RuntimeError(
            f"dike starter install failed rc={install.returncode}"
        )
    return marker


def _parse_json(stdout: str) -> dict:
    text = stdout.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise json.JSONDecodeError("root is not an object", text, 0)
    return value


def verificar(texto: str, *, timeout: int = 180) -> dict:
    """Run `dike constancia --json` and return the CLI JSON unchanged.

    Exit code 1 means some citations failed; that is not an adapter error.
    """
    cmd = ensure_cli()
    ensure_corpus(cmd)
    paths = dike_paths()
    paths["tmp"].mkdir(parents=True, exist_ok=True)
    sample = paths["tmp"] / "constancia.md"
    sample.write_text(texto, encoding="utf-8")
    run = subprocess.run(
        cmd
        + [
            "constancia",
            str(sample),
            "--json",
            "--user",
            USER,
            "--users-root",
            str(paths["users"]),
        ],
        capture_output=True,
        text=True,
        env=isolated_env(),
        timeout=timeout,
    )
    try:
        result = _parse_json(run.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"dike constancia produced no JSON rc={run.returncode}"
        ) from exc
    result["_rc"] = run.returncode
    return result


def emitir_commitment(texto: str, dest: Path, *, timeout: int = 180) -> dict | None:
    """Sign verified citations. Returns None if Diké emits nothing (exit 2)."""
    cmd = ensure_cli()
    ensure_corpus(cmd)
    paths = dike_paths()
    paths["tmp"].mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    sample = dest / "escrito.md"
    sample.write_text(texto, encoding="utf-8")
    run = subprocess.run(
        cmd
        + [
            "constancia",
            str(sample),
            "--json",
            "--emit-commitment",
            str(dest),
            "--sign",
            "--user",
            USER,
            "--users-root",
            str(paths["users"]),
        ],
        capture_output=True,
        text=True,
        env=isolated_env(),
        timeout=timeout,
    )
    commitment = dest / "commitment.json"
    if not commitment.is_file():
        return None
    sig = dest / "commitment.sig.json"
    pub = dest / "content-signing-key.pub"
    payload: dict = {"commitment": _parse_json(commitment.read_text(encoding="utf-8"))}
    if sig.is_file():
        payload["signature"] = _parse_json(sig.read_text(encoding="utf-8"))
    if pub.is_file():
        payload["public_key_pem"] = pub.read_text(encoding="utf-8")
    payload["_rc"] = run.returncode
    return payload
