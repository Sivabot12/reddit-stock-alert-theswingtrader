import json
import html
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

import os

# ============================================================
# CONFIGURATION
# ============================================================

USERNAME = "Responsible-Case-397"

RSS_URL = f"https://www.reddit.com/user/{USERNAME}/.rss"

STATE_FILE = Path("state.json")

# IMPORTANT:
# Put the token you received from BotFather here.
# Do NOT share this token publicly.

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ============================================================
# REDDIT
# ============================================================

def get_reddit_posts():
    """
    Fetch the Reddit RSS feed and return only Reddit posts.

    Reddit IDs:
        t3_ = post/submission
        t1_ = comment
    """

    headers = {
        "User-Agent": "RedditStockAlert/1.0"
    }

    response = requests.get(
        RSS_URL,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    feed = feedparser.parse(response.content)

    posts = []

    for entry in feed.entries:

        entry_id = entry.get("id", "")

        # t3_ = Reddit post
        # Ignore t1_ comments
        if "t3_" not in entry_id:
            continue

        # Try to determine subreddit
        subreddit = ""

        if entry.get("tags"):
            subreddit = entry["tags"][0].get("term", "")

        posts.append({
            "id": entry_id,
            "title": entry.get("title", "No title"),
            "link": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "published": entry.get("published", ""),
            "published_parsed": entry.get("published_parsed"),
            "updated_parsed": entry.get("updated_parsed"),
            "subreddit": subreddit
        })

    return posts


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_state():
    """
    Load previously seen Reddit post IDs.
    """

    if not STATE_FILE.exists():
        return {
            "seen_ids": []
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

    except (json.JSONDecodeError, OSError):
        return {
            "seen_ids": []
        }

    # Compatibility with our previous version
    if "last_seen_id" in state and "seen_ids" not in state:
        return {
            "seen_ids": [state["last_seen_id"]]
        }

    return state


def save_state(seen_ids):
    """
    Save previously seen Reddit post IDs.

    We keep the most recent 50 IDs.
    """

    seen_ids = list(seen_ids)[-50:]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seen_ids": seen_ids
            },
            f,
            indent=4
        )


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_html(text):
    """
    Convert Reddit's HTML content into readable plain text.
    """

    if not text:
        return ""

    soup = BeautifulSoup(
        text,
        "html.parser"
    )

    text = soup.get_text(
        separator="\n",
        strip=True
    )

    return html.unescape(text)


# ============================================================
# TIME FORMATTING
# ============================================================

def format_post_time(post):
    """
    Convert Reddit's UTC timestamp to Indian Standard Time.
    """

    timestamp = (
        post.get("published_parsed")
        or post.get("updated_parsed")
    )

    if timestamp is None:
        return "Time unavailable"

    # feedparser provides UTC time
    utc_time = datetime(
        *timestamp[:6],
        tzinfo=ZoneInfo("UTC")
    )

    # Convert UTC -> IST
    ist_time = utc_time.astimezone(
        ZoneInfo("Asia/Kolkata")
    )

    return ist_time.strftime(
        "%d %b %Y, %I:%M:%S %p IST"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(post):
    """
    Send a Reddit post notification to Telegram.
    """

    post_text = clean_html(
        post.get("summary", "")
    )

    # Telegram has a message size limit.
    # Keep the Reddit content below that limit.
    if len(post_text) > 3000:
        post_text = (
            post_text[:3000]
            + "\n\n[Post truncated...]"
        )

    posted_time = format_post_time(post)

    subreddit = post.get(
        "subreddit",
        ""
    )

    message = (
        "🚨 NEW REDDIT POST\n\n"

        f"👤 u/{USERNAME}\n\n"

        f"📌 {post['title']}\n\n"

        f"🕐 Posted: {posted_time}\n\n"

        f"📍 r/{subreddit}\n\n"
    )

    if post_text:
        message += (
            "📝 POST:\n"
            f"{post_text}\n\n"
        )

    message += (
        f"🔗 {post['link']}"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram error: {result}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("Checking Reddit...")

    # --------------------------------------------------------
    # Get Reddit posts
    # --------------------------------------------------------

    posts = get_reddit_posts()

    if not posts:
        print("No Reddit posts found.")
        return

    # --------------------------------------------------------
    # Load state
    # --------------------------------------------------------

    state = load_state()

    seen_ids = set(
        state.get("seen_ids", [])
    )

    print(
        f"Posts found in RSS feed: {len(posts)}"
    )

    print(
        f"Previously seen posts: {len(seen_ids)}"
    )

    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if not seen_ids:

        print("\nFirst run detected.")

        print(
            "Saving existing posts "
            "without sending notifications."
        )

        for post in posts:
            seen_ids.add(post["id"])

        save_state(seen_ids)

        print("Initial state saved.")

        return

    # --------------------------------------------------------
    # FIND NEW POSTS
    # --------------------------------------------------------

    new_posts = [
        post
        for post in posts
        if post["id"] not in seen_ids
    ]

    if not new_posts:

        print("\nNo new posts.")

        return

    # RSS normally gives newest -> oldest.
    #
    # Reverse them so if multiple posts appeared since
    # our previous check, Telegram receives them oldest -> newest.
    new_posts.reverse()

    print(
        f"\n🚨 {len(new_posts)} new post(s) detected!"
    )

    # --------------------------------------------------------
    # SEND NOTIFICATIONS
    # --------------------------------------------------------

    for post in new_posts:

        print("\n" + "=" * 80)

        print(
            "TITLE:",
            post["title"]
        )

        print(
            "POSTED:",
            format_post_time(post)
        )

        print(
            "LINK:",
            post["link"]
        )

        print("=" * 80)

        try:

            send_telegram_message(post)

            print(
                "Telegram notification "
                "sent successfully."
            )

            # Only mark as seen after successful
            # Telegram delivery.
            seen_ids.add(post["id"])

        except Exception as e:

            print(
                f"Failed to send Telegram notification: {e}"
            )

            print(
                "Post will be retried on the next run."
            )

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    save_state(seen_ids)


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()