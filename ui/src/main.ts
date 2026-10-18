import { type ChessboardElement, type MoveRequest, } from "@mayazrakib/chessboard";
import "@mayazrakib/chessboard";

import type { Capabilities, LiveGame, } from "./types";

import { get_element, request_json, } from "./api";
import { bind_controls, } from "./controls";
import { mark_pending_move, render_game, } from "./render";
import { apply_capabilities, bind_setup, } from "./setup";
import { WORKSPACE_TEMPLATE, } from "./template";
import { bind_theme, } from "./theme";
import "./style.css";

get_element("#app").innerHTML = WORKSPACE_TEMPLATE;
bind_theme();
const board = get_element<ChessboardElement>("chess-board");
let game: LiveGame | null = null;
let opponent_request: string | null = null;
let teaching_request: AbortController | null = null;
let is_mutating = false;
let is_following = true;
const attempted_opponent_turns = new Set<string>();

function show_error(error: unknown): void {
    get_element("#error_text").textContent = error instanceof Error ? error.message : String(error);
    get_element("#error_banner").hidden = false;
}

function accept_game(incoming: LiveGame): void {
    if (game?.game_id === incoming.game_id && incoming.event_sequence <= game.event_sequence) {
        return;
    }

    const is_new_game = game?.game_id !== incoming.game_id;
    const has_position_changed = is_new_game || game?.revision !== incoming.revision;

    if (has_position_changed) {
        teaching_request?.abort();
    }

    game = incoming;

    if (is_new_game) {
        attempted_opponent_turns.clear();
        board.set_options({ orientation: game.player_color });
    }

    render_game(
        game,
        board,
    );

    if (is_following) {
        void play_opponent();
    }
}

async function refresh_game(): Promise<void> {
    const result = await request_json<{ game: LiveGame | null }>("game");

    if (result.game) {
        accept_game(result.game);
    }
}

async function mutate(
    action: string,
    extra: object = {},
): Promise<boolean> {
    if (!game || is_mutating) {
        return false;
    }

    is_mutating = true;
    const captured = game;

    try {
        const result = await request_json<{ game: LiveGame }>(
            action,
            {
                game_id: captured.game_id,
                expected_revision: captured.revision,
                ...extra
            },
        );

        if (game?.game_id === captured.game_id) {
            accept_game(result.game);
        }

        return true;
    } catch (error) {
        show_error(error);
        await refresh_game();

        if (game) {
            render_game(
                game,
                board,
            );
        }

        return false;
    } finally {
        is_mutating = false;
    }
}

async function play_opponent(): Promise<void> {
    if (!game || game.is_game_over || game.side_to_move === game.player_color || opponent_request) {
        return;
    }

    const captured = game;
    const key = `${game.game_id}:${game.revision}`;

    if (attempted_opponent_turns.has(key)) {
        return;
    }

    attempted_opponent_turns.add(key);
    opponent_request = key;
    get_element("#retry_opponent").hidden = true;

    try {
        const result = await request_json<{ game: LiveGame }>(
            "opponent",
            {
                game_id: captured.game_id,
                expected_revision: captured.revision
            },
        );

        if (game?.game_id === captured.game_id) {
            accept_game(result.game);

            if (game?.revision === result.game.revision && get_element<HTMLInputElement>("#auto_coach").checked) {
                void teach("explain");
            }
        }
    } catch (error) {
        await refresh_game();

        if (game?.game_id === captured.game_id && game.revision === captured.revision) {
            show_error(error);
            get_element("#engine_status").textContent = "Reply unavailable";
            get_element("#retry_opponent").hidden = false;
        }
    } finally {
        opponent_request = null;

        if (game && `${game.game_id}:${game.revision}` !== key && is_following) {
            void play_opponent();
        }
    }
}

async function teach(intent: string): Promise<void> {
    if (!game) {
        return;
    }

    teaching_request?.abort();
    const controller = new AbortController();
    teaching_request = controller;
    const captured = game;
    get_element("#teaching_label").textContent = "Analyzing…";

    get_element(".tutor_card").setAttribute(
        "aria-busy",
        "true",
    );

    get_element("#cancel_teaching").hidden = false;

    try {
        const profile = get_element<HTMLSelectElement>("#analysis_profile").value;

        const result = await request_json<{ game: LiveGame }>(
            "teach",
            {
                game_id: captured.game_id,
                expected_revision: captured.revision,
                intent,
                profile
            },
            AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]),
        );

        if (game?.game_id === captured.game_id && !controller.signal.aborted) {
            accept_game(result.game);
        }
    } catch (error) {
        if (!controller.signal.aborted && game?.game_id === captured.game_id && game.revision === captured.revision) {
            show_error(error);
        }
    } finally {
        if (teaching_request === controller) {
            teaching_request = null;
            get_element(".tutor_card").removeAttribute("aria-busy");
            get_element("#cancel_teaching").hidden = true;

            if (game) {
                render_game(
                    game,
                    board,
                );
            }
        }
    }
}

async function handle_move(request: MoveRequest): Promise<void> {
    if (!game || is_mutating || game.side_to_move !== game.player_color) {
        board.reject_move(request.id);

        return;
    }

    teaching_request?.abort();
    is_following = true;
    board.commit_move(request.id);
    mark_pending_move(board);
    get_element("#position_status").textContent = "Stockfish to move.";
    get_element("#teaching_label").textContent = "Position changed";
    get_element("#teaching_message").textContent = "No analysis for this position.";

    await mutate(
        "move",
        { move: `${request.input.from}${request.input.to}${request.input.promotion ?? ""}` },
    );

    await play_opponent();
}

async function initialize(): Promise<void> {
    await board.when_ready();

    board.set_options({
        theme: "sage",
        is_muted: true,
        move_mode: "controlled",
        event_detail: "compact",
        interactive: false,
        animation_duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 120,

        interaction: {
            can_premove: false,

            keyboard_shortcuts: {
                undo: [],
                redo: []
            }
        },

        annotations: { clear_on_left_click: "user" }
    });

    bind_setup(
        (created) => {
            is_following = true;
            accept_game(created);
        },
        () => game,
    );

    bind_controls(
        board,
        {
            get_game: () => game,

            undo: () => {
                is_following = false;
                void mutate("undo");
            },

            clear: () => void mutate("clear"),

            claim_draw: () => {
                is_following = false;
                void mutate("claim_draw");
            },

            teach,
            cancel: () => teaching_request?.abort(),

            retry: () => {
                attempted_opponent_turns.clear();
                void play_opponent();
            },
        },
    );

    board.addEventListener(
        "chessboard:move_request",
        (event) => void handle_move(event.detail),
    );

    get_element("#mcp_address").textContent = location.hostname.endsWith(".ts.net") ? "Use your existing Gambit MCP connection." : `${location.origin}/mcp`;
    const initial_game = refresh_game();
    const capabilities = request_json<Capabilities>("capabilities").then(apply_capabilities).catch(show_error);
    const events = new EventSource("/api/events");

    events.onopen = () => {
        get_element("#connection_text").textContent = "Board connected";
        get_element("#connection_dot").classList.remove("is_offline");
    };

    events.onmessage = (event) => accept_game(JSON.parse(event.data) as LiveGame);

    events.onerror = () => {
        get_element("#connection_text").textContent = "Reconnecting…";
        get_element("#connection_dot").classList.add("is_offline");
    };

    window.addEventListener(
        "pagehide",
        () => events.close(),
        { once: true },
    );

    await Promise.all([initial_game, capabilities]);
}

void initialize().catch(show_error);
