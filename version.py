"""
Git-derived version and commit datetime.

Version is derived from the latest Git tag via `git describe`.
Between tagged releases, the version includes a commit count suffix,
e.g. "v1.0.0+3".  The commit datetime is always the date/time of the
most recent commit.

To create a new release version:
    git tag -a v1.0.0 -m "First stable release"
    git push origin v1.0.0

Major/minor/patch numbering is entirely your choice via the tag name.
"""

import os
import subprocess
from datetime import datetime

_FALLBACK_VERSION = "dev"
_FALLBACK_DATE = ""
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_VERSION_FILE = os.path.join(_PROJECT_DIR, "VERSION")


def _run_git(*args: str) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=5,
            cwd=_PROJECT_DIR,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _read_version_file() -> tuple:
    """Read VERSION file written at deploy time.

    Expected format: '<version> <iso-datetime>'
    e.g. 'v1.0.0 2026-03-10 16:20:00 +0000'
    Returns (version_str, datetime_str) or ('', '').
    """
    try:
        with open(_VERSION_FILE) as f:
            line = f.read().strip()
        if not line:
            return ("", "")
        # Split: first token is version, rest is datetime
        parts = line.split(None, 1)
        version = parts[0] if parts else ""
        raw_dt = parts[1] if len(parts) > 1 else ""
        # Parse version same as git describe
        vparts = version.split("-")
        if len(vparts) >= 3:
            tag = "-".join(vparts[:-2])
            commits_ahead = vparts[-2]
            version = f"{tag}+{commits_ahead}"
        # Format datetime
        if raw_dt:
            try:
                dt = datetime.fromisoformat(raw_dt)
                raw_dt = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                raw_dt = raw_dt[:16]
        return (version, raw_dt)
    except (FileNotFoundError, OSError):
        return ("", "")


def get_version_info() -> dict:
    """Return a dict with 'version' and 'commit_datetime' strings.

    Priority: live git commands > VERSION file > fallback defaults.
    """
    # Try git first
    desc = _run_git("describe", "--tags", "--always")
    if desc:
        parts = desc.split("-")
        if len(parts) >= 3:
            tag = "-".join(parts[:-2])
            commits_ahead = parts[-2]
            version = f"{tag}+{commits_ahead}"
        else:
            version = desc
        iso = _run_git("log", "-1", "--format=%ci")
        if iso:
            try:
                dt = datetime.fromisoformat(iso)
                commit_dt = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                commit_dt = iso[:16]
        else:
            commit_dt = _FALLBACK_DATE
        return {"version": version, "commit_datetime": commit_dt}

    # Fallback: VERSION file (written at deploy time)
    file_ver, file_dt = _read_version_file()
    if file_ver:
        return {"version": file_ver, "commit_datetime": file_dt}

    # Last resort
    return {"version": _FALLBACK_VERSION, "commit_datetime": _FALLBACK_DATE}
