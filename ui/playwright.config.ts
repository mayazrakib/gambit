import { mkdtempSync, } from "node:fs";
import { tmpdir, } from "node:os";
import { join, } from "node:path";

import { defineConfig, } from "@playwright/test";

const RUNTIME_DIRECTORY = mkdtempSync(join(
    tmpdir(),
    "gambit-browser-",
));

const PORT = 3037;

export default defineConfig({
    testDir: "./test",
    fullyParallel: false,
    workers: 1,
    timeout: 30000,

    use: {
        baseURL: `http://127.0.0.1:${PORT}`,

        viewport: {
            width: 1440,
            height: 1080
        },

        trace: "retain-on-failure",
    },

    webServer: {
        command: `../.venv/bin/python -m gambit.main play --port ${PORT}`,
        wait: { stderr: /Uvicorn running on/ },
        reuseExistingServer: false,
        timeout: 20000,

        env: {
            GAMBIT_RUNTIME_DIRECTORY: RUNTIME_DIRECTORY,

            GAMBIT_DATABASE: join(
                RUNTIME_DIRECTORY,
                "gambit.sqlite3",
            )
        },
    },

    projects: [
        {
            name: "chromium",
            use: { browserName: "chromium" }
        },
        {
            name: "firefox",
            use: { browserName: "firefox" }
        },
    ],
});
