import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "..", "business_contact.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Reactivate User #1 (Super Admin)
cur.execute("UPDATE users SET status = 'active', role = 'super_admin' WHERE id = 1")

# Also ensure georgewassup31@gmail.com has super_admin role and active status
cur.execute("UPDATE users SET role = 'super_admin', status = 'active' WHERE email = 'georgewassup31@gmail.com'")

conn.commit()

cur.execute("SELECT id, email, full_name, role, status FROM users WHERE id IN (1, 8)")
rows = [dict(r) for r in cur.fetchall()]
print("UPDATED USERS:")
for r in rows:
    print(r)
conn.close()
