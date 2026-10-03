import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

import chess

from gambit.engine import parse_board, parse_move

def pronounce_move(
    board: chess.Board,
    move: chess.Move,
) -> str:
    if board.is_castling(move,):
        words = (
            "Castle kingside"
            if chess.square_file(move.to_square,) > chess.square_file(move.from_square,)
            else "Castle queenside"
        )
    else:
        piece = board.piece_at(move.from_square,)
        origin = chess.square_name(move.from_square,)
        destination = chess.square_name(move.to_square,)
        action = "takes" if board.is_capture(move,) else "to"
        words = f"{chess.piece_name(piece.piece_type,).capitalize()} from {origin[0]} {origin[1]} {action} {destination[0]} {destination[1]}"

        if move.promotion:
            words += f", promoting to {chess.piece_name(move.promotion,)}"

    next_board = board.copy()
    next_board.push(move,)

    if next_board.is_checkmate():
        words += ", checkmate"
    elif next_board.is_check():
        words += ", check"

    return words + "."

def create_speech_plan(
    fen: str,
    segments: list[str],
    moves: list[str] | None = None,
) -> dict:
    if len(segments,) > 20 or sum((len(segment,) for segment in segments),) > 4000:
        raise ValueError("Speech plans support at most 20 segments and 4000 characters.",)

    board = parse_board(fen,)
    pronunciations = []

    for notation in moves or []:
        move = parse_move(
            board,
            notation,
        )
        pronunciations.append({
            "notation": board.san(move,),
            "spoken": pronounce_move(
                board,
                move,
            ),
        },)
        board.push(move,)

    return {
        "segments": segments,
        "pronunciations": pronunciations,
        "can_interrupt": True,
        "position_fen": fen,
    }

class Speech:
    def __init__(
        self,
        executable: str,
        directory: str,
    ) -> None:
        self.executable = executable
        self.directory = Path(directory,).expanduser()
        self.lock = threading.Lock()

    def synthesize(
        self,
        text: str,
        voice: str = "en",
        rate: int = 170,
    ) -> dict:
        if not text.strip() or len(text,) > 4000 or not 80 <= rate <= 350:
            raise ValueError("Speech requires 1 to 4000 characters and a rate of 80 to 350 words per minute.",)

        if (
            not voice
            or len(voice,) > 40
            or any((character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+"
                for character in voice),)
        ):
            raise ValueError("The speech voice identifier is invalid.",)

        executable = shutil.which(self.executable,)

        if executable is None:
            raise RuntimeError("Local speech synthesis is unavailable. Install espeak-ng or configure its executable.",)

        digest = hashlib.sha256(f"{executable}\n{voice}\n{rate}\n{text}".encode(),).hexdigest()
        destination = self.directory / f"{digest}.wav"

        with self.lock:
            self.directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            if not destination.exists():
                temporary = destination.with_suffix(".partial.wav",)

                try:
                    subprocess.run(
                        [executable, "-v", voice, "-s", str(rate,), "-w", str(temporary,), "--stdin",],
                        input=text,
                        text=True,
                        capture_output=True,
                        timeout=30,
                        check=True,
                    )
                    temporary.replace(destination,)
                except (subprocess.SubprocessError, OSError) as exception:
                    temporary.unlink(missing_ok=True,)
                    raise RuntimeError("Local speech synthesis failed.",) from exception

            cached_files = sorted(
                self.directory.glob("*.wav",),
                key=lambda path: path.stat().st_mtime,
            )

            for old_file in cached_files[:-128]:
                if old_file != destination:
                    old_file.unlink()

        return {
            "audio_uri": destination.as_uri(),
            "mime_type": "audio/wav",
            "voice": voice,
            "rate_words_per_minute": rate,
            "transport": "local file",
            "can_interrupt": True,
        }
