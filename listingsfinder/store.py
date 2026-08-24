import sqlite3,json
from .config import DB_PATH
from .sources import DEFAULT_SOURCES
def connect():
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; return con
def init_db():
    con=connect(); cur=con.cursor(); cur.execute('create table if not exists sources (name text primary key,data text not null)'); cur.execute('create table if not exists runs (run_id text primary key,data text not null,created_at text default current_timestamp)'); cur.execute('create table if not exists listings (listing_id text primary key,data text not null)'); cur.execute('create table if not exists settings (key text primary key,value text not null)')
    legacy_sources = ('BusinessesForSale','BizBuySell','Zonado','SMERGERS','Sunbelt','Transworld','Murphy Business','Flippa','Empire Flippers','LoopNet','Poe Advisors','American Healthcare Capital','N3 Advisors')
    cur.executemany('delete from sources where name=?', [(name,) for name in legacy_sources])
    for s in DEFAULT_SOURCES:
        cur.execute('insert or ignore into sources values (?,?)',(s['Source Name'],json.dumps(s)))
    con.commit(); con.close()
def get_sources(): init_db(); con=connect(); rows=con.execute("select data from sources order by json_extract(data,'$.Priority'), name").fetchall(); con.close(); return [json.loads(r['data']) for r in rows]
def replace_sources(sources):
    init_db(); con=connect(); con.execute('delete from sources')
    for src in sources:
        con.execute('insert or replace into sources values (?,?)',(src.get('Source Name') or src.get('name'),json.dumps(src)))
    con.commit(); con.close()
def save_source(src): init_db(); con=connect(); con.execute('insert or replace into sources values (?,?)',(src.get('Source Name') or src.get('name'),json.dumps(src))); con.commit(); con.close()
def save_run(run_id,data): init_db(); con=connect(); con.execute('insert or replace into runs values (?, ?, current_timestamp)',(run_id,json.dumps(data,default=str))); con.commit(); con.close()
def save_listings(listings):
    init_db(); con=connect()
    for l in listings:
        d=l.to_dict() if hasattr(l,'to_dict') else l; con.execute('insert or replace into listings values (?,?)',(d.get('lead_id') or d.get('listing_id'),json.dumps(d,default=str)))
    con.commit(); con.close()
def list_runs(limit=25):
    init_db(); con=connect(); rows=con.execute('select data from runs order by created_at desc limit ?',(limit,)).fetchall(); con.close(); return [json.loads(r['data']) for r in rows]
def list_listings(limit=500):
    init_db(); con=connect(); rows=con.execute('select data from listings limit ?',(limit,)).fetchall(); con.close(); return [json.loads(r['data']) for r in rows]
def get_setting(key,default=None):
    init_db(); con=connect(); row=con.execute('select value from settings where key=?',(key,)).fetchone(); con.close()
    return json.loads(row['value']) if row else default
def save_setting(key,value):
    init_db(); con=connect(); con.execute('insert or replace into settings values (?,?)',(key,json.dumps(value))); con.commit(); con.close()
