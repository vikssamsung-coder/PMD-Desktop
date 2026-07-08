r"""
engine_loader.py — Reports Engine plugin framework for Plan My Day - Desktop.

An "engine" is a Python file hosted in the app's GitHub repo that conforms to a
contract:

    ENGINE = {"name": "...", "inputs": ["data","prompt"], "output": "xlsx"}
    def run(ctx) -> str:            # returns path to the produced report file
        # ctx.data_files : list[str]  uploaded dump paths (may be empty)
        # ctx.prompt     : str        uploaded prompt text (may be "")
        # ctx.workdir    : str        write outputs here (a per-user reports dir)
        # ctx.ai()       : anthropic client (only if the engine needs AI)

Flow: read registry from GitHub -> user picks engine -> fetch that engine's code
at its PINNED COMMIT -> load in-process -> run(ctx) -> return report path.

Trust boundary: engine code executes locally. Engines are pinned to a commit SHA
in the registry, so a floating-branch push can't silently change what runs.
Everything stays on the machine — nothing is uploaded.
"""

import os
import json
import base64
import logging
import importlib.util

import requests

import desktop_config as cfg

log = logging.getLogger("engine_loader")
GITHUB_API = "https://api.github.com"
_TIMEOUT = 15


class RunContext:
    def __init__(self, data_files, prompt, workdir):
        self.data_files = data_files or []
        self.prompt = prompt or ""
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)

    def ai(self):
        # matches ai.py: Anthropic() reads ANTHROPIC_API_KEY from env
        from anthropic import Anthropic
        return Anthropic()


def _headers():
    h = {"Accept": "application/vnd.github+json"}
    p = cfg.pat()
    if p:
        h["Authorization"] = "Bearer " + p
    return h


def _fetch_git_file(path_in_repo, ref):
    url = "{api}/repos/{owner}/{repo}/contents/{path}".format(
        api=GITHUB_API, owner=cfg.owner(), repo=cfg.repo(), path=path_in_repo
    )
    resp = requests.get(url, headers=_headers(), params={"ref": ref}, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("encoding") == "base64" and payload.get("content"):
        return base64.b64decode(payload["content"]).decode("utf-8")
    dl = payload.get("download_url")
    if not dl:
        raise ValueError("no content/download_url for %s" % path_in_repo)
    return requests.get(dl, headers=_headers(), timeout=_TIMEOUT).text


def load_registry():
    """
    Fetch + parse the engine registry from GitHub. Returns a list of engine dicts.
    On network failure, falls back to a locally cached copy if one exists (so the
    page still works offline); raises only if there's no cache either.
    """
    try:
        raw = _fetch_git_file(cfg.REGISTRY_PATH, cfg.branch())
        try:
            os.makedirs(os.path.dirname(cfg.registry_cache_path()), exist_ok=True)
            with open(cfg.registry_cache_path(), "w", encoding="utf-8") as fh:
                fh.write(raw)
        except Exception:
            pass
    except Exception as exc:
        log.warning("registry fetch failed (%s); trying local cache", exc)
        with open(cfg.registry_cache_path(), "r", encoding="utf-8") as fh:
            raw = fh.read()

    data = json.loads(raw)
    clean = []
    for e in data.get("engines", []):
        if e.get("id") and e.get("name") and e.get("module_path") and e.get("commit"):
            clean.append(e)
        else:
            log.warning("skipping malformed registry entry: %s", e)
    return clean


def _load_engine_module(engine_meta):
    code = _fetch_git_file(engine_meta["module_path"], engine_meta["commit"])
    os.makedirs(cfg.engine_cache_dir(), exist_ok=True)
    fname = "{id}__{sha}.py".format(id=engine_meta["id"], sha=engine_meta["commit"][:12])
    local_py = os.path.join(cfg.engine_cache_dir(), fname)
    with open(local_py, "w", encoding="utf-8") as fh:
        fh.write(code)

    mod_name = "engine_" + engine_meta["id"] + "_" + engine_meta["commit"][:8]
    spec = importlib.util.spec_from_file_location(mod_name, local_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "run") or not callable(module.run):
        raise ValueError("engine '%s' has no callable run()" % engine_meta["id"])
    if not isinstance(getattr(module, "ENGINE", None), dict):
        raise ValueError("engine '%s' has no ENGINE metadata dict" % engine_meta["id"])
    return module


def run_engine(engine_meta, data_files, prompt, workdir):
    """Load the selected engine at its pinned commit and run it. Returns report path."""
    module = _load_engine_module(engine_meta)
    ctx = RunContext(data_files=data_files, prompt=prompt, workdir=workdir)
    out_path = module.run(ctx)
    if not out_path or not os.path.exists(out_path):
        raise RuntimeError(
            "engine '%s' did not return a valid report path" % engine_meta["id"]
        )
    return out_path
