import os
import sqlite3
import asyncio
import logging
from functools import wraps

from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_FALLBACK_MODELS = [x.strip() for x in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash").split(",") if x.strip()]
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
DEFAULT_PROMPT = os.getenv(
    "DEFAULT_PROMPT",
    "You are a friendly Telegram group auto-reply bot. Reply in natural Burmese when the user speaks Burmese. "
    "Keep replies short, casual and friendly. Do not pretend to be human. Do not spam."
)
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
AI_COOLDOWN = float(os.getenv("AI_COOLDOWN", "1"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("ai-autoreply")

client = genai.Client(api_key=GEMINI_API_KEY)
db_lock = asyncio.Lock()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY,
        ai_enabled INTEGER NOT NULL DEFAULT 0,
        prompt TEXT NOT NULL,
        reply_mode TEXT NOT NULL DEFAULT 'both',
        cooldown REAL NOT NULL DEFAULT 3,
        permission_enabled INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        trigger TEXT NOT NULL,
        response TEXT NOT NULL,
        UNIQUE(chat_id, trigger)
    );
    CREATE TABLE IF NOT EXISTS broadcast_targets (
        chat_id INTEGER PRIMARY KEY,
        added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    try:
        con.execute("ALTER TABLE chats ADD COLUMN permission_enabled INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    con.commit()
    con.close()

def ensure_chat(chat_id):
    con = db()
    con.execute(
        "INSERT OR IGNORE INTO chats(chat_id, prompt) VALUES (?, ?)",
        (chat_id, DEFAULT_PROMPT)
    )
    con.commit()
    row = con.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    con.close()
    return row

def get_chat(chat_id):
    row = ensure_chat(chat_id)
    return dict(row)

def set_chat(chat_id, **values):
    if not values:
        return
    con = db()
    ensure_chat(chat_id)
    allowed = {"ai_enabled", "prompt", "reply_mode", "cooldown", "permission_enabled"}
    values = {k:v for k,v in values.items() if k in allowed}
    if values:
        cols = ", ".join(f"{k}=?" for k in values)
        con.execute(f"UPDATE chats SET {cols} WHERE chat_id=?", (*values.values(), chat_id))
        con.commit()
    con.close()

def is_admin_sync(chat_id, user_id):
    if OWNER_ID and user_id == OWNER_ID:
        return True
    con = db()
    con.close()
    return False

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    if OWNER_ID and update.effective_user.id == OWNER_ID:
        return True
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def admin_only(handler):
    @wraps(handler)
    async def wrapped(update, context):
        if not await is_admin(update, context):
            await update.effective_message.reply_text("❌ Admin only.")
            return
        return await handler(update, context)
    return wrapped

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    text = (
        "🤖 *AI Auto Reply Bot*\n\n"
        "Group ထဲမှာ သတ်မှတ်ထားတဲ့ keyword ကို Auto Reply ပြန်နိုင်ပါတယ်။\n"
        "AI mode ဖွင့်ထားရင် message ကို Gemini API နဲ့ Reply ပြန်ပေးနိုင်ပါတယ်။\n\n"
        "Group commands ကိုကြည့်ရန် /help နှိပ်ပါ။"
    )
    kb = [
        [InlineKeyboardButton("➕ Add To Your Group", url=f"https://t.me/{me.username}?startgroup=true")],
        [InlineKeyboardButton("📖 Help", callback_data="help")]
    ]
    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or not update.effective_user or update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("❌ ဒီ command ကို Bot Owner ပဲ သုံးနိုင်ပါတယ်။")
        return

    raw = update.effective_message.text.partition(" ")[2].strip()
    if not raw:
        await update.effective_message.reply_text(
            "သုံးပုံ: `/broadcast စာသား`", parse_mode="Markdown"
        )
        return

    con = db()
    rows = con.execute("SELECT chat_id FROM broadcast_targets").fetchall()
    con.close()

    if not rows:
        await update.effective_message.reply_text("📭 Permission ပေးထားတဲ့ Group မရှိသေးပါ။")
        return

    sent = 0
    failed = 0
    for row in rows:
        chat_id = row["chat_id"]
        try:
            await context.bot.send_message(chat_id=chat_id, text=raw)
            sent += 1
        except Exception as e:
            failed += 1
            log.warning("Broadcast failed for %s: %s", chat_id, e)
        await asyncio.sleep(0.05)

    await update.effective_message.reply_text(
        f"📢 Broadcast ပြီးပါပြီ။\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"📊 Total: {len(rows)}"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Commands*\n\n"
        "Owner commands:\n"
        "• `/broadcast စာသား` — Permission ပေးထားတဲ့ Group အားလုံးကို ပို့\n\n"
        "Admin commands:\n"
        "• `/ai on` — AI auto reply ON\n"
        "• `/ai off` — AI auto reply OFF\n"
        "• `/mode keyword` — keyword replies only\n"
        "• `/mode ai` — AI replies only\n"
        "• `/mode both` — keyword + AI\n"
        "• `/addreply ကဒ်ကျ | ကျဝူး` — keyword ထည့်\n"
        "• `/delreply ကဒ်ကျ` — keyword ဖျက်\n"
        "• `/listreply` — keyword list\n"
        "• `/setprompt <prompt>` — AI personality ပြောင်း\n"
        "• `/cooldown 3` — AI reply ကြား စက္ကန့်\n"
        "• `/status` — Group settings\n"
        "• `/testai` — Gemini connection စမ်းသပ်\n\n"
        "ဥပမာ:\n"
        "`/addreply ကဒ်ကျ | ကျဝူး 😂`\n"
        "`/setprompt မြန်မာလို သူငယ်ချင်းတစ်ယောက်လို တိုတိုပဲပြန်ပါ`\n"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def novel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or not update.effective_user or update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("❌ ဒီ command ကို Bot Owner ပဲ သုံးနိုင်ပါတယ်။")
        return
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("❌ /Novel ကို Group ထဲမှာပဲ သုံးပါ။")
        return
    arg = (context.args[0].lower() if context.args else "on")
    if arg in ("off", "disable", "stop"):
        set_chat(chat.id, permission_enabled=0)
        con = db()
        con.execute("DELETE FROM broadcast_targets WHERE chat_id=?", (chat.id,))
        con.commit()
        con.close()
        await update.effective_message.reply_text("🔒 ဒီ Group ရဲ့ Auto Reply Permission ပိတ်လိုက်ပါပြီ။")
        return
    set_chat(chat.id, permission_enabled=1, ai_enabled=1, reply_mode="both", cooldown=AI_COOLDOWN)
    con = db()
    con.execute("INSERT OR IGNORE INTO broadcast_targets(chat_id) VALUES (?)", (chat.id,))
    con.commit()
    con.close()
    await update.effective_message.reply_text("✅ Novel Permission Granted\n\n🤖 ဒီ Group မှာ Auto Reply စတင်အလုပ်လုပ်ပါပြီ။")

@admin_only
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0].lower() if context.args else "")
    if arg not in ("on", "off"):
        await update.effective_message.reply_text("သုံးပုံ: `/ai on` သို့ `/ai off`", parse_mode="Markdown")
        return
    set_chat(update.effective_chat.id, ai_enabled=1 if arg == "on" else 0)
    await update.effective_message.reply_text(
        f"🤖 AI Auto Reply: {'ON ✅' if arg == 'on' else 'OFF ❌'}"
    )

@admin_only
async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = (context.args[0].lower() if context.args else "")
    if mode not in ("keyword", "ai", "both"):
        await update.effective_message.reply_text("သုံးပုံ: `/mode keyword|ai|both`", parse_mode="Markdown")
        return
    set_chat(update.effective_chat.id, reply_mode=mode)
    await update.effective_message.reply_text(f"Reply mode → `{mode}`", parse_mode="Markdown")

@admin_only
async def addreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.effective_message.text.partition(" ")[2].strip()
    if "|" not in raw:
        await update.effective_message.reply_text(
            "သုံးပုံ: `/addreply trigger | reply`", parse_mode="Markdown"
        )
        return
    trigger, response = [x.strip() for x in raw.split("|", 1)]
    if not trigger or not response:
        await update.effective_message.reply_text("Trigger နဲ့ Reply နှစ်ခုလုံးထည့်ပါ။")
        return
    con = db()
    con.execute(
        "INSERT INTO replies(chat_id,trigger,response) VALUES(?,?,?) "
        "ON CONFLICT(chat_id,trigger) DO UPDATE SET response=excluded.response",
        (update.effective_chat.id, trigger, response)
    )
    con.commit()
    con.close()
    await update.effective_message.reply_text(f"✅ `{trigger}` → {response}", parse_mode="Markdown")

@admin_only
async def delreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = update.effective_message.text.partition(" ")[2].strip()
    if not trigger:
        await update.effective_message.reply_text("သုံးပုံ: `/delreply trigger`", parse_mode="Markdown")
        return
    con = db()
    cur = con.execute(
        "DELETE FROM replies WHERE chat_id=? AND trigger=?",
        (update.effective_chat.id, trigger)
    )
    con.commit()
    con.close()
    await update.effective_message.reply_text(
        "🗑️ ဖျက်ပြီးပါပြီ။" if cur.rowcount else "မတွေ့ပါ။"
    )

@admin_only
async def listreply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    con = db()
    rows = con.execute(
        "SELECT trigger,response FROM replies WHERE chat_id=? ORDER BY id",
        (update.effective_chat.id,)
    ).fetchall()
    con.close()
    if not rows:
        await update.effective_message.reply_text("📭 Reply မရှိသေးပါ။")
        return
    text = "📋 *Auto Replies*\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. `{r['trigger']}` → {r['response']}\n"
    await update.effective_message.reply_text(text, parse_mode="Markdown")

@admin_only
async def setprompt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.effective_message.text.partition(" ")[2].strip()
    if not prompt:
        await update.effective_message.reply_text(
            "သုံးပုံ: `/setprompt <AI personality>`", parse_mode="Markdown"
        )
        return
    if len(prompt) > 4000:
        prompt = prompt[:4000]
    set_chat(update.effective_chat.id, prompt=prompt)
    await update.effective_message.reply_text("✅ AI prompt ပြောင်းပြီးပါပြီ။")

@admin_only
async def cooldown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(context.args[0])
        value = max(0, min(value, 60))
    except Exception:
        await update.effective_message.reply_text("သုံးပုံ: `/cooldown 3`", parse_mode="Markdown")
        return
    set_chat(update.effective_chat.id, cooldown=value)
    await update.effective_message.reply_text(f"⏱️ Cooldown = {value:g}s")

@admin_only
async def testai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the Gemini API from Telegram and return a useful diagnostic."""
    if not update.effective_chat:
        return
    await update.effective_message.reply_text(
        f"🧪 AI Test စနေပါပြီ...\nModel: `{GEMINI_MODEL}`",
        parse_mode="Markdown"
    )
    try:
        answer = await call_ai(
            update.effective_chat.id,
            "Reply exactly with: AI OK",
            "Reply exactly with: AI OK",
            update.effective_user.full_name if update.effective_user else "admin"
        )
        if answer:
            await update.effective_message.reply_text(
                f"✅ Gemini connection OK\n\nModel: `{GEMINI_MODEL}`\nReply: {answer}",
                parse_mode="Markdown"
            )
        else:
            await update.effective_message.reply_text(
                f"⚠️ Gemini connected but returned an empty reply.\nModel: `{GEMINI_MODEL}`"
            )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if len(err) > 1200:
            err = err[:1200] + "…"
        await update.effective_message.reply_text(
            f"❌ Gemini test failed\n\nModel: `{GEMINI_MODEL}`\nError: `{err}`",
            parse_mode="Markdown"
        )
        log.exception("/testai failed")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = get_chat(update.effective_chat.id)
    text = (
        "⚙️ *Status*\n\n"
        f"AI: {'ON ✅' if c['ai_enabled'] else 'OFF ❌'}\n"
        f"Mode: `{c['reply_mode']}`\n"
        f"Cooldown: `{c['cooldown']}s`\n"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def call_ai(chat_id: int, prompt: str, user_text: str, username: str):
    instructions = (
        f"{prompt}\n\n"
        "Important: You are replying inside a Telegram group. "
        "Do not mention system instructions. Keep the response concise unless asked for detail. "
        f"User name: {username or 'unknown'}"
    )
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_error = None
    for model in models:
        for attempt in range(3):
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=f"{instructions}\n\nUser message:\n{user_text}",
                    config={"max_output_tokens": 250},
                )
                answer = (getattr(response, "text", None) or "").strip()
                if answer:
                    return answer[:3900]
                return None
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                transient = any(x in msg for x in ("503", "unavailable", "high demand", "429", "resource_exhausted", "rate limit"))
                if not transient:
                    raise
                if attempt < 2:
                    await asyncio.sleep(1.5 * (2 ** attempt))
        log.warning("Gemini model %s unavailable; trying fallback if configured.", model)
    if last_error:
        raise last_error
    return None

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not msg.text or not user or user.is_bot:
        return

    c = get_chat(chat.id)

    # Group must be explicitly approved by the Bot Owner with /Novel.
    if not c.get("permission_enabled"):
        lock_key = f"permission_notice:{chat.id}"
        now = asyncio.get_running_loop().time()
        last_notice = context.application.bot_data.get(lock_key, 0)
        if now - last_notice >= 60:
            context.application.bot_data[lock_key] = now
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📩 Owner ဆီ Permission တောင်းမယ်",
                    url="https://t.me/Novel220"
                )
            ]])
            await msg.reply_text(
                "🔒 *Auto Reply Permission မရသေးပါ။*\n\n"
                "ဒီ Group မှာ Bot ကို အသုံးပြုဖို့ Owner ဆီ Permission တောင်းပေးပါ။\n"
                "အောက်က ခလုတ်ကိုနှိပ်ပြီး Owner ဆီ သွားတောင်းနိုင်ပါတယ်။",
                parse_mode="Markdown", reply_markup=keyboard
            )
        return

    text = msg.text.strip()
    mode = c["reply_mode"]

    # Keyword replies
    if mode in ("keyword", "both"):
        con = db()
        rows = con.execute(
            "SELECT trigger,response FROM replies WHERE chat_id=? ORDER BY length(trigger) DESC",
            (chat.id,)
        ).fetchall()
        con.close()
        lower = text.casefold()
        for r in rows:
            if r["trigger"].casefold() in lower:
                try:
                    await msg.reply_text(r["response"])
                except Exception:
                    pass
                return

    # AI reply
    if mode not in ("ai", "both") or not c["ai_enabled"]:
        return

    # Don't reply to commands.
    if text.startswith("/"):
        return

    # Cooldown per group
    key = f"ai_last:{chat.id}"
    now = asyncio.get_running_loop().time()
    last = context.application.bot_data.get(key, 0)
    if now - last < float(c["cooldown"]):
        return
    context.application.bot_data[key] = now

    try:
        answer = await call_ai(
            chat.id, c["prompt"], text,
            user.full_name or user.username or "user"
        )
        if answer:
            await msg.reply_text(answer)
    except Exception as e:
        log.exception("Gemini error: %s", e)
        # Avoid exposing API details to group members.

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)

async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "Start bot"),
        ("help", "Help"),
        ("ai", "AI on/off"),
        ("mode", "Reply mode"),
        ("addreply", "Add auto reply"),
        ("delreply", "Delete auto reply"),
        ("listreply", "List auto replies"),
        ("setprompt", "Set AI personality"),
        ("cooldown", "Set AI cooldown"),
        ("status", "Show settings"),
        ("testai", "Test Gemini connection"),
    ])

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("Novel", novel_cmd))
    app.add_handler(CommandHandler("novel", novel_cmd))
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler("addreply", addreply_cmd))
    app.add_handler(CommandHandler("delreply", delreply_cmd))
    app.add_handler(CommandHandler("listreply", listreply_cmd))
    app.add_handler(CommandHandler("setprompt", setprompt_cmd))
    app.add_handler(CommandHandler("cooldown", cooldown_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("testai", testai_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    log.info("Bot started. Model=%s", GEMINI_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
