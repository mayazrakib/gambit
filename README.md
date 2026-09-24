# Gambit

Gambit is a local MCP server for fast, AI-driven chess analysis and tutoring.
It combines Stockfish with chessboard OCR, allowing an AI client to turn a
screenshot or book diagram into an analyzable FEN position.

## Features

- `recognize_chessboard`: local image-to-FEN recognition with confidence,
  orientation detection, and explicit reliability signals.
- `analyze_chessboard`: guarded image-to-FEN-to-Stockfish analysis in one tool
  call, avoiding extra model round trips.
- `analyze_position`, `inspect_position`, and `list_legal_moves`: compact,
  structured position tools.
- `tutor_move`: validates a proposed move and returns high-quality replies.
- Lazy, reusable OCR and Stockfish processes plus bounded result caches for
  low repeated-call latency.

The OCR tool accepts a local path, `file://` URL, raw base64 string, or base64
data URL. It is optimized for roughly axis-aligned 2D boards such as chess.com
and Lichess screenshots or book diagrams. Angled photographs of physical
boards are outside its current scope.

Image pixels cannot reveal whose turn it is or position history. The caller
must supply `side_to_move`; castling is conservatively disabled unless
`infer_castling_rights=true` is explicitly requested. En passant and move
counters use neutral defaults.

## Run

Install Stockfish and make it available on `PATH`, or set `STOCKFISH_PATH`.
Then start the stdio MCP server:

```console
uv sync
uv run gambit
```

Run the test suite with:

```console
uv run python -m unittest discover -s test -v
```

Gambit is licensed under the MIT License; see [LICENSE](LICENSE). The OCR model
and adapted detector carry their own MIT attribution in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
