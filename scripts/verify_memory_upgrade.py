"""Compare historical fingerprints; --dry-run migrates a temporary SQLite backup only."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from agent.memory import MemoryManager,SCHEMA_VERSION


def fingerprint(path,tables=None):
    result={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        names=tables or [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in names:
            quoted='"'+table.replace('"','""')+'"'
            count=0;digest=hashlib.sha256()
            for record in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
                digest.update(json.dumps(record,ensure_ascii=True).encode());digest.update(b'\n');count+=1
            result[table]=(count,digest.hexdigest())
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    path=Path('data/memory.sqlite3').resolve()
    before=fingerprint(path)
    with tempfile.TemporaryDirectory(prefix='minelife-migration-') as folder:
        target=Path(folder)/'memory.sqlite3' if args.dry_run else path
        if args.dry_run:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source:
                with closing(sqlite3.connect(target)) as destination:source.backup(destination)
        memory=MemoryManager(target)
        if memory.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Integridade inválida')
        memory.close()
        if before!=fingerprint(target,before):raise RuntimeError('Registros históricos divergiram')
        if args.dry_run and before!=fingerprint(path,before):raise RuntimeError('Origem mudou durante a verificação')
    print(json.dumps({'historical_rows_unchanged':True,'tables_compared':len(before),'schema_checked':SCHEMA_VERSION,
                      'dry_run':args.dry_run,'real_database_migrated':not args.dry_run},indent=2))


if __name__=='__main__':main()
