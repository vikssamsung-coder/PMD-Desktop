r"""
updater.py — the manual "Update app" control (Settings, desktop only).

The launchers don't pull updates, so this is how a machine gets the latest code,
role prompts, and engines you've pushed to GitHub. Deliberately manual (a button),
not automatic: a bad push shouldn't break every machine at once.

Mechanisms, auto-selected:
  * git checkout -> `git pull --ff-only`
  * zip install  -> download the repo tarball at the branch tip and overwrite the
                    app's code files in place. User DATA lives OUTSIDE the repo
                    (D:\Sarthi - Plan My Day) and .streamlit is skipped, so an
                    update never touches data or secrets.

IMPORTANT: copying new files does NOT change the running app. Python keeps the
already-imported modules (db.py, storage.py, ...) in memory until the process is
fully restarted. A browser refresh is NOT enough — you must stop and relaunch.
"""

import os
import io
import json
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
_SKIP = {".git", ".streamlit", "__pycache__", ".devcontainer"}   # never overwrite these


def _headers():
    h = {"Accept": "application/vnd.github+json"}
    p = cfg.pat()
    if p:
        h["Authorization"] = "Bearer " + p
    return h


def _version_file():
    return os.path.join(paths.common_dir(), ".installed_version.json")


def _installed_sha():
    try:
        with open(_version_file(), "r", encoding="utf-8") as fh:
            return json.load(fh).get("sha", "")
    except Exception:
        return ""


def _save_installed_sha(sha):
    try:
        os.makedirs(os.path.dirname(_version_file()), exist_ok=True)
        with open(_version_file(), "w", encoding="utf-8") as fh:
            json.dump({"sha": sha, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, fh)
    except Exception:
        pass


def _latest_remote_sha():
    """Latest commit SHA on the branch, or '' if it can't be fetched."""
    url = "{api}/repos/{o}/{r}/commits/{ref}".format(
        api=GITHUB_API, o=cfg.owner(), r=cfg.repo(), ref=cfg.branch())
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        resp.raise_for_status()
        return resp.json().get("sha", "") or ""
    except Exception:
        return ""


def _git_pull():
    out = subprocess.run(
        ["git", "-C", paths.repo_dir(), "pull", "--ff-only"],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip())
    return (out.stdout or "").strip()


def _tarball_update():
    """Download the branch tarball and overwrite code files in repo_dir().
    Returns (file_count, list_of_key_files_changed)."""
    url = "{api}/repos/{o}/{r}/tarball/{ref}".format(
        api=GITHUB_API, o=cfg.owner(), r=cfg.repo(), ref=cfg.branch())
    resp = requests.get(url, headers=_headers(), timeout=180)
    resp.raise_for_status()

    tmp = tempfile.mkdtemp()
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        tf.extractall(tmp)
    tops = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
    if not tops:
        raise RuntimeError("empty tarball")
    src = os.path.join(tmp, tops[0])

    dst = paths.repo_dir()
    n = 0
    key = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
            n += 1
            if f in ("app.py", "db.py", "storage.py", "requirements.txt"):
                key.append(f)
    shutil.rmtree(tmp, ignore_errors=True)
    return n, key


def update_available():
    """(is_update_available, latest_sha). Compares the last-installed SHA to GitHub's
    latest commit SHA. Cached in session ~30 min so it doesn't hit GitHub every rerun.
    Baselines silently on first run so a fresh machine isn't nagged."""
    now = time.time()
    cache = st.session_state.get("_upd_check")
    if cache and (now - cache.get("at", 0)) < 1800:
        latest = cache.get("latest", "")
    else:
        latest = _latest_remote_sha()
        st.session_state["_upd_check"] = {"latest": latest, "at": now}
    if not latest:
        return False, ""
    installed = _installed_sha()
    if not installed:
        _save_installed_sha(latest)      # first run -> baseline, don't nag
        return False, latest
    return (installed != latest), latest


def render_update_banner():
    """Prominent main-page banner shown ONLY when a newer build exists on GitHub.
    Disappears automatically once the machine updates to that build."""
    try:
        avail, _latest = update_available()
    except Exception:
        return
    if avail:
        st.warning("🔔  **Update your app — a new build has been released.**  "
                   "Open **Settings → App updates** and click *Download & install*, "
                   "then restart the app.")


def render_update_section(user):
    st.markdown("#### App updates")
    mode = "git checkout" if cfg.is_git_checkout() else "zip install"
    st.caption("Source: github.com/%s/%s · branch %s · mode: %s"
               % (cfg.owner(), cfg.repo(), cfg.branch(), mode))

    installed = _installed_sha()
    latest = _latest_remote_sha()
    if latest:
        if installed and installed == latest:
            st.success("You're on the latest version (%s)." % latest[:8])
        elif installed:
            st.warning("Update available: installed %s → latest %s."
                       % (installed[:8], latest[:8]))
        else:
            st.info("Latest version on GitHub: %s. (Install version unknown — "
                    "update once to start tracking.)" % latest[:8])
    else:
        st.caption("Couldn't reach GitHub to check the latest version (offline?).")

    st.caption("Downloads the latest code, role prompts, and engines from GitHub and "
               "saves them here. Your data and secrets are never touched.")

    if st.button("Download & install update now", type="primary"):
        with st.spinner("Downloading from GitHub…"):
            try:
                if cfg.is_git_checkout():
                    detail = _git_pull() or "Already up to date."
                    changed = []
                else:
                    count, changed = _tarball_update()
                    detail = "%d file(s) updated" % count
            except Exception as exc:
                st.error("Update failed: %s" % exc)
                return
        if latest:
            _save_installed_sha(latest)
        st.session_state["_last_update_ts"] = time.time()
        st.success("Downloaded and installed. " + detail
                   + (" · key files: " + ", ".join(sorted(set(changed))) if changed else ""))
        # The critical part — copying files does nothing until a FULL restart.
        st.error(
            "⚠️ RESTART REQUIRED — the new code is on disk but the app is still running "
            "the old version in memory. A browser refresh will NOT load it.\n\n"
            "1) Go to the terminal running the app and press Ctrl+C to stop it fully.\n"
            "2) Relaunch: double-click 'Start Plan My Day', or run  py -m streamlit run app.py\n"
            "3) Open a fresh browser tab at localhost:8501.")
