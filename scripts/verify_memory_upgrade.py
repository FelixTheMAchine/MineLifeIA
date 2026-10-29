"""Migração idempotente com comparação dos registros reais, sem executar cognição."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from agent.memory import MemoryManager


def fingerprint(path):
    result={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        for table in ('Events','Knowledge','Hypotheses','JournalEntries','Experiments','Goals'):
            records=db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            result[table]=(len(records),hashlib.sha256(json.dumps(records,ensure_ascii=True).encode()).hexdigest())
    return result


def main():
    path=Path('data/memory.sqlite3').resolve()
    before=fingerprint(path)
    memory=MemoryManager(path)
    if memory.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        raise RuntimeError('Integridade inválida')
    memory.close()
    after=fingerprint(path)
    if before!=after: raise RuntimeError('Registros históricos divergiram')
    print(json.dumps({'historical_rows_unchanged':True,'counts':{k:v[0] for k,v in before.items()},'schema':3},indent=2))


if __name__=='__main__':main()
