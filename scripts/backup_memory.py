"""Snapshot consistente do SQLite, incluindo WAL, sem alterar a memória de origem."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from contextlib import closing


def backup(path):
    path = Path(path).resolve()
    if not path.exists():
        return None
    folder = path.parent / 'backups'
    folder.mkdir(exist_ok=True)
    destination = folder / ('memory-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup SQLite não passou na verificação de integridade')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='?', default='data/memory.sqlite3')
    args = parser.parse_args()
    result = backup(args.path)
    print('Backup SQLite verificado: ' + str(result) if result else 'Nenhum banco existente.')
