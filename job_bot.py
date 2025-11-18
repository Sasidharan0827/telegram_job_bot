# job_bot.py
import os
import sqlite3
import asyncio
import requests
import logging
import time
import schedule
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === Workaround for Python 3.13 compatibility ===
import sys
if sys.version_info >= (3, 13):
    from telegram.ext._updater import Updater
    if not hasattr(Updater, '__dict__'):
        # Force __dict__ creation
        Updater.__slots__ = tuple(list(getattr(Updater, '__slots__', [])))

# Load env vars
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_URLS = [url.strip() for url in os.getenv("CHANNELS", "").split(",") if url.strip()]

# === Set up logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ... rest of your code continues ...

# === Set up SQLite database ===
conn = sqlite3.connect("job_bot.db", check_same_thread=False)
cursor = conn.cursor()

# Users who subscribed
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    subscribed INTEGER DEFAULT 0
)
""")

# Store all scraped jobs
cursor.execute("""
CREATE TABLE IF NOT EXISTS scraped_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT UNIQUE,
    source TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()


# === Bot Class ===
class TelegramJobBot:
    def __init__(self, token):
        self.token = token
        self.app = Application.builder().token(token).build()

        # Command Handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("search", self.search_jobs))
        self.app.add_handler(CommandHandler("subscribe", self.subscribe))
        self.app.add_handler(CommandHandler("unsubscribe", self.unsubscribe))
        self.app.add_handler(CommandHandler("dailyjobs", self.manual_daily_jobs))

        self.start_scheduler()

    # /start
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user.id, user.username, user.first_name)
        )
        conn.commit()

        await update.message.reply_text(f"""👋 Hello {user.first_name}!

I'm your Job Bot. Here's what I can do:
/search python developer — Search jobs
/subscribe — Get daily job alerts at 6 PM
/unsubscribe — Stop alerts
/dailyjobs — See today’s jobs now
        """)

    # /subscribe
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        cursor.execute("UPDATE users SET subscribed = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        await update.message.reply_text("✅ Subscribed! You’ll now receive daily job alerts at 6 PM.")

    # /unsubscribe
    async def unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        cursor.execute("UPDATE users SET subscribed = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        await update.message.reply_text("🛑 Unsubscribed from daily alerts.")

    # /search
    async def search_jobs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage:\n/search python developer")
            return

        keyword = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for: {keyword}")

        jobs = await self.fetch_jobs_remoteok(keyword)

        if not jobs:
            await update.message.reply_text("❌ No jobs found from RemoteOK.")
            return

        for job in jobs[:5]:
            msg = f"""
📌 {job['title']}
🏢 {job['company']}
📍 {job['location']}
💰 {job['salary']}
🔗 {job['link']}
            """
            await update.message.reply_text(msg.strip(), parse_mode=None)
            await asyncio.sleep(0.5)

    # Uses RemoteOK
    async def fetch_jobs_remoteok(self, keyword):
        try:
            url = f"https://remoteok.io/api?tag={keyword.replace(' ', '-')}"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            jobs = []
            if response.status_code == 200 and response.json() and isinstance(response.json(), list):
                data = response.json()[1:]  # Skip metadata
                for job in data:
                    jobs.append({
                        "title": job.get("position", "Unknown Title"),
                        "company": job.get("company", "Unknown"),
                        "location": job.get("location", "Remote"),
                        "salary": job.get("salary", "Not disclosed"),
                        "link": job.get("url")
                    })
            return jobs
        except Exception as e:
            logger.error(f"Search fetch error: {e}")
            return []

    # /dailyjobs manual trigger
    async def manual_daily_jobs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📡 Scraping latest jobs from all channels...")
        await self.send_daily_jobs()

    # Scrape all channels
    def scrape_all_channels(self):
        headers = {"User-Agent": "Mozilla/5.0"}
        new_posts = []

        for url in CHANNEL_URLS:
            print(f"[SCRAPING] {url}")
            try:
                res = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(res.text, 'html.parser')
                blocks = soup.find_all("div", class_="tgme_widget_message_text")

                for block in blocks:
                    text = block.get_text(strip=True)
                    if not text:
                        continue

                    cursor.execute("SELECT 1 FROM scraped_jobs WHERE content = ?", (text,))
                    if cursor.fetchone():
                        continue

                    cursor.execute("INSERT OR IGNORE INTO scraped_jobs (content, source) VALUES (?, ?)", (text, url))
                    conn.commit()
                    new_posts.append(text)
            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")

        return new_posts

    # Scheduled or manual job digest sender
    async def send_daily_jobs(self):
        new_posts = self.scrape_all_channels()

        cursor.execute("SELECT user_id FROM users WHERE subscribed = 1")
        user_ids = [u[0] for u in cursor.fetchall()]

        # If no new posts, send fallback
        if not new_posts:
            logger.warning("❕ No new job posts found. Sending fallback...")
            cursor.execute("SELECT content FROM scraped_jobs ORDER BY scraped_at DESC LIMIT 10")
            fallback_posts = [row[0] for row in cursor.fetchall()]

            if not fallback_posts:
                return

            message = f"🔁 No new job updates found. Here are recent jobs:\n\n"
            await self.send_posts_to_users(message, fallback_posts, user_ids)
            return

        # If new posts found
        print(f"✅ Collected {len(new_posts)} new posts.")
        header = "📢 Today's Freshers Jobs:\n\n"
        await self.send_posts_to_users(header, new_posts, user_ids)

    # Utility: split + send jobs to all users
    async def send_posts_to_users(self, header, posts, user_ids):
        MAX_CHARS = 4000
        chunks = []
        temp = header

        for post in posts:
            if len(temp) + len(post) + 4 < MAX_CHARS:
                temp += f"• {post}\n\n"
            else:
                chunks.append(temp)
                temp = f"• {post}\n\n"
        if temp:
            chunks.append(temp)

        for user_id in user_ids:
            for chunk in chunks:
                try:
                    await self.app.bot.send_message(
                        chat_id=user_id,
                        text=chunk,
                        parse_mode=None,
                        disable_web_page_preview=True
                    )
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"❌ Failed to send to {user_id}: {e}")

    # Run every day at 6:00 p.m.
    def start_scheduler(self):
        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(30)

        schedule.every().day.at("18:00").do(lambda: asyncio.run(self.send_daily_jobs()))
        t = threading.Thread(target=run_schedule)
        t.daemon = True
        t.start()

    def run(self):
        print("🚀 Bot is running... CTRL+C to stop.")
        self.app.run_polling()

# Entry point
if __name__ == "__main__":
    import threading
    if not BOT_TOKEN:
        print("❌ Please set BOT_TOKEN in .env file.")
        exit()
    bot = TelegramJobBot(BOT_TOKEN)
    bot.run()