r"""
Reference engine — copy this to make a new one. Lives in the repo; fetched and run
by engine_loader at its pinned commit. Real engines swap the body of run() for a
pandas merge + your analysis and emit xlsx/docx/pdf via the app's existing stack
(openpyxl / python-docx / reportlab). The framework only needs: an ENGINE dict and
a run(ctx) that returns a file path.
"""

import os

ENGINE = {"name": "Reference Rollup", "inputs": ["data", "prompt"], "output": "md"}


def run(ctx):
    lines = ["# Reference Rollup", ""]
    lines.append("Prompt supplied: %s" % ("yes" if ctx.prompt.strip() else "no"))
    lines.append("Data files received: %d" % len(ctx.data_files))
    for p in ctx.data_files:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = -1
        lines.append("- %s (%d bytes)" % (os.path.basename(p), size))
    out_path = os.path.join(ctx.workdir, "reference_rollup.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path
