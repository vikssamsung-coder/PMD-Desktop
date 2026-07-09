# Save as diag.py in D:\PMD-Desktop-main and run: py diag.py
import os, sys
print("=== PMD Neon connection diagnostic ===")
# 1. can we read the secret?
url = None
try:
    import tomllib
    with open(".streamlit/secrets.toml","rb") as f:
        sec = tomllib.load(f)
    url = sec.get("NEON_DATABASE_URL")
    print("secrets.toml found. NEON_DATABASE_URL present:", bool(url))
    if url:
        # show host only, hide credentials
        host = url.split("@")[-1].split("/")[0] if "@" in url else url[:40]
        print("  endpoint/host:", host)
        print("  has channel_binding:", "channel_binding" in url)
except Exception as e:
    print("could NOT read .streamlit/secrets.toml:", e)

# 2. is psycopg importable?
try:
    import psycopg
    from psycopg_pool import ConnectionPool
    print("psycopg import: OK")
except Exception as e:
    print("psycopg import FAILED:", e)
    url = None

# 3. can we actually connect + count users?
if url:
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users")
                print("CONNECTED. users count in this DB:", cur.fetchone()[0])
                cur.execute("SELECT user_key FROM users ORDER BY user_key")
                print("users:", [r[0] for r in cur.fetchall()])
    except Exception as e:
        print("CONNECT/QUERY FAILED:", e)
