from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from scripts.init_data import initialize


class DataMigrationTest(unittest.TestCase):
    def test_seed_is_verified_and_existing_volume_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            seed=Path(folder)/'seed';target=Path(folder)/'volume';seed.mkdir()
            with closing(sqlite3.connect(seed/'news.sqlite3')) as db, db:
                db.execute('create table news_collection(next_page,complete_at,last_error,failures,retry_after)')
                db.execute("insert into news_collection values(30,'old','error',2,999)")
            initialize(seed,target)
            with closing(sqlite3.connect(target/'news.sqlite3')) as db, db:
                self.assertEqual(db.execute('select * from news_collection').fetchone(),(1,None,None,0,0))
                db.execute('update news_collection set next_page=5')
            initialize(seed,target)
            with closing(sqlite3.connect(target/'news.sqlite3')) as db, db:
                self.assertEqual(db.execute('select next_page from news_collection').fetchone()[0],5)

    def test_invalid_source_is_not_copied_and_cannot_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            seed=Path(folder)/'seed';target=Path(folder)/'volume';seed.mkdir()
            (seed/'news.sqlite3').write_text('invalid database')
            with self.assertRaises(sqlite3.DatabaseError):initialize(seed,target)
            self.assertFalse((target/'news.sqlite3').exists())

    def test_valid_primary_takes_precedence_over_an_old_recovery_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            seed=Path(folder)/'seed';target=Path(folder)/'volume';(seed/'recovery').mkdir(parents=True)
            for path,value in [(seed/'news.sqlite3','current'),(seed/'recovery'/'news-recovered.sqlite3','older')]:
                with closing(sqlite3.connect(path)) as db,db:
                    db.execute('create table marker(value)');db.execute('insert into marker values(?)',(value,))
            initialize(seed,target)
            with closing(sqlite3.connect(target/'news.sqlite3')) as db:
                self.assertEqual(db.execute('select value from marker').fetchone()[0],'current')
