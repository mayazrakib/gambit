import type { BoardMark } from "@mayazrakib/chessboard";

export type OpponentSettings = {
    player_color: "white" | "black";
    strength_mode: "skill" | "elo" | "full";
    skill_level: number;
    target_elo: number;
    budget_mode: "time" | "depth" | "nodes";
    think_time_ms: number;
    depth: number;
    nodes: number;
    threads: number;
    hash_mb: number;
};

export type LiveGame = {
    game_id: string;
    revision: number;
    event_id: string;
    event_sequence: number;
    fen: string;
    root_fen: string;
    history: string[];
    moves: { san: string; uci: string; number: number; color: "white" | "black" }[];
    pgn: string;
    side_to_move: "white" | "black";
    player_color: "white" | "black";
    ply: number;
    is_check: boolean;
    is_game_over: boolean;
    can_claim_draw_now: boolean;
    result: string | null;
    termination: string | null;
    settings: OpponentSettings;
    annotations: BoardMark[];
    teaching: {
        schema_version: 3;
        facts: { variation: { move_san: string; is_capture: boolean; facts: { is_check: boolean; is_checkmate: boolean } }[] } | null;
        evaluation: { centipawns: number | null; mate_in: number | null } | null;
        evidence_status: string | null;
        intent: string;
        profile: string;
        analysis_id: string | null;
        elapsed_ms: number;
        revision: number;
    } | null;
};

export type Capabilities = {
    name: string;
    options: Record<
        string,
        { min: number | null; max: number | null; default: number | boolean }

    >;
};
