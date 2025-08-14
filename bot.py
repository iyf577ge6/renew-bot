# -*- coding: utf-8 -*-
# telegram.py  (aiogram 2.x)

import os
import asyncio
import logging
import sqlite3
from contextlib import closing
from datetime import datetime

import pytz
import jdatetime               # pip install jdatetime
from aiogram import Bot, Dispatcher, executor, types  # pip install aiogram==2.25.2
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from renew_service import MarzbanRenewService
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

# ---------------- تنظیمات ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set in the environment")

def _ids_from_env(key: str):
    raw = os.getenv(key, "").strip()
    if not raw:
        return set()
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}

SUPERADMINS = _ids_from_env("SUPERADMIN_IDS")  # اگر خالی باشد، بوت‌استرپ فعال است
ADMINS = _ids_from_env("ADMIN_IDS")

MARZBAN_ADDRESS = os.getenv("MARZBAN_ADDRESS")
MARZBAN_USERNAME = os.getenv("MARZBAN_USERNAME")
MARZBAN_PASSWORD = os.getenv("MARZBAN_PASSWORD")
if not all([MARZBAN_ADDRESS, MARZBAN_USERNAME, MARZBAN_PASSWORD]):
    raise RuntimeError("Marzban credentials are not fully set in the environment")

# وضعیت فعال بودن ربات (on/off)
BOT_STATUS = os.getenv("BOT_STATUS", "on").lower() in ("on", "1", "true")

IR_TZ = pytz.timezone("Asia/Tehran")
DB_PATH = "/var/lib/marzban/renew-tg-bot/bot.db"

# ---------------- نقش‌ها ----------------
def is_superadmin(tid: int) -> bool:
    return tid in SUPERADMINS or (len(SUPERADMINS) == 0)

def is_admin_db(tid: int) -> bool:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT 1 FROM admins WHERE telegram_id=?", (tid,)).fetchone()
        return row is not None

def is_admin(tid: int) -> bool:
    return is_superadmin(tid) or is_admin_db(tid)

# ---------------- دیتابیس ----------------
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")

        c.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS customers (telegram_id INTEGER PRIMARY KEY, credits INTEGER NOT NULL DEFAULT 0, username TEXT, full_name TEXT)"
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            actor_username TEXT,
            target_marzban_username TEXT,
            success INTEGER NOT NULL,
            message TEXT
        )"""
        )
        # مهاجرت جدول admins برای افزودن username و full_name (اگر قبلاً نبوده)
        try:
            c.execute("ALTER TABLE admins ADD COLUMN username TEXT")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE admins ADD COLUMN full_name TEXT")
        except Exception:
            pass

        # مهاجرت جدول customers برای افزودن username و full_name (اگر قبلاً نبوده)
        try:
            c.execute("ALTER TABLE customers ADD COLUMN username TEXT")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE customers ADD COLUMN full_name TEXT")
        except Exception:
            pass

        for aid in ADMINS:
            c.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (aid,))

def upsert_admin_profile(tid: int, username: str, full_name: str):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("""
            INSERT INTO admins (telegram_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
        """, (tid, username or "", full_name or ""))

def add_admin(tid: int):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (tid,))

def remove_admin(tid: int):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("DELETE FROM admins WHERE telegram_id=?", (tid,))

def ensure_customer(tid: int, username: str | None = None, full_name: str | None = None):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO customers (telegram_id, credits) VALUES (?, 0)", (tid,))
        if username is not None or full_name is not None:
            conn.execute(
                "UPDATE customers SET username = COALESCE(?, username), full_name = COALESCE(?, full_name) WHERE telegram_id=?",
                (username, full_name, tid),
            )

def add_credits(tid: int, amount: int):
    ensure_customer(tid)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("UPDATE customers SET credits = credits + ? WHERE telegram_id=?", (amount, tid))

def set_credits(tid: int, amount: int):
    ensure_customer(tid)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("UPDATE customers SET credits = ? WHERE telegram_id=?", (amount, tid))

def get_credits(tid: int) -> int:
    ensure_customer(tid)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT credits FROM customers WHERE telegram_id=?", (tid,)).fetchone()
        return int(row[0]) if row else 0

def dec_credit(tid: int) -> bool:
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        row = conn.execute("SELECT credits FROM customers WHERE telegram_id=?", (tid,)).fetchone()
        if not row or int(row[0]) <= 0:
            return False
        conn.execute("UPDATE customers SET credits = credits - 1 WHERE telegram_id=?", (tid,))
        return True

def log_action(actor_id: int, actor_username: str, marz_user: str, success: bool, message: str):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            "INSERT INTO logs (ts_utc, actor_id, actor_username, target_marzban_username, success, message) VALUES (?,?,?,?,?,?)",
            (datetime.utcnow().isoformat(), actor_id, actor_username, marz_user, 1 if success else 0, message)
        )

def jalali_now_str() -> str:
    now_teh = datetime.now(IR_TZ)
    jnow = jdatetime.datetime.fromgregorian(datetime=now_teh)
    return jnow.strftime("%Y/%m/%d - %H:%M:%S")

# ---------------- کیبوردها ----------------
def main_kb(is_admin_user: bool, is_super: bool) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔁 تمدید کاربر"))
    kb.add(KeyboardButton("💳 اعتبار من"))
    if is_admin_user:
        kb.add(KeyboardButton("🛠 پنل ادمین"))
    kb.add(KeyboardButton("ℹ️ راهنما"))
    return kb

def admin_kb(is_super: bool) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if is_super:
        kb.row(KeyboardButton("➕ افزودن مشتری"), KeyboardButton("📌 تنظیم اعتبار"))
        kb.row(KeyboardButton("➕ شارژ اعتبار"), KeyboardButton("🔁 تمدید برای مشتری"))
        kb.row(KeyboardButton("🔎 اعتبار مشتری"), KeyboardButton("👑 مدیریت ادمین‌ها"))
        kb.add(KeyboardButton("👥 لیست ادمین‌ها"))
        kb.add(KeyboardButton("👥 لیست مشتری‌ها"))
    else:
        # ادمین معمولی فقط عملیات‌های مرتبط با تمدید را می‌بیند
        kb.row(KeyboardButton("🔁 تمدید برای مشتری"), KeyboardButton("🔎 اعتبار مشتری"))
    kb.add(KeyboardButton("⬅️ بازگشت"))
    return kb

def admins_manage_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ افزودن ادمین"), KeyboardButton("➖ حذف ادمین"))
    kb.add(KeyboardButton("⬅️ بازگشت به پنل ادمین"))
    return kb

def cancel_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("⬅️ انصراف"))
    return kb

# ---------------- FSM ----------------
class RenewFlow(StatesGroup):
    ask_username = State()

class AdminAddCustomerFlow(StatesGroup):
    ask_tid = State()

class AdminSetCreditsFlow(StatesGroup):
    ask_tid_amount = State()

class AdminAddCreditsFlow(StatesGroup):
    ask_tid_amount = State()

class AdminRenewForFlow(StatesGroup):
    ask_tid_username = State()

class AdminGetCreditsFlow(StatesGroup):
    ask_tid = State()

class AdminAddAdminFlow(StatesGroup):
    ask_tid = State()

class AdminRmAdminFlow(StatesGroup):
    ask_tid = State()

# ---------------- ربات ----------------
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

svc = MarzbanRenewService(MARZBAN_ADDRESS, MARZBAN_USERNAME, MARZBAN_PASSWORD)

async def notify_admins(text: str):
    targets = set()
    targets |= SUPERADMINS
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT telegram_id FROM admins").fetchall()
        targets |= {int(r[0]) for r in rows}
    for tid in targets:
        try:
            await bot.send_message(chat_id=tid, text=text)
        except Exception:
            pass

def sync_admin_profile_if_needed(user: types.User):
    tid = user.id
    ensure_customer(tid, user.username or "", user.full_name or "")
    if is_admin(tid):
        upsert_admin_profile(tid, user.username or "", user.full_name or "")

# ---------------- فیلتر دسترسی ----------------
# برای کاربران معمولی که هیچ اعتباری ندارند پاسخی ارسال می‌کنیم
# تا بدانند چرا بات به پیامشان جواب نمی‌دهد. سوپرادمین‌ها از این
# فیلتر مستثنا هستند تا همیشه دسترسی کامل داشته باشند.
@dp.message_handler(
    lambda msg: not is_superadmin(msg.from_user.id) and get_credits(msg.from_user.id) <= 0,
    content_types=types.ContentTypes.ANY,
)
async def no_credit_reply(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    await m.reply("اعتباری برای شما باقی نمانده است")

# ---------------- دستورات عمومی ----------------
@dp.message_handler(commands=['whoami'])
async def whoami(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    role = "سوپرادمین" if is_superadmin(m.from_user.id) else ("ادمین" if is_admin(m.from_user.id) else "کاربر")
    await m.reply(f"ID: {m.from_user.id}\nنقش: {role}")

@dp.message_handler(commands=['start'])
async def start(m: types.Message, state: FSMContext):
    await state.finish()
    sync_admin_profile_if_needed(m.from_user)
    await m.reply(
        "سلام! به ربات تمدید خوش آمدید.",
        reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
    )

@dp.message_handler(lambda msg: msg.text == "ℹ️ راهنما")
async def help_btn(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    await m.reply(
        "با دکمه‌ها کار کن:\n"
        "🔁 «تمدید کاربر» → نام کاربری را می‌گیرد و تمدید ۳۱روزه انجام می‌دهد.\n"
        "💳 «اعتبار من» → تعداد تمدیدهای باقی‌مانده را نشان می‌دهد.\n"
        "🛠 «پنل ادمین» → فقط برای ادمین‌ها."
    )

@dp.message_handler(lambda msg: msg.text == "💳 اعتبار من")
async def my_credits_btn(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    cr = get_credits(m.from_user.id)
    await m.reply(f"اعتبار تمدید باقی‌مانده: {cr}")

# ---------------- انصراف سراسری (برای همه مراحل) ----------------
@dp.message_handler(lambda msg: msg.text == "⬅️ انصراف", state='*')
async def cancel_any(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    current = await state.get_state()
    if current is not None:
        await state.finish()
    await m.reply("لغو شد.", reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id)))

# ---------------- تمدید کاربر ----------------
@dp.message_handler(lambda msg: msg.text == "🔁 تمدید کاربر")
async def renew_btn(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    cr = get_credits(m.from_user.id)
    if cr <= 0:
        return await m.reply("اعتباری برای شما باقی نمانده است")
    await RenewFlow.ask_username.set()
    await m.reply("نام کاربری را ارسال کن:", reply_markup=cancel_kb())

@dp.message_handler(state=RenewFlow.ask_username)
async def renew_get_username(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    username = (m.text or "").strip()
    if not username or username == "⬅️ انصراف":
        return  # هندلر انصراف جداست
    ok = False
    msg = ""
    try:
        result = await svc.renew_user_31d(username)
        ok = bool(result.get("ok"))
        msg = result.get("message", "")
    except Exception as e:
        ok = False
        msg = f"خطا در ارتباط با سرور: {e}"
    if ok:
        if not dec_credit(m.from_user.id):
            await state.finish()
            return await m.reply(
                "اعتبار شما کافی نبود.",
                reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
            )
        await m.reply(
            "✅ تمدید انجام شد. (۳۱ روزه + ریست حجم + اکتیو)",
            reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
        )
    else:
        await m.reply(
            f"❌ {msg or 'تمدید ناموفق بود.'}",
            reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
        )
    stamp = jalali_now_str()
    actor = f"{m.from_user.id} ({m.from_user.full_name or ''})"
    report = (f"🧾 گزارش تمدید ({stamp})\n"
              f"کاربر تلگرام: {actor}\n"
              f"نام کاربری: {username}\n"
              f"نتیجه: {'موفق' if ok else 'ناموفق'}\n"
              f"پیام: {msg}")
    log_action(m.from_user.id, m.from_user.username or "", username, ok, msg)
    await notify_admins(report)
    await state.finish()

# ---------------- پنل ادمین ----------------
@dp.message_handler(lambda msg: msg.text == "🛠 پنل ادمین")
async def admin_panel(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_admin(m.from_user.id):
        return await m.reply(
            "دسترسی کافی نداری.",
            reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
        )
    await state.finish()
    await m.reply(
        "پنل ادمین:",
        reply_markup=admin_kb(is_superadmin(m.from_user.id))
    )

@dp.message_handler(lambda msg: msg.text == "⬅️ بازگشت")
async def back_to_main(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    await state.finish()
    await m.reply(
        "منوی اصلی:",
        reply_markup=main_kb(is_admin(m.from_user.id), is_superadmin(m.from_user.id))
    )

# ---- افزودن مشتری (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "➕ افزودن مشتری")
async def admin_add_customer(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.", reply_markup=admin_kb(False))
    await AdminAddCustomerFlow.ask_tid.set()
    await m.reply("آیدی عددی تلگرام مشتری را وارد کن:", reply_markup=cancel_kb())

@dp.message_handler(state=AdminAddCustomerFlow.ask_tid)
async def admin_add_customer_tid(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    if not (m.text or "").isdigit():
        return await m.reply("یک آیدی عددی معتبر بفرست.", reply_markup=cancel_kb())
    tid = int(m.text.strip())
    ensure_customer(tid)
    await m.reply(f"مشتری {tid} اضافه شد.", reply_markup=admin_kb(is_superadmin(m.from_user.id)))
    await state.finish()

# ---- تنظیم اعتبار (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "📌 تنظیم اعتبار")
async def admin_setcredits(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.", reply_markup=admin_kb(False))
    await AdminSetCreditsFlow.ask_tid_amount.set()
    await m.reply("فرمت: <telegram_id> <n>\nمثال: 12345678 20", reply_markup=cancel_kb())

@dp.message_handler(state=AdminSetCreditsFlow.ask_tid_amount)
async def admin_setcredits_args(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    try:
        tid_s, amt_s = (m.text or "").split()
        set_credits(int(tid_s), int(amt_s))
        await m.reply(
            f"اعتبار مشتری {tid_s} به {amt_s} تنظیم شد.",
            reply_markup=admin_kb(is_superadmin(m.from_user.id))
        )
        await state.finish()
    except Exception:
        await m.reply("فرمت درست نیست. دوباره بفرست: <telegram_id> <n>", reply_markup=cancel_kb())

# ---- شارژ اعتبار (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "➕ شارژ اعتبار")
async def admin_addcredits(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.", reply_markup=admin_kb(False))
    await AdminAddCreditsFlow.ask_tid_amount.set()
    await m.reply("فرمت: <telegram_id> <n>\nمثال: 12345678 10", reply_markup=cancel_kb())

@dp.message_handler(state=AdminAddCreditsFlow.ask_tid_amount)
async def admin_addcredits_args(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    try:
        tid_s, amt_s = (m.text or "").split()
        add_credits(int(tid_s), int(amt_s))
        await m.reply(
            f"{amt_s} واحد اعتبار به مشتری {tid_s} اضافه شد.",
            reply_markup=admin_kb(is_superadmin(m.from_user.id))
        )
        await state.finish()
    except Exception:
        await m.reply("فرمت درست نیست. دوباره بفرست: <telegram_id> <n>", reply_markup=cancel_kb())

# ---- تمدید برای مشتری (ادمین و سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "🔁 تمدید برای مشتری")
async def admin_renew_for(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_admin(m.from_user.id):
        return await m.reply("دسترسی کافی نداری.")
    await AdminRenewForFlow.ask_tid_username.set()
    await m.reply("فرمت: <telegram_id> <username>\nمثال: 12345678 myuser", reply_markup=cancel_kb())

@dp.message_handler(state=AdminRenewForFlow.ask_tid_username)
async def admin_renew_for_args(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    try:
        tid_s, username = (m.text or "").split(maxsplit=1)
        tid = int(tid_s)
    except Exception:
        return await m.reply("فرمت درست نیست. دوباره بفرست: <telegram_id> <username>", reply_markup=cancel_kb())
    credits = get_credits(tid)
    if credits <= 0:
        await state.finish()
        return await m.reply("اعتبار مشتری صفر است.", reply_markup=admin_kb(is_superadmin(m.from_user.id)))

    ok = False
    msg = ""
    try:
        result = await svc.renew_user_31d(username.strip())
        ok = bool(result.get("ok"))
        msg = result.get("message", "")
    except Exception as e:
        ok = False
        msg = f"خطا در ارتباط با سرور: {e}"

    if ok:
        if not dec_credit(tid):
            await m.reply("اعتبار مشتری کافی نبود (Race).", reply_markup=admin_kb(is_superadmin(m.from_user.id)))
        else:
            await m.reply(f"✅ تمدید برای {tid} انجام شد.", reply_markup=admin_kb(is_superadmin(m.from_user.id)))
    else:
        await m.reply(f"❌ {msg or 'تمدید ناموفق بود.'}", reply_markup=admin_kb(is_superadmin(m.from_user.id)))

    stamp = jalali_now_str()
    actor = f"{m.from_user.id} ({m.from_user.full_name or ''})"
    report = (f"🧾 گزارش تمدید ({stamp})\n"
              f"ادمین: {actor}\n"
              f"برای مشتری: {tid}\n"
              f"نام کاربری: {username}\n"
              f"نتیجه: {'موفق' if ok else 'ناموفق'}\n"
              f"پیام: {msg}")
    log_action(m.from_user.id, m.from_user.username or "", username, ok, msg)
    await notify_admins(report)
    await state.finish()

# ---- اعتبار مشتری (ادمین و سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "🔎 اعتبار مشتری")
async def admin_getcredits(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_admin(m.from_user.id):
        return await m.reply("دسترسی کافی نداری.")
    await AdminGetCreditsFlow.ask_tid.set()
    await m.reply("آیدی عددی مشتری را بفرست:", reply_markup=cancel_kb())

@dp.message_handler(state=AdminGetCreditsFlow.ask_tid)
async def admin_getcredits_tid(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    if not (m.text or "").isdigit():
        return await m.reply("یک آیدی عددی معتبر بفرست.", reply_markup=cancel_kb())
    tid = int(m.text.strip())
    cr = get_credits(tid)
    await m.reply(f"اعتبار باقی‌ماندهٔ مشتری {tid}: {cr}", reply_markup=admin_kb(is_superadmin(m.from_user.id)))
    await state.finish()

# ---- مدیریت ادمین‌ها (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "👑 مدیریت ادمین‌ها")
async def admins_manage(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.")
    await m.reply("مدیریت ادمین‌ها:", reply_markup=admins_manage_kb())

@dp.message_handler(lambda msg: msg.text == "➕ افزودن ادمین")
async def admins_add_btn(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.")
    await AdminAddAdminFlow.ask_tid.set()
    await m.reply("آیدی عددی تلگرام ادمین جدید را بفرست:", reply_markup=cancel_kb())

@dp.message_handler(state=AdminAddAdminFlow.ask_tid)
async def admins_add_tid(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    if not (m.text or "").isdigit():
        return await m.reply("یک آیدی عددی معتبر بفرست.", reply_markup=cancel_kb())
    tid = int(m.text.strip())
    add_admin(tid)
    await m.reply(f"ادمین {tid} افزوده شد.", reply_markup=admins_manage_kb())
    await state.finish()

@dp.message_handler(lambda msg: msg.text == "➖ حذف ادمین")
async def admins_rm_btn(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.")
    await AdminRmAdminFlow.ask_tid.set()
    await m.reply("آیدی عددی تلگرام ادمینی که باید حذف شود را بفرست:", reply_markup=cancel_kb())

@dp.message_handler(state=AdminRmAdminFlow.ask_tid)
async def admins_rm_tid(m: types.Message, state: FSMContext):
    sync_admin_profile_if_needed(m.from_user)
    if (m.text or "") == "⬅️ انصراف":
        return
    if not (m.text or "").isdigit():
        return await m.reply("یک آیدی عددی معتبر بفرست.", reply_markup=cancel_kb())
    tid = int(m.text.strip())
    remove_admin(tid)
    await m.reply(f"ادمین {tid} حذف شد.", reply_markup=admins_manage_kb())
    await state.finish()

# ---- لیست ادمین‌ها (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "👥 لیست ادمین‌ها")
async def admins_list(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.")
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT telegram_id, COALESCE(username,''), COALESCE(full_name,'') FROM admins ORDER BY telegram_id").fetchall()
    if not rows:
        return await m.reply("هیچ ادمینی در سیستم ثبت نشده است.")
    lines = []
    for tid, uname, fname in rows:
        tag = f"@{uname}" if uname else "(بدون یوزرنیم)"
        name = f" - {fname}" if fname else ""
        lines.append(f"• {tid}  {tag}{name}")
    await m.reply("لیست ادمین‌ها:\n" + "\n".join(lines))

# ---- لیست مشتری‌ها (فقط سوپرادمین)
@dp.message_handler(lambda msg: msg.text == "👥 لیست مشتری‌ها")
async def customers_list(m: types.Message):
    sync_admin_profile_if_needed(m.from_user)
    if not is_superadmin(m.from_user.id):
        return await m.reply("فقط سوپرادمین.")
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT telegram_id, COALESCE(username,''), COALESCE(full_name,''), credits FROM customers ORDER BY telegram_id"
        ).fetchall()
    if not rows:
        return await m.reply("هیچ مشتری‌ای در سیستم ثبت نشده است.")
    lines = []
    for tid, uname, fname, credits in rows:
        if not uname or not fname:
            try:
                chat = await bot.get_chat(tid)
                uname = uname or (chat.username or "")
                fname = fname or (chat.full_name or "")
                ensure_customer(tid, uname or "", fname or "")
            except Exception:
                pass
        tag = f"@{uname}" if uname else "(بدون یوزرنیم)"
        name = f" - {fname}" if fname else ""
        lines.append(f"• {tid}  {tag}{name} - اعتبار: {credits}")
    await m.reply("لیست مشتری‌ها:\n" + "\n".join(lines))

# ---------------- اجرا ----------------
if __name__ == "__main__":
    init_db()
    if not BOT_STATUS:
        print("Bot status is off. Exiting.")
    else:
        try:
            executor.start_polling(dp, skip_updates=True)
        finally:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(svc.close())
