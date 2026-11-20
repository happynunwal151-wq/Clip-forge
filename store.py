import json, sqlite3, time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'clipforge.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def connect():
    c=sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS creators (id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL, handle TEXT DEFAULT '', created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS queue_items (id TEXT PRIMARY KEY, title TEXT NOT NULL, clip_url TEXT NOT NULL, platform TEXT NOT NULL, scheduled_at TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Draft', created_at REAL NOT NULL);
        ''')

def save_job(job):
    with connect() as c:
        c.execute('INSERT INTO jobs(id,payload,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at', (job['id'],json.dumps(job,ensure_ascii=False),time.time()))

def load_jobs():
    with connect() as c:
        return {r['id']:json.loads(r['payload']) for r in c.execute('SELECT payload,id FROM jobs ORDER BY updated_at DESC')}

def list_creators():
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM creators ORDER BY created_at DESC')]

def add_creator(name,platform,handle):
    import uuid
    row={'id':uuid.uuid4().hex[:12],'name':name,'platform':platform,'handle':handle,'created_at':time.time()}
    with connect() as c: c.execute('INSERT INTO creators VALUES(?,?,?,?,?)',(row['id'],name,platform,handle,row['created_at']))
    return row

def delete_creator(cid):
    with connect() as c: cur=c.execute('DELETE FROM creators WHERE id=?',(cid,))
    return cur.rowcount>0

def list_queue():
    with connect() as c: return [dict(r) for r in c.execute('SELECT * FROM queue_items ORDER BY CASE WHEN scheduled_at="" THEN 1 ELSE 0 END, scheduled_at ASC, created_at DESC')]

def add_queue(title,clip_url,platform,scheduled_at):
    import uuid
    row={'id':uuid.uuid4().hex[:12],'title':title,'clip_url':clip_url,'platform':platform,'scheduled_at':scheduled_at,'status':'Draft' if not scheduled_at else 'Scheduled','created_at':time.time()}
    with connect() as c: c.execute('INSERT INTO queue_items VALUES(?,?,?,?,?,?,?)',(row['id'],title,clip_url,platform,scheduled_at,row['status'],row['created_at']))
    return row

def delete_queue(qid):
    with connect() as c: cur=c.execute('DELETE FROM queue_items WHERE id=?',(qid,))
    return cur.rowcount>0
