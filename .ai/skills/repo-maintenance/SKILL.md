---
name: repo-maintenance
description: "Maintain the gambit repository and verify its supported development workflows."
---

## 1. Scope

Use when maintaining this repository or its independently configured projects.

## 2. Procedure

- Initialize Python with `uv sync --locked --extra vision`; run `uv run --locked --extra vision pytest` and `uv build --out-dir build/packages`.
- The independent `ui/` NPM project owns `ui/package-lock.json`. Build the sibling Chessboard package before initializing and building the UI; it is a local package dependency.
- `tools/scripts/generate_tutor_skill.py` generates `.ai/skills/chess/` from the canonical Agents chess rules and skill. Edit the canonical sources, regenerate, and validate the resulting local links rather than editing generated copies.
- Preserve `src/gambit/web/assets/` as the built UI package resource location. The Python distribution and `src/gambit/server/live_http.py` require these embedded files; repository compatibility rules permit this generated location. Verify the UI build and Python package build.
- Keep temporary game and evidence state process-local and preserve protocol contracts during repository maintenance.
