import type { Capabilities, LiveGame, OpponentSettings, } from "./types";

import { get_element, request_json, } from "./api";

const STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export function bind_setup(
    on_create: (game: LiveGame) => void,
    get_game: () => LiveGame | null,
): void {
    const dialog = get_element<HTMLDialogElement>("#setup_dialog");
    const form = get_element<HTMLFormElement>("#setup_form");

    for (const selector of ["#new_game", "#start_first"]) {
        get_element(selector).addEventListener(
            "click",
            () => {
                get_element("#setup_error").textContent = "";
                get_element("#setup_note").textContent = get_game() ? "Replaces the active game. Export PGN to retain it." : "Opponent settings are independent of tutor analysis.";
                dialog.showModal();
            },
        );
    }

    for (const selector of ["#close_setup", "#cancel_setup"]) {
        get_element(selector).addEventListener(
            "click",
            () => dialog.close(),
        );
    }

    get_element("#skill_level").addEventListener(
        "input",
        () => {
            get_element("#skill_value").textContent = `${get_element<HTMLInputElement>("#skill_level").value} / 20`;
        },
    );

    get_element("#strength_mode").addEventListener(
        "change",
        update_fields,
    );

    get_element("#budget_mode").addEventListener(
        "change",
        update_fields,
    );

    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();
            const button = get_element<HTMLButtonElement>("#start_game");
            button.disabled = true;
            button.textContent = "Starting game…";
            get_element("#setup_error").textContent = "";

            try {
                const values = new FormData(form);
                const settings = Object.fromEntries([...values].map(([key, value]) => [key, ["player_color", "strength_mode", "budget_mode"].includes(key) ? value : Number(value)])) as OpponentSettings;
                const root_fen = get_element<HTMLTextAreaElement>("#root_fen").value.trim() || STARTING_FEN;

                const result = await request_json<{ game: LiveGame }>(
                    "new",
                    {
                        settings,
                        root_fen
                    },
                );

                dialog.close();
                on_create(result.game);
            } catch (error) {
                get_element("#setup_error").textContent = error instanceof Error ? error.message : "Could not start the game.";
            } finally {
                button.disabled = false;
                button.textContent = "Start game";
            }
        },
    );
}

function update_fields(): void {
    const strength = get_element<HTMLSelectElement>("#strength_mode").value;
    const budget = get_element<HTMLSelectElement>("#budget_mode").value;
    get_element("#skill_field").hidden = strength !== "skill";
    get_element("#elo_field").hidden = strength !== "elo";
    get_element("#depth_field").hidden = budget !== "depth";
    get_element("#nodes_field").hidden = budget !== "nodes";
}

export function apply_capabilities(capabilities: Capabilities): void {
    for (const [option, input_name] of [["UCI_Elo", "target_elo"], ["Threads", "threads"], ["Hash", "hash_mb"]]) {
        const bounds = capabilities.options[option];
        const input = get_element<HTMLInputElement>(`[name="${input_name}"]`);

        if (bounds?.min !== null && bounds?.min !== undefined) {
            input.min = String(Math.max(
                Number(input.min),
                bounds.min,
            ));
        }

        if (bounds?.max !== null && bounds?.max !== undefined) {
            input.max = String(Math.min(
                Number(input.max),
                bounds.max,
            ));
        }

        input.value = String(Math.max(
            Number(input.min),
            Math.min(
                Number(input.max),
                Number(input.value),
            ),
        ));
    }
}
