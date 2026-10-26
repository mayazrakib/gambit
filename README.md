# `gambit`

![Version](https://img.shields.io/badge/Version-0.3.0-737373?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-737373?style=flat-square)
![Languages](https://img.shields.io/badge/Languages-Python%2C%20TypeScript-737373?style=flat-square)
![Frameworks](https://img.shields.io/badge/Frameworks-MCP%2C%20Stockfish%2C%20Vite-737373?style=flat-square)
![Compatibility](https://img.shields.io/badge/Compatibility-Not%20verified-737373?style=flat-square)
![Build](https://img.shields.io/badge/Build-Not%20run%20remotely-737373?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-147%20backend%20passing-737373?style=flat-square)
![Vulnerabilities](https://img.shields.io/badge/Vulnerabilities-0%20known%20dependency%20findings-737373?style=flat-square)

## 1. Introduction

Gambit provides validated chess facts, bounded local Stockfish analysis, attributed API information, and a localhost playing workspace. The connected host owns explanations and audio.

## 2. Usage

Run `uv sync --locked --extra vision`, `uv run gambit initialize`, and `uv run gambit`. Install Stockfish first. Configure optional values using `.env.example`; keep real credentials private.

For the playing workspace, build sibling `../chessboard`, run `npm ci --prefix ui` and `npm run build --prefix ui`, then `uv run gambit play --port 3030`. HTTP MCP uses `uv run gambit serve --transport streamable-http --port 3025`. See `showcase/configuration.toml` for TOML configuration.

## 3. Features

Position facts, batch analysis, move comparisons, PGN validation, board recognition, opening classifications, opt-in attributed provider requests, and temporary live games are implemented. Contract version 3 preserves White-relative scores, history identity, units, attribution, search bounds, and revision checks.

Only opening classifications and non-personal configuration persist. Games, evidence, jobs, and API caches remain bounded and process-local. No learner profiles, personalized databases, server-authored explanations, speech synthesis, local tablebases, or bulk personal downloads are supported. Never persist personal identifiers or response bodies in logs.

HTTP binds to loopback and validates peer, host, origin, request type, and size. `GAMBIT_UI_ORIGIN` may allow one exact HTTPS `.ts.net` origin through loopback. Forwarded headers never replace the peer. Preserve the existing remote MCP connection.

## 4. Architecture

`src/gambit/` separates providers, knowledge, game evidence, local engines, live state, and MCP/HTTP transport. `ui/src/` owns browser presentation and uses sibling chessboard events. Stale revisions never publish annotations, rejected optimistic moves roll back, hints hide solutions, and opponent strength remains separate from evidence analysis.

`tools/scripts/generate_tutor_skill.py --check` validates the portable `.agents/skills/chess_tutor/` output against authoritative Agents sources. Backend checks use `uv run --locked --extra vision pytest`; explicit style checks use `uv run ruff check src tests tools/scripts` and `uv run python tools/scripts/format_code.py --check`. Do not add Python comments or docstrings.

## 5. Dependencies

| Dependency | Version | Use |
|---|---|---|
| `mcp` | `2.3.0` | runtime |
| `python-chess` | `1.999` | runtime |
| `python-dotenv` | `1.2.4` | runtime |
| `httpx` | `0.28.1` | runtime |
| `numpy` | `2.5.4` | optional vision |
| `onnxruntime` | `1.31.0` | optional vision |
| `pillow` | `13.0.0` | optional vision |
| `libcst` | `1.9.0` | dev tools |
| `pytest` | `9.1.1` | dev tools |
| `pytest-asyncio` | `1.4.1` | dev tools |
| `ruff` | `0.17.2` | dev tools |
| `uv_build` | `>=0.12,<0.13 (declared; build resolution not locked)` | build |

## 6. Roadmap

- [x] Contract version 3 and temporary live workspace.
- [ ] Revalidate remote and voice behavior separately when deployment is requested.

## 7. Contributing

Read `AGENTS.md` and the applicable skills in `.ai/skills/` before contributing. Set up the development environment with `uv sync --locked --extra vision`. Follow the repository conventions, preserve supported behavior, and add relevant tests for behavior changes. Run `uv run --locked --extra vision pytest` and `uv build --out-dir build/packages` before opening a pull request. Describe the change, its purpose, and the validation results in the pull request.

## 8. License

`gambit` is licensed under the MIT license. See LICENSE for the complete license text.

See `ACKNOWLEDGEMENTS.md` for third-party notices and attributions.
