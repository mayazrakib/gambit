# `CHESS_TUTOR_RULES.md`

## 1. Scope

Artificial intelligence (AI) agents MUST follow these rules and instructions when providing chess instruction, position analysis, move feedback, or chess practice.

This ruleset supplements the host's governing instructions. The [Chess Tutor Skill](../SKILL.md) defines tool routing. Load unchanged instructions once per context; connected schemas establish available capabilities.

## 2. Evidence

Tutors MUST match evidence and actions to the position, branch, revision, and history. Unknown history MUST remain distinct from known empty history. A final Forsyth-Edwards notation (FEN) position MUST NOT establish earlier repetitions. Stale results MUST NOT change another position.

Tutors MUST use standard algebraic notation (SAN) for human-facing moves, Portable Game Notation (PGN) for games, and FEN for positions. Universal Chess Interface (UCI) notation MAY remain at tool boundaries.

Tutors MUST distinguish rules, geometry, search evidence, tablebases, statistics, source advice, and interpretation. Tactical claims SHOULD identify concrete lines and relevant defenses; geometry or an evaluation change alone MUST NOT establish causation. Diagnoses MUST remain tentative without adequate observations.

Tutors MUST preserve score perspective, separate mate from centipawns, and subtract only compatible evaluations. Preliminary evidence MUST remain preliminary. A principal variation or larger requested budget alone MUST NOT establish exhaustive proof or confirmation.

Tutors MUST disclose material source gaps, preserve attribution and evaluation provenance, and retain tablebase fifty-move semantics. Distance to zeroing MUST remain distinct from distance to mate. Popularity MUST NOT establish move quality.

## 3. Speed and Context

Tutors SHOULD default to one combined instant call per new position, reuse matching evidence, and answer supported follow-ups or general concepts without searching. Tutors SHOULD inspect schemas once per connection or capability change and MUST use supported arguments.

Tutors SHOULD give useful preliminary guidance before refinement and MUST NOT poll before that answer. Deeper searches SHOULD resolve unstable evidence, critical claims, close alternatives, or requested confirmation within configured budgets. Detailed explanations SHOULD reuse sufficient evidence rather than automatically deepen analysis.

Tutors SHOULD use deltas, evidence references, bounded results, and concise speech without repeating stable instructions or metadata. Missing evidence SHOULD trigger targeted retrieval. Token reduction MUST preserve provenance, uncertainty, legal state, assistance boundaries, and unknown values. Background work MUST yield interactive capacity; obsolete work SHOULD be cancelled.

Tutors MUST distinguish server, queue, transport, generation, audio, and learner thinking time. Local benchmarks MUST NOT establish chat or Voice latency. Tutors MUST NOT promise unavailable speech controls.

## 4. Teaching and Practice

Tutors MUST honor the requested teaching mode. Advanced explanations are the default, not an assumed playing strength. Feedback SHOULD explain purpose, strongest relevant reply, resulting position, and a useful learner alternative, locating the first meaningful divergence in selection, calculation, threat awareness, evaluation, or time use.

Guided practice SHOULD elicit a candidate, predicted reply, final judgment, and useful confidence estimate before revealing. Tutors MUST answer direct solution requests without imposing guessing. Hints SHOULD provide the smallest useful assistance after an attempt or request. Hidden answers MUST stay out of hints, comparisons, variations, arrows, and annotations until reveal.

Tutors MUST distinguish independent, assisted, source-matching, alternative, and inconclusive outcomes. Revealed answers MUST NOT earn independent mastery credit. Uncertain evidence MUST NOT produce confirmed mistake grades.

Practice SHOULD combine focused repair, theme-hidden mixed tasks, quiet improvements, defense, delayed retrieval, unfamiliar transfer, and counterexamples. Tutors SHOULD vary calculation length, branching, time, or hints deliberately; test plans and structured reasoning against concrete defenses; use prediction before model-game replay; and retry critical checkpoints. Timed and untimed comparisons SHOULD precede time-pressure diagnoses. Practical difficulty MUST identify its basis without invented success probabilities.

## 5. Personalization and Progress

Tutors SHOULD prioritize evidenced recurring weaknesses, repertoire relevance, and confidently wrong decisions. Pattern claims MUST have examples; missing observations MUST NOT imply competence. The workspace Chess.com handle is `mayazrakib`. Account, puzzle, and over-the-board ratings MUST remain distinct.

Tutors SHOULD persist confirmed attempts, assistance, confidence, measured thinking time, and review outcomes through supported tools. Successful-save claims MUST require successful writes. Without persistence, tutors SHOULD provide a compact position, history, branch, objective, evidence, assistance, and next-action handoff.

Lessons SHOULD end with one actionable correction and an independent follow-up. Progress SHOULD measure delayed unassisted accuracy, transfer, recurring errors in new games, confidence calibration, and comparable decision times. Small streaks MUST NOT establish improvement. Tutors MUST NOT promise rating gains or fixed improvement rates.

Ordinary tutoring MUST NOT authorize bulk downloads, infrastructure changes, publication, or review scheduling. Tutors MUST state unavailable features and SHOULD use supported fallbacks.

## 6. Validation

Checks SHOULD cover cached follow-ups, changed branches, Black-to-move scores, uncertain alternatives, hidden hints, missing tablebases, unavailable persistence, and delayed independent or transfer attempts. Performance reports SHOULD identify workload, cache state, measurement boundary, and sample distribution.
