# Save in D:\PMD-Desktop-main next to app.py, then run:  py diag2.py
import os
print("=== PMD app-path diagnostic ===")
print("running from folder:", os.getcwd())

# 0) is the NEW db.py actually here?
try:
    src = open("db.py", encoding="utf-8").read()
    print("db.py has the FIX:", ("NEVER caches a False" in src))
except Exception as e:
    print("cannot read db.py here:", e)

# make the URL available via env too (fallback path)
try:
    import tomllib
    with open(".streamlit/secrets.toml", "rb") as f:
        sec = tomllib.load(f)
    if sec.get("NEON_DATABASE_URL"):
        os.environ["NEON_DATABASE_URL"] = sec["NEON_DATABASE_URL"]
        print("secrets.toml NEON_DATABASE_URL: present")
    else:
        print("secrets.toml NEON_DATABASE_URL: MISSING")
except Exception as e:
    print("secrets.toml read error:", e)

# 1) import the app's real modules and walk the login decision chain
try:
    import db, storage
    print("db._HAVE_PG (psycopg imported):", db._HAVE_PG)
    print("db._url() present:", bool(db._url()))
    print("db.enabled():", db.enabled())
    print("storage._use_pg():", storage._use_pg())
    print("storage._on_cloud_host():", storage._on_cloud_host())
    try:
        print("storage._pg_for(users table):", storage._pg_for(storage._users_path()))
    except Exception as e:
        print("_pg_for error:", e)
    df = storage.get_users()
    print("get_users() count:", len(df))
    if not df.empty:
        print("users seen by app:", list(df["user_key"]))
    else:
        print(">>> get_users() is EMPTY -> app falls back to DEMO users (why login fails)")
except Exception as e:
    import traceback
    print("ERROR importing/using app modules:")
    print(traceback.format_exc()[-1500:])
