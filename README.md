# Gambit

Gambit is an MCP server for validated chess facts, engine analysis, and attributed information. Analysis runs locally with Stockfish. The connected AI writes explanations and supplies audio. Gambit distinguishes computed facts, finite engine searches, tablebase results, source commentary, and observed game statistics. It cannot guarantee that an AI's explanation is correct.

## Learning history and persistence

Gambit 0.3 does not provide persistent learning history, learner profiles, progress tracking, or review scheduling. Active games, move history, analysis evidence, jobs, and API caches are temporary and process-local. Restart clears them. Persistent data is limited to opening classifications, their index and metadata, and non-personal configuration. Any conversation history retained by a connected AI host is separate from Gambit.

Older project summaries and third-party descriptions may describe learner tracking or persistent history from earlier versions. Those claims do not describe Gambit 0.3. Use this README and the server's `get_capabilities` response to check current capabilities and retention. The migration section below lists the removed interfaces.

## Install and connect

Install Python 3.14, uv, and Stockfish, then run:

```sh
uv sync --extra vision
uv run gambit initialize
uv run gambit
```

`initialize` validates the bundled, version-pinned opening classifications. It does not download games, puzzles, evaluations, or tablebases. Explicit opening updates use `uv run gambit update-openings --revision FULL_COMMIT_SHA`; all five ECO volumes are validated before atomically replacing the snapshot. MCP uses standard input and output by default. Configure a host to launch `uv --directory /absolute/path/to/gambit run gambit`. Set `STOCKFISH_PATH` for another executable and `GAMBIT_CONFIG` for a TOML configuration based on [the example](examples/configuration.toml).

The HTTP transport uses `uv run gambit serve --transport streamable-http --port 3025`. It binds to loopback and serves MCP at `/mcp`. Existing tunnel service templates remain supported; installing or changing remote infrastructure is a separate operation. Preserve package-local `.env` credentials.

## Evidence tools

The server exposes 27 tools. `get_position` returns board state, material, legal moves, and optional typed rules answers without engine or network work. Supply `fen` with optional `history`, or a live `game_id` with `expected_revision`. Optional `continuation` explores a hypothetical line without changing the game.

`get_evidence` combines selected `facts`, `analysis`, `openings`, `statistics`, `cloud`, and `tablebase` sections. The default is local facts and instant preliminary analysis. External information is opt-in. `analyze_position` accepts either `fen` with optional `history`, or up to 128 `positions` containing those fields. Batches return `items` in request order. Both forms share `profile` and `is_compact`. `analyze_move` and `compare_moves` assess legal candidates.

`read_board` converts a board image to FEN with reliability information. Check uncertain recognition before passing the position to analysis. `read_pgn` validates a game without an engine. `analyze_game` includes move classifications and player summaries by default; set `should_review=false` for analysis only. Background game analysis uses `start_game_analysis`, `get_analysis_job`, and `cancel_analysis_job`. `get_metrics` reports process-local analysis metrics.

Engine scores are White-relative. Mate scores use moves, while tablebase distances use plies. Search bounds and preliminary status remain explicit. A principal variation is not exhaustive proof. Position references include history identity and scope. Unknown prior history cannot rule out repetition. API failures preserve available local sections. Responses use native structured content without duplicating the payload in text.

`get_analysis` retrieves full temporary evidence. Missing references return `status: expired`; recompute when necessary. Evidence, jobs, and API caches are bounded and process-local. Restart clears them. Source comments are attributed advice, not verified engine explanations.

## Information sources

| Information | Access |
|---|---|
| Opening names, ECO codes, and identifying lines | Bundled Lichess opening classifications, revision pinned |
| Masters and Lichess move outcomes | `get_opening_stats`, opening-explorer API |
| Public puzzles | `get_puzzle`, Lichess API |
| Selected games | `get_game`, Lichess or Masters API |
| Annotated studies | `get_study`, explicit public study and chapter IDs |
| Existing cloud evaluations | `get_cloud_analysis`, Lichess API |
| Endgames with at most seven pieces and no castling rights | `get_tablebase`, remote tablebase API |
| One explicit Chess.com account month | `get_chesscom_games`, API only |

The [opening corpus](https://github.com/lichess-org/chess-openings) provides classifications, not complete opening theory. Explorer responses retain population, filters, outcomes, sample size, and example references. Popularity does not establish quality. Providers may require authentication, throttle requests, omit positions, or lack exhaustive search. Set `GAMBIT_LICHESS_TOKEN` for opening-explorer authentication when required; it is sent only to the explorer host. Study selection is explicit; arbitrary annotated-study search is not provided. Licenses absent from source responses remain unknown.

The HTTP client reuses connections, serializes requests per provider, deduplicates matching cacheable requests, bounds response size and elapsed time, and respects rate-limit cooldowns. Cloud lookup does not request remote engine execution. Chess.com responses are not cached or indexed on disk. No learner profiles, personal account defaults, conversation history, or review scheduler exist.

## Local playing workspace

Build the sibling `../chessboard`, then run:

```sh
npm --prefix ui install
npm --prefix ui run build
uv run gambit play --port 3030
```

Open `http://127.0.0.1:3030`. This process also serves `/mcp`. UI and MCP share the active game only within that process. Restart clears the game, variations, annotations, and evidence. `analyze_live_game` returns evidence and publishes revision-matched annotations. `get_live_game` omits full history by default. `annotate_live_game` changes only the annotation group. Hint mode hides solutions. Opponent strength is independent of analysis strength.

Local routes enforce loopback peers, approved host/origin, request type, and size. `GAMBIT_UI_ORIGIN` can allow an exact HTTPS Tailscale origin through Serve. Browser events do not establish automatic spoken commentary or remote voice latency.

## Migration from version 0.2

Version 0.3 introduces contract version 3 at `gambit://contracts/v3`. Learner, repertoire, tutoring-session, practice-progress, dataset synchronization, speech, and local tablebase interfaces are removed. Replace `create_tutor_turn` with `get_evidence`; replace personal archive sync with bounded `get_chesscom_games` requests. `analyze_position` now reports White-relative scores. Remove `database_path`, `syzygy_path`, speech, automatic-refinement, and prefetch options from TOML configuration. `GAMBIT_DATABASE` no longer configures storage.

The simplified MCP catalog replaces the earlier tool names without aliases. Use `get_position` instead of `inspect_position`, `list_legal_moves`, or `query_chess_facts`; use `analyze_position` instead of `evaluate_position` or `analyze_positions`. It uses search profiles and returns structured evidence rather than the former `lines` response. Use `analyze_game` instead of `review_game`, `read_board` instead of `recognize_chessboard` or `analyze_chessboard`, and `analyze_live_game` instead of `teach_live_game`. Opening tools are `find_openings`, `get_opening`, and `get_opening_stats`. Reconnect clients after restarting the updated server to refresh their tool catalogs.

Preview recognized obsolete artifacts under `GAMBIT_RUNTIME_DIRECTORY` with `uv run gambit cleanup`. Apply removal with `uv run gambit cleanup --apply` while old Gambit processes are stopped. Cleanup removes recognized personal databases, local downloads, tablebases, and dependent metadata without creating a backup. It preserves opening snapshots, configuration, credentials, symlinks, and unclassified files. Inspect reported preserved files separately. Cleanup covers the specified runtime root, not external backups or forensic erasure.

## Development

Run `uv run pytest`, `uv run ruff check src test scripts`, `uv run python scripts/format_code.py --check`, and `uv run python scripts/generate_tutor_skill.py --check`. Frontend validation uses `npm --prefix ui run build` and `npm --prefix ui test`. API tests use deterministic fixtures; live provider smoke checks are separate. Run `uv run python tests/perf/benchmark_mcp.py` for local MCP latency and response-size measurements. These exclude model generation and audio.

## License

MIT. See [LICENSE](LICENSE) and [third-party notices](src/gambit/THIRD_PARTY_NOTICES.md).
