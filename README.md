# `gambit`

![Version](https://img.shields.io/badge/Version-0.3.0-737373?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-737373?style=flat-square)
![Languages](https://img.shields.io/badge/Languages-Python%2C%20TypeScript-737373?style=flat-square)
![Frameworks](https://img.shields.io/badge/Frameworks-MCP%2C%20Stockfish%2C%20Vite-737373?style=flat-square)
![Compatibility](https://img.shields.io/badge/Compatibility-Not%20verified-737373?style=flat-square)
![Build](https://img.shields.io/badge/Build-Not%20verified-737373?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-147%20backend%20passing-737373?style=flat-square)
![Vulnerabilities](https://img.shields.io/badge/Vulnerabilities-0%20known%20dependency%20findings-737373?style=flat-square)

## 1. Introduction

Gambit is an MCP server that gives connected hosts validated chess facts, bounded local Stockfish analysis, attributed API information, and a localhost playing workspace. The connected host writes the explanations and handles audio.

## 2. Usage

Install Python 3.14.7, uv 0.12.10, Node.js 24.22.0, npm 11.19.1, Task 3.54.0, and Stockfish. Then initialize and start the server:

```sh
uv sync --locked --extra vision
uv run gambit initialize
uv run gambit
```

`.env.example` documents the optional settings. Keep real credentials private. `showcase/configuration.toml` shows TOML configuration, and `uv run gambit serve --transport streamable-http --port 3025` serves MCP over HTTP.

### Playing Workspace

Build the sibling `../chessboard` checkout first. Then build the interface and start the workspace:

```sh
npm ci --prefix ui
npm run build --prefix ui
uv run gambit play --port 3030
```

## 3. Features

- Position facts, batch analysis, and move comparisons.
- PGN validation and board recognition.
- Opening classifications.
- Opt-in, attributed provider requests.
- Temporary live games.

Contract version 3 preserves White-relative scores, history identity, units, attribution, search bounds, and revision checks.

Only opening classifications and non-personal configuration persist. Games, evidence, jobs, and API caches stay bounded and process-local. Gambit doesn't support learner profiles, personalized databases, server-authored explanations, speech synthesis, local tablebases, or bulk personal downloads.

## 4. Architecture

`src/gambit/` separates providers, knowledge, game evidence, local engines, live state, and MCP and HTTP transport. `ui/src/` owns browser presentation and uses sibling Chessboard events. Stale revisions never publish annotations, rejected optimistic moves roll back, hints hide solutions, and opponent strength stays separate from evidence analysis.

HTTP binds to loopback and validates the peer, host, origin, request type, and size. `GAMBIT_UI_ORIGIN` can allow one exact HTTPS `.ts.net` origin through loopback. Forwarded headers never replace the peer.

### Conventions

- Never persist personal identifiers or response bodies in logs.
- Preserve the existing remote MCP connection.
- Don't add Python comments or docstrings.

### Verification

Backend checks use `uv run --locked --extra vision pytest`. Explicit style checks use `uv run ruff check src tests tools/scripts` and `uv run python tools/scripts/format_code.py --check`. `tools/scripts/generate_tutor_skill.py --check` validates the portable `.agents/skills/chess_tutor/` output against the authoritative Agents sources.

## 5. Dependencies

| Dependency | Version | Use |
|---|---|---|
| `mcp` | 2.3.0 | Runtime: MCP server |
| `python-chess` | 1.999 | Runtime: chess rules and engine protocol |
| `python-dotenv` | 1.2.4 | Runtime: environment configuration |
| `httpx` | 0.28.1 | Runtime: provider requests |
| `numpy` | 2.5.4 | Optional `vision` runtime: image arrays |
| `onnxruntime` | 1.31.0 | Optional `vision` runtime: recognition model inference |
| `pillow` | 13.0.0 | Optional `vision` runtime: image decoding |
| `libcst` | 1.9.0 | Development: source formatting checks |
| `pytest` | 9.1.1 | Development: tests |
| `pytest-asyncio` | 1.4.1 | Development: asynchronous tests |
| `ruff` | 0.17.2 | Development: static checks |
| `uv_build` | `>=0.12,<0.13`, declared; not locked | Build: package backend |

`ui/README.md` lists the browser workspace's dependencies.

## 6. Roadmap

- [x] Contract version 3 and the temporary live workspace.
- [ ] Revalidate remote and voice behavior separately when deployment is requested.

## 7. Contributing

Read `AGENTS.md` and the applicable skills in `.ai/skills/` before contributing. Set up the development environment with `uv sync --locked --extra vision`. Follow the repository conventions, preserve supported behavior, and add relevant tests for behavior changes. Run `uv run --locked --extra vision pytest` and `uv build --out-dir build/packages` before opening a pull request. Describe the change, its purpose, and the validation results in the pull request.

## 8. License

`gambit` is licensed under the MIT license. See LICENSE for the complete license text.

See `ACKNOWLEDGEMENTS.md` for third-party notices and attributions.
