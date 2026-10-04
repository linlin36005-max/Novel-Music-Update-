import os
import asyncio
import sqlite3
from collections import defaultdict

from pyrogram import Client, filters
from pyrogram.types import Message

# PyTgCalls/Pyrogram compatibility fix
import pyrogram.errors as pyrogram_errors
if not hasattr(pyrogram_errors, "GroupcallForbidden"):
    if hasattr(pyrogram_errors, "GroupCallForbidden"):
        pyrogram_errors.GroupcallForbidden = pyrogram_errors.GroupCallForbidden

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
import yt_dlp

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
SESSION_STRING = os.environ["SESSION_STRING"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

app = Client("music_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
call = PyTgCalls(user)

queues = defaultdict(list)
DB = "groups.db"

def init_db():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)")
    con.commit()
    con.close()

def save_group(chat_id, title):
    con = sqlite3.connect(DB)
    con.execute("INSERT OR REPLACE INTO groups(chat_id,title) VALUES(?,?)", (chat_id, title or "Unknown"))
    con.commit()
    con.close()

def get_groups():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT chat_id,title FROM groups").fetchall()
    con.close()
    return rows

def delete_group(chat_id):
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM groups WHERE chat_id=?", (chat_id,))
    con.commit()
    con.close()

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "extract_flat": False,
}

def get_audio(query):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return {"title": info.get("title", "Unknown"), "url": info["url"]}

async def play_next(chat_id):
    if not queues[chat_id]:
        try:
            await call.leave_group_call(chat_id)
        except Exception:
            pass
        return
    item = queues[chat_id][0]
    stream = MediaStream(item["url"], video_flags=MediaStream.Flags.IGNORE)
    await call.play(chat_id, stream)

@app.on_message(filters.group)
async def group_tracker(_, message: Message):
    save_group(message.chat.id, message.chat.title)

@app.on_message(filters.command("play") & filters.group)
async def play_handler(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("🎵 အသုံးပြုပုံ: `/play song name`")
    query = message.text.split(None, 1)[1]
    status = await message.reply_text(f"🔎 ရှာနေပါတယ် — `{query}`")
    try:
        item = await asyncio.to_thread(get_audio, query)
        chat_id = message.chat.id
        if not queues[chat_id]:
            queues[chat_id].append(item)
            try:
                await play_next(chat_id)
                return await status.edit_text(f"▶️ **Now Playing**\n🎵 {item['title']}")
            except Exception:
                queues[chat_id].clear()
                return await status.edit_text(
                    "❌ VC ထဲဝင်/ဖွင့်လို့မရပါ။ User session account ကို Group ထဲထည့်ပြီး VC ဖွင့်ထားပါ။"
                )
        queues[chat_id].append(item)
        await status.edit_text(f"➕ Queue ထဲထည့်ပြီးပါပြီ\n🎵 {item['title']}\n📌 Position: {len(queues[chat_id])}")
    except Exception as e:
        await status.edit_text(f"❌ သီချင်းရှာမတွေ့ပါ: {e}")

@app.on_message(filters.command("skip") & filters.group)
async def skip_handler(_, message: Message):
    q = queues[message.chat.id]
    if not q:
        return await message.reply_text("❌ Queue မရှိပါ။")
    q.pop(0)
    try:
        await play_next(message.chat.id)
        await message.reply_text("⏭️ Skip လုပ်ပြီးပါပြီ။")
    except Exception as e:
        await message.reply_text(f"❌ {e}")

@app.on_message(filters.command("pause") & filters.group)
async def pause_handler(_, message: Message):
    try:
        await call.pause(message.chat.id)
        await message.reply_text("⏸️ Paused")
    except Exception as e:
        await message.reply_text(f"❌ {e}")

@app.on_message(filters.command("resume") & filters.group)
async def resume_handler(_, message: Message):
    try:
        await call.resume(message.chat.id)
        await message.reply_text("▶️ Resumed")
    except Exception as e:
        await message.reply_text(f"❌ {e}")

@app.on_message(filters.command("stop") & filters.group)
async def stop_handler(_, message: Message):
    queues[message.chat.id].clear()
    try:
        await call.leave_group_call(message.chat.id)
    except Exception:
        pass
    await message.reply_text("⏹️ Music stopped.")

@app.on_message(filters.command("queue") & filters.group)
async def queue_handler(_, message: Message):
    q = queues[message.chat.id]
    if not q:
        return await message.reply_text("📭 Queue empty.")
    text = "📜 **Queue**\n\n" + "\n".join(f"{i}. {x['title']}" for i, x in enumerate(q, 1))
    await message.reply_text(text)

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_handler(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("📢 အသုံးပြုပုံ: `/broadcast message`")
    text = message.text.split(None, 1)[1]
    groups = get_groups()
    sent = failed = 0
    status = await message.reply_text(f"📢 Broadcasting to {len(groups)} groups...")
    for chat_id, title in groups:
        try:
            await app.send_message(chat_id, text)
            sent += 1
        except Exception:
            failed += 1
            delete_group(chat_id)
        await asyncio.sleep(0.15)
    await status.edit_text(
        f"📢 **Broadcast Complete**\n\n"
        f"✅ Sent: `{sent}`\n"
        f"❌ Failed/Removed: `{failed}`"
    )

@app.on_message(filters.command("broadcast") & ~filters.user(ADMIN_ID))
async def broadcast_denied(_, message: Message):
    await message.reply_text("⛔ Admin only.")

@app.on_message(filters.command("start"))
async def start_handler(_, message: Message):
    await message.reply_text(
        "🎵 **Telegram Music Bot**\n\n"
        "/play song name\n"
        "/pause\n"
        "/resume\n"
        "/skip\n"
        "/queue\n"
        "/stop\n\n"
        "Admin: /broadcast message"
    )

async def main():
    init_db()
    await app.start()
    await user.start()
    await call.start()
    print("Music bot is running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
