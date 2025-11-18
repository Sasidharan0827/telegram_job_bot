# check_db.py
import sqlite3

# Connect to your bot database
conn = sqlite3.connect("job_bot.db")
cursor = conn.cursor()

# Show user subscriptions
print("🧑‍💻 Subscribed Users:")
cursor.execute("SELECT user_id, first_name, subscribed FROM users;")
for row in cursor.fetchall():
    print(row)

print("\n📋 Recent Scraped Job Posts:")
cursor.execute("SELECT id, source, scraped_at FROM scraped_jobs ORDER BY scraped_at DESC LIMIT 5;")
for row in cursor.fetchall():
    print(row)

print("\n🧮 Total scraped jobs:")
cursor.execute("SELECT COUNT(*) FROM scraped_jobs;")
print(cursor.fetchone()[0])