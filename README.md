# `gambit`

---

[![Testing](https://img.shields.io/badge/Testing-87%20passing-237c65)](#development-and-verification)
[![License: MIT](https://img.shields.io/badge/License-MIT-237c65)](LICENSE)

`gambit` is a local-first chess analysis and tutoring server for the Model Context Protocol (MCP). It connects an AI tutor to Stockfish, opening knowledge, and persistent learning history.

It features:
- Bounded Stockfish analysis with warm engine workers, cached results, candidate comparisons, and progressive feedback.
- Whole-game analysis with persistent checkpoints, cancellation, and restart recovery.
- Position-specific teaching sessions, graduated hints, game-derived lessons, and spaced review.
- A bundled corpus of 3,864 named opening lines, study imports, transposition-aware repertoires, and source-attributed plans.
- Tactical puzzles, pawn-structure analysis, endgame evaluation, and local Syzygy tablebase probing.
- Structured speech plans, optional local speech synthesis, and optional screenshot recognition.
- Local stdio and HTTP transports, persistent Linux services, and an optional outbound tunnel.
- SQLite storage with explicit backup, restore, and retention commands.

It is authored by Mayaz Rakib.

## Installation and Setup

Install Python 3.14 or newer, uv, and Stockfish 18 or a newer compatible UCI engine. From the package directory, install dependencies and initialize the bundled opening knowledge:
```sh
uv sync --extra vision
uv run gambit initialize
uv run gambit
```

Omit `--extra vision` if screenshot recognition is not needed. The distribution and Python import package are both named `gambit`; the source package is [src/gambit](src/gambit/).

The default transport is MCP stdio. Configure your MCP host to run `uv --directory /absolute/path/to/gambit run gambit`. Protocol messages use stdout. For the background service and tunnel, keep credentials in the ignored package-local `.env`, never in committed configuration or a parent dotenv.

Set `STOCKFISH_PATH` to override the executable. Set `GAMBIT_DATABASE` to select the local SQLite database. Set `GAMBIT_CONFIG` to a TOML configuration file. Configuration keys and defaults are defined in [configuration.py](src/gambit/configuration.py).

## Background Services and Connections

Install the official [OpenAI tunnel client](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Copy [.env.example](.env.example) to `.env` inside this package, and replace its placeholders with your runtime API key and tunnel ID. Existing environment variables take precedence when launching Gambit directly. The loader reads only this package's dotenv, not parent directories.

On Linux with systemd, run from this package after `uv sync`:
```sh
chmod 600 .env
uv run python scripts/install_services.py
loginctl enable-linger "$USER"
systemctl --user status gambit.service gambit_tunnel.service
```

The installer creates and enables two user services from [the service templates](deploy/). Gambit serves streamable HTTP at `http://127.0.0.1:3025/mcp`; the tunnel connects outbound to OpenAI. Both restart after failures. Linger keeps them running after logout and starts them when the systemd host boots. Closing a shell does not stop them. Shutting down Windows or WSL, suspending the host, or stopping the Linux machine still interrupts availability.

In ChatGPT developer mode, create an app from the Plugins page, select **Tunnel** as its connection, and select the tunnel matching `CONTROL_PLANE_TUNNEL_ID`. The runtime key must have Tunnels Read and Use permissions, and the tunnel must belong to the relevant workspace. The key authenticates the tunnel, not an LLM: the model selected in ChatGPT supplies the conversational tutoring. See the [official connection instructions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Check tunnel readiness, restart the services, or stop them with these commands:
```sh
curl --noproxy '*' --max-time 5 http://127.0.0.1:3026/readyz
systemctl --user restart gambit.service gambit_tunnel.service
systemctl --user stop gambit_tunnel.service gambit.service
```

Use `disable --now` instead of `stop` to also disable automatic startup. After changing `.env`, restart both services. The tunnel's local status interface is `http://127.0.0.1:3026/ui`. Keep both listeners on loopback; do not expose Gambit's unauthenticated HTTP server directly to the network. The tunnel can reconnect without restarting Gambit or interrupting its analysis jobs. Restarting Gambit itself interrupts unfinished jobs.

## Architecture

The server exposes factual chess tools and structured teaching turns to an MCP host. The host's language model provides conversational explanation. No model key or network model call is required by Gambit. Engine evidence, corpus provenance, learning state, board directives, and speech segments remain separate:
- [engine.py](src/gambit/engine.py) owns warm Stockfish subprocesses and bounded searches.
- [analysis.py](src/gambit/analysis.py) provides configurable worker pooling, duplicate-search coalescing, persistent analysis, and background game jobs.
- [games.py](src/gambit/games.py) validates PGN and produces adaptive game analysis and review classifications.
- [knowledge.py](src/gambit/knowledge.py) imports PGN studies and opening TSV, matches transpositions, and probes local Syzygy files.
- [training.py](src/gambit/training.py) manages learner preferences, source-attributed puzzles, spaced repetition, and lessons.
- [features.py](src/gambit/features.py) computes geometric and pawn-structure facts.
- [tutoring.py](src/gambit/tutoring.py) assembles grounded teaching turns.
- [speech.py](src/gambit/speech.py) pronounces legal moves and optionally synthesizes local WAV audio with espeak-ng.
- [ocr.py](src/gambit/ocr.py) recognizes axis-aligned board screenshots with the optional vision dependencies.

The sibling chessboard package can consume the FEN, legal UCI variations, and arrow directives. A client owns playback, animation timing, audio interruption, and stale-position rejection.

## Configuration

Copy [the example configuration](examples/configuration.toml) to a local TOML file and set `GAMBIT_CONFIG` to its absolute path. Environment overrides include `STOCKFISH_PATH` for the executable and `GAMBIT_DATABASE` for storage.

| Setting | Default | Purpose |
|---|---|---|
| `worker_count` | `2` | Number of warm engine processes. |
| `threads_per_worker` | `1` | Engine threads per process. |
| `hash_mb_per_worker` | `64` | Hash memory per process, in MiB. |
| `cache_capacity` | `512` | Maximum in-memory analysis cache entries. |
| `instant_nodes` | `12000` | Preliminary search budget. |
| `quick_nodes` | `100000` | Routine search budget. |
| `deep_nodes` | `1000000` | Deeper verification budget. |
| `candidate_count` | `3` | Candidate variations for quick and deep searches. |
| `search_time_ms` | `5000` | Per-search time ceiling, in milliseconds. |
| `search_depth` | `64` | Per-search depth ceiling, in plies. |
| `max_jobs` | `16` | Background job capacity. |
| `is_reproducible` | `false` | Clear engine hash before uncached work. |
| `syzygy_path` | Empty | Local tablebase directories. |
| `speech_executable` | `espeak-ng` | Optional local speech executable. |
| `speech_directory` | `~/.cache/gambit/speech` | Generated audio directory. |

### Analysis Budgets and Evidence

Profiles use node budgets, not latency guarantees: `instant` defaults to 12,000 nodes and one variation, `quick` to 100,000 nodes and three variations, and `deep` to 1,000,000 nodes and three variations. Customize `instant_nodes`, `quick_nodes`, `deep_nodes`, and `candidate_count` in [the example configuration](examples/configuration.toml). Searches additionally stop at `search_time_ms` (5,000 by default) or `search_depth` (64 by default), whichever search limit is reached first. End-to-end latency includes queueing and depends on CPU, position, and concurrent work. Each engine operation has a 30-second response deadline.

The default pool has two workers, one thread per worker, and 64 MiB of hash per worker. Adjust `worker_count`, `threads_per_worker`, and `hash_mb_per_worker` together to avoid CPU oversubscription. `is_reproducible` resets search hash before uncached work. Exact results can still differ between engine versions and hardware. New analysis responses record the engine version and executable SHA-256.

New evaluation tools use White-relative scores. Legacy `analyze_position` and `tutor_move` preserve side-to-move scoring. Mate values are separate from centipawns. Review labels are Gambit policy, not native Stockfish labels or a rating estimate.

Supply initial FEN plus move history to `evaluate_position` when repetition history matters. A standalone FEN cannot establish previous repetitions. Opening transposition keys intentionally omit move counters; engine cache keys retain counters and supplied history.

Background game searches use at most one fewer worker than the pool size, reserving interactive capacity when there are at least two workers. A one-worker configuration cannot reserve separate interactive capacity. `get_analysis_metrics` reports a bounded window of queue and search latency samples, cache hits, and pending requests.

Game jobs checkpoint completed searches to SQLite. Checkpoint identity includes the root position, move history, search settings, engine binary digest, and configuration. Queued, running, and interrupted jobs with saved inputs resume at startup within the job limit. `resume_analysis_job` also resumes explicitly cancelled or failed jobs. Old jobs without saved inputs remain interrupted and require resubmission. Cancellation sends UCI `stop` to active searches and drains the engine response before reuse. Completed reports remain readable. Job status distinguishes completed and reused search counts; neither is an estimated completion percentage.

`start_progressive_analysis` returns preliminary evidence and a request ID for deeper background analysis. Reusing a context ID cancels the previous request. Poll `get_progressive_analysis`, then retrieve its analysis ID through `get_analysis`; use `cancel_progressive_analysis` when a board is closed. Clients must still reject mismatched context IDs and FENs. These short-lived requests do not resume after a process restart; whole-game jobs do.

`assess_candidate_move` compares an unrestricted root search with a candidate-restricted search at quick and deep budgets. It preserves supplied move history, reports mate transitions separately from centipawn loss, and includes legal lines and observed captures or checks. A serious-mistake label requires agreeing classifications and root best moves, a larger configured budget, and increased measured search work. Disagreement returns `uncertain`. Search agreement is not calibrated confidence or proof of optimality. `evaluate_move` preserves its previous fields and adds this assessment. `compare_candidate_moves` and `create_tutor_turn` accept history; the tutor's `compare` intent now returns candidate assessments.

## Public Tools

The MCP host discovers input schemas from the server. Tools return engine evidence and stored records; the host model supplies conversational explanations.

| Area | Tools |
|---|---|
| Positions | `inspect_position`, `list_legal_moves`, `analyze_position`, `evaluate_position`, `analyze_positions`, `explain_position`, `analyze_pawn_structure` |
| Candidate moves | `tutor_move`, `evaluate_move`, `compare_candidate_moves`, `assess_candidate_move` |
| Games and jobs | `parse_game`, `analyze_game`, `review_game`, `start_analysis_job`, `get_analysis_job`, `cancel_analysis_job`, `resume_analysis_job`, `get_analysis` |
| Progressive analysis | `start_progressive_analysis`, `get_progressive_analysis`, `cancel_progressive_analysis`, `get_analysis_metrics` |
| Opening knowledge | `initialize_openings`, `import_study`, `import_opening_tsv`, `find_opening`, `get_opening_position`, `import_opening_plan`, `get_opening_plans`, `import_opening_statistics`, `get_opening_coverage` |
| Repertoires | `get_repertoire_move`, `create_repertoire_drill`, `get_due_repertoire_drill`, `submit_repertoire_move` |
| Endgames | `get_tablebase_result`, `evaluate_endgame`, `get_tablebase_diagnostics` |
| Learners and puzzles | `update_learner_profile`, `get_learner_progress`, `import_puzzles`, `get_tactic`, `submit_tactic_move`, `record_training_attempt` |
| Lessons and teaching | `start_lesson`, `advance_lesson`, `create_tutor_turn`, `start_teaching_session`, `get_teaching_hint`, `submit_teaching_move`, `get_concept_progress`, `create_game_lessons` |
| Speech and vision | `get_speech_plan`, `synthesize_speech`, `recognize_chessboard`, `analyze_chessboard` |
| Discovery | `get_capabilities` |

The server also publishes a teaching prompt and an analysis resource. Tool contracts are implemented in [main.py](src/gambit/main.py), [tools.py](src/gambit/tools.py), and [extended_tools.py](src/gambit/extended_tools.py).

## Knowledge and Training

Call `initialize_openings` once to load the bundled 3,864 named Lichess opening lines. The corpus is pinned to revision `5a13018164f6bd88f48b3dc31a8e2a39f31a060a` and includes CC0 attribution. Import one PGN study with all its variations through `import_study`. Use the repertoire flag for personal preparation. `import_opening_tsv` accepts the Lichess opening format with `eco`, `name`, and `pgn` columns. Sources are required and retained. Imports are local and do not silently download datasets.

`import_puzzles` accepts bounded batches of the Lichess puzzle CSV schema. Its first move is the opponent's setup move. Subsequent moves form the source solution. Legality is checked, but importing does not independently prove optimality. An alternative move is described as not matching the source, not automatically as a chess mistake.

No corpus can promise every known or studied line. Import versioned sources and personal studies, then use engine analysis beyond their coverage. Opening matches are evidence of corpus membership, not proof that a move is best.

Configure `syzygy_path` for local tablebases. Multiple directories use the platform path separator, a colon on Linux. Paths are expanded consistently for Gambit and Stockfish. Gambit's tablebase handles stay open within a bounded descriptor budget and close with the runtime. Restart after installing or replacing table files. Missing files produce an explicit unavailable result. Raw WDL and DTZ values are returned with their side-to-move perspective and draw-rule caveats; distance to zeroing is not distance to mate.

`get_tablebase_diagnostics` reports missing directories and unpaired WDL/DTZ files. Pairing alone does not prove complete material coverage. For offline integrity verification, supply a trusted SHA-256 manifest containing plain filenames:
```sh
uv run python scripts/check_tablebases.py
uv run python scripts/check_tablebases.py --manifest /absolute/path/to/checksums.sha256
```

Tablebase datasets are not downloaded automatically.

### Adaptive Teaching and Opening Plans

Use `start_teaching_session`, `get_teaching_hint`, and `submit_teaching_move` for a persisted diagnose, ask, assess, explain, and revisit cycle. Hint levels reveal the concept, candidate piece, candidate move, and legal line in that order. `get_concept_progress` reports attempts, independent successes, and spaced-review dates. Assisted answers do not earn independent-success credit, and inconclusive engine assessments do not count as failed attempts. These counts are learning history, not a calibrated mastery probability. Ask the host model to discuss the learner's reasoning; Gambit assesses the move, not the semantic quality of an explanation.

`create_game_lessons` generates up to twenty position-specific lessons from a saved game report for the learner's chosen side. It retains the source report and move history. Repeated topics identify practice candidates; geometric observations do not establish why an engine evaluation changed.

Puzzle answers matching the source continue its line. Alternatives receive two-budget root verification. A sound alternative can be accepted separately, but does not automatically satisfy the source's teaching objective or earn source-solution mastery credit. Unstable alternatives remain inconclusive. Repertoire drills use position identity for spaced review, so transpositions share recall history. `get_due_repertoire_drill` selects a due position without revealing its moves.

`import_opening_plan` accepts plans, pawn breaks, piece placements, and common mistakes with a source, source version, and source date. `get_opening_plans` matches these records by position, including transpositions. Imported advice is explicitly not engine-verified; check a proposed tactical refutation with `assess_candidate_move` in its actual position. `import_opening_statistics` records aggregate outcomes with a source date and population description, separately from theoretical advice. `get_opening_coverage` reports exact local records and positions by source. No external annotated-plan or game-statistics corpus is silently fetched or claimed complete.

The new workflows use versioned output contracts in [contracts.py](src/gambit/contracts.py) and typed assessment and teaching records. Existing legacy tools retain their response shapes unless an additive field is documented here.

Opening initialization also imports four original starter teaching plans for open games, the Sicilian, the Queen's Gambit Declined, and the French. They are explicitly labeled instructional advice, not engine-verified theory. Tutor turns include matching plans except when hiding a solution. This is a small starter set, not comprehensive annotated opening coverage.

## Storage Maintenance and Credentials

Backups use SQLite's online backup API and an integrity check, not a copy of a potentially active database file. Backup and restore destinations must be new files. Restore into a new database, stop Gambit, set `GAMBIT_DATABASE` to the restored path, and restart. The restore command never overwrites the active database.

Use the local maintenance commands to back up, restore, preview retention, or apply retention with a backup:
```sh
uv run python scripts/maintain_storage.py backup --path /absolute/path/to/new_backup.sqlite3
uv run python scripts/maintain_storage.py restore --path /absolute/path/to/new_backup.sqlite3 --destination /absolute/path/to/restored.sqlite3
uv run python scripts/maintain_storage.py prune --age-days 90
uv run python scripts/maintain_storage.py prune --age-days 90 --apply --path /absolute/path/to/new_retention_backup.sqlite3
```

Retention defaults to a preview. Applying it first creates a backup and removes at most 1,000 old, unreferenced analysis records and 1,000 old checkpoints belonging to completed jobs per invocation. It preserves learner records, lessons, opening knowledge, reports referenced by other collections, and checkpoints for resumable jobs. Nothing is pruned automatically.

The tunnel continues reading credentials from the ignored package-local `.env`. Gambit's service explicitly removes tunnel credential variables, its dotenv loader imports only `GAMBIT_*` and `STOCKFISH_PATH`, and Stockfish subprocesses receive an environment without OpenAI or control-plane variables. Administrative backup, restore, and checksum operations are local CLI commands rather than remote MCP tools.

## Speech and AI Clients

`create_tutor_turn` returns concise teaching text, evidence, and a speech plan. `get_speech_plan` expands algebraic and UCI move notation into unambiguous spoken moves. `synthesize_speech` uses an installed espeak-ng executable and returns a local WAV URI. No voice model is bundled. A remote MCP client cannot automatically access local file URIs.

For higher-quality streaming speech, send individual plan segments to the client's preferred TTS provider. The server does not stream audio over MCP or manage microphone input. A client should interrupt playback on a new move and discard directives whose FEN no longer matches the board.

The model should use the tutor prompt and supplied evidence, ask short questions, and call `evaluate_move` to check the learner's answer. It should not invent tactical motifs from an evaluation number. Learner preferences customize rating band, Socratic/direct style, detail, speech rate, and voice.

## Development and Verification

Run these commands from the package directory. The project formatter implements the required four-space indentation, call layout, and logical blank-line rules.

| Command | Purpose |
|---|---|
| `uv run pytest` | Run the test suite, including installed-engine checks. |
| `uv run ruff check src test scripts` | Check imports and Python errors. |
| `uv run python scripts/format_code.py` | Apply the project formatting rules. |
| `uv run python scripts/format_code.py --check` | Verify formatting without changes. |
| `uv run python scripts/benchmark_analysis.py --iterations 3` | Measure local analysis latency and check authored positions. |
| `uv build` | Build the source distribution and wheel. |

The test suite contains 87 tests. Install Stockfish and the vision extra to exercise the corresponding integrations. The testing badge records the verified suite count, not code coverage; coverage has not been measured.

Tests include strict PGN parsing, engine protocol fakes, storage persistence, training state, knowledge imports, HTTP reconnects, schema publication, interruption, engine recovery, checkpoint reuse, and MCP round trips. Tests named `test_live_*` exercise installed Stockfish. The benchmark runs fixed authored positions, validates legal variations, tactical results, terminal states, positional facts, and hint leakage, and reports platform and engine provenance alongside cold and warm latency samples. These measurements exclude tunnel latency, model generation, and human teaching-quality assessment. They do not establish an improvement over a previous version without a comparable baseline run. Speech playback remains client-owned; no dedicated voice client is added.

## Licensing

Gambit is authored by Mayaz Rakib and distributed under the [MIT license](LICENSE).

Stockfish is a separately installed GPLv3 executable; python-chess has its own GPL license. The optional screenshot-recognition model and detector attribution are preserved in [third-party notices](src/gambit/THIRD_PARTY_NOTICES.md). The bundled Lichess opening corpus retains its CC0 terms. These third-party terms are separate from Gambit's license.
