import sqlite3
import json
from pathlib import Path

# Prefer the storage path used by the app's DATABASE_URL, fallback to root mafia.db
candidates = [Path.cwd() / "storage" / "mafia.db", Path.cwd() / "mafia.db"]
found = None
for p in candidates:
    if p.exists():
        found = p
        break

out = {"db_path": str(found) if found else None, "tables": {}}
if not found:
    print(json.dumps(out, ensure_ascii=False))
    raise SystemExit(1)

con = sqlite3.connect(found)
cur = con.cursor()
rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
out['all_tables'] = [r[0] for r in rows]
check = ['clans','clan_members','clan_applications','clan_transactions','clan_game_rewards','clan_audit_logs','users']
for t in check:
    try:
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        out['tables'][t] = [{'cid': c[0],'name':c[1],'type':c[2],'notnull':c[3],'dflt_value':c[4],'pk':c[5]} for c in cols]
    except Exception as e:
        out['tables'][t] = {'error': str(e)}

con.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
