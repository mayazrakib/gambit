import type { ChessboardElement } from "@mayazrakib/chessboard";

import type { LiveGame } from "./types";

import { get_element } from "./api";

type RenderState = {
    position: string;
    annotations: string;
    interactive: boolean;
    playable_color: string;
};

const RENDER_STATES = new WeakMap<
    ChessboardElement,
    RenderState
>();

export function mark_pending_move(board: ChessboardElement): void {
    board.set_annotations(
        [],
        "gambit",
    );
    board.set_options({ interactive: false });
    const state = RENDER_STATES.get(board);

    if (state) {
        state.interactive = false;
        state.annotations = "[]";
    }
}

export function get_strength_label(game: LiveGame): string {
    const settings = game.settings;

    return settings.strength_mode === "full" ? "Full strength" : settings.strength_mode === "elo" ? `Target Elo ${settings.target_elo}` : `Skill ${settings.skill_level} / 20`;
}

export function render_game(
    game: LiveGame,
    board: ChessboardElement,

): void {
    get_element("#board_empty").hidden = true;

    const previous = RENDER_STATES.get(board);
    const position_key = `${game.game_id}:${game.revision}`;

    if (board.get_position() !== game.fen || board.get_uci_moves().length !== game.history.length || previous?.position.split(":")[0] !== game.game_id) {
        const current = board.get_uci_moves();
        const can_advance = game.history.length === current.length + 1 && current.every((
            move,
            index,

        ) => move === game.history[index]);

        if (can_advance) {
            board.move_uci(game.history.at(-1)!);
        } else {
            board.set_pgn(game.pgn);
        }
    }

    const annotation_key = JSON.stringify(game.annotations);

    if (previous?.annotations !== annotation_key || previous.position !== position_key) {
        board.set_annotations(
            game.annotations,
            "gambit",
        );
    }

    const is_player_turn = game.side_to_move === game.player_color && !game.is_game_over;

    if (previous?.interactive !== is_player_turn || previous.playable_color !== game.player_color) {
        board.set_options({ interactive: is_player_turn, playable_color: game.player_color === "white" ? "w" : "b" });
    }

    RENDER_STATES.set(
        board,
        { position: position_key, annotations: annotation_key, interactive: is_player_turn, playable_color: game.player_color },
    );
    get_element("#opponent_summary").textContent = `${get_strength_label(game)} · ${game.settings.think_time_ms / 1000}s time cap`;
    get_element("#player_color").textContent = `${game.player_color === "white" ? "White" : "Black"} pieces`;
    get_element("#player_status").hidden = !is_player_turn;
    get_element("#engine_status").textContent = game.is_game_over ? "Game complete" : is_player_turn ? "Waiting" : "Thinking…";
    get_element("#engine_status").classList.toggle(
        "is_thinking",
        !is_player_turn && !game.is_game_over,

    );
    get_element("#position_status").textContent = game.is_game_over ? `${game.result} · ${game.termination}` : `${is_player_turn ? "Your turn." : "Stockfish to move."}${game.is_check ? " Check." : ""}`;
    get_element("#position_fen").textContent = game.fen;
    get_element("#move_counter").textContent = `Move ${Number(game.fen.split(" ")[5])} · ${game.side_to_move} to play`;
    get_element<HTMLButtonElement>("#undo").disabled = game.history.length === 0;
    get_element<HTMLButtonElement>("#clear").disabled = game.annotations.length === 0;
    get_element<HTMLButtonElement>("#export").disabled = false;
    get_element<HTMLButtonElement>("#claim_draw").disabled = !is_player_turn || !game.can_claim_draw_now;

    for (const selector of ["#hint", "#explain"]) {
        get_element<HTMLButtonElement>(selector).disabled = false;
    }

    render_history(game);
    render_teaching(game);
}

function render_history(game: LiveGame): void {
    get_element("#history_count").textContent = `${game.ply} ${game.ply === 1 ? "ply" : "plies"}`;
    const list = get_element("#move_list");
    const key = `${game.game_id}:${game.revision}`;

    if (list.dataset.position === key) {
        return;
    }

    list.dataset.position = key;
    list.replaceChildren();

    if (!game.moves.length) {
        const empty = document.createElement("p");
        empty.className = "empty_history";
        empty.textContent = "No moves.";
        list.append(empty);

        return;
    }

    let row: HTMLDivElement | null = null;

    for (const [index, move] of game.moves.entries()) {
        if (move.color === "white" || row === null) {
            row = document.createElement("div");
            row.className = "move_row";
            const number = document.createElement("span");
            number.textContent = `${move.number}.`;
            const white = document.createElement("span");
            const black = document.createElement("span");
            row.append(
                number,
                white,
                black,

            );
            list.append(row);
        }

        const cell = row.children[move.color === "white" ? 1 : 2] as HTMLElement;
        cell.textContent = move.san;
        cell.classList.toggle(
            "latest_move",
            index === game.moves.length - 1,

        );
    }

    list.scrollTop = list.scrollHeight;
}

function render_teaching(game: LiveGame): void {
    const teaching = game.teaching;
    const is_pending = get_element(".tutor_card").getAttribute("aria-busy") === "true";
    get_element("#teaching_label").textContent = is_pending ? "Analyzing…" : teaching ? teaching.intent === "hint" ? "Hint" : "Analysis" : "Idle";
    const variation = teaching?.facts?.variation ?? [];
    const evaluation = teaching?.evaluation;
    const rows = variation.map(entry => `${entry.move_san}  capture=${entry.is_capture}  check=${entry.facts.is_check}  mate=${entry.facts.is_checkmate}`);

    if (evaluation) {
        rows.push(evaluation.mate_in !== null ? `Mate score: ${evaluation.mate_in} moves` : `White evaluation: ${evaluation.centipawns ?? "unknown"} cp`);
    }

    if (teaching?.evidence_status) {
        rows.push(`Search: ${teaching.evidence_status}`);
    }

    get_element("#teaching_message").textContent = rows.join("\n") || (teaching?.intent === "hint" ? "Solution hidden" : "No analysis.");
    get_element("#teaching_metrics").textContent = teaching ? `${teaching.profile} · ${Math.round(teaching.elapsed_ms)} ms` : "";
}
