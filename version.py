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

import subprocess
from datetime import datetime

_FALLBACK_VERSION = "dev"
_FALLBACK_DATE = ""


def _run_git(*args: str) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def get_version() -> str:
    """Return version string derived from the latest git tag.

    Examples: 'v1.0.0', 'v1.0.0+3', 'dev' (no tags).
    """
    desc = _run_git("describe", "--tags", "--always")
    if not desc:
        return _FALLBACK_VERSION
    # git describe output: 'v1.0.0' or 'v1.0.0-3-gabc1234'
    parts = desc.split("-")
    if len(parts) >= 3:
        tag = "-".join(parts[:-2])
        commits_ahead = parts[-2]
        return f"{tag}+{commits_ahead}"
    return desc


def get_commit_datetime() -> str:
    """Return the datetime of the most recent commit as 'YYYY-MM-DD HH:MM'."""
    iso = _run_git("log", "-1", "--format=%ci")
    if not iso:
        return _FALLBACK_DATE
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16]


def get_version_info() -> dict:
    """Return a dict with 'version' and 'commit_datetime' strings."""
    return {
        "version": get_version(),
        "commit_datetime": get_commit_datetime(),
    }
