r"""
dump_sender.py — the "Sarthi" screen: Send Dump + Request MIS (Outlook email).

Two actions to Sarthi, both over Outlook:
  * Send Dump    — zip file(s), split into <=N MB parts, email each part
                   ([CDP MULTIPART] ... Part=x/N). Dump types come from the shared
                   dump_types registry (Neon, Admin-managed), not hardcoded.
  * Request MIS  — email a report request ([MIS REQUEST] ...) with the requester's email
                   so Sarthi can send the finished report straight back to them.

No encryption (key-free) for now — bodies are marked `encryption: none`.
Windows + Outlook only (pywin32 COM). Elsewhere the send reports Outlook isn't available.
"""

import os
import json
import time
import socket
import hashlib
import zipfile
import shutil
from datetime import datetime

import streamlit as st

import paths
import storage

DEFAULT_RECEIVER = os.getenv("SARTHI_RECEIVER_EMAIL", "growth@bigul.co")
MULTIPART_KEYWORD = "[CDP MULTIPART]"
MIS_KEYWORD = "[MIS REQUEST]"
DEFAULT_PART_MB = 10


def _work_dir():
    d = os.path.join(paths.common_dir(), "dump_sender")
    os.makedirs(d, exist_ok=True)
    return d


def _history_path():
    return os.path.join(_work_dir(), "send_history.json")


def _now_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sha256_bytes(b):
    h = hashlib.sha256(); h.update(b); return h.hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _human(n):
    n = float(n)
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def _save_uploads(files, batch_id):
    dest = os.path.join(_work_dir(), batch_id, "src")
    os.makedirs(dest, exist_ok=True)
    out = []
    for f in files:
        p = os.path.join(dest, f.name)
        with open(p, "wb") as fh:
            fh.write(f.getbuffer())
        out.append(p)
    return out


def _zip_files(saved_paths, batch_id):
    zip_path = os.path.join(_work_dir(), batch_id, f"{batch_id}.zip")
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in saved_paths:
            zf.write(p, os.path.basename(p))
    return zip_path


def _split(path, batch_id, part_mb):
    part_size = int(part_mb * 1024 * 1024)
    parts_dir = os.path.join(_work_dir(), batch_id, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    parts = []
    with open(path, "rb") as f:
        i = 1
        while True:
            chunk = f.read(part_size)
            if not chunk:
                break
            pp = os.path.join(parts_dir, f"{batch_id}.part{i:03d}")
            with open(pp, "wb") as o:
                o.write(chunk)
            parts.append({"part_no": i, "path": pp, "file_name": os.path.basename(pp),
                          "size_bytes": len(chunk), "sha256": _sha256_bytes(chunk)})
            i += 1
    return parts


def _outlook_app():
    import pythoncom  # noqa
    import win32com.client as win32
    return win32.Dispatch("Outlook.Application")


def _send_outlook(to_email, subject, body, attachment_path=None, dry_run=False):
    if dry_run:
        return True, "Dry run — not sent."
    try:
        import pythoncom
        import win32com.client as win32  # noqa
    except Exception:
        return False, "Outlook / pywin32 not available on this machine (Windows + Outlook required)."
    try:
        pythoncom.CoInitialize()
        outlook = _outlook_app()
        mail = outlook.CreateItem(0)
        mail.To = to_email
        mail.Subject = subject
        mail.Body = body
        if attachment_path:
            mail.Attachments.Add(str(os.path.abspath(attachment_path)))
        mail.Send()
        return True, "sent"
    except Exception as e:
        return False, f"Outlook send failed: {e}"
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _delete_from_sent_items(batch_id, tries=3, wait=2.0):
    """Remove the just-sent emails from Outlook Sent Items (match batch_id in the subject).
    Best-effort: Sent Items may take a moment to populate, so retry a few times."""
    try:
        import pythoncom
        import win32com.client as win32  # noqa
    except Exception:
        return 0, "Outlook not available."
    deleted = 0
    try:
        pythoncom.CoInitialize()
        outlook = _outlook_app()
        ns = outlook.GetNamespace("MAPI")
        sent = ns.GetDefaultFolder(5)   # olFolderSentMail
        for _ in range(tries):
            items = sent.Items
            to_del = []
            for it in list(items):
                try:
                    if batch_id in str(it.Subject):
                        to_del.append(it)
                except Exception:
                    continue
            for it in to_del:
                try:
                    it.Delete(); deleted += 1
                except Exception:
                    pass
            if deleted:
                break
            time.sleep(wait)
        return deleted, f"deleted {deleted} sent item(s)"
    except Exception as e:
        return deleted, f"sent-items cleanup error: {e}"
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _build_body(batch_id, part, total, pkg_name, pkg_sha, rows, sender, receiver,
                dtype_key, dtype_name, handler, uploaded_names, notes, types_version):
    lines = [
        "SARTHI CDP MULTIPART FILE", "",
        "encryption: none",
        f"batch_id: {batch_id}",
        f"part: {part['part_no']}/{total}",
        f"part_no: {part['part_no']}",
        f"total_parts: {total}", "",
        f"final_package_name: {pkg_name}",
        f"final_package_sha256: {pkg_sha}",
        f"part_file_name: {part['file_name']}",
        f"part_sha256: {part['sha256']}",
        f"part_size_bytes: {part['size_bytes']}", "",
        f"rows_count: {rows}",
        f"dump_type_key: {dtype_key}",
        f"dump_type_handler: {handler}",
        f"dump_types_version: {types_version}",
        f"report_key: {dtype_key}",
        f"report_name: {dtype_name}",
        f"sender_email: {sender}",
        f"from_email: {sender}",
        f"to_email: {receiver}",
        f"machine_name: {socket.gethostname()}",
        f"created_at: {_now_text()}", "",
        f"uploaded_files: {', '.join(uploaded_names)}",
    ]
    if notes.strip():
        lines += ["", "notes:", notes.strip()]
    return "\n".join(lines)


def _row_count(saved_paths):
    for p in saved_paths:
        low = p.lower()
        try:
            import pandas as pd
            if low.endswith(".csv"):
                return int(len(pd.read_csv(p)))
            if low.endswith((".xlsx", ".xls")):
                return int(len(pd.read_excel(p)))
        except Exception:
            continue
    return 0


def _log(record):
    try:
        hist = []
        if os.path.exists(_history_path()):
            with open(_history_path(), "r", encoding="utf-8") as fh:
                hist = json.load(fh)
        hist.insert(0, record)
        with open(_history_path(), "w", encoding="utf-8") as fh:
            json.dump(hist[:200], fh, indent=2)
    except Exception:
        pass


def send_dump(saved_paths, dtype, sender_email, receiver_email, notes,
              part_mb=DEFAULT_PART_MB, dry_run=False, delete_sent=True,
              cleanup=True, types_version=0, progress=None):
    """Zip -> split -> email each part. dtype is a dict from the dump_types registry.
    Cleans up temp parts and (optionally) removes the sent emails from Sent Items."""
    key = dtype.get("key", "generic")
    name = dtype.get("name", "Dump")
    handler = dtype.get("handler", key)
    batch_id = key + "_" + _now_id()
    uploaded_names = [os.path.basename(p) for p in saved_paths]
    rows = _row_count(saved_paths)

    zip_path = _zip_files(saved_paths, batch_id)
    pkg_sha = _sha256_file(zip_path)
    pkg_name = os.path.basename(zip_path)
    parts = _split(zip_path, batch_id, part_mb)
    total = len(parts)

    manifest = {"batch_id": batch_id, "created_at": _now_text(), "type": name,
                "dump_type_key": key, "handler": handler, "encryption": "none",
                "package": pkg_name, "package_sha256": pkg_sha, "rows_count": rows,
                "sender": sender_email, "receiver": receiver_email, "total_parts": total,
                "uploaded_files": uploaded_names, "notes": notes,
                "parts": [{k: p[k] for k in ("part_no", "file_name", "size_bytes", "sha256")}
                          for p in parts]}
    with open(os.path.join(_work_dir(), batch_id, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    sent, failed = [], []
    for i, part in enumerate(parts, start=1):
        subject = (f"{MULTIPART_KEYWORD} {name} | Batch={batch_id} "
                   f"| Part={i}/{total} | Sender={sender_email}")
        body = _build_body(batch_id, part, total, pkg_name, pkg_sha, rows, sender_email,
                           receiver_email, key, name, handler, uploaded_names, notes,
                           types_version)
        ok, msg = _send_outlook(receiver_email, subject, body, part["path"], dry_run=dry_run)
        (sent if ok else failed).append({"part": i, "file": part["file_name"], "msg": msg})
        if progress:
            progress(i, total)

    sent_cleanup = ""
    if not dry_run and not failed and delete_sent:
        n, sent_cleanup = _delete_from_sent_items(batch_id)
    if not dry_run and not failed and cleanup:
        shutil.rmtree(os.path.join(_work_dir(), batch_id), ignore_errors=True)

    result = {"batch_id": batch_id, "total_parts": total, "sent": len(sent),
              "failed": len(failed), "package_size": os.path.getsize(zip_path)
              if os.path.exists(zip_path) else 0, "rows_count": rows,
              "receiver": receiver_email, "dry_run": dry_run, "failures": failed,
              "sent_cleanup": sent_cleanup}
    _log({"at": _now_text(), "kind": "dump", **{k: result[k] for k in
          ("batch_id", "total_parts", "sent", "failed", "receiver")},
          "type": name, "sender": sender_email})
    return result


def request_mis(user_key, mis, sender_email, receiver_email, params, notes, dry_run=False):
    """Email an MIS request to Sarthi. mis is a dict from the mis_types registry. No
    attachment. The requester's email is stamped so Sarthi replies straight to them."""
    key = mis.get("key", "")
    name = mis.get("name", key)
    handler = mis.get("handler", key)
    req_id = "mis_" + _now_id()
    subject = f"{MIS_KEYWORD} {name} | ReqId={req_id} | Requester={sender_email}"
    body = "\n".join([
        "SARTHI MIS REQUEST", "",
        f"req_id: {req_id}",
        f"mis_type_key: {key}",
        f"mis_type_handler: {handler}",
        f"mis_name: {name}",
        f"requester_email: {sender_email}",
        f"reply_to: {sender_email}",
        f"user_key: {user_key}",
        f"machine_name: {socket.gethostname()}",
        f"created_at: {_now_text()}", "",
        "parameters:", (params.strip() or "(none)"),
    ] + (["", "notes:", notes.strip()] if notes.strip() else []))
    ok, msg = _send_outlook(receiver_email, subject, body, None, dry_run=dry_run)
    if ok and not dry_run:
        storage.log_mis_request(user_key, req_id, key, name, params, sender_email)
    _log({"at": _now_text(), "kind": "mis", "req_id": req_id, "mis": name,
          "requester": sender_email, "ok": ok, "msg": msg})
    return ok, msg, req_id


def sarthi_view(user):
    uk = user.get("user_key", "")
    st.markdown("### 📮 Sarthi")
    st.caption("Send a data dump to Sarthi, or request an MIS report. Sarthi emails finished "
               "reports back to you directly.")

    mode = st.radio("Action", ["Send Dump", "Request MIS"], horizontal=True, key="sarthi_mode")

    # Requester email — type once, saved on the user record, auto-filled next time.
    saved_email = storage.get_user_email(uk)
    c = st.columns(2)
    sender_email = c[0].text_input("Your email", value=saved_email,
                                   placeholder="name@bigul.co", key="sarthi_from")
    receiver_email = c[1].text_input("Sarthi email", value=DEFAULT_RECEIVER, key="sarthi_to")
    if sender_email.strip() and sender_email.strip() != saved_email:
        try:
            storage.set_user_email(uk, sender_email.strip())
        except Exception:
            pass

    if mode == "Send Dump":
        _send_dump_ui(user, sender_email, receiver_email)
    else:
        _request_mis_ui(user, sender_email, receiver_email)


def _send_dump_ui(user, sender_email, receiver_email):
    st.info("Encryption is OFF for now — the dump is sent as a plain zip.")
    types = storage.get_dump_types(active_only=True)
    if not types:
        st.warning("No dump types configured. Ask an admin to add one (Admin → Dump types)."); return
    labels = [t["name"] for t in types]
    sel = st.selectbox("Dump type", labels, key="dump_type_sel")
    dtype = types[labels.index(sel)]
    max_files = int(float(dtype.get("max_files", 1) or 1))

    ups = st.file_uploader(f"Dump file(s) — up to {max_files}",
                           accept_multiple_files=(max_files > 1),
                           type=["csv", "xlsx", "xls", "zip", "txt"], key="dump_files")
    files = ups if isinstance(ups, list) else ([ups] if ups else [])
    if len(files) > max_files:
        st.warning(f"{sel} accepts at most {max_files} file(s); extra ones ignored.")
        files = files[:max_files]

    c = st.columns(3)
    part_mb = c[0].number_input("Part size (MB)", 1, 20, DEFAULT_PART_MB, 1, key="dump_part")
    delete_sent = c[1].checkbox("Remove from Sent Items", value=True, key="dump_delsent")
    dry = c[2].checkbox("Dry run", key="dump_dry")
    notes = st.text_area("Notes (optional)", height=68, key="dump_notes")

    if st.button("Send dump to Sarthi", type="primary", key="dump_send"):
        if not files:
            st.error("Upload at least one file."); return
        if not sender_email.strip() or not receiver_email.strip():
            st.error("Your email and Sarthi email are required."); return
        with st.spinner("Zipping, splitting and sending…"):
            saved = _save_uploads(files, "_" + _now_id())
            bar = st.progress(0.0)
            res = send_dump(saved, dtype, sender_email.strip(), receiver_email.strip(),
                            notes, part_mb=int(part_mb), dry_run=dry, delete_sent=delete_sent,
                            types_version=len(types),
                            progress=lambda i, t: bar.progress(i / t))
        if res["failed"] == 0:
            extra = f" · {res['sent_cleanup']}" if res.get("sent_cleanup") else ""
            st.success(f"{'Prepared' if dry else 'Sent'} {res['total_parts']} part(s) "
                       f"({_human(res['package_size'])} zip, {res['rows_count']} rows) "
                       f"to {res['receiver']}.{extra}  Batch: {res['batch_id']}")
        else:
            st.error(f"{res['sent']} sent, {res['failed']} failed. "
                     + "; ".join(f"part {x['part']}: {x['msg']}" for x in res["failures"]))


def _request_mis_ui(user, sender_email, receiver_email):
    uk = user.get("user_key", "")
    types = storage.get_mis_types(active_only=True)
    if not types:
        st.warning("No MIS types configured yet. Ask an admin to add one (Admin → MIS types)."); return
    labels = [t["name"] for t in types]
    sel = st.selectbox("MIS report", labels, key="mis_type_sel")
    mis = types[labels.index(sel)]
    hint = str(mis.get("params_hint", "") or "")
    if hint:
        st.caption("Parameters: " + hint)
    params = st.text_area("Parameters (e.g. date range, filters)", height=80,
                          placeholder=hint or "e.g. 1–30 Jun 2026, Kolkata team", key="mis_params")
    notes = st.text_input("Notes (optional)", key="mis_notes")
    dry = st.checkbox("Dry run", key="mis_dry")

    if st.button("Send request to Sarthi", type="primary", key="mis_send"):
        if not sender_email.strip():
            st.error("Your email is required — Sarthi sends the report there."); return
        with st.spinner("Sending request…"):
            ok, msg, req_id = request_mis(uk, mis, sender_email.strip(), receiver_email.strip(),
                                          params, notes, dry_run=dry)
        if ok:
            st.success(f"{'Prepared' if dry else 'Requested'} “{sel}”. Sarthi will email the "
                       f"report to {sender_email.strip()}. Request id: {req_id}")
        else:
            st.error(f"Couldn't send: {msg}")

    reqs = storage.get_mis_requests(uk, limit=15)
    if reqs:
        st.divider()
        st.markdown("##### My recent requests")
        for r in reqs:
            st.markdown(f"- **{r.get('mis_name', '')}** · {r.get('created_at', '')} "
                        f"· to {r.get('requester_email', '')}")
