""" migration_utils.py

shared helpers for all Django/CMS upgrade steps.

import from any step script: `from migration_utils import *`
"""
import re
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union


# colour helpers (no external deps) ─────────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def ok(msg): print(f"{GREEN}  ✔  {msg}{RESET}")
def info(msg): print(f"{CYAN}  ℹ  {msg}{RESET}")
def warn(msg): print(f"{YELLOW}  ⚠  {msg}{RESET}")
def error(msg): print(f"{RED}  ✘  {msg}{RESET}")


def banner(title: str):
    line = "─" * (len(title) + 4)
    print(f"\n{CYAN}┌{line}┐")
    print(f"│  {title}  │")
    print(f"└{line}┘{RESET}\n")


# shell / pip helpers  ─────────────────────────────────────────────

def run(cmd: str, cwd: Optional[str] = None, check: bool = True) -> int:
    """Run a shell command, stream output, return exit code."""
    info(f"$ {cmd}")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        stdout=sys.stdout, stderr=sys.stderr
    )
    if check and result.returncode != 0:
        error(f"Command failed (exit {result.returncode}): {cmd}")
        raise SystemExit(result.returncode)
    return result.returncode


def pip_install(*packages: str, upgrade: bool = True):
    flag = "--upgrade" if upgrade else ""
    pkgs = " ".join(packages)
    run(f"{sys.executable} -m pip install {flag} {pkgs}")


def pip_uninstall(*packages: str):
    pkgs = " ".join(packages)
    run(f"{sys.executable} -m pip uninstall -y {pkgs}", check=False)


# file / text helpers  ─────────────────────────────────────────────

def backup_file(path: Union[Path, str]) -> Path:
    """Copy file → file.bak (overwrites existing .bak)."""
    src = Path(path)
    dst = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, dst)
    ok(f"Backed up {src} → {dst.name}")
    return dst


def replace_in_file(path: Union[Path, str], old: str, new: str,
                    count: int = 0, regex: bool = False) -> int:
    """
    Replace text in a file in-place.
    Returns number of substitutions made.
    """
    p = Path(path)
    original = p.read_text(encoding="utf-8")
    if regex:
        modified, n = re.subn(old, new, original, count=count)
    else:
        n = original.count(old)
        if count:
            modified = original.replace(old, new, count)
            n = min(n, count)
        else:
            modified = original.replace(old, new)
    if n:
        p.write_text(modified, encoding="utf-8")
        ok(f"  {p}: {n} replacement(s)  '{old[:60]}' → '{new[:60]}'")
    return n


def replace_in_dir(root: Union[Path, str], glob: str,
                   old: str, new: str, regex: bool = False) -> int:
    """Apply replace_in_file to every matching file under root."""
    total = 0
    for p in Path(root).rglob(glob):
        total += replace_in_file(p, old, new, regex=regex)
    return total


def ensure_setting(settings_path: Union[Path, str], key: str, value: str):
    """
    If `key` is not already in the settings file, append it.
    value should be the full right-hand side (e.g. '"sqlite3"' or 'True').
    """
    p = Path(settings_path)
    content = p.read_text(encoding="utf-8")
    pattern = rf"^\s*{re.escape(key)}\s*="
    if re.search(pattern, content, re.MULTILINE):
        warn(f"Setting '{key}' already present in {p.name} – skipping.")
    else:
        p.write_text(content + f"\n{key} = {value}\n", encoding="utf-8")
        ok(f"Added '{key} = {value}' to {p.name}")


def comment_out_setting(settings_path: Union[Path, str], key: str):
    replace_in_file(settings_path,
                    f"\n{key}",
                    f"\n# {key}",
                    regex=False)


def manage(project_root: Union[Path, str], *args: str, settings_module: Optional[str] = None):
    """ Django management command runner. """
    root = Path(project_root)
    manage_py = root / "manage.py"
    if not manage_py.exists():
        error(f"manage.py not found in {root}")
        raise FileNotFoundError(manage_py)
    env_flag = f"DJANGO_SETTINGS_MODULE={settings_module} " if settings_module else ""
    run(f"{env_flag}{sys.executable} manage.py {' '.join(args)}", cwd=str(root))


def update_requirements(req_file: Union[Path, str],
                        updates: dict[str, str],
                        removals: Optional[list[str]] = None,
                        additions: Optional[list[str]] = None):
    """ requirements.txt helper, rewriting a requirements file:
      updates  = { "package-name": "==X.Y.Z" }   (case-insensitive name match)
      removals = ["package-to-drop", ...]
      additions= ["new-package==X.Y.Z", ...]
    """
    p = Path(req_file)
    backup_file(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # skip blank / comment
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        # extract package name (before any version specifier or extras)
        pkg_name = re.split(r"[=<>!\[;@\s]", stripped)[0].lower()
        if removals and pkg_name in [r.lower() for r in removals]:
            warn(f"  Removing: {stripped}")
            continue
        if updates:
            for upd_name, upd_ver in updates.items():
                if pkg_name == upd_name.lower():
                    new_line = f"{upd_name}{upd_ver}"
                    ok(f"  Updating: {stripped}  →  {new_line}")
                    line = new_line
                    break
        new_lines.append(line)
    if additions:
        new_lines.append("")
        for add in additions:
            new_lines.append(add)
            ok(f"  Adding: {add}")
    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def backup_sqlite(db_path: Union[Path, str], label: str = ""):
    """ DB backup helper. """
    src = Path(db_path)
    if not src.exists():
        warn(f"DB not found at {src} – skipping backup.")
        return
    suffix = f"_{label}" if label else ""
    dst = src.with_name(src.stem + suffix + ".db.bak")
    shutil.copy2(src, dst)
    ok(f"DB backed up → {dst}")


# Pre-flight checks ─────────────────────────────────────────────

def check_python_version(min_tuple: tuple[int, int]):
    if sys.version_info < min_tuple:
        error(f"Python {'.'.join(map(str, min_tuple))}+ required, "
              f"you have {sys.version}")
        raise SystemExit(1)
    ok(f"Python {sys.version.split()[0]} ✔")


def check_venv():
    if sys.prefix == sys.base_prefix:
        warn("Not inside a virtual environment – strongly recommended!")
    else:
        ok(f"Virtual env: {sys.prefix}")
