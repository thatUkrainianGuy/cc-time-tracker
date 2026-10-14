"""Install/uninstall the cc-time-sync launchd agent + write a config template."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .sync import CONFIG_FILE, TRACKING_DIR
from .common import atomic_write_text, ensure_dir, harden_file_perms

LABEL = "rocks.thatukrainianguy.cc-time-sync"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

# The launchd agent cannot import the package from its normal home when that
# home is a TCC-protected folder. An editable install's source lives in the repo
# (commonly ~/Documents/...), and macOS denies background LaunchAgents read
# access to Documents/Desktop/Downloads — so `-m cc_time_tracker.sync` dies with
# ModuleNotFoundError even though it works from an (already-granted) terminal.
# Granting the interpreter Full Disk Access is not durable: a Homebrew python
# relink swaps the binary identity and drops the grant (this is what silently
# broke sync on 2026-06-23). Instead we mirror the package into TRACKING_DIR
# (under ~/.claude, already agent-readable) and point the agent's PYTHONPATH
# there. Snapshot semantics: re-run `install` after editing sync/common code.
PKG_DIR = Path(__file__).resolve().parent           # .../cc_time_tracker
AGENT_LIB_DIR = TRACKING_DIR / "agent-lib"           # PYTHONPATH root for the agent


def _mirror_package() -> Path:
    """Copy the cc_time_tracker package to a launchd-readable location and
    return the directory to put on the agent's PYTHONPATH."""
    ensure_dir(AGENT_LIB_DIR)
    dest = AGENT_LIB_DIR / PKG_DIR.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PKG_DIR, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return AGENT_LIB_DIR


def _build_plist(pythonpath: Path) -> dict:
    return {
        "Label": LABEL,
        # Absolute interpreter (not `env python3`) so a relinked Homebrew python
        # on PATH can't repoint the job at an interpreter without the package.
        "ProgramArguments": [
            sys.executable,
            "-m",
            "cc_time_tracker.sync",
        ],
        "EnvironmentVariables": {"PYTHONPATH": str(pythonpath)},
        "StartInterval": 900,  # 15 min
        "StandardOutPath": str(TRACKING_DIR / "cc-time-sync.log"),
        "StandardErrorPath": str(TRACKING_DIR / "cc-time-sync.err"),
        "RunAtLoad": True,
    }


def _bootout() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _reload_agent() -> int:
    """Reload via bootout/bootstrap. Legacy `launchctl load/unload` silently
    no-op against an already-bootstrapped job, so plist changes wouldn't apply."""
    _bootout()
    return subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)], check=False,
    ).returncode


def install(endpoint: str | None) -> int:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_dir(TRACKING_DIR)
    pythonpath = _mirror_package()
    print(f"mirrored package to {pythonpath / PKG_DIR.name}")
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(_build_plist(pythonpath), f)
    print(f"wrote {PLIST_PATH}")

    if not CONFIG_FILE.exists():
        template = {
            "endpoint": endpoint or "https://projects.thatukrainianguy.rocks/api/sync",
            "api_key": "REPLACE_ME",
        }
        atomic_write_text(CONFIG_FILE, json.dumps(template, indent=2) + "\n")
        harden_file_perms(CONFIG_FILE)
        print(f"wrote config template at {CONFIG_FILE} — fill in api_key before reloading")
    else:
        harden_file_perms(CONFIG_FILE)
        print(f"config already exists at {CONFIG_FILE} — leaving as-is")

    rc = _reload_agent()
    if rc != 0:
        print(f"launchctl reload returned {rc}", file=sys.stderr)
        return rc
    print("loaded.")
    return 0


def uninstall() -> int:
    _bootout()
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"removed {PLIST_PATH}")
    else:
        print("plist not found — nothing to do")
    if AGENT_LIB_DIR.exists():
        shutil.rmtree(AGENT_LIB_DIR, ignore_errors=True)
        print(f"removed {AGENT_LIB_DIR}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cc-time-sync-install")
    sub = p.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install")
    inst.add_argument("--endpoint", default=None)
    sub.add_parser("uninstall")
    args = p.parse_args()
    if args.cmd == "install":
        return install(args.endpoint)
    return uninstall()


if __name__ == "__main__":
    sys.exit(main())
