"""Fast, local chessboard screenshot recognition.

The board detector is a NumPy adaptation of the MIT-licensed fenshot detector
and the bundled ONNX classifier is fenshot's chess-tiles-v2 model. See
THIRD_PARTY_NOTICES.md for attribution. The implementation is optimized for
axis-aligned 2D boards (screenshots and book diagrams), not angled photographs
of physical boards.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote, urlparse

import numpy as np

# ONNX Runtime 1.30 enables Linux telemetry by default. OCR is deliberately
# local-only, so disable it before importing the native runtime.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import onnxruntime as ort
from PIL import Image, ImageOps, UnidentifiedImageError

ort.disable_telemetry_events()

MAX_DETECT_DIMENSION = 1_600
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
CONFIDENCE_FLOOR = 0.7
UNCERTAIN_TILE_FLOOR = 0.85
MAX_SCAN_PASSES = 3
MAX_CANDIDATE_SEQUENCES = 5
MAX_PEAKS_PER_AXIS = 96
PEAK_KEEP_RATIO = 0.2
MIN_SEQUENCE_LENGTH = 7
SEQUENCE_ERROR_PIXELS = 5
LABELS = "1KQRBNPkqrbnp"
EMPTY_PLACEMENT = "8/8/8/8/8/8/8/8"
MODEL_FILENAME = "chess-tiles-v2.onnx"

Orientation = Literal["auto", "white", "black"]


@dataclass(frozen=True)
class BoardCorners:
    x0: int
    y0: int
    x1: int
    y1: int


@dataclass(frozen=True)
class GrayImage:
    data: np.ndarray
    width: int
    height: int


@dataclass(frozen=True)
class Recognition:
    placement: str
    confidences: tuple[float, ...]
    min_confidence: float
    mean_confidence: float
    corners: BoardCorners
    reliable: bool
    plausible: bool


@dataclass(frozen=True)
class LoadedImage:
    gray: GrayImage
    original_width: int
    original_height: int
    scale: float
    digest: str


@dataclass(frozen=True)
class PeakSequence:
    trimmed: tuple[int, ...]
    full: tuple[int, ...]


def _gradient_rows(image: GrayImage) -> np.ndarray:
    return np.gradient(image.data, axis=0)


def _gradient_columns(image: GrayImage) -> np.ndarray:
    return np.gradient(image.data, axis=1)


def _hough_response(
    gradient: np.ndarray, axis: Literal["rows", "columns"]
) -> np.ndarray:
    sum_axis = 1 if axis == "rows" else 0
    positive = np.maximum(gradient, 0).sum(axis=sum_axis, dtype=np.float64)
    negative = np.maximum(-gradient, 0).sum(axis=sum_axis, dtype=np.float64)
    return positive * negative


def _nonmax_suppress(values: np.ndarray, window_size: int = 5) -> np.ndarray:
    output = values.copy()
    length = len(values)
    for index in range(length):
        left = (
            0.0
            if index == 0
            else float(values[max(0, index - window_size) : index].max())
        )
        right = (
            0.0
            if index >= length - 2
            else float(values[index + 1 : min(length - 1, index + window_size)].max())
        )
        if values[index] < left or values[index] <= right:
            output[index] = 0
    return output


def _all_sequences(points: list[int]) -> list[list[int]]:
    if len(points) < MIN_SEQUENCE_LENGTH:
        return []

    sequences: list[list[int]] = []
    used_pairs: set[tuple[int, int]] = set()
    points_array = np.asarray(points)
    for first_index in range(len(points) - 1):
        for second_index in range(first_index + 1, len(points)):
            first = points[first_index]
            second = points[second_index]
            if (first, second) in used_pairs:
                continue

            distance = second - first
            if distance < SEQUENCE_ERROR_PIXELS:
                continue

            sequence = [first, second]
            target = second + distance
            while True:
                nearest_index = int(np.abs(points_array - target).argmin())
                nearest = points[nearest_index]
                if abs(nearest - target) >= SEQUENCE_ERROR_PIXELS:
                    break
                sequence.append(nearest)
                target = nearest + distance

            if len(sequence) >= MIN_SEQUENCE_LENGTH:
                sequences.append(sequence)
                used_pairs.update(pairwise(sequence))

    return sequences


def _trim_sequence(
    sequence: list[int], values: list[float]
) -> tuple[list[int], list[float]]:
    trimmed = sequence[:]
    strengths = values[:]
    if len(trimmed) > 9:
        while len(trimmed) > 7:
            if strengths[0] > strengths[-1]:
                trimmed.pop()
                strengths.pop()
            else:
                trimmed.pop(0)
                strengths.pop(0)
    return trimmed, strengths


def _ranked_peak_sequences(hough: np.ndarray) -> list[PeakSequence]:
    suppressed = _nonmax_suppress(hough)
    peak = float(suppressed.max(initial=0))
    if peak <= 0:
        return []

    candidates = np.flatnonzero(suppressed / peak >= PEAK_KEEP_RATIO)
    if len(candidates) > MAX_PEAKS_PER_AXIS:
        strengths = suppressed[candidates]
        keep = np.argpartition(strengths, -MAX_PEAKS_PER_AXIS)[-MAX_PEAKS_PER_AXIS:]
        candidates = np.sort(candidates[keep])

    positions = [int(position) for position in candidates]
    normalized = {
        position: float(suppressed[position] / peak) for position in positions
    }
    scored: list[tuple[float, PeakSequence]] = []
    for sequence in _all_sequences(positions):
        trimmed, strengths = _trim_sequence(
            sequence, [normalized.get(position, 0.0) for position in sequence]
        )
        scored.append(
            (
                float(np.mean(strengths)),
                PeakSequence(tuple(trimmed), tuple(sequence)),
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    unique: list[PeakSequence] = []
    for _, candidate in scored:
        if candidate.full not in {item.full for item in unique}:
            unique.append(candidate)
        if len(unique) >= MAX_CANDIDATE_SEQUENCES:
            break
    return unique


_CHECKERBOARD_KERNEL = np.fromfunction(
    lambda y, x: np.where(((x // 8 + y // 8) % 2) == 0, 1.0, -1.0),
    (64, 64),
    dtype=int,
)


def _checkerboard_score(image: GrayImage, corners: BoardCorners) -> float:
    width = corners.x1 - corners.x0
    height = corners.y1 - corners.y0
    if width <= 0 or height <= 0:
        return 0.0

    xs = corners.x0 + np.floor(np.arange(64) * width / 64).astype(np.int32)
    ys = corners.y0 + np.floor(np.arange(64) * height / 64).astype(np.int32)
    valid_x = (xs >= 0) & (xs < image.width)
    valid_y = (ys >= 0) & (ys < image.height)
    sampled = image.data[
        np.ix_(np.clip(ys, 0, image.height - 1), np.clip(xs, 0, image.width - 1))
    ]
    sampled = sampled * np.outer(valid_y, valid_x)
    return float(np.sum(sampled * _CHECKERBOARD_KERNEL) / 64)


def snap_corners(image: GrayImage, corners: BoardCorners) -> BoardCorners:
    tile = (corners.x1 - corners.x0) / 8
    radius = max(2, round(tile / 3))
    best_dx = 0
    best_dy = 0
    best_score = -float("inf")

    def evaluate(dx: int, dy: int) -> None:
        nonlocal best_dx, best_dy, best_score
        candidate = BoardCorners(
            corners.x0 + dx,
            corners.y0 + dy,
            corners.x1 + dx,
            corners.y1 + dy,
        )
        score = _checkerboard_score(image, candidate)
        if score > best_score:
            best_dx, best_dy, best_score = dx, dy, score

    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            evaluate(dx, dy)
    coarse_x, coarse_y = best_dx, best_dy
    for dy in range(coarse_y - 2, coarse_y + 3):
        for dx in range(coarse_x - 2, coarse_x + 3):
            evaluate(dx, dy)

    return BoardCorners(
        corners.x0 + best_dx,
        corners.y0 + best_dy,
        corners.x1 + best_dx,
        corners.y1 + best_dy,
    )


def _candidate_extents(lines: tuple[int, ...], tile: float) -> list[tuple[int, int]]:
    extents = [(round(lines[0]), round(lines[-1]))]
    padding = round(tile)
    for start in range(len(lines) - 6):
        extent = (round(lines[start]) - padding, round(lines[start + 6]) + padding)
        if not any(
            abs(left - extent[0]) <= 2 and abs(right - extent[1]) <= 2
            for left, right in extents
        ):
            extents.append(extent)
    return extents


def _reconstruct_square_board(
    image: GrayImage,
    lines: tuple[int, ...],
    axis: Literal["x", "y"],
) -> tuple[BoardCorners, float] | None:
    tile = float(np.median(np.diff(lines)))
    if tile <= 0:
        return None

    limit = image.height if axis == "x" else image.width
    best: BoardCorners | None = None
    best_score = -float("inf")
    for extent_start, extent_end in _candidate_extents(lines, tile):
        span = extent_end - extent_start
        if span <= 0:
            continue
        step = max(2, round(tile / 8))
        for window_start in range(-span, limit + 1, step):
            window_end = window_start + span
            corners = (
                BoardCorners(extent_start, window_start, extent_end, window_end)
                if axis == "x"
                else BoardCorners(window_start, extent_start, window_end, extent_end)
            )
            score = _checkerboard_score(image, corners)
            if score > best_score:
                best, best_score = corners, score
    return (best, best_score) if best is not None else None


def _reconstruct_from_candidates(
    image: GrayImage,
    candidates: list[PeakSequence],
    axis: Literal["x", "y"],
) -> BoardCorners | None:
    best: BoardCorners | None = None
    best_score = -float("inf")
    for candidate in candidates:
        reconstruction = _reconstruct_square_board(image, candidate.full, axis)
        if reconstruction is not None and reconstruction[1] > best_score:
            best, best_score = reconstruction
    return best


def _repair_parity(image: GrayImage, corners: BoardCorners) -> BoardCorners:
    best = corners
    best_score = _checkerboard_score(image, corners)
    if best_score >= 0:
        return corners

    tile = round((corners.x1 - corners.x0) / 8)
    for shift_x, shift_y in ((tile, 0), (-tile, 0), (0, tile), (0, -tile)):
        candidate = BoardCorners(
            corners.x0 + shift_x,
            corners.y0 + shift_y,
            corners.x1 + shift_x,
            corners.y1 + shift_y,
        )
        score = _checkerboard_score(image, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best


def find_chessboard_corners(image: GrayImage) -> BoardCorners | None:
    rows = _hough_response(_gradient_rows(image), "rows")
    columns = _hough_response(_gradient_columns(image), "columns")
    candidates_y = _ranked_peak_sequences(rows)
    candidates_x = _ranked_peak_sequences(columns)
    lines_y = candidates_y[0].trimmed if candidates_y else None
    lines_x = candidates_x[0].trimmed if candidates_x else None

    if lines_x and not lines_y:
        reconstructed = _reconstruct_from_candidates(image, candidates_x, "x")
        return _repair_parity(image, reconstructed) if reconstructed else None
    if lines_y and not lines_x:
        reconstructed = _reconstruct_from_candidates(image, candidates_y, "y")
        return _repair_parity(image, reconstructed) if reconstructed else None
    if not lines_x or not lines_y:
        return None

    step_x = float(np.median(np.diff(lines_x)))
    step_y = float(np.median(np.diff(lines_y)))
    best: BoardCorners | None = None
    best_score = -float("inf")
    for x_start in range(len(lines_x) - 6):
        for y_start in range(len(lines_y) - 6):
            corners = BoardCorners(
                round(lines_x[x_start] - step_x),
                round(lines_y[y_start] - step_y),
                round(lines_x[x_start + 6] + step_x),
                round(lines_y[y_start + 6] + step_y),
            )
            score = _checkerboard_score(image, corners)
            if score > best_score:
                best, best_score = corners, score
    return _repair_parity(image, best) if best else None


def _extract_tiles(image: GrayImage, corners: BoardCorners) -> np.ndarray:
    board_size = 256
    target = np.arange(board_size, dtype=np.float32) + 0.5
    source_x = corners.x0 + target * (corners.x1 - corners.x0) / board_size - 0.5
    source_y = corners.y0 + target * (corners.y1 - corners.y0) / board_size - 0.5
    floor_x = np.floor(source_x).astype(np.int32)
    floor_y = np.floor(source_y).astype(np.int32)
    weight_x = source_x - floor_x
    weight_y = source_y - floor_y
    x0 = np.clip(floor_x, 0, image.width - 1)
    x1 = np.clip(floor_x + 1, 0, image.width - 1)
    y0 = np.clip(floor_y, 0, image.height - 1)
    y1 = np.clip(floor_y + 1, 0, image.height - 1)

    top = (
        image.data[np.ix_(y0, x0)] * (1 - weight_x)
        + image.data[np.ix_(y0, x1)] * weight_x
    )
    bottom = (
        image.data[np.ix_(y1, x0)] * (1 - weight_x)
        + image.data[np.ix_(y1, x1)] * weight_x
    )
    board = (top * (1 - weight_y[:, None]) + bottom * weight_y[:, None]) / 255
    tiles = board.reshape(8, 32, 8, 32).transpose(0, 2, 1, 3)[::-1]
    return np.ascontiguousarray(tiles.reshape(64, 1_024), dtype=np.float32)


def _probabilities_to_recognition(
    probabilities: np.ndarray, corners: BoardCorners
) -> Recognition:
    probabilities = np.asarray(probabilities).reshape(64, 13)
    class_indices = probabilities.argmax(axis=1)
    confidences_array = probabilities[np.arange(64), class_indices]
    pieces = [LABELS[index] for index in class_indices]
    ranks = ["".join(pieces[start : start + 8]) for start in range(56, -1, -8)]
    compressed_ranks: list[str] = []
    for rank in ranks:
        output = ""
        empty_count = 0
        for piece in rank:
            if piece == "1":
                empty_count += 1
            else:
                if empty_count:
                    output += str(empty_count)
                    empty_count = 0
                output += piece
        if empty_count:
            output += str(empty_count)
        compressed_ranks.append(output)

    placement = "/".join(compressed_ranks)
    confidences = tuple(float(value) for value in confidences_array)
    return Recognition(
        placement=placement,
        confidences=confidences,
        min_confidence=min(confidences),
        mean_confidence=sum(confidences) / len(confidences),
        corners=corners,
        reliable=min(confidences) >= CONFIDENCE_FLOOR,
        plausible=placement.count("K") == 1 and placement.count("k") == 1,
    )


def _mask_region(image: GrayImage, corners: BoardCorners) -> GrayImage:
    data = image.data.copy()
    x0 = max(0, corners.x0)
    y0 = max(0, corners.y0)
    x1 = min(image.width, corners.x1)
    y1 = min(image.height, corners.y1)
    data[y0:y1, x0:x1] = 128
    return GrayImage(data, image.width, image.height)


def _read_image_bytes(source: str) -> bytes:
    if source.startswith("data:"):
        header, separator, encoded = source.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("image data URL must use base64 encoding.")
    elif source.startswith("file://"):
        parsed = urlparse(source)
        if parsed.netloc not in ("", "localhost"):
            raise ValueError("remote file URLs are not supported.")
        return _read_image_path(Path(unquote(parsed.path)))
    elif len(source) <= 4_096 and Path(source).is_file():
        return _read_image_path(Path(source))
    else:
        encoded = source

    if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3) + 8:
        raise ValueError(
            f"image must be no larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exception:
        raise ValueError(
            "image must be a local path, file URL, base64 string, or base64 data URL."
        ) from exception
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"image must be no larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    return data


def _read_image_path(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exception:
        raise ValueError(f"cannot read image path: {path}") from exception
    if size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"image must be no larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    try:
        return path.read_bytes()
    except OSError as exception:
        raise ValueError(f"cannot read image path: {path}") from exception


def load_image(source: str) -> LoadedImage:
    raw = _read_image_bytes(source)
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"image must contain no more than {MAX_IMAGE_PIXELS:,} pixels."
                )
            image = ImageOps.exif_transpose(opened).convert("L")
            original_width, original_height = image.size
            scale = min(1.0, MAX_DETECT_DIMENSION / max(image.size))
            if scale < 1:
                image = image.resize(
                    (round(original_width * scale), round(original_height * scale)),
                    Image.Resampling.BILINEAR,
                )
            data = np.asarray(image, dtype=np.float32)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exception:
        raise ValueError("image is not a supported or valid image file.") from exception

    height, width = data.shape
    return LoadedImage(
        gray=GrayImage(data, width, height),
        original_width=original_width,
        original_height=original_height,
        scale=scale,
        digest=hashlib.sha256(raw).hexdigest(),
    )


def flip_placement(placement: str) -> str:
    return "/".join(rank[::-1] for rank in reversed(placement.split("/")))


def _mean_pawn_ranks(placement: str) -> tuple[float | None, float | None]:
    white: list[int] = []
    black: list[int] = []
    for index, row in enumerate(placement.split("/")):
        rank = 8 - index
        for piece in row:
            if piece == "P":
                white.append(rank)
            elif piece == "p":
                black.append(rank)
    return (
        sum(white) / len(white) if white else None,
        sum(black) / len(black) if black else None,
    )


def resolve_orientation(placement: str, requested: Orientation) -> tuple[str, str]:
    if requested == "black":
        return flip_placement(placement), "black"
    if requested == "white":
        return placement, "white"
    if requested != "auto":
        raise ValueError("orientation must be 'auto', 'white', or 'black'.")

    white_rank, black_rank = _mean_pawn_ranks(placement)
    if white_rank is not None and black_rank is not None and white_rank > black_rank:
        return flip_placement(placement), "black"
    return placement, "white"


def infer_castling(placement: str) -> str:
    rows = placement.split("/")
    if len(rows) != 8:
        return "-"

    def expand(rank: str) -> str:
        return "".join(
            "." * int(character) if character.isdigit() else character
            for character in rank
        )

    white = expand(rows[7])
    black = expand(rows[0])
    rights = ""
    if len(white) == 8 and white[4] == "K":
        rights += "K" if white[7] == "R" else ""
        rights += "Q" if white[0] == "R" else ""
    if len(black) == 8 and black[4] == "k":
        rights += "k" if black[7] == "r" else ""
        rights += "q" if black[0] == "r" else ""
    return rights or "-"


def compose_fen(placement: str, side_to_move: str, infer_castling_rights: bool) -> str:
    turns = {"white": "w", "w": "w", "black": "b", "b": "b"}
    try:
        turn = turns[side_to_move.lower()]
    except KeyError as exception:
        raise ValueError(
            "side_to_move must be 'white', 'black', 'w', or 'b'."
        ) from exception
    castling = infer_castling(placement) if infer_castling_rights else "-"
    return f"{placement} {turn} {castling} - 0 1"


def _square_name(tile_index: int, orientation: str) -> str:
    rank = tile_index // 8 + 1
    file_index = tile_index % 8
    if orientation == "black":
        rank = 9 - rank
        file_index = 7 - file_index
    return f"{chr(ord('a') + file_index)}{rank}"


class ChessboardRecognizer:
    """Lazy, reusable ONNX recognizer with a small result cache."""

    def __init__(self) -> None:
        self._session: ort.InferenceSession | None = None
        self._session_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[str, Recognition | None] = OrderedDict()

    def _model_path(self) -> Path:
        configured = os.environ.get("GAMBIT_OCR_MODEL")
        return (
            Path(configured)
            if configured
            else Path(__file__).with_name("models") / MODEL_FILENAME
        )

    def _get_session(self) -> ort.InferenceSession:
        if self._session is not None:
            return self._session
        with self._session_lock:
            if self._session is None:
                model_path = self._model_path()
                if not model_path.is_file():
                    raise RuntimeError(
                        f"Chess OCR model was not found at {model_path}. "
                        "Set GAMBIT_OCR_MODEL to a chess-tiles-v2.onnx file."
                    )
                options = ort.SessionOptions()
                options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                options.graph_optimization_level = (
                    ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                )
                options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
                options.inter_op_num_threads = 1
                self._session = ort.InferenceSession(
                    str(model_path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
        return self._session

    def warm_up(self) -> None:
        self._get_session()

    def _classify(self, image: GrayImage, corners: BoardCorners) -> Recognition:
        probabilities = cast(
            np.ndarray,
            self._get_session().run(
                ["probs"],
                {"tiles": _extract_tiles(image, corners)},
            )[0],
        )
        return _probabilities_to_recognition(probabilities, corners)

    def _scan_once(self, image: GrayImage) -> Recognition | None:
        corners = find_chessboard_corners(image)
        if corners is None:
            return None
        best = self._classify(image, corners)
        snapped = snap_corners(image, corners)
        if snapped != corners:
            candidate = self._classify(image, snapped)
            if candidate.mean_confidence > best.mean_confidence:
                best = candidate
        return best

    def _recognize_uncached(self, image: GrayImage) -> Recognition | None:
        working = image
        fallback: Recognition | None = None
        for _ in range(MAX_SCAN_PASSES):
            result = self._scan_once(working)
            if result is None:
                break
            if result.plausible:
                return result
            if fallback is None or (
                fallback.placement == EMPTY_PLACEMENT
                and result.placement != EMPTY_PLACEMENT
            ):
                fallback = result
            working = _mask_region(working, result.corners)
        return fallback

    def recognize(self, loaded: LoadedImage) -> Recognition | None:
        with self._cache_lock:
            if loaded.digest in self._cache:
                result = self._cache.pop(loaded.digest)
                self._cache[loaded.digest] = result
                return result

        result = self._recognize_uncached(loaded.gray)
        with self._cache_lock:
            self._cache[loaded.digest] = result
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
        return result


recognizer = ChessboardRecognizer()


def recognize_chessboard_image(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
) -> dict[str, object]:
    """Recognize an image and return a compact, AI-friendly result."""

    started = time.perf_counter()
    loaded = load_image(image)
    result = recognizer.recognize(loaded)
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 1)
    if result is None:
        raise ValueError("no axis-aligned chessboard was detected in the image.")

    placement, detected_orientation = resolve_orientation(result.placement, orientation)
    fen = compose_fen(placement, side_to_move, infer_castling_rights)
    uncertain = sorted(
        (
            {
                "square": _square_name(index, detected_orientation),
                "confidence": round(confidence, 4),
            }
            for index, confidence in enumerate(result.confidences)
            if confidence < UNCERTAIN_TILE_FLOOR
        ),
        key=lambda item: item["confidence"],
    )

    scale = loaded.scale
    corners = {
        "x0": round(result.corners.x0 / scale),
        "y0": round(result.corners.y0 / scale),
        "x1": round(result.corners.x1 / scale),
        "y1": round(result.corners.y1 / scale),
    }
    return {
        "fen": fen,
        "piece_placement": placement,
        "side_to_move": "white" if " w " in fen else "black",
        "orientation": detected_orientation,
        "castling_rights_inferred": infer_castling_rights,
        "reliable": result.reliable,
        "plausible": result.plausible,
        "confidence": {
            "minimum": round(result.min_confidence, 4),
            "mean": round(result.mean_confidence, 4),
        },
        "uncertain_squares": uncertain[:12],
        "detected_board": corners,
        "image_size": {
            "width": loaded.original_width,
            "height": loaded.original_height,
        },
        "elapsed_ms": elapsed_ms,
        "history_warning": (
            "Castling, en passant, and move clocks cannot be observed in an image. "
            "Castling was inferred from piece locations."
            if infer_castling_rights
            else "Castling, en passant, and move clocks cannot be observed in an image; neutral values were used."
        ),
    }
