---
name: chess
description: "Use Gambit to verify chess claims and obtain structured engine evidence, openings, puzzles, and attributed game information."
---

## 1. Scope

Artificial intelligence (AI) agents MUST follow these rules and instructions when using Gambit for chess instruction, position analysis, move feedback, or chess practice.

This skill supplements [Chess Rules](references/chess_rules.md). Connected schemas establish capabilities. Gambit supplies evidence; the client authors explanations and audio.

## 2. Procedure

### 2.1. Evidence Procedure

- Resolve the actual position and known history from context.
- Ask for missing information only when it changes the answer.
- Keep hypothetical analysis separate from the mainline.

- Use `get_position` for board state, material, legal moves, and optional typed rules predicates.
- Supply a FEN with optional history, or a live game identifier with its expected revision.
- An *optional continuation* is hypothetical and does not change the game.
- Use `get_evidence` for selected sections: facts, analysis, openings, statistics, cloud, and tablebase.
- Defaults are local facts and instant preliminary analysis.
- External sections are opt-in.
- Request only needed sections; use deeper analysis when the claim needs it.

- Reuse matching evidence.
- Retrieve full temporary evidence with `get_analysis`.
- A missing reference is expired, not a result.
- Apply the evidence and claim requirements in [Chess Rules](references/chess_rules.md#2-evidence-and-claims).

### 2.2. Tool Routing

- Board image recognition: `read_board`, then verify reliability before analysis
- PGN validation: `read_pgn`
- Single or batch position analysis: `analyze_position`
- Move assessment or comparison: `analyze_move`, `compare_moves`
- Local opening identification: `find_openings`, `get_opening`
- Masters or Lichess outcomes and examples: `get_opening_stats`
- Public puzzle: `get_puzzle`
- Selected public game or study chapter: `get_game`, `get_study`
- Existing cloud analysis: `get_cloud_analysis`
- Remote endgame evidence: `get_tablebase`
- Explicit Chess.com account and month: `get_chesscom_games`
- Whole-game analysis and classifications: `analyze_game`
- Background game analysis: `start_game_analysis`, `get_analysis_job`, `get_analysis`, `cancel_analysis_job`
- Active board evidence and annotations: `analyze_live_game`, `annotate_live_game`

- Studies require explicit public study and chapter identifiers.
- Missing cloud analysis does not start remote engine work.
- API failures must remain visible.

- `analyze_position` accepts either `fen` with optional `history`, or `positions` containing those fields.
- Both use the same search profile; batches return `items` in input order.
- `analyze_game` includes classifications by default; set `should_review=false` for analysis only.
- Use current connected tool names rather than removed interfaces.

### 2.3. Live Board and Hints

- Use `analyze_live_game` with the known game identifier and revision for combined board evidence and matching annotations.
- Use `get_live_game` for state questions.
- Reuse `known_analysis_id` only when its evidence is already in context.
- After a revision conflict, read current state and reconsider the request.
- Annotation changes do not move pieces.
- The UI and MCP share a game only within the same server process; restart clears all game and evidence state.

- Gambit has no learner tracking, personal database, scheduled review, or conversational memory.

## 3. Exclusions

- Generic discussion without position-specific claims need not invoke every evidence tool.
- Personal tracking and unsupported persistence MUST NOT be implied.

## 4. Required Inputs

- Identify the position, known history, live revision where relevant, requested answer or hint mode, and available schemas.

## 5. Completion Evidence

- Keep position identity, evidence provenance, score perspective, history scope, preliminary status, and uncertainty explicit.

## 6. Failure Handling

- Treat expired references and API failures as missing evidence.
- Retrieve narrowly, preserve hint boundaries, and qualify or omit unsupported claims.
