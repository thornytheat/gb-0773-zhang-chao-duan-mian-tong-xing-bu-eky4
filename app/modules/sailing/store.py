import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.modules.journal.manifest import canonical

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sailing_supplements (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    sample TEXT NOT NULL,
    created TEXT NOT NULL,
    rows TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sailing_advices (
    id TEXT PRIMARY KEY,
    sample TEXT NOT NULL,
    vessel TEXT NOT NULL,
    created TEXT NOT NULL,
    tiers TEXT NOT NULL,
    tide_rev TEXT NOT NULL,
    result TEXT NOT NULL,
    status TEXT NOT NULL,
    confirmed_at TEXT,
    superseded_by TEXT);
'''

COLUMNS = ('id', 'sample', 'vessel', 'created', 'tiers', 'tide_rev', 'result',
           'status', 'confirmed_at', 'superseded_by')


def to_advice(row):
    advice = dict(zip(COLUMNS, row))
    advice['tiers'] = json.loads(advice['tiers'])
    advice['result'] = json.loads(advice['result'])
    return advice


class SailingBook:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.execute('COMMIT')
        except BaseException:
            connection.execute('ROLLBACK')
            raise
        finally:
            connection.close()

    @contextmanager
    def reader(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            yield connection

    def add_supplement(self, connection, sample, created, rows):
        cursor = connection.execute('INSERT INTO sailing_supplements (sample, created, rows) VALUES (?, ?, ?)',
                                    (sample, created, canonical(rows)))
        return cursor.lastrowid

    def supplements(self, sample, connection=None):
        sql = 'SELECT rows FROM sailing_supplements WHERE sample=? ORDER BY seq'
        if connection is not None:
            return [row for (text,) in connection.execute(sql, (sample,)) for row in json.loads(text)]
        with self.reader() as reader:
            return [row for (text,) in reader.execute(sql, (sample,)) for row in json.loads(text)]

    def put(self, connection, advice):
        cursor = connection.execute(
            f'INSERT INTO sailing_advices VALUES ({", ".join("?" for _ in COLUMNS)}) ON CONFLICT(id) DO NOTHING',
            tuple(canonical(advice[key]) if key in ('tiers', 'result') else advice[key] for key in COLUMNS))
        return cursor.rowcount == 1

    def get_advice(self, advice_id, connection=None):
        sql = f'SELECT {", ".join(COLUMNS)} FROM sailing_advices WHERE id=?'
        if connection is not None:
            row = connection.execute(sql, (advice_id,)).fetchone()
            return to_advice(row) if row else None
        with self.reader() as reader:
            row = reader.execute(sql, (advice_id,)).fetchone()
            return to_advice(row) if row else None

    def advices_by_status(self, connection, sample, status):
        rows = connection.execute(
            f'SELECT {", ".join(COLUMNS)} FROM sailing_advices WHERE sample=? AND status=? ORDER BY created, id',
            (sample, status)).fetchall()
        return [to_advice(row) for row in rows]

    def list_advices(self, sample):
        with self.reader() as reader:
            rows = reader.execute(
                f'SELECT {", ".join(COLUMNS)} FROM sailing_advices WHERE sample=? ORDER BY created DESC, rowid DESC LIMIT 40',
                (sample,)).fetchall()
        return [to_advice(row) for row in rows]

    def mark_stale(self, connection, advice_id, superseded_by):
        connection.execute("UPDATE sailing_advices SET status='stale', superseded_by=? WHERE id=?",
                           (superseded_by, advice_id))

    def refresh_revision(self, connection, advice_id, tide_rev):
        connection.execute('UPDATE sailing_advices SET tide_rev=? WHERE id=?', (tide_rev, advice_id))

    def confirm(self, connection, advice_id, confirmed_at):
        connection.execute("UPDATE sailing_advices SET status='confirmed', confirmed_at=? WHERE id=?",
                           (confirmed_at, advice_id))
