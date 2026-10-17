import { expect, test } from "@playwright/test";

const STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const SETTINGS = { player_color: "white", strength_mode: "skill", skill_level: 5, target_elo: 1500, budget_mode: "time", think_time_ms: 150, depth: 12, nodes: 100000, threads: 1, hash_mb: 32 };

test(
    "use temporary theme choices and restore system theme on refresh",
    async ({ page }) => {
        await page.emulateMedia({ colorScheme: "dark" });
        await page.goto("/");
        await expect(page.locator("html")).toHaveAttribute(
            "data-theme",
            "dark",
        );
        await expect(page.locator("body")).toHaveCSS(
            "color",
            "rgb(242, 242, 242)",
        );
        await expect(page.locator("html")).toHaveCSS(
            "background-color",
            "rgb(17, 17, 17)",
        );
        await page.getByRole(
            "button",
            { name: "New game", exact: true },
        ).click();
        await expect(page.getByRole("dialog")).toHaveCSS(
            "background-color",
            "rgb(17, 17, 17)",
        );
        await page.keyboard.press("Escape");
        const teaching_response = page.waitForResponse(response => response.url().endsWith("/api/live/teach") && response.request().method() === "POST");
        await page.getByRole(
            "button",
            { name: "Analyze position", exact: true },
        ).click();
        const teaching = (await (await teaching_response).json()).game.teaching;
        expect(teaching.schema_version).toBe(3);
        expect(teaching.message).toBeUndefined();
        await expect(page.locator("#teaching_message")).toContainText("White evaluation:");
        const toggle = page.getByRole(
            "button",
            { name: "Switch to light mode" },
        );
        await toggle.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("html")).toHaveAttribute(
            "data-theme",
            "light",
        );
        await expect(page.locator("html")).toHaveCSS(
            "background-color",
            "rgb(255, 255, 255)",
        );
        await page.reload();
        await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
        expect(await page.evaluate(() => localStorage.getItem("mayaz_theme"))).toBeNull();
        await expect(page.locator("#teaching_message")).toContainText("White evaluation:");
        await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute(
            "content",
            /^#(?:111|111111)$/,
        );
    },
);

test.beforeEach(async ({ request }) => {
    const response = await request.post(
        "/api/live/new",
        { data: { settings: SETTINGS, root_fen: STARTING_FEN } },
    );
    expect(response.ok()).toBeTruthy();
});

test(
    "play, teach, hide hint solutions, take back, and recover on refresh",
    async ({ page }) => {
        const errors: string[] = [];
        page.on(
            "pageerror",
            error => errors.push(error.message),
        );
        await page.goto("/");
        await expect(page.locator("#connection_text")).toHaveText("Board connected");
        await page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        ).click();
        await page.getByRole(
            "gridcell",
            { name: /^e4, / },
        ).click();
        await expect(page.locator("#history_count")).toHaveText("2 plies");
        await page.getByRole(
            "button",
            { name: "Analyze position", exact: true },
        ).click();
        await expect(page.locator("#teaching_metrics")).toContainText("ms");
        await expect.poll(() => page.locator("chess-board").evaluate((board: any) => board.get_annotations("gambit").length)).toBeGreaterThan(0);
        await page.getByRole(
            "button",
            { name: /^Hint$/ },
        ).click();
        await expect(page.locator("#teaching_label")).toHaveText("Hint");
        await expect.poll(() => page.locator("chess-board").evaluate((board: any) => board.get_annotations("gambit").length)).toBe(0);
        await page.reload();
        await expect(page.locator("#history_count")).toHaveText("2 plies");
        await page.getByRole(
            "button",
            { name: "Take back your last turn", exact: true },
        ).click();
        await expect(page.locator("#history_count")).toHaveText("0 plies");
        await expect(page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        )).toBeVisible();
        expect(errors).toEqual([]);
    },
);

test(
    "show a move immediately while its authoritative request is delayed",
    async ({ page }) => {
        await page.goto("/");
        await expect(page.locator("#connection_text")).toHaveText("Board connected");
        let release_request: () => void = () => { };
        const release = new Promise<void>(resolve => { release_request = resolve; });
        await page.route(
            "**/api/live/move",
            async route => { await release; await route.continue(); },
        );
        await page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        ).click();
        await page.getByRole(
            "gridcell",
            { name: /^e4, / },
        ).click();
        await expect(page.getByRole(
            "gridcell",
            { name: "e4, white pawn", exact: true },
        )).toBeVisible();
        await expect(page.locator("#history_count")).toHaveText("0 plies");
        release_request();
        await expect(page.locator("#history_count")).toHaveText("2 plies");
    },
);

test(
    "rollback a rejected optimistic move without locking the board",
    async ({ page }) => {
        await page.goto("/");
        await expect(page.locator("#connection_text")).toHaveText("Board connected");
        await page.route(
            "**/api/live/move",
            route => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "The position changed." }) }),
        );
        await page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        ).click();
        await page.getByRole(
            "gridcell",
            { name: /^e4, / },
        ).click();
        await expect(page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        )).toBeVisible();
        await expect(page.locator("#error_banner")).toContainText("The position changed.");
        expect(await page.locator("chess-board").evaluate((board: any) => board.get_options().interactive)).toBe(true);
    },
);

test(
    "retry a failed opponent request",
    async ({ page }) => {
        await page.goto("/");
        await expect(page.locator("#connection_text")).toHaveText("Board connected");
        await page.route(
            "**/api/live/opponent",
            route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "Engine unavailable." }) }),
            { times: 1 },
        );
        await page.getByRole(
            "gridcell",
            { name: "e2, white pawn", exact: true },
        ).click();
        await page.getByRole(
            "gridcell",
            { name: /^e4, / },
        ).click();
        await page.getByRole(
            "button",
            { name: "Retry reply", exact: true },
        ).click();
        await expect(page.locator("#history_count")).toHaveText("2 plies");
    },
);

test(
    "mobile layout, keyboard focus, and engine configuration",
    async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.goto("/");
        await page.getByRole(
            "button",
            { name: "New game", exact: true },
        ).click();
        await expect(page.getByRole("dialog")).toBeVisible();
        await page.getByLabel(
            "Black",
            { exact: true },
        ).check();
        await page.locator("#strength_mode").selectOption("elo");
        const elo = page.locator('[name="target_elo"]');
        await expect(elo).toBeVisible();
        await elo.fill("1800");
        await page.getByRole(
            "button",
            { name: "Start game", exact: true },
        ).click();
        await expect(page.locator("#player_color")).toHaveText("Black pieces");
        await expect(page.locator("#history_count")).toHaveText("1 ply");
        await expect(page.locator("#opponent_summary")).toContainText("Target Elo 1800");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.keyboard.press("f");
        expect(await page.locator("chess-board").evaluate((board: any) => board.get_options().orientation)).toBe("white");
        await page.getByRole(
            "button",
            { name: "New game", exact: true },
        ).click();
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).not.toBeVisible();
        await expect(page.getByRole(
            "button",
            { name: "New game", exact: true },
        )).toBeFocused();
    },
);

test(
    "promotion choices and completed games",
    async ({ page, request }) => {
        await request.post(
            "/api/live/new",
            { data: { settings: SETTINGS, root_fen: "7k/P7/8/8/8/8/8/7K w - - 0 1" } },
        );
        await page.goto("/");
        await page.getByRole(
            "gridcell",
            { name: "a7, white pawn", exact: true },
        ).click();
        await page.getByRole(
            "gridcell",
            { name: /^a8, / },
        ).click();
        await page.getByRole(
            "button",
            { name: /Promote to queen/i },
        ).click();
        await expect(page.locator("#move_list")).toContainText("a8=Q+");
        await request.post(
            "/api/live/new",
            { data: { settings: SETTINGS, root_fen: "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1" } },
        );
        await expect(page.locator("#position_status")).toContainText("checkmate");
        expect(await page.locator("chess-board").evaluate((board: any) => board.get_options().interactive)).toBe(false);
    },
);

test(
    "claimable draw continues until an explicit claim",
    async ({ page, request }) => {
        await request.post(
            "/api/live/new",
            { data: { settings: SETTINGS, root_fen: "7k/8/8/8/8/8/8/KR6 w - - 100 51" } },
        );
        await page.goto("/");
        const claim = page.getByRole(
            "button",
            { name: "Claim draw", exact: true },
        );
        await expect(claim).toBeEnabled();
        await expect(page.locator("#position_status")).toContainText("Your turn.");
        await claim.click();
        await expect(page.locator("#position_status")).toContainText("1/2-1/2");
        await expect(claim).toBeDisabled();
        await expect(page.locator("#history_count")).toHaveText("0 plies");
    },
);
