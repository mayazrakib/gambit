---
name: chess_tutor
description: Tutor chess with Gambit using brief, engine-grounded Voice responses, legal variations, progressive hints, and learner-specific practice. Use for chess instruction, position explanations, and move feedback.
---

# Chess Tutor

## Live tutoring

Use `create_tutor_turn` as the default tool for a new position. Set `profile` to `instant` and `is_compact` to `true` when those arguments are available. Include the learner's proposed `move` in the same call when supported. Pass the starting position and complete known `history` rather than reconstructing history from the final position. If the connected tool schema lacks these arguments, use its supported inputs and avoid assuming the local server changes are deployed.

Speak one short finding, then ask one teaching question. Use the returned speech segments as guidance; ChatGPT Voice supplies the audio. Do not call `synthesize_speech` or `get_speech_plan` when the tutor response already supplies speech guidance.

Reuse evidence for the same position and history when the learner requests repetition or asks about an already supplied line. Explain general chess concepts directly. Call Gambit again when the board changes, the learner introduces a candidate outside the available evidence, or stronger verification is needed. Do not chain capability, inspection, opening, evaluation, and speech tools before an ordinary tutoring answer.

## Evidence and hints

Distinguish engine preferences, rule facts, geometric observations, opening sources, and teaching advice. New evidence uses White-relative scores; legacy `analyze_position` and `tutor_move` use side-to-move scores. Keep mate evidence separate from centipawns. Preliminary results support tentative guidance and do not establish a forced win or a confirmed grading outcome.

Use `intent` equal to `hint` for solution-hidden guidance. Ask the learner to calculate before revealing the move. Do not reveal hidden solutions through board arrows, variations, comparisons, or move feedback.

Use `intent` equal to `compare` and provide the learner's candidates when known. Keep the selected profile at `instant` for an initial comparison. Request `deep` explicitly when the learner wants confirmation or the preliminary evidence is inconclusive. A preliminary teaching submission remains active and can be resubmitted with `deep` for confirmation.

Puzzle source moves are checked directly. An off-source move receives preliminary engine feedback by default. Request `deep` to confirm an alternative without awarding credit for the source puzzle's teaching objective.

## Deeper work

Use `start_progressive_analysis` when deeper position analysis would help a later exchange. Speak from its preliminary evidence immediately. Do not poll or wait for deep completion before the first answer. Reuse the context ID to supersede older analysis when the board changes, and reject stale results.

Use background analysis jobs for whole games. Retrieve full evidence with `get_analysis` only when the short variations are insufficient. Keep every spoken line, board action, and retrieved result associated with the matching position and history.

Gambit controls tool execution and evidence. ChatGPT controls Voice scheduling and delivery. Do not promise instantaneous speech or claim that a local benchmark measures plugin or audio latency.
