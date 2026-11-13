"""Seed a Linux Docker volume once; never replace an existing database."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile


def verify(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise RuntimeError(f'{path.name}: 무결성 오류 · 기존 파일 보존, 시작 중단')


def initialize(seed, target):
    seed,target=Path(seed).resolve(),Path(target).resolve()
    target.mkdir(parents=True,exist_ok=True)
    for name in ('news.sqlite3','analysis.sqlite3'):
        destination=target/name
        if destination.exists():
            verify(destination)
            continue
        source=seed/name
        if not source.exists():
            continue
        try:
            verify(source)
        except (sqlite3.DatabaseError,RuntimeError):
            recovered=seed/'recovery'/'news-recovered.sqlite3'
            if name!='news.sqlite3' or not recovered.exists():
                raise
            verify(recovered)
            source=recovered
        with tempfile.NamedTemporaryFile(dir=target,prefix=name+'.importing-',delete=False) as file:
            staging=Path(file.name)
        try:
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original:
                with closing(sqlite3.connect(staging)) as copy, copy:
                    original.backup(copy)
                    if name=='news.sqlite3' and copy.execute("SELECT 1 FROM sqlite_master WHERE name='news_collection'").fetchone():
                        copy.execute('UPDATE news_collection SET next_page=1,complete_at=NULL,last_error=NULL,failures=0,retry_after=0')
            verify(staging)
            if destination.exists():
                raise RuntimeError('다른 초기화 작업이 먼저 완료됨 · 기존 파일 보존')
            staging.replace(destination)
        finally:
            staging.unlink(missing_ok=True)
        print(name+': 무결성 확인 및 최초 이관 완료',flush=True)


if __name__=='__main__':
    initialize('/seed','/data')
    owner=int(os.environ['DATA_UID'])
    os.chown('/data',owner,0)
    for file in Path('/data').glob('*.sqlite3'):
        os.chown(file,owner,0)
