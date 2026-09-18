"""
Telegram Bot Info Fetcher — Backend for the screenshot maker.
Uses Pyrogram userbot to fetch bot name, PFP, and MAU.

Usage:
  1. pip install -r requirements.txt
  2. Fill in API_ID, API_HASH, SESSION_STRING below
  3. python server.py
  4. Open index.html in your browser
"""

import asyncio
import base64
import io
import logging
import sys
import time

# Fix Windows console encoding for emoji/unicode
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from flask import Flask, request, jsonify
from flask_cors import CORS

# Pyrogram needs an event loop at import time (Python 3.12+)
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client
from pyrogram.raw.functions.users import GetFullUser
from pyrogram.errors import (
    FloodWait,
    PeerIdInvalid,
    UsernameNotOccupied,
    UsernameInvalid,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuration --------------------------------------------------------
API_ID = 20028561
API_HASH = "0f3793daaf4d3905e55b0e44d8719cad"
SESSION_STRING = "BQE8buMAkBu7Aibch2rJ7hez7mrbZk9821L-ZFaW7CZ9D67x26pmHDvmSmgmPWv0cXNB4sbYWbubzaQhUHOfGq2qIrGOF01IWMlxrXSQMUjut4JWyx4k3-iyk2CAUlHIeGNLuRmUUcO7nqoKmcMZgQ6MRO3Zqhnf1Bkpdnx-ZmORkkcRh-Ye9JZoUtZOHURsL_uOvEPbR3qcpMfmMg16mjugMsA-A9hhzFM5mcgH3YCdraCQaC7hFU-1sIgDNQz7Yn06IBlDzzH6vtemX4nNiXYgUGiZ3XppkEwJNkXlnDwaRagnD-mGZxMJoWRQxuVj5uBvF9QhHOAymAXNtRukHiCBCZX74wAAAAIF-NnCAA"
# --------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)

# Pyrogram client
client = Client(
    name="ss_fetcher",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    no_updates=True,
)

# --- Background asyncio loop ----------------------------------------------

loop = asyncio.new_event_loop()

async def _init_client():
    await client.start()
    print("[OK] Pyrogram client connected.")

def _run_loop():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_init_client())
    loop.run_forever()

import threading
threading.Thread(target=_run_loop, daemon=True).start()
time.sleep(3)  # give it time to connect

# --- Core fetch logic -----------------------------------------------------

async def _fetch_bot(username: str) -> dict:
    """Fetch bot name, MAU, and profile photo using raw API."""
    result = {}

    # Resolve the user
    try:
        peer = await client.resolve_peer(username)
    except (UsernameNotOccupied, UsernameInvalid, PeerIdInvalid):
        return {"error": f"User @{username} not found."}
    except FloodWait as e:
        return {"error": f"Telegram rate limit. Retry in {e.value}s."}

    # Get full user info (includes bot_active_users)
    try:
        full_result = await client.invoke(GetFullUser(id=peer))
        full_user = full_result.full_user

        hydrated_user = None
        for u in full_result.users:
            if u.id == full_user.id:
                hydrated_user = u
                break

        if not hydrated_user:
            return {"error": f"Could not resolve @{username}."}

    except FloodWait as e:
        return {"error": f"Telegram rate limit. Retry in {e.value}s."}
    except Exception as e:
        logger.error("GetFullUser failed: %s", e)
        return {"error": f"Failed to fetch user info: {e}"}

    # Name
    first = getattr(hydrated_user, "first_name", "") or ""
    last = getattr(hydrated_user, "last_name", "") or ""
    name = (first + " " + last).strip() or username
    result["name"] = name

    # MAU (bot_active_users)
    bot_active = getattr(hydrated_user, "bot_active_users", None)
    if bot_active:
        result["mau"] = bot_active
    elif getattr(hydrated_user, "bot", False):
        result["mau"] = 0
    else:
        result["mau"] = 0

    # Profile photo
    result["pfp"] = ""
    photo = getattr(hydrated_user, "photo", None)
    if photo:
        try:
            user_obj = await client.get_users(username)
            if user_obj and user_obj.photo:
                photo_file = await client.download_media(
                    user_obj.photo.big_file_id, in_memory=True
                )
                if photo_file and isinstance(photo_file, io.BytesIO):
                    b64 = base64.b64encode(photo_file.getvalue()).decode("ascii")
                    result["pfp"] = f"data:image/jpeg;base64,{b64}"
        except Exception as exc:
            logger.warning("Could not download profile photo: %s", exc)

    result["start_message"] = ""
    result["buttons"] = []

    return result


# --- Flask Routes ---------------------------------------------------------

@app.route("/fetch", methods=["POST"])
def fetch_bot():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "No username provided."}), 400

    try:
        future = asyncio.run_coroutine_threadsafe(_fetch_bot(username), loop)
        result = future.result(timeout=30)
        return jsonify(result)
    except TimeoutError:
        return jsonify({"error": "Request timed out."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# --- Main -----------------------------------------------------------------

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    print(f"Bot Fetcher running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
