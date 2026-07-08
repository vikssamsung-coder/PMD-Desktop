r"""
updater.py — the manual "Update app" control (Settings).

The .bat/.command launchers don't pull updates, so this is how a machine gets the
latest code, role prompts, and engines you've pushed to GitHub. Deliberately
manual (a button), not automatic on login: a bad push shouldn't break every
analyst at once — the person chooses when to update.

Two mechanisms, auto-selected:
  * git checkout  -> `git pull --ff-only` (clean, fast, preserves nothing local)
  * zip install   -> download the repo tarball at the branch tip and overwrite the
                     app's code files in place. User data lives OUTSIDE the repo
                     (under D:\Sarthi - Plan My Day), so code overwrite is safe.

After a successful update the app must be restarted to load new code — Streamlit
can't hot-swap running modules reliably. We tell the user clearly.
"""

import os
import io
import time
import shutil
import tarfile
import tempfile
import subprocess

import requests
import streamlit as st

import paths
import desktop_config as cfg

GITHUB_API = "https://api.github.com"

# files/dirs we never overwrite from an update (local/data, not code)
_SKIP = {".git", ".streamlit", "__pycache__"}


def _headers():
    h = {"Accept": "application/vnd.github+json"}
    p = cfg.pat()
    if p:
        h["Authorization"] = "Bearer " + p
    return h


def _git_pull():
    out = subprocess.run(
        ["git", "-C", paths.repo_dir(), "pull", "--ff-only"],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip())
    return (out.stdout or "").strip()


def _tarball_update():
    """Download the branch tarball and overwrite code files in repo_dir()."""
    url = "{api}/repos/{o}/{r}/tarball/{ref}".format(
        api=GITHUB_API, o=cfg.owner(), r=cfg.repo(), ref=cfg.branch())
    resp = requests.get(url, headers=_headers(), timeout=120)
    resp.raise_for_status()

    tmp = tempfile.mkdtemp()
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        tf.extractall(tmp)
    # tarball extracts to a single top folder like owner-repo-<sha>/
    tops = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
    if not tops:
        raise RuntimeError("empty tarball")
    src = os.path.join(tmp, tops[0])

    dst = paths.repo_dir()
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
            n += 1
    shutil.rmtree(tmp, ignore_errors=True)
    return "%d file(s) updated" % n


def render_update_section(user):
    st.markdown("#### App updates")
    mode = "git checkout" if cfg.is_git_checkout() else "zip install"
    st.caption("Source: github.com/%s/%s · branch %s · mode: %s"
               % (cfg.owner(), cfg.repo(), cfg.branch(), mode))
    st.caption("Pulls the latest app code, role prompts, and engines. Your data is "
               "kept separately and is never touched. Restart the app after updating.")

    if st.button("Check for updates & update now"):
        with st.spinner("Updating from GitHub…"):
            try:
                if cfg.is_git_checkout():
                    msg = _git_pull()
                    detail = msg or "Already up to date."
                else:
                    detail = _tarball_update()
            except Exception as exc:
                st.error("Update failed: %s" % exc)
                return
        st.session_state["_last_update_ts"] = time.time()
        st.success("Updated. " + detail)
        st.warning("Close this window and restart Plan My Day to load the new version "
                   "(double-click the Start Plan My Day launcher again).")
