r"""
mindmap.py — Level 1 mind map: multiple saved maps, blocks with parent/child, auto-layout.

You build a map by structure (each block goes UNDER a chosen parent); the tree lays itself
out left→right and renders as an SVG. No free drag-and-drop (that's Level 2). The SVG is
shown via components.html so it renders reliably; all editing is done with normal Streamlit
widgets below the picture (so there's no fragile in-iframe interaction).
"""

import html as _html

import streamlit as st
import streamlit.components.v1 as components

import storage

_COLORS = ["#7F77DD", "#1D9E75", "#D85A30", "#378ADD", "#BA7517", "#D4537E"]  # by depth


def _build_tree(nodes):
    by_id = {str(n["node_id"]): n for n in nodes}
    children = {}
    roots = []
    for n in nodes:
        nid = str(n["node_id"])
        pid = str(n.get("parent_id") or "")
        if pid and pid in by_id:
            children.setdefault(pid, []).append(nid)
        else:
            roots.append(nid)
    # stable order by sort_order then text
    def _key(nid):
        n = by_id[nid]
        try:
            return (int(float(n.get("sort_order", 0) or 0)), str(n.get("text", "")))
        except Exception:
            return (0, str(n.get("text", "")))
    for k in children:
        children[k].sort(key=_key)
    roots.sort(key=_key)
    return by_id, children, roots


def _layout(nodes):
    by_id, children, roots = _build_tree(nodes)
    pos = {}
    counter = [0]
    ROW = 46

    def visit(nid, depth):
        kids = children.get(nid, [])
        if not kids:
            y = counter[0] * ROW
            counter[0] += 1
        else:
            ys = [visit(k, depth + 1) for k in kids]
            y = sum(ys) / len(ys)
        pos[nid] = (depth, y)
        return y

    for r in roots:
        visit(r, 0)
    return pos, children, by_id


def _render_svg(nodes):
    pos, children, by_id = _layout(nodes)
    COLW, NODE_W, NODE_H, MX, TOP = 172, 148, 34, 16, 16
    maxdepth = max((d for d, _ in pos.values()), default=0)
    maxy = max((y for _, y in pos.values()), default=0)
    W = MX * 2 + (maxdepth + 1) * COLW
    H = int(TOP * 2 + maxy + NODE_H)

    def cx(d):
        return MX + d * COLW

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" font-family="Inter,system-ui,sans-serif">']
    # connectors
    for pid, kids in children.items():
        pd_, py = pos[pid]
        px = cx(pd_) + NODE_W
        pcy = TOP + py + NODE_H / 2
        for k in kids:
            kd, ky = pos[k]
            kx = cx(kd)
            kcy = TOP + ky + NODE_H / 2
            mid = (px + kx) / 2
            parts.append(
                f'<path d="M{px} {pcy} C{mid} {pcy},{mid} {kcy},{kx} {kcy}" '
                f'fill="none" stroke="#C9C6BD" stroke-width="1.2"/>')
    # nodes
    for nid, (d, y) in pos.items():
        x = cx(d)
        ny = TOP + y
        col = _COLORS[d % len(_COLORS)]
        txt = _html.escape(str(by_id[nid].get("text", ""))[:26])
        parts.append(
            f'<rect x="{x}" y="{ny}" width="{NODE_W}" height="{NODE_H}" rx="9" '
            f'fill="{col}1A" stroke="{col}" stroke-width="1"/>')
        parts.append(
            f'<text x="{x + NODE_W / 2}" y="{ny + NODE_H / 2}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="12.5" fill="#1B2733">{txt}</text>')
    parts.append("</svg>")
    svg = "".join(parts)
    wrap = (f'<div style="overflow-x:auto;padding:6px 0;">{svg}</div>')
    return wrap, H


def _node_label(n, by_id, depth=0):
    return ("— " * depth) + str(n.get("text", ""))[:40]


def mindmap_view(user):
    uk = user.get("user_key", "")
    st.markdown("### 🧠 Mind Map")
    st.caption("Map a process as blocks. Add a block under any other block — the map draws "
               "itself. Create as many maps as you like; changes save automatically.")

    maps = storage.get_mind_maps(uk)
    map_rows = maps.to_dict("records") if not maps.empty else []

    top = st.columns([3, 1])
    if map_rows:
        labels = [m["name"] for m in map_rows]
        ids = [m["map_id"] for m in map_rows]
        cur = st.session_state.get("mm_current")
        idx = ids.index(cur) if cur in ids else 0
        sel = top[0].selectbox("Map", labels, index=idx, key="mm_pick")
        map_id = ids[labels.index(sel)]
        st.session_state["mm_current"] = map_id
    else:
        top[0].info("No maps yet — create your first one.")
        map_id = None

    with top[1]:
        st.write("")
        if st.button("➕ New map", key="mm_new", use_container_width=True):
            new_name = "Map " + str(len(map_rows) + 1)
            mid = storage.create_mind_map(uk, new_name)
            storage.add_mind_node(uk, mid, "Start here", "")
            st.session_state["mm_current"] = mid
            st.rerun()

    if not map_id:
        return

    nodes = storage.get_mind_nodes(uk, map_id)

    # ---- the picture ----
    if nodes:
        wrap, h = _render_svg(nodes)
        components.html(wrap, height=min(h + 24, 900), scrolling=True)
    else:
        st.info("Empty map — add your first block below.")

    by_id = {str(n["node_id"]): n for n in nodes}

    # ---- add a block ----
    st.markdown("##### Add a block")
    parent_opts = ["(top level)"] + [str(n["node_id"]) for n in nodes]

    def _fmt(nid):
        if nid == "(top level)":
            return "(top level)"
        return str(by_id.get(nid, {}).get("text", nid))[:40]

    ca = st.columns([3, 2, 1])
    new_text = ca[0].text_input("Block text", key="mm_text", placeholder="e.g. KYC verification")
    parent = ca[1].selectbox("Under", parent_opts, format_func=_fmt, key="mm_parent")
    with ca[2]:
        st.write("")
        if st.button("Add", type="primary", key="mm_add", use_container_width=True):
            if new_text.strip():
                pid = "" if parent == "(top level)" else parent
                storage.add_mind_node(uk, map_id, new_text.strip(), pid)
                st.rerun()
            else:
                st.warning("Type some text for the block.")

    # ---- edit / delete existing blocks ----
    if nodes:
        with st.expander("✏️ Edit or delete blocks"):
            for n in nodes:
                nid = str(n["node_id"])
                rc = st.columns([4, 3, 1])
                new_t = rc[0].text_input("Text", value=str(n.get("text", "")),
                                         key=f"mm_e_{nid}", label_visibility="collapsed")
                # re-parent options exclude self
                opts = ["(top level)"] + [str(x["node_id"]) for x in nodes if str(x["node_id"]) != nid]
                cur_p = str(n.get("parent_id") or "") or "(top level)"
                if cur_p not in opts:
                    cur_p = "(top level)"
                new_p = rc[1].selectbox("Under", opts, index=opts.index(cur_p),
                                        format_func=_fmt, key=f"mm_p_{nid}",
                                        label_visibility="collapsed")
                if new_t != n.get("text") or (("" if new_p == "(top level)" else new_p) != (n.get("parent_id") or "")):
                    storage.update_mind_node(uk, map_id, nid, text=new_t,
                                             parent_id=("" if new_p == "(top level)" else new_p))
                if rc[2].button("🗑", key=f"mm_d_{nid}", help="Delete this block and everything under it"):
                    storage.delete_mind_node(uk, map_id, nid)
                    st.rerun()

    # ---- map admin ----
    with st.expander("⚙️ Rename / delete this map"):
        rn = st.text_input("Map name", value=sel if map_rows else "", key="mm_rn")
        cc = st.columns(2)
        if cc[0].button("Rename", key="mm_rename"):
            storage.rename_mind_map(uk, map_id, rn.strip() or "Untitled map")
            st.rerun()
        if cc[1].button("Delete map", key="mm_delmap"):
            storage.delete_mind_map(uk, map_id)
            st.session_state.pop("mm_current", None)
            st.rerun()
