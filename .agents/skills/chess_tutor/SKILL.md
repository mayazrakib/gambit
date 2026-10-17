---
name: chess_tutor
description: "Use Gambit to verify chess claims and obtain structured engine evidence, openings, puzzles, and attributed game information."
---

# `SKILL.md`

## 1. Scope

Artificial intelligence (AI) agents MUST follow these rules and instructions when using Gambit for chess instruction, position analysis, move feedback, or chess practice.

This skill supplements [Chess Tutor Rules](references/chess_tutor_rules.md). Connected schemas establish capabilities. Gambit supplies evidence; the client authors explanations and audio.

## 2. Evidence Workflow

Resolve the actual position and known history from context. Ask for missing information only when it changes the answer. Keep hypothetical analysis separate from the mainline.

Use `get_position` for board state, material, legal moves, and optional typed rules predicates. Supply a FEN with optional history, or a live game identifier with its expected revision. An optional continuation is hypothetical and does not change the game. Use `get_evidence` for selected sections: facts, analysis, openings, statistics, cloud, and tablebase. Defaults are local facts and instant preliminary analysis. External sections are opt-in. Request only needed sections; use deeper analysis when the claim needs it.

Reuse matching evidence. Retrieve full temporary evidence with `get_analysis`. A missing reference is expired, not a result. Preserve position identity, history scope, score perspective, bounds, provenance, and limitations. Verify concrete claims before explaining them. Distinguish attacks from captures, observed gains from forced wins, engine preferences from proofs, and source advice from verified facts.

## 3. Tool Routing

| Need | Interface |
|---|---|
| Board image recognition | `read_board`, then verify reliability before analysis |
| PGN validation | `read_pgn` |
| Single or batch position analysis | `analyze_position` |
| Move assessment or comparison | `analyze_move`, `compare_moves` |
| Local opening identification | `find_openings`, `get_opening` |
| Masters or Lichess outcomes and examples | `get_opening_stats` |
| Public puzzle | `get_puzzle` |
| Selected public game or study chapter | `get_game`, `get_study` |
| Existing cloud analysis | `get_cloud_analysis` |
| Remote endgame evidence | `get_tablebase` |
| Explicit Chess.com account and month | `get_chesscom_games` |
| Whole-game analysis and classifications | `analyze_game` |
| Background game analysis | `start_game_analysis`, `get_analysis_job`, `get_analysis`, `cancel_analysis_job` |
| Active board evidence and annotations | `analyze_live_game`, `annotate_live_game` |

Opening statistics must preserve population, filters, and sample size. Opening classifications do not contain exhaustive theory. Studies require explicit public study and chapter identifiers. Missing cloud analysis does not start remote engine work. API failures must remain visible.

`analyze_position` accepts either `fen` with optional `history`, or `positions` containing those fields. Both use the same search profile; batches return `items` in input order. `analyze_game` includes classifications by default; set `should_review=false` for analysis only. Use current connected tool names rather than removed interfaces.

## 4. Live Board and Hints

Use `analyze_live_game` with the known game identifier and revision for combined board evidence and matching annotations. Use `get_live_game` for state questions. Reuse `known_analysis_id` only when its evidence is already in context. After a revision conflict, read current state and reconsider the request. Do not poll the board.

Hint responses must keep solution moves out of all returned facts, references, and annotations. Reveal puzzle solutions only when requested. Draw claims require an explicit user choice. Annotation changes do not move pieces. The UI and MCP share a game only within the same server process; restart clears all game and evidence state.

Gambit has no learner tracking, personal database, scheduled review, or conversational memory. Do not imply successful saving of personal information. Do not fetch account history without an explicit account and relevant bounded request.
