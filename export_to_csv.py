# export_to_csv.py
import sqlite3
import pandas as pd

# Connect to bot database
conn = sqlite3.connect('job_bot.db')

# Read the scraped_jobs table
df = pd.read_sql_query("""
    SELECT id, content, source, scraped_at 
    FROM scraped_jobs 
    ORDER BY scraped_at DESC
""", conn)

# Export to CSV
df.to_csv('exported_jobs.csv', index=False)
print("✅ Exported to exported_jobs.csv")

# Optional: Export to Excel
df.to_excel('exported_jobs.xlsx', index=False)
print("✅ Exported to exported_jobs.xlsx")