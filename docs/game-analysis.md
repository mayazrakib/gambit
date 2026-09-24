# Whole-game analysis

Gambit returns structured chess facts, not generated coaching. `parse_game`,
`analyze_positions`, `analyze_game`, and `review_game` are MCP tools. The reusable
Python functions and frozen result dataclasses live in `gambit.games`.

## Tools and defaults

```python
parse_game(pgn: str)
analyze_positions(positions: list[PositionAnalysisRequest])
analyze_game(
    pgn: str,
    side: Literal["white", "black", "both"] = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
)
review_game(...)  # Same parameters as analyze_game.
```

Each batch request has `fen`, `nodes=100_000`, and `multipv=3`. All requests are
validated before any searches start, and results preserve input order. The MCP
framework wraps a sequence in `structuredContent.result`; the other tools return
objects directly in `structuredContent`.

For example, call `review_game` with:

```json
{
  "pgn": "[Event \"Example\"]\n\n1. f3 e5 2. g4 Qh4# 0-1",
  "side": "both",
  "initial_nodes": 20000,
  "critical_nodes": 250000,
  "multipv": 3,
  "critical_loss_cp": 40
}
```

`parse_game` uses python-chess, without starting Stockfish. It accepts standard
chess, including custom `FEN`/`SetUp` headers, incomplete games, comments, numeric
annotation glyphs, castling, promotion, and en passant. Recognized `[%clk ...]`
and `[%emt ...]` annotations become seconds; absent values stay null. Only the
main line is returned; side variations are parsed and validated. The supplied
headers are retained without synthesizing missing event or player names.
A missing result is null; an explicit unfinished result remains `"*"`. Results
such as resignation and agreed draws are preserved without guessing their cause.
A header-only game can be parsed, but engine analysis requires a played move.

**Ply numbering is one-based from the supplied initial position.** A custom game
starting with Black's move 42 has `ply=1`, `move_number=42`, and `side="black"`.
Normal chess move numbers come from the board, including custom FEN counters.
Each move contains SAN (standard algebraic notation), UCI (coordinate notation),
before/after FENs, and available move metadata.

## Scores and principal variations

All four new APIs use **White's perspective**: positive centipawns favor White,
negative centipawns favor Black. One pawn equals 100 centipawns. The existing
`analyze_position` and `tutor_move` score perspective remains side-to-move-relative.

An `EngineEvaluation` has `centipawns`, `mate_in`, and `mating_side`. For engine
scores, exactly one of the first two is populated. `mate_in=3` means White can
force mate; `mate_in=-4` means Black can force mate. A checkmated position uses
`mate_in=0`, with `mating_side` identifying the winner because zero has no sign.
Mate scores are never converted into artificial centipawn scores.

Checkmate, stalemate, insufficient material, and automatic draws detectable from
the supplied FEN are resolved without engine work. Draws return zero centipawns
and no variations. Searches use FEN positions, matching the existing engine
contract: repetition history and optional draw claims are not incorporated into
engine scores. PGN results do not override the board evaluation, for example
when a player resigns or agrees a draw in a nonterminal position.

Each principal variation contains its one-based `rank`, White-relative evaluation,
`moves_uci`, and `moves_san`. SAN is generated sequentially on the evolving board.
Variations contain at most 64 plies. A malformed or illegal continuation returns
only its legal prefix. An invalid root move or absent engine evaluation fails the
request, rather than inventing a candidate. `played_move_rank=null` means the
move was absent from the returned candidate set, not that it was necessarily bad.

Centipawn loss is `max(0, before - after)` for White and
`max(0, after - before)` for Black. It is null whenever either evaluation is a
mate score, including a retained forced mate. `best_move_difference_cp` in a
review is the same before/after loss estimate, not a separate search constrained
to the played move. Independent finite searches can disagree slightly; losses
are clamped at zero, but the underlying scores are retained.

## Adaptive analysis and process reuse

The first pass searches each required position at `initial_nodes`. Gambit marks
moves critical when any of these deterministic conditions hold:

- Provisional centipawn loss is at least `critical_loss_cp` (default 40).
- A mate appears, disappears, or changes winning side.
- Mate distance differs by at least two moves from its expected progression.
  The expected distance decreases by one when the mating side moves.
- The evaluation crosses from at least +200 to at most -200, or vice versa.
- An advantage of at least 200 centipawns becomes approximately equal
  (absolute score at most 50), or an equal position becomes such an advantage.

Only critical moves' before and after positions are searched at `critical_nodes`.
These deeper scores are authoritative for that move, and both scores use the
same budget. Noncritical moves retain their initial results, even if a neighbor
caused the shared position to receive a deeper search. Thus, neighboring returned
scores can differ when their budgets differ. `is_critical` records the first-pass
selection even if deeper analysis reduces the loss. `was_reanalyzed` is true only
when the selected budget exceeds the initial budget. `nodes` is the configured
budget per position, not actual consumed nodes or the sum of both searches.
Equal budgets reuse the first-pass search without running it again.

Filtering by side changes the returned moves and summaries, while preserving
complete game headers and the initial position. The positions following selected
moves are still analyzed, even when the other player is next to move.

A request-local cache shares results for identical normalized FEN, node budget,
and MultiPV settings. The existing bounded engine cache is also retained.
All tools reuse one warm Stockfish process, with a lock around each search.
Game requests run through a bounded thread pool so the MCP event loop can serve
other requests. A polling bridge avoids unreliable thread completion wakeups in
Gambit's Python 3.14 runtime; it does not create additional engine processes.

The engine uses one thread and 16 MiB hash, and resets search hash state before
uncached searches. These settings apply to existing position tools as well, so
exact scores may differ from earlier versions while their score perspective and
response format remain unchanged. Game metadata reports the engine's UCI name,
version when available, budgets, MultiPV, thread count, and hash size. Fixed node
budgets and reset search state improve reproducibility for a given Stockfish
binary; exact scores need not match across engine versions or platforms.

## Review classifications and summaries

Labels are Gambit policy derived from engine facts, not native Stockfish labels.
Thresholds are centralized in `gambit.games.CLASSIFICATION_THRESHOLDS` and related
constants. They can be changed in code; they are not per-request parameters.
There is no opening database, so no `book` label is emitted.

The sole legal move is always `forced`. Otherwise, the engine's first candidate
is `best`, including when shallow and deeper position searches disagree. A move
that is not the first candidate uses these inclusive centipawn-loss boundaries:

| Loss | Classification |
| --- | --- |
| 0–20 | excellent |
| 21–50 | good |
| 51–100 | inaccuracy |
| 101–200 | mistake |
| Above 200 | blunder |

Mate situations bypass these boundaries. Losing one's own forced mate or newly
allowing the opponent a forced mate is a `blunder`, even if independent root
searches disagree about the top move. Otherwise, matching the top move is `best`.
Securing or retaining one's own mate is `excellent`, except a material change to
an existing mate distance is conservatively `good`. Escaping an opponent's forced
mate is `excellent`; other retained losing-mate situations are `good`. These
conservative labels do not measure centipawn loss or tactical motifs. `forced`
continues to take precedence over all other labels.

Each reviewed move includes the raw analysis, classification, top-move identity,
legal-move count, and before/after check, checkmate, and stalemate flags. Summaries
are returned only for requested players, including zero-move summaries where
applicable. They include classification counts (also `forced_moves`), mean and
median loss, largest loss and its ply, and first-pass critical plies. Mate-based
moves are excluded from all centipawn aggregates. Empty aggregates are null.
Tied largest losses use the earliest ply.

## Limits and errors

- One non-empty PGN, at most 262,144 UTF-8 bytes and 1,024 main-line plies.
- Between 1 and 128 requests per position batch.
- Node budgets from 1 to 2,000,000, with `critical_nodes >= initial_nodes`.
- MultiPV from 1 to 5, following the existing server limit.
- Non-negative integer `critical_loss_cp`.
- A 30-second response deadline per UCI handshake/search, not per game.

Invalid inputs, variants (including Chess960), illegal SAN, malformed PGN tokens,
multiple games, engine crashes, timeouts, and invalid root moves produce explicit
MCP tool errors. Illegal SAN errors include the token, move number, and ply.
Gambit never presents partial analysis as complete. Failed engine processes are
closed, and a subsequent request can start a fresh process.
