# `AGENTS.md`

## 1. Scope

Artificial intelligence (AI) agents MUST follow these instructions when working in Gambit. Workspace work also follows the applicable rules in the workspace's `agents/` checkout.

## 2. Responsibilities

Gambit provides validated chess facts, bounded local Stockfish analysis, attributed API information, and a localhost playing workspace. The connected host owns all explanations and audio. Agents MUST preserve contract version 3, score perspectives, source attribution, history identity, and finite-search limitations. Agents MUST NOT add learner tracking, personalized databases, server-authored explanations, or speech synthesis.

Python modules live under `src/gambit/`. `providers/` owns bounded remote requests and provider semantics. `knowledge/` owns the opening-classification corpus. `game/` owns position facts and evidence composition. `live/` owns temporary game state and the separate Stockfish opponent. `server/` exposes MCP and protected localhost routes. `ui/src/` owns browser presentation.

## 3. State and Privacy

Only opening classifications, their index and metadata, and non-personal configuration may persist. Agents MUST keep games, evidence, jobs, and API caches bounded and process-local. Agents MUST NOT persist usernames, personal game history, conversations, or learner information. Restart clears game and evidence references. Separate processes do not share games.

Agents MUST preserve unrelated dirty work, `.env`, and credentials. Agents MUST NOT print secrets. Authorized cleanup MUST be scoped to recognized Gambit runtime artifacts, support preview, preserve unknown files, and avoid personal backups. Local tablebase and bulk data downloads MUST NOT be introduced. Chess.com history and tablebases are API-only. Personal identifiers and response bodies MUST NOT appear in logs.

## 4. Correctness and Playing Workspace

Agents MUST validate legal positions, moves, turn ownership, game identifiers, and expected revisions. Stale results MUST NOT publish annotations. Claimable draws MUST remain distinct from terminal outcomes. Rules facts MUST distinguish attacks, captures, and pins. Unknown history MUST remain explicit. Scores MUST remain White-relative; mate units, bounds, and tablebase conditions MUST remain intact. Caches MUST include all evidence inputs and contract version.

The frontend MUST use the sibling `@mayazrakib/chessboard` package without copying its implementation. Opponent strength MUST remain separate from evidence analysis. Hints MUST hide solution moves and evidence references. Optimistic moves MUST roll back on rejection. Board events MUST replace model polling. UI restart and temporary-state semantics MUST remain visible.

HTTP MUST bind to loopback. UI routes MUST validate client, host, origin, content type, and request size. An exact configured HTTPS `.ts.net` origin may be accepted through loopback using `GAMBIT_UI_ORIGIN`. Forwarded headers MUST NOT replace the actual peer. Agents MUST preserve the existing remote MCP connection without infrastructure changes.

## 5. Skills and Verification

Canonical chess rules and skills live in the workspace `agents/` repository. Agents MUST edit authoritative sources and use `scripts/generate_tutor_skill.py` to regenerate `.agents/skills/chess_tutor/`. Generation MUST pass `--check`. The retained `chess_tutor` identifier is an explicit compatibility exception to hyphenated skill naming.

Backend checks use `uv run pytest`, `uv run ruff check src test scripts`, and `uv run python scripts/format_code.py --check`. Agents MUST format only affected Python files when unrelated dirty work exists. Agents MUST NOT add Python comments or docstrings. Frontend checks use `npm --prefix ui run build` and `npm --prefix ui test`. Browser results MUST NOT establish remote or voice behaviour.

Use `uv run gambit play --port 3030` after building the sibling chessboard and UI. The same process serves `/mcp`. Generated static assets MUST be built before packaging. Benchmarks MUST identify transport, cache state, workload, and sample distribution. Correctness MUST NOT be weakened to improve latency.
