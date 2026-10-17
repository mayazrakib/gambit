import csv
import hashlib
import io
import json
import os
import threading
from collections import defaultdict
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile

import chess

from gambit.engine.client import parse_board

OPENING_REVISION = '5a13018164f6bd88f48b3dc31a8e2a39f31a060a'
OPENING_SOURCE = f'https://github.com/lichess-org/chess-openings/tree/{OPENING_REVISION}'

def get_position_key(board: chess.Board,) -> str:
    return ' '.join(board.fen(en_passant='legal',).split()[:4],)

class Knowledge:
    def __init__(
        self,
        directory: str,
    ) -> None:
        self.directory = Path(directory,).expanduser()
        self.lock = threading.Lock()
        self.records = None
        self.positions = None
        self.revision = OPENING_REVISION

    def load(self,) -> None:
        with self.lock:
            if self.records is not None:
                return

            path = self.directory / 'openings.json'

            if path.is_file():
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError('The opening snapshot is too large.',)

                snapshot = json.loads(path.read_text(),)
                revision = snapshot['revision']

                if len(revision,) != 40 or any((character not in '0123456789abcdef' for character in revision),):
                    raise ValueError('An opening revision must be a Git commit SHA.',)

                rows = snapshot['rows']
            else:
                revision = OPENING_REVISION
                rows = []

                for letter in 'abcde':
                    content = files('gambit',).joinpath(
                        'data',
                        f'{letter}.tsv',
                    ).read_text()

                    rows.extend(csv.DictReader(
                        io.StringIO(content,),
                        delimiter='\t',
                    ),)

            records, positions = self.validate_rows(rows,)
            self.revision = revision
            self.records = records
            self.positions = positions

    @staticmethod
    def validate_rows(rows: list[dict],) -> tuple[
        list,
        dict,
    ]:
        if not rows or len(rows,) > 20000:
            raise ValueError('An opening snapshot requires between 1 and 20000 lines.',)

        records = []
        positions = defaultdict(list,)

        for row in rows:
            if not row.get('name',) or not row.get('eco',) or not row.get('pgn',):
                raise ValueError('Opening lines require name, ECO, and PGN.',)

            board = chess.Board()
            edges = []

            for token in row['pgn'].split():
                if token.endswith('.',):
                    continue

                if len(edges,) >= 256:
                    raise ValueError('An opening line exceeds 256 plies.',)

                move = board.parse_san(token,)
                edges.append((get_position_key(board,), move.uci(), board.san(move,)),)
                board.push(move,)

            record = {'eco': row['eco'], 'name': row['name'], 'pgn': row['pgn'], 'position_key': get_position_key(board,),}
            records.append(record,)
            positions[get_position_key(board,)].append({'opening': record,},)

            for key, uci, san in edges:
                positions[key].append({'move_uci': uci, 'move_san': san, 'eco': row['eco'], 'name': row['name'],},)

        return records, dict(positions,)

    def find_moves(
        self,
        fen: str,
        offset: int = 0,
        limit: int = 12,
    ) -> dict:
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError('Opening pagination is outside supported bounds.',)

        board = parse_board(fen,)
        self.load()

        matches = self.positions.get(
            get_position_key(board,),
            [],
        )

        return {'status': 'available' if matches else 'empty', 'fen': board.fen(), 'records': deepcopy(matches[offset:offset + limit],), 'next_offset': offset + limit if len(matches,) > offset + limit else None, 'source': f'https://github.com/lichess-org/chess-openings/tree/{self.revision}', 'revision': self.revision, 'evidence_kind': 'opening_classification', 'limitation_codes': ['classification_not_complete_theory', 'corpus_move_not_quality_assessment',],}

    def search_openings(
        self,
        query: str,
        offset: int = 0,
        limit: int = 12,
    ) -> dict:
        if len(query,) > 200 or not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError('Opening search is outside supported bounds.',)

        self.load()
        matches = [record for record in self.records if query.casefold() in record['name'].casefold()]

        return {'status': 'available' if matches else 'empty', 'items': deepcopy(matches[offset:offset + limit],), 'next_offset': offset + limit if len(matches,) > offset + limit else None, 'revision': self.revision, 'source': f'https://github.com/lichess-org/chess-openings/tree/{self.revision}',}

    def publish(
        self,
        revision: str,
        rows: list[dict],
    ) -> dict:
        if len(revision,) != 40 or any((character not in '0123456789abcdef' for character in revision),):
            raise ValueError('Supply a full lowercase opening commit SHA.',)

        records, positions = self.validate_rows(rows,)

        payload = json.dumps(
            {'revision': revision, 'rows': rows,},
            separators=(',', ':'),
        ).encode()

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = None

        try:
            with NamedTemporaryFile(
                dir=self.directory,
                prefix='.openings-',
                delete=False,
            ) as stream:
                temporary = Path(stream.name,)
                stream.write(payload,)
                stream.flush()
                os.fsync(stream.fileno(),)

            with self.lock:
                os.replace(
                    temporary,
                    self.directory / 'openings.json',
                )

                self.revision, self.records, self.positions = revision, records, positions
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True,)

        return {'status': 'available', 'revision': revision, 'lines': len(records,), 'sha256': hashlib.sha256(payload,).hexdigest(),}
