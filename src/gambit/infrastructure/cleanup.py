import re
import sqlite3
from pathlib import Path

LEGACY_TABLES = {'record', 'analysis_cache', 'puzzle', 'game', 'game_position', 'import_checkpoint', 'position_evaluation',}
LEGACY_NAMES = {'datasets.json', 'downloads.json', 'capacity.json', 'capacity.lock', 'download.lock', 'import.lock', 'storage.lock', 'reservations.json', 'downloads.log',}

def is_owned_database(path: Path,) -> bool:
    try:
        with path.open('rb',) as stream:
            if stream.read(16,) != b'SQLite format 3\x00':
                return False

        with sqlite3.connect(
            path.as_uri() + '?mode=ro&immutable=1',
            uri=True,
        ) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'",)}

        return bool(tables & LEGACY_TABLES,)
    except (OSError, sqlite3.Error):
        return False

def clean_runtime(
    directory: str,
    should_apply: bool = False,
) -> dict:
    root = Path(directory,).expanduser().absolute()

    if root.is_symlink():
        raise ValueError('Runtime cleanup does not follow symbolic links.',)

    if not root.is_dir():
        return {'status': 'empty', 'root': str(root,), 'targets': [], 'removed_files': 0, 'remaining_owned_artifacts': 0,}

    targets = set()
    skipped_links = []
    unclassified = []

    for path in root.rglob('*',):
        if path.is_symlink() or any((parent.is_symlink() for parent in path.parents if parent != root.parent),):
            skipped_links.append(str(path.relative_to(root,),),)
            continue

        if not path.is_file() or path.name == 'openings.json':
            continue

        relative = path.relative_to(root,)

        is_download = relative.parts[0] == 'downloads' and ((path.name.startswith(('personal-', 'lichess_db_'),) or re.fullmatch(
            r'[A-Za-z0-9_-]+-(?:\d{4}-\d{2}|archives)\.json',
            path.name,
        )) or path.suffix in ('.part', '.zst', '.bz2', '.pgn'))

        is_tablebase = path.suffix in ('.rtbw', '.rtbz')
        is_generated_metadata = path.name in LEGACY_NAMES or path.name.startswith('.capacity',)
        is_database = path.suffix in ('.sqlite3', '.sqlite', '.db', '.bak', '.backup') and is_owned_database(path,)

        if is_download or is_tablebase or is_generated_metadata or is_database:
            targets.add(path,)

            if is_database:
                for suffix in ('-wal', '-shm', '-journal'):
                    sidecar = Path(str(path,) + suffix,)

                    if sidecar.is_file() and not sidecar.is_symlink():
                        targets.add(sidecar,)
        elif not path.name.endswith(('-wal', '-shm', '-journal'),):
            unclassified.append(str(relative,),)

    inventory = [{'path': str(path.relative_to(root,),), 'bytes': path.stat().st_size,} for path in sorted(targets,)]
    removed = 0

    if should_apply:
        for path in sorted(targets,):
            if path.is_symlink() or any((parent.is_symlink() for parent in path.parents if parent != root.parent),):
                raise ValueError('A cleanup target changed into a symbolic link.',)

            path.unlink(missing_ok=True,)
            removed += 1

    return {'status': 'applied' if should_apply else 'preview', 'root': str(root,), 'targets': inventory, 'removed_files': removed, 'remaining_owned_artifacts': sum((path.exists() for path in targets),), 'skipped_links': sorted(set(skipped_links,),), 'unclassified_files': unclassified, 'limitation_codes': ['only_inspected_runtime_root', 'unclassified_files_preserved', 'not_forensic_erasure',],}
