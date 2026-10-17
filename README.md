# Gambit

`gambit` is a local chess analysis and tutoring server for the Model Context Protocol (MCP). It gives an MCP host access to Stockfish analysis, opening records, game reviews, puzzles, and learner history. The host's language model handles the conversation; Gambit supplies chess evidence and stores learning state.

## Install and connect

Gambit requires Python 3.14 or newer, uv, and a compatible Stockfish executable. From the project directory:
```sh
uv sync
uv run gambit initialize
uv run gambit
```

`initialize` loads the bundled opening corpus into the local SQLite database. The final command starts MCP over standard input and output. Configure an MCP host to run `uv --directory /absolute/path/to/gambit run gambit`.

Set `STOCKFISH_PATH` to choose the engine, `GAMBIT_DATABASE` to choose the database, and `GAMBIT_CONFIG` to point to a local TOML file. Copy [the example configuration](examples/configuration.toml) to set worker counts, analysis budgets, cache size, and optional tablebase paths. The default pool uses two Stockfish workers, one engine thread and 64 MiB of hash per worker.

## Chess tools and evidence

The MCP host discovers tool schemas from the server. For live tutoring, use one `create_tutor_turn` call per new position. Its default `instant` profile returns compact evidence and speech guidance; supply `move` to assess a learner's move in the same call. Reuse matching evidence for follow-up explanations. Set `is_compact` to `false` or retrieve the analysis ID with `get_analysis` when a full report is needed. The repository's [chess tutoring skill](.agents/skills/chess_tutor/SKILL.md) defines this workflow.

Interactive evaluation, candidate assessment, and teaching submissions default to `instant`. Single-position legacy tools default to 12,000 nodes and one variation. Request `deep` explicitly for two-budget candidate confirmation. Preliminary teaching feedback does not count as confirmed progress; an inconclusive session stays active for deeper resubmission. `parse_game`, `analyze_game`, and `review_game` handle Portable Game Notation (PGN) games. Whole-game jobs retain their review budgets and can be started, polled, cancelled, and resumed.

The `instant`, `quick`, and `deep` profiles default to 12,000, 100,000, and 1,000,000 search nodes. These are work budgets, not response-time promises. Worker queueing, CPU load, and position complexity affect latency. New evaluation tools report scores from White's perspective; legacy `analyze_position` and `tutor_move` retain side-to-move scores. Mate results are separate from centipawn scores.

Engine startup runs during server initialization. Searches at or below the instant and quick node budgets also have default engine time limits of 150 and 600 milliseconds, capped by `search_time_ms`. These limits exclude startup, queueing, transport, and audio. Repeated evaluations reuse stored evidence with matching profile and history. Server logs report operation queue and execution times; ChatGPT controls Voice scheduling and delivery.

Supply the initial Forsyth-Edwards notation (FEN) position and move history when repetition matters. A FEN alone cannot establish earlier repetitions. Review labels describe Gambit's policy, not Stockfish's native labels or a rating estimate. Candidate comparisons can return `uncertain` when searches disagree.

`start_progressive_analysis` returns an early result while deeper work continues. Progressive requests are short-lived and do not survive a server restart. Whole-game jobs save completed searches to SQLite and can resume from checkpoints. Cancelling a job stops active engine searches; completed reports remain readable.

## Openings, practice, and optional features

The bundled opening data contains 3,864 named Lichess lines. `initialize_openings` loads them, and `import_study` and `import_opening_tsv` add sourced local material. Repertoire drills share review history across transpositions. Corpus membership does not show that a move is best, and Gambit does not download extra opening or game data on its own.

For lessons, use `start_teaching_session`, `get_teaching_hint`, and `submit_teaching_move`. Gambit records attempts and spaced review. Assisted answers do not count as independent successes. `import_puzzles` accepts sourced Lichess-format puzzles; a move outside the source line is checked separately instead of being called a mistake automatically. `create_game_lessons` builds lessons from a saved game report. Learning counts are history, not a calibrated mastery score.

Set `syzygy_path` to use local Syzygy tablebases. Missing files produce an unavailable result; tablebase files are never downloaded automatically. `get_tablebase_diagnostics` checks local paths and file pairs, while `scripts/check_tablebases.py` can verify files against a trusted checksum manifest.

`get_speech_plan` prepares move text for speech. With espeak-ng installed, `synthesize_speech` writes a local WAV file; remote clients cannot read that file URI automatically. Screenshot recognition requires `uv sync --extra vision` and the optional model described in [third-party notices](src/gambit/THIRD_PARTY_NOTICES.md). Gambit does not provide microphone input, streamed audio, or a built-in conversational model.

## Personal game archive

Import your Chess.com history once, then use the same command to sync new games:
```sh
uv run python scripts/sync_games.py --username mayazrakib
```

Gambit keeps monthly JSON archives, including PGNs and game metadata, under `runtime/downloads` and indexes standard games in `runtime/corpus.sqlite3`. The first sync downloads every listed month. Later syncs revalidate the archive index, current month, and previous month using ETag and Last-Modified headers. Older downloaded months stay local; `--refresh` revalidates them too. Requests to Chess.com are sequential, rate-limit retries respect Retry-After, and unchanged responses reuse local files. The API can lag behind completed games. See the [Chess.com API documentation](https://www.chess.com/news/view/published-data-api).

From MCP, use `manage_chess_data` with action `sync_games`, then inspect action `status`. This path syncs personal games without downloading the bulk teaching datasets. Game URLs identify games across repeated imports and updated annotations. Use `search_chess_material` and `get_chess_game` to select a local game for review.

Downloading and importing games never starts Stockfish. Analyze requested games or selected training examples separately. Whole-game searches reuse durable checkpoints across jobs and restarts when engine identity, analysis settings, root position, and move history match. Changed evidence inputs trigger new analysis. Repository runtime data remains outside Git and shares the 20 GB capacity limit.

## Background service

The default MCP transport is stdio. On Linux with systemd, Gambit can instead serve streamable HTTP on `127.0.0.1:3025/mcp` behind an outbound tunnel. Copy [.env.example](.env.example) to the ignored package-local `.env`, fill in the tunnel credentials, and keep the file private. The HTTP server has no independent authentication, so keep it on loopback.

After installing the tunnel client and running `uv sync`, install the user services with:
```sh
chmod 600 .env
uv run python scripts/install_services.py
loginctl enable-linger "$USER"
systemctl --user status gambit.service gambit_tunnel.service
```

The installer enables Gambit and the tunnel as separate services. Restart both after changing `.env` with `systemctl --user restart gambit.service gambit_tunnel.service`. The tunnel can reconnect without restarting Gambit; restarting Gambit interrupts unfinished work. Host shutdown or suspension also interrupts availability.

## Storage and development

Gambit stores analysis and learning records in SQLite. `scripts/maintain_storage.py` backs up a live database with SQLite's backup API, restores into a new file, and previews retention before applying it. Retention is never automatic. For example:
```sh
uv run python scripts/maintain_storage.py backup --path /absolute/path/to/new_backup.sqlite3
uv run python scripts/maintain_storage.py prune --age-days 90
```

Run the local checks from the project directory:
```sh
uv run pytest
uv run ruff check src test scripts
uv run python scripts/format_code.py --check
uv build
```

Installed Stockfish and the vision extra are needed for their respective integration tests. These checks cover chess and protocol behavior; they do not measure tutoring quality, model generation latency, or remote tunnel latency.

The package groups its contracts, engine integration, game analysis, infrastructure, knowledge sources, learning services, MCP server, and optional vision support into matching subpackages under `src/gambit/`.

## License

Gambit is released under the [MIT license](LICENSE). Stockfish, python-chess, the bundled opening corpus, and optional vision assets retain their own licenses and attribution.
