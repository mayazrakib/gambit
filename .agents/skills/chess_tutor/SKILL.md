---
name: chess_tutor
description: "Teach chess with Gambit using reusable engine evidence, guided calculation, personal game review, and targeted practice."
---

# `SKILL.md`

## 1. Scope

Artificial intelligence (AI) agents MUST follow these rules and instructions when providing chess instruction, position analysis, move feedback, or chess practice.

This skill supplements [Chess Tutor Rules](references/chess_tutor_rules.md). Use only interfaces and arguments exposed by connected schemas.

## 2. Fast Turn

Resolve mode, root position, known history, branch, and objective from context. Ask only for missing information that materially changes the answer. Preserve the mainline during hypothetical analysis.

Prefer one `create_tutor_turn` with instant analysis, the proposed move, history, and relevant candidates. In supported sessions, send the expected revision, delta response mode, and known evidence references; mutations also need an operation identifier.

Answer directly in direct mode. In guided mode, give one useful finding and a focused question. Reuse returned speech guidance without extra synthesis calls for ChatGPT Voice.

Reuse matching evidence. Retrieve missing detail with `get_analysis`; search for new candidates or unsupported claims. Read completed background evidence on a relevant later turn without duplicate refinement or polling before the first answer.

## 3. Tool Routing

| Task | Interface |
|---|---|
| Persistent branches | `start_tutor_session`, `get_tutor_session`, `navigate_tutor_session` |
| Reasoning and confidence | `submit_tutor_reasoning` |
| Plans or practical alternatives | `assess_tutor_plan`, `compare_practical_moves` |
| Calculation, refutation, defense, openings, prediction, transfer, endgames | `start_practice`, `act_practice`, `get_practice` |
| Retention and patterns | `get_due_reviews`, `get_learner_patterns`, `get_learning_dashboard` |
| Examples and personal games | `search_chess_material`, then selected `get_chess_game` |
| Study export | `export_tutor_study` |
| Whole-game review | Background analysis jobs |

Inspect action choices when needed. Read current state after revision conflicts; reuse operation identifiers only for identical retries. If newer interfaces are absent, use legacy teaching or verification tools and state persistence limits.

## 4. Learning Cycle

Choose one evidenced bottleneck. Elicit the learner's line and judgment, verify concrete claims, explain the first meaningful divergence, and request repair. Follow with an unfamiliar related position and counterexample; retest independently later.

Use model-game prediction for planning, opening deviations for understanding, fixed-board calculation for visualization, and checkpoint retries for technique. Contrast alternatives with concrete evidence.

Use imported `mayazrakib` games for personal review. Authorized data synchronization uses `manage_chess_data` and is not a turn prerequisite. Record supported outcomes, then leave one correction and next task.

For requested exports or interrupted sessions, retain legal moves, history, branch, objective, evidence references, assistance, and next action. If export is unavailable, provide legal PGN or a compact handoff. Remote clients may not open server-local file URIs.
