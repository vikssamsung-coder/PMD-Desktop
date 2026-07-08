r"""
reports_engine.py — the Reports Engine page for Plan My Day - Desktop.

Analyst flow: pick an engine (from the GitHub registry) -> upload a prompt and/or
data dump(s) -> Run -> download the report. Runs entirely on the local machine;
reports are written under the user's own reports folder (paths.user_reports_dir).
"""

import os
import tempfile

import streamlit as st

import paths
import engine_loader


def _save_uploads(files, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    out = []
    for f in files or []:
        p = os.path.join(dest_dir, f.name)
        with open(p, "wb") as fh:
            fh.write(f.getbuffer())
        out.append(p)
    return out


def reports_view(user):
    uk = user["user_key"]
    st.markdown("### 📊 Reports Engine")
    st.caption("Pick an engine, add a prompt and your data, and download the report. "
               "Everything runs on this machine — nothing is uploaded.")

    try:
        engines = engine_loader.load_registry()
    except Exception as exc:
        st.error("Couldn't load the engine list from GitHub, and no local copy exists yet. "
                 "Use Settings → App updates once you're online. (%s)" % exc)
        return
    if not engines:
        st.warning("No engines are registered yet.")
        return

    by_label = {e["name"]: e for e in engines}
    label = st.selectbox("Engine", list(by_label.keys()))
    engine = by_label[label]
    if engine.get("description"):
        st.caption(engine["description"])
    st.caption("pinned commit %s · output: %s"
               % (engine.get("commit", "")[:12], engine.get("output", "?")))

    needs = engine.get("inputs", [])

    prompt_text = ""
    if "prompt" in needs:
        up = st.file_uploader("Prompt file (.md / .txt)", type=["md", "txt"],
                              key="re_prompt")
        if up is not None:
            prompt_text = up.getvalue().decode("utf-8", errors="replace")

    data_files = []
    if "data" in needs:
        ups = st.file_uploader("Data dump(s)", accept_multiple_files=True,
                               type=["csv", "xlsx", "xls"], key="re_data")
        if ups:
            data_files = _save_uploads(
                ups, os.path.join(tempfile.gettempdir(), "re_data_" + uk))

    if st.button("Run engine", type="primary"):
        missing = []
        if "prompt" in needs and not prompt_text.strip():
            missing.append("a prompt file")
        if "data" in needs and not data_files:
            missing.append("at least one data file")
        if missing:
            st.error("This engine needs " + " and ".join(missing) + ".")
            return

        with st.spinner("Running %s…" % engine["name"]):
            try:
                workdir = os.path.join(paths.user_reports_dir(uk), "engine_" + engine["id"])
                out_path = engine_loader.run_engine(
                    engine, data_files=data_files, prompt=prompt_text, workdir=workdir)
            except Exception as exc:
                st.error("Engine failed: %s" % exc)
                return

        st.success("Report ready — saved to your reports folder.")
        st.caption(out_path)
        with open(out_path, "rb") as fh:
            st.download_button("Download report", fh.read(),
                               file_name=os.path.basename(out_path))
