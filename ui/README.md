# `gambit-workspace`

![Version](https://img.shields.io/badge/Version-0.3.0-737373?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-737373?style=flat-square)
![Languages](https://img.shields.io/badge/Languages-TypeScript-737373?style=flat-square)
![Frameworks](https://img.shields.io/badge/Frameworks-Vite%2C%20Chessboard-737373?style=flat-square)
![Compatibility](https://img.shields.io/badge/Compatibility-Browser%20targets%3B%20not%20verified-737373?style=flat-square)
![Build](https://img.shields.io/badge/Build-Not%20verified-737373?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-8%20Chromium%20passing-737373?style=flat-square)
![Vulnerabilities](https://img.shields.io/badge/Vulnerabilities-0%20known%20dependency%20findings-737373?style=flat-square)

## 1. Introduction

`gambit-workspace` is Gambit's browser workspace. It presents temporary local chess games and analysis.

## 2. Usage

Build the sibling `../../chessboard` checkout first. Then, from this directory, run `npm ci` and `npm run build`. Start the workspace from the Gambit root with `uv run gambit play --port 3030`. `npm test` runs the browser tests.

## 3. Features

- Interactive play with hints and annotations.
- Revision-aware local analysis.

Restarting the backend clears games and evidence.

## 4. Architecture

`src/` consumes protected local HTTP routes and sibling Chessboard events. Vite packages the browser assets into `../src/gambit/web/assets` for the Python distribution.

## 5. Dependencies

| Dependency | Version | Use |
|---|---|---|
| `@mayazrakib/chessboard` | Local link to `file:../../chessboard` | Runtime: interactive board |
| `@playwright/test` | 1.64.1 | Development: browser tests |
| `typescript` | 5.9.3 | Development: type checks |
| `vite` | 8.3.4 | Development: bundling |

## 6. Roadmap

- [x] Temporary local playing workspace.
- [ ] Verify remote and voice behavior independently.

## 7. Contributing

Read `AGENTS.md` and the applicable skills in `.ai/skills/` before contributing. Set up the development environment with `npm ci`. Follow the repository conventions, preserve supported behavior, and add relevant tests for behavior changes. Run `npm test` and `npm run build` before opening a pull request. Describe the change, its purpose, and the validation results in the pull request.

## 8. License

`gambit-workspace` is licensed under the MIT license. See LICENSE for the complete license text.

See `ACKNOWLEDGEMENTS.md` for third-party notices and attributions.
