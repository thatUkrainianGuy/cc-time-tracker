"""Install/uninstall the cc-time-sync launchd agent + write a config template."""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .sync import CONFIG_FILE, TRACKING_DIR

LABEL = "rocks.thatukrainianguy.cc-time-sync"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _build_plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/env",
            "python3",
            "-m",
            "cc_time_tracker.sync",
        ],
        "StartInterval": 900,  # 15 min
        "StandardOutPath": "/tmp/cc-time-sync.log",
        "StandardErrorPath": "/tmp/cc-time-sync.err",
        "RunAtLoad": True,
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        },
    }


def install(endpoint: str | None) -> int:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(_build_plist(), f)
    print(f"wrote {PLIST_PATH}")

    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        template = {
            "endpoint": endpoint or "https://projects.thatukrainianguy.rocks/api/sync",
            "api_key": "REPLACE_ME",
        }
        import json
        CONFIG_FILE.write_text(json.dumps(template, indent=2))
        os.chmod(CONFIG_FILE, 0o600)
        print(f"wrote config template at {CONFIG_FILE} — fill in api_key before launchctl load")
    else:
        print(f"config already exists at {CONFIG_FILE} — leaving as-is")

    rc = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    rc = subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=False).returncode
    if rc != 0:
        print(f"launchctl load returned {rc}", file=sys.stderr)
        return rc
    print("loaded.")
    return 0


def uninstall() -> int:
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        PLIST_PATH.unlink()
        print(f"removed {PLIST_PATH}")
    else:
        print("plist not found — nothing to do")
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
