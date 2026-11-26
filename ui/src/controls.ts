import type { ChessboardElement, } from "@mayazrakib/chessboard";

import type { LiveGame, } from "./types";

import { get_element, } from "./api";

type WorkspaceActions = {
    get_game: () => LiveGame | null;
    undo: () => void;
    claim_draw: () => void;
    clear: () => void;
    teach: (intent: string) => Promise<void>;
    cancel: () => void;
    retry: () => void;
};

export function bind_controls(
    board: ChessboardElement,
    actions: WorkspaceActions,
): void {
    get_element("#undo").addEventListener(
        "click",
        actions.undo,
    );

    get_element("#claim_draw").addEventListener(
        "click",
        actions.claim_draw,
    );

    get_element("#clear").addEventListener(
        "click",
        actions.clear,
    );

    get_element("#flip").addEventListener(
        "click",
        () => board.flip(),
    );

    get_element("#hint").addEventListener(
        "click",
        () => void actions.teach("hint"),
    );

    get_element("#explain").addEventListener(
        "click",
        () => void actions.teach("explain"),
    );

    get_element("#cancel_teaching").addEventListener(
        "click",
        actions.cancel,
    );

    get_element("#retry_opponent").addEventListener(
        "click",
        actions.retry,
    );

    get_element("#dismiss_error").addEventListener(
        "click",
        () => {
            get_element("#error_banner").hidden = true;
        },
    );

    get_element("#export").addEventListener(
        "click",
        () => {
            const game = actions.get_game();

            if (!game) {
                return;
            }

            const url = URL.createObjectURL(new Blob(
                [game.pgn],
                { type: "application/x-chess-pgn" },
            ));

            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = `gambit-${game.game_id}.pgn`;
            anchor.click();
            URL.revokeObjectURL(url);
        },
    );

    document.addEventListener(
        "keydown",
        (event) => {
            const target = event.target as HTMLElement;

            if (target.closest("input, select, textarea, dialog") || event.metaKey || event.ctrlKey || event.altKey || event.repeat) {
                return;
            }

            if (event.key === "f") {
                board.flip();
            } else if (event.key === "h" && actions.get_game()) {
                void actions.teach("hint");
            }
        },
    );
}
