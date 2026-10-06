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

The MCP host discovers tool schemas from the server. A typical session can call `inspect_position` or `evaluate_position`, compare moves with `assess_candidate_move`, and build a grounded explanation with `create_tutor_turn`. `parse_game`, `analyze_game`, and `review_game` handle Portable Game Notation (PGN) games. Whole-game jobs can be started, polled, cancelled, and resumed through the analysis-job tools.

The `instant`, `quick`, and `deep` profiles default to 12,000, 100,000, and 1,000,000 search nodes. These are work budgets, not response-time promises. Worker queueing, CPU load, and position complexity affect latency. New evaluation tools report scores from White's perspective; legacy `analyze_position` and `tutor_move` retain side-to-move scores. Mate results are separate from centipawn scores.

Supply the initial Forsyth-Edwards notation (FEN) position and move history when repetition matters. A FEN alone cannot establish earlier repetitions. Review labels describe Gambit's policy, not Stockfish's native labels or a rating estimate. Candidate comparisons can return `uncertain` when searches disagree.

`start_progressive_analysis` returns an early result while deeper work continues. Progressive requests are short-lived and do not survive a server restart. Whole-game jobs save completed searches to SQLite and can resume from checkpoints. Cancelling a job stops active engine searches; completed reports remain readable.

## Openings, practice, and optional features

The bundled opening data contains 3,864 named Lichess lines. `initialize_openings` loads them, and `import_study` and `import_opening_tsv` add sourced local material. Repertoire drills share review history across transpositions. Corpus membership does not show that a move is best, and Gambit does not download extra opening or game data on its own.

For lessons, use `start_teaching_session`, `get_teaching_hint`, and `submit_teaching_move`. Gambit records attempts and spaced review. Assisted answers do not count as independent successes. `import_puzzles` accepts sourced Lichess-format puzzles; a move outside the source line is checked separately instead of being called a mistake automatically. `create_game_lessons` builds lessons from a saved game report. Learning counts are history, not a calibrated mastery score.

Set `syzygy_path` to use local Syzygy tablebases. Missing files produce an unavailable result; tablebase files are never downloaded automatically. `get_tablebase_diagnostics` checks local paths and file pairs, while `scripts/check_tablebases.py` can verify files against a trusted checksum manifest.

`get_speech_plan` prepares move text for speech. With espeak-ng installed, `synthesize_speech` writes a local WAV file; remote clients cannot read that file URI automatically. Screenshot recognition requires `uv sync --extra vision` and the optional model described in [third-party notices](src/gambit/THIRD_PARTY_NOTICES.md). Gambit does not provide microphone input, streamed audio, or a built-in conversational model.

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

## License

Gambit is released under the [MIT license](LICENSE). Stockfish, python-chess, the bundled opening corpus, and optional vision assets retain their own licenses and attribution.
