# Plan My Day — Desktop

The local Windows build. Same app as the cloud version, plus three Desktop
capabilities. Data lives under `D:\Sarthi - Plan My Day\` and never leaves the
machine; only code/prompts flow **down** from GitHub.

## What's new in Desktop

- **Reports Engine** (`Reports` tab) — pick an engine from the GitHub registry,
  upload a prompt and/or data dump(s), run the Python engine **locally**, download
  the report (saved under your `reports/` folder). Engines are fetched at a pinned
  commit SHA; nothing is uploaded. Framework: `engine_loader.py`, `reports_engine.py`,
  `engines/`.
- **In-app Update** (`Settings → App updates`) — deliberate, manual pull of the
  latest code, role prompts, and engines. `git pull` on a checkout, or a repo
  tarball on a zip install. Your data is untouched; restart after updating.
  (`updater.py`, `desktop_config.py`.)
- **Self-learning prompts** — already built into the base app: `storage.read_role_prompt()`
  stacks base + tweak + learn layers, and `ai.distill_learnings()` maintains the
  local learn layer. Nothing new needed; the layer composes at runtime.

## Setup

See `LOCAL_TESTING.md`. Short version, per machine:
1. `cp .streamlit/secrets.toml.example .streamlit/secrets.toml`
2. Fill `OPENAI_API_KEY` (GPT + Whisper voice) and/or `ANTHROPIC_API_KEY`.
   Set `github_owner`/`github_repo` (auto-detected on git checkouts). Add
   `github_pat` only for a private repo (read-only, contents:read).
3. Windows: double-click **Start Plan My Day.bat**. Else: `streamlit run app.py`.

## Before first real use

- `desktop_config.py` — set `DEFAULT_OWNER`/`DEFAULT_REPO` if shipping as a zip
  (no git to auto-detect from).
- `engines/registry.json` — replace `REPLACE_WITH_COMMIT_SHA` with each engine's
  real commit SHA after you commit it. The pin is what stops a stray push from
  changing what runs on every machine.

## Adding a real engine

Copy `engines/reference_rollup.py`, replace the body of `run(ctx)` with your pandas
merge + analysis (emit xlsx/docx/pdf via openpyxl / python-docx / reportlab), commit,
add a line to `engines/registry.json`, and pin its SHA.
