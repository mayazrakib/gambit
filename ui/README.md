# `gambit-workspace`

![Version](https://img.shields.io/badge/Version-0.3.0-737373?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-737373?style=flat-square)
![Languages](https://img.shields.io/badge/Languages-TypeScript-737373?style=flat-square)
![Frameworks](https://img.shields.io/badge/Frameworks-Vite%2C%20Chessboard-737373?style=flat-square)
![Compatibility](https://img.shields.io/badge/Compatibility-Browser%20targets%3B%20not%20verified-737373?style=flat-square)
![Build](https://img.shields.io/badge/Build-Not%20run%20remotely-737373?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-8%20Chromium%20passing-737373?style=flat-square)
![Vulnerabilities](https://img.shields.io/badge/Vulnerabilities-0%20known%20dependency%20findings-737373?style=flat-square)

## 1. Introduction

Gambit's browser workspace presents temporary local chess games and analysis.

## 2. Usage

Build sibling `../../chessboard`, then run `npm ci` and `npm run build`. From the Gambit root, run `uv run gambit play --port 3030`.

## 3. Features

Interactive play, hints, annotations, and revision-aware local analysis. Restarting the backend clears games and evidence.

## 4. Architecture

`src/` consumes protected local HTTP routes and sibling Chessboard events. Vite packages browser assets into `../src/gambit/web/assets` for Python distribution.

## 5. Dependencies

| Dependency | Version | Use |
|---|---|---|
| `@mayazrakib/chessboard` | `file:../../chessboard` | dependencies |
| `@playwright/test` | `1.64.1` | devDependencies |
| `typescript` | `5.9.3` | devDependencies |
| `vite` | `8.3.4` | devDependencies |

## 6. Roadmap

- [x] Temporary local playing workspace.
- [ ] Verify remote and voice behavior independently.

## 7. Contributing

Read `AGENTS.md` and the applicable skills in `.ai/skills/` before contributing. Set up the development environment with `npm ci`. Follow the repository conventions, preserve supported behavior, and add relevant tests for behavior changes. Run `npm test` and `npm run build` before opening a pull request. Describe the change, its purpose, and the validation results in the pull request.

## 8. License

`gambit-workspace` is licensed under the MIT license. See LICENSE for the complete license text.

See `ACKNOWLEDGEMENTS.md` for third-party notices and attributions.
