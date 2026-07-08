r"""
desktop_config.py — coordinates the Desktop build needs that paths.py doesn't cover:
the GitHub repo to pull updates and engines from.

Resolution order for OWNER/REPO/BRANCH:
  1. Streamlit secrets  (github_owner / github_repo / github_branch)
  2. env vars           (GITHUB_OWNER / GITHUB_REPO / GITHUB_BRANCH)
  3. auto-detected from `git remote get-url origin` if this is a git checkout
  4. the DEFAULT_* fallbacks below  <-- set these if you ship as a zip (no git)

A read-only PAT is only needed for a PRIVATE repo. Put it in secrets as
github_pat, or env GITHUB_PAT. Public repos need no token.
"""

import os
import re
import subprocess

import paths

# ----------------------------------------------------------- fill these if no git
DEFAULT_OWNER = "your-github-user-or-org"
DEFAULT_REPO = "planmyday"
DEFAULT_BRANCH = "main"

REGISTRY_PATH = "engines/registry.json"   # path INSIDE the repo


def _secret(key):
    try:
        import streamlit as st
        v = st.secrets.get(key, "")
        if v:
            return str(v).strip()
    except Exception:
        pass
    return os.environ.get(key.upper(), "").strip()


def _from_git_remote():
    """Return (owner, repo) parsed from the origin remote, or (None, None)."""
    try:
        url = subprocess.check_output(
            ["git", "-C", paths.repo_dir(), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        return None, None
    # git@github.com:owner/repo.git   or   https://github.com/owner/repo(.git)
    m = re.search(r"[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def owner():
    v = _secret("github_owner")
    if v:
        return v
    g, _ = _from_git_remote()
    return g or DEFAULT_OWNER


def repo():
    v = _secret("github_repo")
    if v:
        return v
    _, r = _from_git_remote()
    return r or DEFAULT_REPO


def branch():
    return _secret("github_branch") or DEFAULT_BRANCH


def pat():
    """Read-only PAT for a private repo; None for public."""
    return _secret("github_pat") or None


# ------------------------------------------------------------------- local paths
def engine_cache_dir():
    return os.path.join(paths.common_dir(), "engine_cache")


def registry_cache_path():
    return os.path.join(paths.common_dir(), "engine_registry.json")


def is_git_checkout():
    return os.path.isdir(os.path.join(paths.repo_dir(), ".git"))
