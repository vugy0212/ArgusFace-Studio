"""
ArgusFace Studio - 24/7 Telegram Bot
Runs in Docker, communicates with the host machine AI engine via REST API.
Supports:
  - Admin Panel with user management (Add / Remove Telegram users)
  - PIN protection & Session locking (with anti-bruteforce protection)
  - 1:N database search (direct photo upload or menu)
  - 1:1 biometrical face comparison (2 photos)
  - Person enrollment (photo + name + role + notes) directly from mobile
  - Live system status & stats
"""

import base64
import io
import os
import sys
import time
import logging
import requests
import re
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    constants
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Load configuration from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ARGUSFACE_API_URL = os.getenv("ARGUSFACE_API_URL", "http://host.docker.internal:5055").rstrip("/")
ARGUSFACE_API_KEY = os.getenv("ARGUSFACE_API_KEY", "").strip()
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "").strip()
WEBAPP_URL = (os.getenv("ARGUSFACE_WEBAPP_URL") or os.getenv("WEBAPP_URL") or "http://192.168.100.2:5055/webapp").rstrip("/")

# Local in-memory caches
_cached_bot_config = None
_cached_bot_config_time = 0
CACHE_TTL = 10  # refresh config from API every 10 seconds

# State dictionaries for PIN security & access requests
authenticated_sessions = {}   # chat_id -> last_activity_timestamp (float)
failed_attempts = {}          # chat_id -> {"count": int, "blocked_until": float}
pending_access_requests = {}  # chat_id -> {"name": str, "username": str, "time": str}

# Parse env allowed chat IDs as fallback
ENV_ALLOWED_CHAT_IDS = set()
if ALLOWED_CHAT_IDS_RAW:
    for cid in ALLOWED_CHAT_IDS_RAW.replace(";", ",").split(","):
        cid = cid.strip()
        if cid:
            try:
                ENV_ALLOWED_CHAT_IDS.add(int(cid))
            except ValueError:
                pass

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ArgusFaceBot")

# Conversation states for 2-image comparison
WAITING_PHOTO_1, WAITING_PHOTO_2 = range(2)

# Conversation states for person enrollment
ENROLL_NAME, ENROLL_ROLE, ENROLL_NOTES, ENROLL_PHOTOS = range(2, 6)

# Conversation states for Admin Panel
ADMIN_ADD_ID, ADMIN_ADD_NAME, ADMIN_ADD_ROLE, ADMIN_REMOVE_ID, ADMIN_PIN_NEW = range(6, 11)

# Keyboards
CANCEL_KEYBOARD = [["❌ Odustani"]]
CANCEL_MARKUP = ReplyKeyboardMarkup(CANCEL_KEYBOARD, resize_keyboard=True)

ROLE_KEYBOARD = [
    ["👤 Standard", "⭐ VIP"],
    ["🚨 Crna lista", "❌ Odustani"]
]
ROLE_MARKUP = ReplyKeyboardMarkup(ROLE_KEYBOARD, resize_keyboard=True)

NOTES_KEYBOARD = [
    ["➡️ Preskoči bilješke"],
    ["❌ Odustani"]
]
NOTES_MARKUP = ReplyKeyboardMarkup(NOTES_KEYBOARD, resize_keyboard=True)

ADMIN_MENU_KEYBOARD = [
    ["🗂️ Baza registriranih osoba", "👥 Popis bot korisnika"],
    ["➕ Dodaj korisnika", "❌ Ukloni korisnika"],
    ["🔑 Promijeni PIN", "🔙 Povratak u glavni meni"]
]
ADMIN_MENU_MARKUP = ReplyKeyboardMarkup(ADMIN_MENU_KEYBOARD, resize_keyboard=True)

ADMIN_ROLE_CHOICE = [
    ["👤 Običan korisnik", "👑 Administrator"],
    ["❌ Odustani"]
]
ADMIN_ROLE_MARKUP = ReplyKeyboardMarkup(ADMIN_ROLE_CHOICE, resize_keyboard=True)

def get_api_headers() -> dict:
    headers = {}
    if ARGUSFACE_API_KEY:
        headers["X-API-Key"] = ARGUSFACE_API_KEY
    return headers

def get_remote_bot_config(force: bool = False) -> dict:
    """Fetches user permissions and PIN config from host ArgusFace API."""
    global _cached_bot_config, _cached_bot_config_time
    now = time.time()
    if not force and _cached_bot_config and (now - _cached_bot_config_time) < CACHE_TTL:
        return _cached_bot_config

    url = f"{ARGUSFACE_API_URL}/api/v1/bot/users"
    try:
        resp = requests.get(url, headers=get_api_headers(), timeout=5)
        if resp.status_code == 200:
            _cached_bot_config = resp.json()
            _cached_bot_config_time = now
            return _cached_bot_config
    except Exception as e:
        logger.warning(f"Greška pri dohvatu bot konfiguracije: {e}")

    # Fallback to local default if API is momentarily unreachable
    fallback = {
        "pin": os.getenv("BOT_ACCESS_PIN", "121977"),
        "session_timeout_minutes": int(os.getenv("SESSION_TIMEOUT_MINUTES", "30")),
        "admin_chat_ids": [],
        "allowed_users": []
    }
    return _cached_bot_config or fallback

def is_authorized(user_id: int) -> bool:
    """Verifies whether user is authorized in database or env whitelist."""
    if user_id in ENV_ALLOWED_CHAT_IDS:
        return True

    cfg = get_remote_bot_config()
    allowed_list = cfg.get("allowed_users", [])

    # If no users have been registered yet, allow access so admin can initialize
    if not allowed_list:
        return True

    allowed_ids = {u.get("chat_id") for u in allowed_list}
    return user_id in allowed_ids

def is_admin(user_id: int) -> bool:
    """Checks if user has admin privileges."""
    cfg = get_remote_bot_config()
    admin_ids = set(cfg.get("admin_chat_ids", []))
    if user_id in admin_ids:
        return True

    # Also check allowed_users role
    for u in cfg.get("allowed_users", []):
        if u.get("chat_id") == user_id and u.get("role") == "admin":
            return True
    return False

def get_main_menu(user_id: int = 0):
    """Returns ReplyKeyboardRemove to completely remove the duplicate bottom keyboard."""
    return ReplyKeyboardRemove()

def get_main_inline_menu(user_id: int) -> InlineKeyboardMarkup:
    """Generates modern inline card buttons."""
    buttons = [
        [
            InlineKeyboardButton("🔍 Skeniraj lice (1:N)", callback_data="nav_search"),
            InlineKeyboardButton("⚖️ Usporedi 2 slike", callback_data="nav_compare")
        ],
        [
            InlineKeyboardButton("➕ Registriraj osobu", callback_data="nav_enroll"),
            InlineKeyboardButton("🗂️ Baza osoba", callback_data="nav_search_persons")
        ],
        [
            InlineKeyboardButton("📊 Status sustava", callback_data="nav_status"),
            InlineKeyboardButton("📱 Mini Web App", callback_data="nav_webapp")
        ]
    ]
    if is_admin(user_id):
        buttons.append([
            InlineKeyboardButton("⚙️ Admin panel", callback_data="nav_admin"),
            InlineKeyboardButton("🔒 Zaključaj sesiju", callback_data="nav_lock")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("ℹ️ Pomoć", callback_data="nav_help"),
            InlineKeyboardButton("🔒 Zaključaj sesiju", callback_data="nav_lock")
        ])
    return InlineKeyboardMarkup(buttons)

def get_status_inline_menu() -> InlineKeyboardMarkup:
    """Generates inline buttons for status view."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Osvježi podatke", callback_data="nav_status_refresh"),
            InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
        ]
    ])

def get_admin_inline_menu() -> InlineKeyboardMarkup:
    """Generates inline buttons for admin panel."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗂️ Pretraži bazu osoba", callback_data="admin_search_persons"),
            InlineKeyboardButton("👥 Popis korisnika", callback_data="admin_list_users")
        ],
        [
            InlineKeyboardButton("➕ Dodaj korisnika", callback_data="admin_add_info"),
            InlineKeyboardButton("❌ Ukloni korisnika", callback_data="admin_del_info")
        ],
        [
            InlineKeyboardButton("🔑 PIN i sigurnost", callback_data="admin_pin_info"),
            InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
        ]
    ])

def get_back_to_admin_menu() -> InlineKeyboardMarkup:
    """Back button for admin sub-screens."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Natrag u admin panel", callback_data="nav_admin")
        ]
    ])

def get_back_to_main_menu() -> InlineKeyboardMarkup:
    """Back button to return to main card."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
        ]
    ])

def format_welcome_text(user_first_name: str, chat_id: int) -> str:
    role_title = " (👑 Administrator)" if is_admin(chat_id) else ""
    return (
        f"🛡️ **ARGUSFACE BIOMETRIC STUDIO** 🛡️\n\n"
        f"Pozdrav, **{user_first_name}**{role_title}!\n\n"
        f"Sustav je povezan s lokalnim AI engineom za biometrijsko prepoznavanje i analizu lica.\n\n"
        f"🆔 Vaš Chat ID: `{chat_id}`\n\n"
        f"⚡ **Brzi vodič:**\n"
        f"• Pošaljite fotografiju u chat za **trenutnu provjeru lica**\n"
        f"• Ili odaberite operaciju s interaktivne kartice u nastavku:"
    )

def check_authentication(chat_id: int) -> tuple[bool, str]:
    """Checks if session is authenticated with PIN and not expired or blocked."""
    cfg = get_remote_bot_config()
    pin = cfg.get("pin", "")
    timeout_min = cfg.get("session_timeout_minutes", 30)

    if not pin:
        return True, ""  # No PIN configured -> open

    # Check bruteforce lockout
    if chat_id in failed_attempts:
        blocked_until = failed_attempts[chat_id].get("blocked_until", 0)
        if time.time() < blocked_until:
            remaining = int(blocked_until - time.time())
            return False, f"⏳ **Privremena blokada:** Previše netočnih unosa PIN-a.\nPokušajte ponovno za `{remaining} sekundi`."

    # Check active session
    if chat_id not in authenticated_sessions:
        return False, "🔒 **Sustav je zaključan.**\n\nMolimo unesite **sigurnosni PIN** za pristup biometrijskom sustavu:"

    # Check session timeout
    if timeout_min > 0:
        last_active = authenticated_sessions[chat_id]
        if (time.time() - last_active) > (timeout_min * 60):
            del authenticated_sessions[chat_id]
            return False, "⏳ **Sesija je istekla zbog neaktivnosti.**\n\nMolimo ponovno unesite **sigurnosni PIN** za nastavak rada:"

    authenticated_sessions[chat_id] = time.time()
    return True, ""

# =========================================================================
# BOT COMMANDS & GENERAL HANDLERS
# =========================================================================

async def send_unauthorized_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends interactive unauthorized notification with a 1-tap Request Access button."""
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("📩 Zatraži pristup od administratora", callback_data=f"req_access:{chat_id}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    msg_text = (
        f"⛔ **Pristup nije odobren.**\n\n"
        f"🆔 Vaš Telegram Chat ID je: `{chat_id}`\n\n"
        f"Ovaj bot je zaštićen biometrijski sustav namijenjen isključivo ovlaštenom osoblju.\n\n"
        f"👉 Kliknite na gumb ispod kako biste poslali automatski zahtjev administratoru za odobrenje pristupa:"
    )
    if update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode=constants.ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg_text, reply_markup=markup, parse_mode=constants.ParseMode.MARKDOWN)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets user, verifies authorization and PIN, and reveals main menu."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(
            f"👋 Pozdrav, **{user.first_name}**!\n\n"
            f"🤖 **ArgusFace AI Asistent** je zaštićen sigurnosnim PIN-om.\n\n"
            f"{lock_msg}",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("✨", reply_markup=ReplyKeyboardRemove())
    welcome_text = format_welcome_text(user.first_name, chat_id)
    await update.message.reply_text(welcome_text, reply_markup=get_main_inline_menu(chat_id), parse_mode=constants.ParseMode.MARKDOWN)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main interactive card menu."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return
    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return
    user = update.effective_user
    await update.message.reply_text("✨", reply_markup=ReplyKeyboardRemove())
    welcome_text = format_welcome_text(user.first_name, chat_id)
    await update.message.reply_text(welcome_text, reply_markup=get_main_inline_menu(chat_id), parse_mode=constants.ParseMode.MARKDOWN)

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Locks user session immediately."""
    chat_id = update.effective_chat.id
    authenticated_sessions.pop(chat_id, None)
    await update.message.reply_text(
        "🔒 **Sustav je uspješno zaključan.**\n\nZa ponovni pristup unesite svoj sigurnosni PIN:",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays user guidance."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    help_text = (
        "📖 **ArgusFace AI Asistent - Upute za rad**\n\n"
        "1️⃣ **Pretraga u bazi (1:N):**\n"
        "Pošaljite fotografiju jedne ili više osoba. Sustav detektira lica, "
        "uspoređuje ih s bazom na računalu i javlja ime, status (Crna lista / VIP / Djelatnik), "
        "postotak podudaranja, procjenu dobi i autentičnost lica (anti-spoofing).\n\n"
        "2️⃣ **Usporedba 2 slike (1:1):**\n"
        "Kliknite '⚖️ Usporedi 2 slike' i pošaljite dvije uzastopne fotografije. "
        "AI model izvlači biometrijske točke i daje postotak sličnosti i presudu.\n\n"
        "3️⃣ **Dodavanje nove osobe u bazu (Enrollment):**\n"
        "Kliknite '➕ Dodaj novu osobu' i pratite jednostavna 3 koraka:\n"
        "• Pošaljite fotografiju lica\n"
        "• Upišite ime i prezime\n"
        "• Odaberite status (Standard / VIP / Crna lista) i unesite bilješke.\n\n"
        "4️⃣ **Administracija i sigurnost:**\n"
        "• Administratori kroz '⚙️ Admin panel' mogu dodavati ili uklanjati korisnike te mijenjati PIN.\n"
        "• Gumb '🔒 Zaključaj' omogućuje trenutnu odjavu."
    )
    await update.message.reply_text(help_text, reply_markup=get_back_to_main_menu(), parse_mode=constants.ParseMode.MARKDOWN)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and displays host system status from the API."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    url = f"{ARGUSFACE_API_URL}/api/v1/status"
    cfg = get_remote_bot_config()
    try:
        resp = requests.get(url, headers=get_api_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            spoof_txt = "🟢 Uključena" if data.get("anti_spoofing") else "⚪ Isključena"
            faiss_txt = "🟢 FAISS Ubrzan" if data.get("has_faiss") else "🟡 NumPy BLAS"
            status_text = (
                "📊 **Status ArgusFace Sustava na Računalu:**\n\n"
                f"🖥️ **Stanje AI Enginea:** `✅ Online`\n"
                f"👥 **Broj osoba u bazi:** `{data.get('total_persons', 0)}`\n"
                f"📸 **Broj spremljenih uzoraka lica:** `{data.get('total_samples', 0)}`\n"
                f"⚡ **Vektorski indeks:** `{data.get('index_backend', 'N/A')}` ({faiss_txt})\n"
                f"🛡️ **Anti-Spoofing (Liveness):** {spoof_txt}\n"
                f"🔐 **PIN Zaštita bota:** `🟢 Aktivna (Timeout: {cfg.get('session_timeout_minutes', 30)} min)`\n"
                f"👥 **Ovlaštenih korisnika bota:** `{len(cfg.get('allowed_users', []))}`\n"
                f"🌐 **Poveznica:** `{ARGUSFACE_API_URL}`"
            )
        else:
            status_text = f"⚠️ API na računalu je vratio grešku: HTTP {resp.status_code} ({resp.text})"
    except requests.exceptions.ConnectionError:
        status_text = (
            "⚠️ **Računalo / ArgusFace API nije dostupan.**\n\n"
            "Provjerite je li uključeno računalo i je li pokrenut lokalni API poslužitelj u postavkama."
        )
    except Exception as e:
        status_text = f"❌ Greška pri provjeri statusa: {str(e)}"

    await update.message.reply_text(status_text, reply_markup=get_status_inline_menu(), parse_mode=constants.ParseMode.MARKDOWN)

def get_effective_webapp_url() -> str:
    """Reads latest Cloudflare tunnel URL if available, else falls back to configured URL."""
    for p in ["/data/tunnel.log", "docker/telegram_bot/tunnel_data/tunnel.log", "./tunnel_data/tunnel.log", "tunnel.log"]:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                if matches:
                    base = matches[-1].rstrip('/')
                    return f"{base}/webapp/"
            except Exception:
                pass
    return WEBAPP_URL

async def safe_edit_or_reply(query, text, reply_markup=None, parse_mode=constants.ParseMode.MARKDOWN):
    """
    Sigurno uređuje tekst poruke ako je tekstualna, ili šalje novu poruku ako je poruka slika/media
    (sprječava grešku 'There is no text in the message to edit' Telegram Bot API-ja).
    """
    msg = query.message if query else None
    is_media = bool(msg and (msg.photo or msg.video or msg.document or msg.caption))
    if not is_media and query:
        try:
            return await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.info(f"safe_edit_or_reply fallback na slanje poruke: {e}")

    if msg:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            return await msg.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            return await msg.reply_text(text, reply_markup=reply_markup, parse_mode=None)

async def webapp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prikazuje poveznicu i upute za Mini Web App."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    cfg = get_remote_bot_config()
    current_pin = cfg.get("pin", "121977")
    effective_url = get_effective_webapp_url()
    sep = "&" if "?" in effective_url else "?"
    authed_url = f"{effective_url}{sep}auth=1&chat_id={chat_id}"

    keyboard = []
    if effective_url.startswith("https://"):
        keyboard.append([
            InlineKeyboardButton("🚀 Pokreni unutar Telegrama", web_app=WebAppInfo(url=authed_url))
        ])
    keyboard.append([
        InlineKeyboardButton("🌐 Otvori u pregledniku", url=authed_url)
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
    ])
    markup = InlineKeyboardMarkup(keyboard)

    text = (
        "📱 **ARGUSFACE MINI WEB APP** 📱\n\n"
        "Mobilno prilagođeno web sučelje (sve u jednom zaslonu):\n\n"
        "• 🔍 **Foto skeniranje (1:N)**: Odabir ili slikanje lica za pretragu u bazi\n"
        "• ⚖️ **Usporedba 2 lica (1:1)**: Biometrijska komparacija dviju fotografija\n"
        "• ➕ **Registracija lica**: Brzo dodavanje novih osoba u bazu\n"
        "• 📊 **Status & Nadzor**: Pregled stanja motora i baze u stvarnom vremenu\n\n"
        f"🔗 **Poveznica:**\n`{authed_url}`\n\n"
        "🔓 *Pristup je automatski odobren (PIN je već unesen u botu).*"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit_or_reply(update.callback_query, text, reply_markup=markup, parse_mode=constants.ParseMode.MARKDOWN)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=constants.ParseMode.MARKDOWN)

# =========================================================================
# ADMIN PANEL LOGIC & WORKFLOWS
# =========================================================================

async def admin_panel_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens the Admin Panel menu (admin only)."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id) or not is_admin(chat_id):
        await update.message.reply_text("⛔ Nemate administratorske ovlasti.", reply_markup=get_main_menu(chat_id))
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    cfg = get_remote_bot_config(force=True)
    total_u = len(cfg.get("allowed_users", []))

    await update.message.reply_text(
        "⚙️ **ArgusFace - Administracijski Panel**\n\n"
        f"• Ukupno ovlaštenih korisnika: **{total_u}**\n"
        f"• Trenutni PIN: `{cfg.get('pin', 'N/A')}`\n"
        f"• Automatsko zaključavanje: `{cfg.get('session_timeout_minutes', 30)} min`\n\n"
        "Odaberite željenu administratorsku radnju:",
        reply_markup=get_admin_inline_menu(),
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all authorized users."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id) or not is_admin(chat_id):
        return

    cfg = get_remote_bot_config(force=True)
    users = cfg.get("allowed_users", [])

    if not users:
        await update.message.reply_text(
            "ℹ️ Trenutno **nema registriranih korisnika** (otvoren početni pristup).",
            reply_markup=get_back_to_admin_menu()
        )
        return

    lines = ["👥 **Popis ovlaštenih Telegram korisnika:**\n"]
    for idx, u in enumerate(users, start=1):
        role_icon = "👑 [Admin]" if u.get("role") == "admin" else "👤 [Korisnik]"
        name = u.get("name", "Bez imena")
        uid = u.get("chat_id")
        date = u.get("added_at", "-")
        lines.append(f"{idx}. {role_icon} **{name}**\n   🆔 Chat ID: `{uid}`\n   📅 Dodano: `{date}`")

    out_msg = "\n\n".join(lines)
    await update.message.reply_text(out_msg, reply_markup=get_back_to_admin_menu(), parse_mode=constants.ParseMode.MARKDOWN)

async def admin_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns to the main menu from the admin panel."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    welcome_text = format_welcome_text(user.first_name, chat_id)
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_inline_menu(chat_id),
        parse_mode=constants.ParseMode.MARKDOWN
    )

# ----------------- Add User Conversation -----------------

async def admin_add_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts add user workflow."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id) or not is_admin(chat_id):
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "➕ **Dodavanje novog Telegram korisnika**\n\n"
        "**Korak 1/3:** Molimo upišite **Telegram Chat ID** korisnika (npr. `123456789`).\n\n"
        "💡 *Savjet: Taj broj korisnik može saznati tako da pokrene bota i pošalje /start.*",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ADMIN_ADD_ID

async def admin_add_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    try:
        new_chat_id = int(text)
    except ValueError:
        await update.message.reply_text("⚠️ Chat ID mora biti cijeli broj (npr. `123456789`). Pokušajte ponovno:")
        return ADMIN_ADD_ID

    context.user_data["new_user_id"] = new_chat_id
    await update.message.reply_text(
        f"✅ Chat ID `{new_chat_id}` zaprimljen!\n\n"
        f"**Korak 2/3:** Upišite **ime i prezime ili opis** za ovog korisnika (npr. *Kolega Marko - Smjena A*):",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ADMIN_ADD_NAME

async def admin_add_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name or len(name) < 2:
        await update.message.reply_text("⚠️ Molimo upišite valjano ime (najmanje 2 znaka):")
        return ADMIN_ADD_NAME

    context.user_data["new_user_name"] = name
    await update.message.reply_text(
        f"**Korak 3/3:** Odaberite razinu ovlasti za korisnika **{name}**:\n\n"
        f"• 👤 **Običan korisnik** — Može pretraživati bazu i dodavati lica\n"
        f"• 👑 **Administrator** — Puni pristup uključujući Admin panel",
        reply_markup=ADMIN_ROLE_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ADMIN_ADD_ROLE

async def admin_add_user_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    role = "admin" if "Admin" in text or "admin" in text.lower() else "user"

    new_chat_id = context.user_data.get("new_user_id")
    name = context.user_data.get("new_user_name")

    url = f"{ARGUSFACE_API_URL}/api/v1/bot/users/add"
    data = {
        "chat_id": new_chat_id,
        "name": name,
        "role": role
    }

    try:
        resp = requests.post(url, data=data, headers=get_api_headers(), timeout=10)
        if resp.status_code == 200:
            get_remote_bot_config(force=True)  # Invalidate cache
            role_label = "👑 Administrator" if role == "admin" else "👤 Običan korisnik"
            out_msg = (
                f"🎉 **Korisnik je uspješno dodan!**\n\n"
                f"👤 **Ime:** `{name}`\n"
                f"🆔 **Chat ID:** `{new_chat_id}`\n"
                f"🏷️ **Uloga:** {role_label}\n\n"
                f"✨ Korisnik sada može otvoriti bota, unijeti PIN i započeti s radom."
            )
        else:
            out_msg = f"⚠️ Greška API-ja: HTTP {resp.status_code} ({resp.text})"
    except Exception as e:
        out_msg = f"❌ Greška pri dodavanju korisnika: {str(e)}"

    context.user_data.clear()
    await update.message.reply_text(out_msg, reply_markup=ADMIN_MENU_MARKUP, parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

# ----------------- Remove User Conversation -----------------

async def admin_remove_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts remove user workflow."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id) or not is_admin(chat_id):
        return ConversationHandler.END

    cfg = get_remote_bot_config(force=True)
    users = cfg.get("allowed_users", [])

    if not users:
        await update.message.reply_text("ℹ️ Popis korisnika je prazan.", reply_markup=ADMIN_MENU_MARKUP)
        return ConversationHandler.END

    # Generate buttons for each user
    buttons = []
    for u in users:
        buttons.append([f"🗑️ {u.get('name', 'Korisnik')} ({u.get('chat_id')})"])
    buttons.append(["❌ Odustani"])
    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    await update.message.reply_text(
        "❌ **Uklanjanje korisnika**\n\n"
        "Odaberite korisnika s tipkovnice ili upišite njegov Chat ID za uklanjanje:",
        reply_markup=markup,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ADMIN_REMOVE_ID

async def admin_remove_user_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    target_id = None

    # Parse from button text or direct number
    if "(" in text and ")" in text:
        try:
            target_id = int(text.split("(")[-1].split(")")[0].strip())
        except ValueError:
            pass

    if target_id is None:
        try:
            target_id = int(text.replace("🗑️", "").strip())
        except ValueError:
            pass

    if target_id is None:
        await update.message.reply_text("⚠️ Neispravan odabir. Kliknite korisnika ili unesite valjani broj:")
        return ADMIN_REMOVE_ID

    url = f"{ARGUSFACE_API_URL}/api/v1/bot/users/remove"
    data = {"chat_id": target_id}
    try:
        resp = requests.post(url, data=data, headers=get_api_headers(), timeout=10)
        if resp.status_code == 200:
            get_remote_bot_config(force=True)
            # Also kick their session immediately
            authenticated_sessions.pop(target_id, None)
            out_msg = f"🗑️ **Korisnik s Chat ID `{target_id}` je uspješno uklonjen!** Njegov pristup botu je ukinut."
        else:
            out_msg = f"⚠️ Greška API-ja: HTTP {resp.status_code} ({resp.text})"
    except Exception as e:
        out_msg = f"❌ Greška pri uklanjanju korisnika: {str(e)}"

    await update.message.reply_text(out_msg, reply_markup=ADMIN_MENU_MARKUP, parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

# ----------------- Change PIN Conversation -----------------

async def admin_change_pin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id) or not is_admin(chat_id):
        return ConversationHandler.END

    await update.message.reply_text(
        "🔑 **Promjena sigurnosnog PIN-a bota**\n\n"
        "Upišite **novi sigurnosni PIN** (najmanje 4 znamenke/znaka):",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ADMIN_PIN_NEW

async def admin_change_pin_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_pin = (update.message.text or "").strip()
    if len(new_pin) < 4:
        await update.message.reply_text("⚠️ PIN mora imati najmanje 4 znaka. Upišite novi PIN:")
        return ADMIN_PIN_NEW

    url = f"{ARGUSFACE_API_URL}/api/v1/bot/pin"
    data = {"pin": new_pin}
    try:
        resp = requests.post(url, data=data, headers=get_api_headers(), timeout=10)
        if resp.status_code == 200:
            get_remote_bot_config(force=True)
            out_msg = f"✅ **Sigurnosni PIN je uspješno promijenjen!**\nNovi PIN je: `{new_pin}`"
        else:
            out_msg = f"⚠️ Greška API-ja: HTTP {resp.status_code} ({resp.text})"
    except Exception as e:
        out_msg = f"❌ Greška pri promjeni PIN-a: {str(e)}"

    await update.message.reply_text(out_msg, reply_markup=ADMIN_MENU_MARKUP, parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Radnja u Admin panelu je prekinuta.", reply_markup=ADMIN_MENU_MARKUP)
    return ConversationHandler.END

# =========================================================================
# TWO-IMAGE COMPARISON CONVERSATION FLOW (1:1)
# =========================================================================

async def compare_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates 2-photo comparison workflow."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return ConversationHandler.END

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        msg = update.effective_message
        if msg:
            await msg.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return ConversationHandler.END

    context.user_data.clear()

    if update.callback_query:
        await update.callback_query.answer()

    msg = update.effective_message
    await msg.reply_text(
        "⚖️ **Biometrijska komparacija dviju fotografija (1:1)**\n\n"
        "📸 **Korak 1/2:** Molimo pošaljite **prvu fotografiju** (referentno lice).\n"
        "*(ili kliknite '❌ Odustani' za povratak)*",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return WAITING_PHOTO_1

async def compare_photo_1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives 1st photo and prompts for 2nd photo."""
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("⚠️ Molimo pošaljite fotografiju ili kliknite '❌ Odustani'.")
        return WAITING_PHOTO_1

    photo = photos[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()

    context.user_data["photo_1_bytes"] = bytes(photo_bytes)

    await update.message.reply_text(
        "✅ **Prva fotografija je zaprimljena!**\n\n"
        "📸 **Korak 2/2:** Sada pošaljite **drugu fotografiju** za usporedbu.",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return WAITING_PHOTO_2

async def compare_photo_2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives 2nd photo, triggers host comparison and outputs detailed result."""
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("⚠️ Molimo pošaljite fotografiju ili kliknite '❌ Odustani'.")
        return WAITING_PHOTO_2

    photo = photos[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_2_bytes = await file.download_as_bytearray()

    photo_1_bytes = context.user_data.get("photo_1_bytes")
    if not photo_1_bytes:
        await update.message.reply_text("❌ Došlo je do greške u sesiji. Pokušajte ponovno.", reply_markup=get_main_menu(update.effective_chat.id))
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    # Call ArgusFace API
    url = f"{ARGUSFACE_API_URL}/api/v1/compare"
    files = {
        "image1": ("photo1.jpg", photo_1_bytes, "image/jpeg"),
        "image2": ("photo2.jpg", bytes(photo_2_bytes), "image/jpeg")
    }
    data = {"threshold": 0.50}

    try:
        resp = requests.post(url, files=files, data=data, headers=get_api_headers(), timeout=15)
        if resp.status_code == 200:
            res = resp.json()
            if not res.get("success"):
                out_msg = f"⚠️ **Analiza nije uspjela:** {res.get('error', 'Nepoznata greška')}"
            else:
                same = res.get("same_person")
                sim_pct = res.get("similarity_pct", 0.0)
                conf = res.get("confidence", "Srednja")
                f1 = res.get("face1", {})
                f2 = res.get("face2", {})

                if same:
                    verdict_icon = "✅"
                    verdict_title = "**POTVRĐENO: Radi se o ISTOJ osobi!**"
                else:
                    verdict_icon = "❌"
                    verdict_title = "**ODBIJENO: Nije ista osoba.**"

                f1_desc = f"Slika 1: ~{f1.get('age', '-')} god ({f1.get('gender', '-')})"
                f2_desc = f"Slika 2: ~{f2.get('age', '-')} god ({f2.get('gender', '-')})"

                out_msg = (
                    f"{verdict_icon} {verdict_title}\n\n"
                    f"📊 **Biometrijska sličnost:** `{sim_pct}%` (Prag: `50%`)\n"
                    f"🎯 **Pouzdanost ocjene:** `{conf}`\n\n"
                    f"👤 **Procjena lica:**\n"
                    f"• {f1_desc}\n"
                    f"• {f2_desc}"
                )
        else:
            out_msg = f"⚠️ Greška API poslužitelja: HTTP {resp.status_code} ({resp.text})"
    except requests.exceptions.ConnectionError:
        out_msg = (
            "⚠️ **Računalo / ArgusFace API nije dostupan.**\n"
            "Provjerite je li uključeno računalo i je li pokrenut lokalni API poslužitelj."
        )
    except Exception as e:
        out_msg = f"❌ Greška pri komparaciji: {str(e)}"

    chat_id = update.effective_chat.id
    context.user_data.clear()

    compare_nav_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚖️ Usporedi ponovno (1:1)", callback_data="nav_compare"),
            InlineKeyboardButton("🔍 Skeniraj lice u bazi", callback_data="nav_search")
        ],
        [
            InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
        ]
    ])

    # Visual biometric card (Option 1)
    card_b64 = None
    if 'res' in locals() and isinstance(res, dict):
        card_b64 = res.get("comparison_card_base64")

    if card_b64:
        try:
            img_bytes = base64.b64decode(card_b64)
            if len(out_msg) <= 1024:
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=out_msg,
                        reply_markup=compare_nav_markup,
                        parse_mode=constants.ParseMode.MARKDOWN
                    )
                except Exception:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=out_msg,
                        reply_markup=compare_nav_markup,
                        parse_mode=None
                    )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=io.BytesIO(img_bytes),
                    caption="⚖️ **ArgusFace Biometrijska Usporedba (1:1)**",
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                try:
                    await update.message.reply_text(out_msg, reply_markup=compare_nav_markup, parse_mode=constants.ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(out_msg, reply_markup=compare_nav_markup, parse_mode=None)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Greška pri slanju komparacijske kartice: {e}")

    try:
        await update.message.reply_text(out_msg, reply_markup=compare_nav_markup, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(out_msg, reply_markup=compare_nav_markup, parse_mode=None)
    return ConversationHandler.END

async def compare_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels comparison and returns to main menu."""
    chat_id = update.effective_chat.id
    context.user_data.clear()
    msg = update.effective_message
    if msg:
        await msg.reply_text("❌ **Biometrijska usporedba je prekinuta.**", reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        welcome_text = format_welcome_text(update.effective_user.first_name, chat_id)
        await msg.reply_text(welcome_text, reply_markup=get_main_inline_menu(chat_id), parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

# =========================================================================
# PERSON ENROLLMENT WORKFLOW (DODAVANJE OSOBE I DO 3 UZORKA LICA)
# =========================================================================

async def enroll_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates person enrollment workflow."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return ConversationHandler.END

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        msg = update.effective_message
        if msg:
            await msg.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["enroll_photos"] = []

    prefilled_name = None
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data or ""
        if data.startswith("nav_enroll_for:"):
            prefilled_name = data.split(":", 1)[1].strip()

    msg = update.effective_message

    if prefilled_name:
        context.user_data["enroll_name"] = prefilled_name
        url = f"{ARGUSFACE_API_URL}/api/v1/persons?limit=1&query={requests.utils.quote(prefilled_name)}"
        try:
            resp = requests.get(url, headers=get_api_headers(), timeout=5)
            if resp.status_code == 200:
                p_list = resp.json().get("persons", [])
                exact = [p for p in p_list if p.get("name", "").lower() == prefilled_name.lower()]
                if exact:
                    context.user_data["enroll_role"] = exact[0].get("role", "standard")
                    context.user_data["enroll_notes"] = exact[0].get("notes", "")
        except Exception:
            pass

        await msg.reply_text(
            f"📸 **Dodavanje novih fotografija za profil: `{prefilled_name}`**\n\n"
            "⭐ **Pošaljite 1 do 3 fotografije lica** (idealno različiti kutovi: frontalno, lijevi i desni profil).\n\n"
            "👉 Pošaljite **prvu fotografiju**:",
            reply_markup=CANCEL_MARKUP,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return ENROLL_PHOTOS

    await msg.reply_text(
        "➕ **Registracija osobe / Dodavanje lica u bazu**\n\n"
        "👤 **Korak 1/3:** Upišite **ime i prezime** osobe koju želite registrirati:\n"
        "*(Primjer: Ivan Horvat)*\n\n"
        "💡 *Možete upisati i ime već postojeće osobe u bazi kako biste joj dodali nove fotografije ili kutove lica.*",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ENROLL_NAME

async def enroll_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives person's name, checks if already in DB, and asks for role or proceeds directly to photos."""
    name_text = (update.message.text or "").strip()
    if name_text in ["❌ Odustani", "🔙 Glavni izbornik", "🔙 Povratak u glavni meni", "/cancel", "/menu"]:
        return await enroll_cancel(update, context)

    if not name_text or len(name_text) < 2:
        await update.message.reply_text("⚠️ Ime mora imati najmanje 2 slova. Molimo upišite ime i prezime:")
        return ENROLL_NAME

    context.user_data["enroll_name"] = name_text
    context.user_data["enroll_photos"] = []

    # Check if person already exists in the database
    url = f"{ARGUSFACE_API_URL}/api/v1/persons?limit=5&query={requests.utils.quote(name_text)}"
    try:
        resp = requests.get(url, headers=get_api_headers(), timeout=5)
        if resp.status_code == 200:
            persons = resp.json().get("persons", [])
            exact = [p for p in persons if p.get("name", "").strip().lower() == name_text.lower()]
            if exact:
                p = exact[0]
                context.user_data["existing_person_id"] = p["id"]
                context.user_data["enroll_role"] = p.get("role", "standard")
                context.user_data["enroll_notes"] = p.get("notes", "")
                await update.message.reply_text(
                    f"ℹ️ Osoba **{name_text}** već postoji u bazi (#{p['id']}, trenutno ima `{p.get('sample_count', 1)}` uzorak/ka lica).\n\n"
                    f"📸 **Dodavanje novih uzoraka lica (1 do 3 slike)**\n"
                    f"⭐ *Preporučujemo poslati do 3 slike (frontalno, blagi lijevi i desni profil) za maksimalnu točnost prepoznavanja.*\n\n"
                    f"👉 Pošaljite **prvu fotografiju**:",
                    reply_markup=CANCEL_MARKUP,
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                return ENROLL_PHOTOS
    except Exception as e:
        logger.warning(f"Greška pri provjeri postojećeg imena: {e}")

    await update.message.reply_text(
        f"🏷️ Odaberite **sigurnosnu ulogu / status** za osobu **{name_text}**:\n\n"
        f"• 👤 **Standard** — Zaposlenik, korisnik ili član\n"
        f"• ⭐ **VIP** — Poseban gost / prioritetni protokol\n"
        f"• 🚨 **Crna lista** — Nepoželjno lice / zabrana pristupa",
        reply_markup=ROLE_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ENROLL_ROLE

async def enroll_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives role choice and asks for optional notes."""
    text = (update.message.text or "").strip()
    if text in ["❌ Odustani", "🔙 Glavni izbornik", "🔙 Povratak u glavni meni", "/cancel", "/menu"]:
        return await enroll_cancel(update, context)

    if "VIP" in text or "vip" in text.lower():
        role = "vip"
    elif "Crna" in text or "crna" in text.lower() or "blacklist" in text.lower():
        role = "blacklist"
    else:
        role = "standard"

    context.user_data["enroll_role"] = role

    await update.message.reply_text(
        "📝 **Korak 2/3 (Opcionalno):** Upišite **dodatne bilješke** (npr. *Odjel prodaje*, *Voditelj*, *Razlog zabrane*...) "
        "ili jednostavno kliknite **'➡️ Preskoči bilješke'**:",
        reply_markup=NOTES_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ENROLL_NOTES

async def enroll_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives notes and initiates multi-photo upload step."""
    text = (update.message.text or "").strip()
    if text in ["❌ Odustani", "🔙 Glavni izbornik", "🔙 Povratak u glavni meni", "/cancel", "/menu"]:
        return await enroll_cancel(update, context)

    if text in ["➡️ Preskoči bilješke", "/skip"]:
        notes = "Dodano putem Telegram bota"
    else:
        notes = f"{text} (Telegram bot)"

    context.user_data["enroll_notes"] = notes
    context.user_data["enroll_photos"] = []
    name = context.user_data.get("enroll_name", "Osoba")

    await update.message.reply_text(
        f"📸 **Korak 3/3: Fotografije lica za: {name} (1 do 3 slike)**\n\n"
        f"⭐ **Za maksimalnu biometrijsku točnost idealno je poslati 3 slike:**\n"
        f"  1️⃣ **Frontalno** (ravno u kameru)\n"
        f"  2️⃣ **Blagi lijevi profil** (poluprofil)\n"
        f"  3️⃣ **Blagi desni profil** (poluprofil)\n\n"
        f"👉 Pošaljite **prvu fotografiju**:",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ENROLL_PHOTOS

async def enroll_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collects up to 3 enrollment photos sequentially."""
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("⚠️ Molimo pošaljite fotografiju ili kliknite '❌ Odustani'.")
        return ENROLL_PHOTOS

    photo = photos[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()

    photos_list = context.user_data.setdefault("enroll_photos", [])
    photos_list.append(bytes(photo_bytes))
    count = len(photos_list)

    if count == 1:
        markup = ReplyKeyboardMarkup([
            ["✅ Završi i spremi (1 slika)"],
            ["❌ Odustani"]
        ], resize_keyboard=True)
        await update.message.reply_text(
            "✅ **Slika 1/3 zaprimljena!** 📸\n\n"
            "💡 *Preporuka:* Pošaljite još 1 ili 2 fotografije (npr. lijevi i desni profil lica) za maksimalnu točnost prepoznavanja.\n\n"
            "Ili kliknite **'✅ Završi i spremi (1 slika)'** ako je ova jedna slika dovoljna.",
            reply_markup=markup,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return ENROLL_PHOTOS
    elif count == 2:
        markup = ReplyKeyboardMarkup([
            ["✅ Završi i spremi (2 slike)"],
            ["❌ Odustani"]
        ], resize_keyboard=True)
        await update.message.reply_text(
            "✅ **Slika 2/3 zaprimljena!** 📸📸\n\n"
            "💡 Pošaljite još **treću fotografiju** (npr. drugi profil) ili kliknite **'✅ Završi i spremi (2 slike)'**.",
            reply_markup=markup,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return ENROLL_PHOTOS
    else:
        await update.message.reply_text(
            "✅ **Sve 3 fotografije su zaprimljene!** 📸📸📸\n\n"
            "⏳ *Obrađujem biometrijske vektore i spremam profil u bazu...*",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return await enroll_submit_workflow(update, context)

async def enroll_photo_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input while in photo upload mode (e.g. Finish button or Cancel)."""
    text = (update.message.text or "").strip()
    if text in ["❌ Odustani", "🔙 Glavni izbornik", "🔙 Povratak u glavni meni", "/cancel", "/menu"]:
        return await enroll_cancel(update, context)

    if "završi" in text.lower() or "spremi" in text.lower() or text == "/done":
        photos = context.user_data.get("enroll_photos", [])
        if not photos:
            await update.message.reply_text("⚠️ Još niste poslali niti jednu fotografiju. Molimo pošaljite sliku lica:")
            return ENROLL_PHOTOS
        await update.message.reply_text(
            f"⏳ *Obrađujem i spremam {len(photos)} zaprimljene fotografije...*",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return await enroll_submit_workflow(update, context)

    count = len(context.user_data.get("enroll_photos", []))
    btn_label = f"✅ Završi i spremi ({count} slike)" if count > 0 else "❌ Odustani"
    markup = ReplyKeyboardMarkup([[btn_label], ["❌ Odustani"]], resize_keyboard=True) if count > 0 else CANCEL_MARKUP
    await update.message.reply_text(
        "📸 Molimo pošaljite fotografiju lica ili kliknite gumb u nastavku:",
        reply_markup=markup
    )
    return ENROLL_PHOTOS

async def enroll_submit_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Submits collected photos and person details to the ArgusFace API on host PC."""
    photos = context.user_data.get("enroll_photos", [])
    name = context.user_data.get("enroll_name")
    role = context.user_data.get("enroll_role", "standard")
    notes = context.user_data.get("enroll_notes", "Dodano putem Telegram bota")

    chat_id = update.effective_chat.id
    if not photos or not name:
        context.user_data.clear()
        await update.message.reply_text("❌ Došlo je do greške u sesiji (nedostaje slika ili ime).", reply_markup=ReplyKeyboardRemove())
        welcome_text = format_welcome_text(update.effective_user.first_name, chat_id)
        await update.message.reply_text(welcome_text, reply_markup=get_main_inline_menu(chat_id), parse_mode=constants.ParseMode.MARKDOWN)
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    url = f"{ARGUSFACE_API_URL}/api/v1/enroll"
    files = [("images", (f"enroll_{i+1}.jpg", pb, "image/jpeg")) for i, pb in enumerate(photos)]
    data = {
        "name": name,
        "role": role,
        "notes": notes
    }

    try:
        resp = requests.post(url, files=files, data=data, headers=get_api_headers(), timeout=35)
        if resp.status_code == 200:
            res = resp.json()
            if not res.get("success"):
                out_msg = f"⚠️ **Registracija nije uspjela:** {res.get('error', 'Nepoznata greška')}"
            else:
                p_name = res.get("name")
                p_role = res.get("role")
                added_count = res.get("added_samples_count", len(photos))
                total_s = res.get("total_samples", added_count)
                age = res.get("age", "-")
                gender = res.get("gender", "-")
                is_real = res.get("is_real", True)
                liveness_conf = int(res.get("liveness_conf", 1.0) * 100)

                if p_role == "blacklist":
                    role_badge = "🚨 **CRNA LISTA (ZABRANA)**"
                elif p_role == "vip":
                    role_badge = "⭐ **VIP OSOBA**"
                else:
                    role_badge = "🟢 **STANDARDNI ČLAN / ZAPOSLENIK**"

                out_msg = (
                    "🎉 **Osoba je uspješno registrirana u bazi!**\n\n"
                    f"👤 **Ime i prezime:** `{p_name}`\n"
                    f"🏷️ **Status:** {role_badge}\n"
                    f"📝 **Bilješke:** `{notes}`\n"
                    f"📸 **Uspješno spremljeno slika:** `{added_count}` (Ukupno u profilu: `{total_s}`)\n"
                    f"📐 **Procjena lica:** `~{age} god, {gender}`\n"
                    f"🛡️ **Liveness provjera:** `{'Autentično lice' if is_real else '⚠️ Mogući ekran/slika'} ({liveness_conf}%)`\n\n"
                    f"✨ *Vektorski FAISS indeks na računalu je automatski ažuriran.* Lice je odmah spremno za prepoznavanje na kamerama i pri pretrazi!"
                )
        else:
            out_msg = f"⚠️ Greška API poslužitelja: HTTP {resp.status_code} ({resp.text})"
    except requests.exceptions.ConnectionError:
        out_msg = (
            "⚠️ **Računalo / ArgusFace API nije dostupan.**\n"
            "Provjerite je li uključeno računalo i je li pokrenut lokalni API poslužitelj."
        )
    except Exception as e:
        out_msg = f"❌ Greška pri registraciji: {str(e)}"

    context.user_data.clear()

    nav_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Registriraj novo lice", callback_data="nav_enroll"),
            InlineKeyboardButton("🔍 Provjeri lice u bazi", callback_data="nav_search")
        ],
        [
            InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
        ]
    ])

    await update.message.reply_text(out_msg, reply_markup=nav_markup, parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

async def enroll_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels enrollment and smoothly returns to main menu."""
    chat_id = update.effective_chat.id
    context.user_data.clear()
    msg = update.effective_message
    if msg:
        await msg.reply_text("❌ **Registracija lica je prekinuta.**", reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        welcome_text = format_welcome_text(update.effective_user.first_name, chat_id)
        await msg.reply_text(welcome_text, reply_markup=get_main_inline_menu(chat_id), parse_mode=constants.ParseMode.MARKDOWN)
    return ConversationHandler.END

# =========================================================================
# DIRECT PHOTO SEARCH IN DATABASE (1:N)
# =========================================================================

async def handle_direct_photo_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered when user sends a photo outside of a comparison conversation.
    Performs 1:N database search against ArgusFace database.
    """
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    photos = update.message.photo
    if not photos:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    photo = photos[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()

    url = f"{ARGUSFACE_API_URL}/api/v1/search"
    files = {"image": ("query.jpg", bytes(photo_bytes), "image/jpeg")}
    data = {"threshold": 0.50, "check_spoofing": True}

    try:
        resp = requests.post(url, files=files, data=data, headers=get_api_headers(), timeout=15)
        if resp.status_code == 200:
            res = resp.json()
            if not res.get("success"):
                out_msg = f"⚠️ **Greška pri pretrazi:** {res.get('error', 'Nepoznata greška')}"
            else:
                faces_count = res.get("faces_detected", 0)
                if faces_count == 0:
                    out_msg = "🔍 Na poslanoj fotografiji **nije pronađeno niti jedno lice**."
                else:
                    items = []
                    for idx, f in enumerate(res.get("results", [])):
                        matched = f.get("matched", False)
                        name = str(f.get("person_name", "Nepoznato")).replace("_", " ")
                        sim = f.get("similarity_pct", 0.0)
                        role = f.get("role", "standard")
                        raw_age = f.get("age")
                        age_str = f"~{raw_age} god" if (raw_age is not None and str(raw_age).lower() != "none") else "N/A"
                        gender_str = f.get("gender") or "N/A"
                        bio_desc = f"{age_str}, {gender_str}" if (age_str != "N/A" or gender_str != "N/A") else "N/A"
                        is_real = f.get("is_real", True)
                        live_conf = round(float(f.get("liveness_conf", 1.0)) * 100, 1)

                        if matched:
                            if role == "blacklist":
                                role_badge = "🚨 **CRNA LISTA (ZABRANA)**"
                            elif role == "vip":
                                role_badge = "⭐ **VIP OSOBA**"
                            else:
                                role_badge = "🟢 **PRIJAVLJENA OSOBA**"

                            item_txt = (
                                f"👤 **Lice #{idx+1}: {name}**\n"
                                f"🏷️ Status: {role_badge}\n"
                                f"📈 Podudaranje: `{sim}%` (Uzoraka u bazi: {f.get('sample_count', 1)})\n"
                                f"📐 Dob/Spol: `{bio_desc}`\n"
                                f"🛡️ Liveness provjera: `{'Autentično lice' if is_real else '⚠️ Mogući ekran/slika'} ({live_conf}%)`"
                            )
                        else:
                            item_txt = (
                                f"👤 **Lice #{idx+1}: Nepoznata osoba**\n"
                                f"❌ Nema poklapanja u bazi (Maks. sličnost: `{sim}%`)\n"
                                f"📐 Dob/Spol: `{bio_desc}`"
                            )
                        items.append(item_txt)

                    header = f"🔍 **Rezultati biometrijske pretrage (Pronađeno lica: {faces_count})**\n\n"
                    out_msg = header + "\n\n────────────────\n\n".join(items)
        else:
            out_msg = f"⚠️ Greška API poslužitelja: HTTP {resp.status_code} ({resp.text})"
    except requests.exceptions.ConnectionError:
        out_msg = (
            "⚠️ **Računalo / ArgusFace API nije dostupan.**\n\n"
            "Provjerite je li uključeno računalo i je li pokrenut lokalni API poslužitelj u ArgusFace postavkama."
        )
    except Exception as e:
        out_msg = f"❌ Greška pri pretrazi baze: {str(e)}"

    # Smart inline navigation based on search results
    matched_person = None
    if 'res' in locals() and isinstance(res, dict):
        for f in res.get("results", []):
            if f.get("matched") and f.get("person_name"):
                matched_person = str(f.get("person_name")).replace("_", " ")
                break

    if matched_person:
        search_nav_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"📸 Dodaj slike ({matched_person[:14]})", callback_data=f"nav_enroll_for:{matched_person}"),
                InlineKeyboardButton("🔍 Skeniraj ponovno", callback_data="nav_search")
            ],
            [
                InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
            ]
        ])
    else:
        search_nav_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Registriraj ovo lice", callback_data="nav_enroll"),
                InlineKeyboardButton("🔍 Skeniraj ponovno", callback_data="nav_search")
            ],
            [
                InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
            ]
        ])

    # Visual biometric card (Option 1)
    card_b64 = None
    if 'res' in locals() and isinstance(res, dict):
        card_b64 = res.get("verification_card_base64") or res.get("annotated_image_base64")

    if card_b64:
        try:
            img_bytes = base64.b64decode(card_b64)
            if len(out_msg) <= 1024:
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=out_msg,
                        reply_markup=search_nav_markup,
                        parse_mode=constants.ParseMode.MARKDOWN
                    )
                except Exception:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=out_msg,
                        reply_markup=search_nav_markup,
                        parse_mode=None
                    )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=io.BytesIO(img_bytes),
                    caption="🔍 **ArgusFace Biometrijski Rezultat**",
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                try:
                    await update.message.reply_text(out_msg, reply_markup=search_nav_markup, parse_mode=constants.ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(out_msg, reply_markup=search_nav_markup, parse_mode=None)
            return
        except Exception as e:
            logger.error(f"Greška pri slanju biometrijske kartice: {e}")

    try:
        await update.message.reply_text(out_msg, reply_markup=search_nav_markup, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(out_msg, reply_markup=search_nav_markup, parse_mode=None)

async def search_button_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds when user clicks the '🔍 Provjeri u bazi' button."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    await update.message.reply_text(
        "📸 **Pretraga u bazi lica:**\n\n"
        "Pošaljite fotografiju lica koje želite provjeriti u bazi podataka ArgusFace sustava.",
        reply_markup=get_back_to_main_menu(),
        parse_mode=constants.ParseMode.MARKDOWN
    )

# ----------------- Person Search (Text / Name query) -----------------

async def perform_person_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str):
    """Searches the registered persons database by name or notes and displays results with thumbnails."""
    chat_id = update.effective_chat.id
    query_clean = (query_text or "").strip()

    api_query = "" if query_clean.lower() in ["sve", "all", "*"] else query_clean
    url = f"{ARGUSFACE_API_URL}/api/v1/persons?limit=10"
    if api_query:
        url += f"&query={requests.utils.quote(api_query)}"

    try:
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", 0)
            persons = data.get("persons", [])

            if total == 0:
                msg = (
                    f"❌ **Osoba se NE nalazi u bazi podataka.**\n\n"
                    f"Nije pronađen niti jedan zapis za pojam: `{query_clean}`\n\n"
                    f"💡 Možete registrirati ovu osobu putem gumba u nastavku:"
                )
                search_not_found_markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(f"➕ Registriraj '{query_clean[:14]}'", callback_data=f"nav_enroll_for:{query_clean}"),
                        InlineKeyboardButton("🔍 Pretraži ponovno", callback_data="nav_search_persons")
                    ],
                    [
                        InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
                    ]
                ])
                try:
                    await update.message.reply_text(msg, reply_markup=search_not_found_markup, parse_mode=constants.ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(msg, reply_markup=search_not_found_markup, parse_mode=None)
                return

            # Single match with thumbnail
            if total == 1 and persons[0].get("thumbnail_base64"):
                p = persons[0]
                p_name = p.get("name", "Osoba")
                role_label = "STANDARD"
                if p.get("role") == "blacklist":
                    role_label = "🚨 CRNA LISTA"
                elif p.get("role") == "vip":
                    role_label = "⭐ VIP"

                caption = (
                    f"✅ **Osoba je pronađena u bazi podataka!**\n\n"
                    f"👤 **Ime:** `{p['name']}`\n"
                    f"🆔 **ID u bazi:** `#{p['id']}`\n"
                    f"🏷️ **Status/Uloga:** `{role_label}`\n"
                    f"📸 **Uzoraka lica:** `{p.get('sample_count', 1)}`\n"
                )
                if p.get("notes"):
                    caption += f"📝 **Bilješke:** `{p['notes']}`\n"
                if p.get("created_at"):
                    caption += f"📅 **Registrirano:** `{p['created_at'][:10]}`\n"

                single_match_markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("📸 Dodaj slike (1-3)", callback_data=f"nav_enroll_for:{p_name}"),
                        InlineKeyboardButton("🔍 Pretraži ponovno", callback_data="nav_search_persons")
                    ],
                    [
                        InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
                    ]
                ])

                img_bytes = base64.b64decode(p["thumbnail_base64"])
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=caption,
                        reply_markup=single_match_markup,
                        parse_mode=constants.ParseMode.MARKDOWN
                    )
                except Exception:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=caption,
                        reply_markup=single_match_markup,
                        parse_mode=None
                    )
                return

            # Multiple persons found or no thumbnail
            lines = [f"🔎 **Pronađeno u bazi ({total} osoba):**\n"]
            for idx, p in enumerate(persons[:10]):
                role_icon = "🚨" if p.get("role") == "blacklist" else ("⭐" if p.get("role") == "vip" else "👤")
                sample_cnt = p.get("sample_count", 1)
                lines.append(f"{idx+1}. {role_icon} **{p['name']}** (ID #{p['id']}) • {sample_cnt} uzoraka • `{p.get('role', 'standard').upper()}`")

            if total > 10:
                lines.append(f"\n_... i još {total - 10} osoba u bazi. Upišite točnije ime za detalje._")

            multi_match_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔍 Pretraži ponovno", callback_data="nav_search_persons"),
                    InlineKeyboardButton("➕ Registriraj osobu", callback_data="nav_enroll")
                ],
                [
                    InlineKeyboardButton("🔙 Glavni izbornik", callback_data="nav_main_menu")
                ]
            ])

            out_text = "\n".join(lines)
            try:
                await update.message.reply_text(out_text, reply_markup=multi_match_markup, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception:
                await update.message.reply_text(out_text, reply_markup=multi_match_markup, parse_mode=None)
        else:
            await update.message.reply_text(f"⚠️ Greška API poslužitelja: HTTP {resp.status_code}", reply_markup=get_back_to_main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Greška pri pretrazi baze: {str(e)}", reply_markup=get_back_to_main_menu())

async def search_persons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /trazi or /osobe <ime> to search persons in the database."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return

    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    args = context.args or []
    query = " ".join(args).strip()

    if not query:
        context.user_data["awaiting_person_search"] = True
        await update.message.reply_text(
            "🔍 **Pretraga registriranih osoba u bazi**\n\n"
            "Upišite ime ili dio imena osobe koju tražite (ili pošaljite `sve` za popis):\n"
            "_Primjer:_ `/trazi Aleksandar`",
            reply_markup=CANCEL_MARKUP,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    await perform_person_search(update, context, query)

async def search_persons_button_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles click on the 🗂️ Baza registriranih osoba button."""
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return
    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    context.user_data["awaiting_person_search"] = True
    await update.message.reply_text(
        "🗂️ **Pretraga baze registriranih osoba**\n\n"
        "Upišite ime ili dio imena osobe koju želite provjeriti u bazi (ili pošaljite `sve` za prikaz):",
        reply_markup=CANCEL_MARKUP,
        parse_mode=constants.ParseMode.MARKDOWN
    )

# =========================================================================
# GENERAL TEXT / PIN HANDLER
# =========================================================================

async def handle_general_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles PIN entry, lock requests, and general navigation."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    if not is_authorized(chat_id):
        await send_unauthorized_message(update, context)
        return

    text = (update.message.text or "").strip()

    # Handle awaiting person search text
    if context.user_data.get("awaiting_person_search"):
        context.user_data.pop("awaiting_person_search", None)
        if text not in ["❌ Odustani", "🔙 Povratak u glavni meni", "🔙 Glavni izbornik", "/cancel", "/menu"]:
            await perform_person_search(update, context, text)
            return

    # Handle direct text shortcuts
    if text == "🗂️ Baza registriranih osoba":
        await search_persons_button_prompt(update, context)
        return

    if text in ["👥 Popis bot korisnika", "👥 Popis korisnika"]:
        await admin_list_users(update, context)
        return

    # 1. Handle explicit lock request
    if text in ["🔒 Zaključaj", "/lock"]:
        await lock_command(update, context)
        return

    # 2. Check if user is entering the PIN
    cfg = get_remote_bot_config()
    current_pin = cfg.get("pin", "")

    if current_pin and text == current_pin:
        # Check if currently blocked
        if chat_id in failed_attempts:
            blocked_until = failed_attempts[chat_id].get("blocked_until", 0)
            if time.time() < blocked_until:
                remaining = int(blocked_until - time.time())
                await update.message.reply_text(
                    f"⏳ **Privremena blokada:** Previše pokušaja. Pričekajte još `{remaining} sekundi`.",
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                return

        # Auto-promote first authenticated user to Admin if no admin exists
        admin_ids = cfg.get("admin_chat_ids", [])
        if not admin_ids:
            try:
                admin_name = f"{user.first_name} {user.last_name or ''}".strip() or "Administrator"
                requests.post(
                    f"{ARGUSFACE_API_URL}/api/v1/bot/users/add",
                    data={"chat_id": chat_id, "name": admin_name, "role": "admin"},
                    headers=get_api_headers(),
                    timeout=5
                )
                get_remote_bot_config(force=True)
            except Exception as e:
                logger.warning(f"Neuspjelo automatsko postavljanje administratora: {e}")

        # Success - unlock session!
        authenticated_sessions[chat_id] = time.time()
        failed_attempts.pop(chat_id, None)

        role_info = " (👑 Administrator)" if is_admin(chat_id) else ""
        await update.message.reply_text(
            f"🔓 **PIN prihvaćen — Sustav otključan!**\n\n"
            f"Dobrodošli u ArgusFace biometrijski centar{role_info}. Odaberite željenu opciju:",
            reply_markup=get_main_menu(chat_id),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        user = update.effective_user
        welcome_text = format_welcome_text(user.first_name, chat_id)
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_inline_menu(chat_id),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    # 3. If not already authenticated, check if this was a wrong PIN attempt
    is_auth, lock_msg = check_authentication(chat_id)
    if not is_auth:
        if current_pin:
            # Check if user is already blocked
            if chat_id in failed_attempts and time.time() < failed_attempts[chat_id].get("blocked_until", 0):
                remaining = int(failed_attempts[chat_id]["blocked_until"] - time.time())
                await update.message.reply_text(
                    f"⏳ **Privremena blokada:** Pričekajte još `{remaining} sekundi`.",
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                return

            fa = failed_attempts.setdefault(chat_id, {"count": 0, "blocked_until": 0})
            fa["count"] += 1

            if fa["count"] >= 5:
                fa["blocked_until"] = time.time() + 300  # 5 min lockout
                await update.message.reply_text(
                    "🚨 **Previše netočnih unosa PIN-a!**\n"
                    "Bot je privremeno blokiran na 5 minuta.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                return

            await update.message.reply_text(
                f"❌ **Netočan PIN!** (Pokušaj {fa['count']}/5)\n\n"
                "Molimo unesite ispravan sigurnosni PIN za pristup sustavu:",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        await update.message.reply_text(lock_msg, reply_markup=ReplyKeyboardRemove(), parse_mode=constants.ParseMode.MARKDOWN)
        return

    # 4. If authenticated and text is back button or general message
    user = update.effective_user
    welcome_text = format_welcome_text(user.first_name, chat_id)
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_inline_menu(chat_id),
        parse_mode=constants.ParseMode.MARKDOWN
    )

# =========================================================================
# INTERACTIVE CALLBACK QUERY HANDLER (ACCESS REQUESTS & 1-TAP APPROVALS)
# =========================================================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button clicks for requesting and granting bot access."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = update.effective_chat.id
    user = update.effective_user

    # 1. Unauthorized user clicks "📩 Zatraži pristup od administratora"
    if data.startswith("req_access:"):
        req_chat_id = int(data.split(":")[1])
        cfg = get_remote_bot_config()
        admin_ids = cfg.get("admin_chat_ids", [])
        if not admin_ids and ENV_ALLOWED_CHAT_IDS:
            admin_ids = list(ENV_ALLOWED_CHAT_IDS)

        if not admin_ids:
            await safe_edit_or_reply(
                query,
                "⚠️ Administrator još nije konfiguriran u sustavu.\n"
                "Molimo obratite se izravno vlasniku računala.",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Korisnik"
        uname = f"@{user.username}" if user.username else ""
        req_time = time.strftime('%Y-%m-%d %H:%M:%S')

        # Store in pending requests
        pending_access_requests[req_chat_id] = {
            "name": name,
            "username": uname,
            "time": req_time
        }

        admin_text = (
            "🔔 **Novi zahtjev za pristup ArgusFace botu!**\n\n"
            f"👤 **Korisnik:** {name} {f'({uname})' if uname else ''}\n"
            f"🆔 **Chat ID:** `{req_chat_id}`\n"
            f"📅 **Vrijeme:** `{req_time}`\n\n"
            "Želite li ovoj osobi odobriti pristup biometrijskom sustavu?"
        )
        admin_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Odobri pristup", callback_data=f"approve_user:{req_chat_id}"),
                InlineKeyboardButton("❌ Odbij", callback_data=f"reject_user:{req_chat_id}")
            ]
        ])

        sent_count = 0
        for aid in admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=aid,
                    text=admin_text,
                    reply_markup=admin_markup,
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                sent_count += 1
            except Exception as e:
                logger.warning(f"Greška pri slanju notifikacije adminu {aid}: {e}")

        await safe_edit_or_reply(
            query,
            f"⏳ **Vaš zahtjev je uspješno poslan administratoru!**\n\n"
            f"🆔 Vaš Chat ID: `{req_chat_id}`\n\n"
            f"Čim administrator odobri vaš pristup na svom Telegramu, "
            f"primit ćete obavijest i moći ćete otključati sustav.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    # 2. Administrator clicks "✅ Odobri pristup"
    if data.startswith("approve_user:"):
        if not is_admin(chat_id):
            await safe_edit_or_reply(query, "⛔ Nemate administratorska prava za odobravanje pristupa.")
            return

        target_id = int(data.split(":")[1])
        req_info = pending_access_requests.get(target_id, {})
        target_name = req_info.get("name", "Korisnik")

        # Call host API to add user
        url = f"{ARGUSFACE_API_URL}/api/v1/bot/users/add"
        post_data = {
            "chat_id": target_id,
            "name": target_name,
            "role": "user"
        }
        try:
            resp = requests.post(url, data=post_data, headers=get_api_headers(), timeout=10)
            if resp.status_code == 200:
                get_remote_bot_config(force=True)
                pending_access_requests.pop(target_id, None)

                await safe_edit_or_reply(
                    query,
                    f"✅ **Pristup ODOBREN!**\n\n"
                    f"👤 Korisnik: **{target_name}** (`{target_id}`)\n"
                    f"🏷️ Uloga: `👤 Običan korisnik`\n"
                    f"📅 Odobrio: {user.first_name} u {time.strftime('%H:%M:%S')}\n\n"
                    f"Korisnik je dodan na popis ovlaštenih i poslana mu je obavijest.",
                    parse_mode=constants.ParseMode.MARKDOWN
                )
                # Notify the approved user
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text=(
                            "🎉 **Čestitamo! Administrator vam je odobrio pristup ArgusFace biometrijskom sustavu.**\n\n"
                            "Pošaljite **/start** ili unesite **sigurnosni PIN** za početak rada."
                        ),
                        parse_mode=constants.ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.warning(f"Neuspjelo slanje poruke odobrenom korisniku {target_id}: {e}")
            else:
                await safe_edit_or_reply(query, f"⚠️ Greška API-ja pri odobrenju: HTTP {resp.status_code}")
        except Exception as e:
            await safe_edit_or_reply(query, f"❌ Greška pri odobrenju: {e}")
        return

    # 3. Administrator clicks "❌ Odbij"
    if data.startswith("reject_user:"):
        if not is_admin(chat_id):
            await safe_edit_or_reply(query, "⛔ Nemate administratorska prava za ovu akciju.")
            return

        target_id = int(data.split(":")[1])
        req_info = pending_access_requests.get(target_id, {})
        target_name = req_info.get("name", "Korisnik")
        pending_access_requests.pop(target_id, None)

        await safe_edit_or_reply(
            query,
            f"❌ **Zahtjev ODBIJEN.**\n\n"
            f"👤 Korisnik: **{target_name}** (`{target_id}`)\n"
            f"📅 Odbio: {user.first_name} u {time.strftime('%H:%M:%S')}",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ **Vaš zahtjev za pristup sustavu je odbijen od strane administratora.**",
                parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    # 4. Interactive Card UI Navigation (Option 2)
    if data == "nav_main_menu":
        welcome_text = format_welcome_text(user.first_name, chat_id)
        await safe_edit_or_reply(
            query,
            welcome_text,
            reply_markup=get_main_inline_menu(chat_id),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data in ("nav_status", "nav_status_refresh"):
        url = f"{ARGUSFACE_API_URL}/api/v1/status"
        cfg = get_remote_bot_config()
        try:
            resp = requests.get(url, headers=get_api_headers(), timeout=5)
            if resp.status_code == 200:
                s_data = resp.json()
                spoof_txt = "🟢 Uključena" if s_data.get("anti_spoofing") else "⚪ Isključena"
                faiss_txt = "🟢 FAISS Ubrzan" if s_data.get("has_faiss") else "🟡 NumPy BLAS"
                status_text = (
                    "📊 **ARGUSFACE STATUS SUSTAVA**\n\n"
                    f"🖥️ **AI Engine:** `✅ Online`\n"
                    f"👥 **Baza lica:** `{s_data.get('total_persons', 0)}` osoba\n"
                    f"📸 **Spremljenih uzoraka:** `{s_data.get('total_samples', 0)}`\n"
                    f"⚡ **Vektorski indeks:** `{s_data.get('index_backend', 'N/A')}` ({faiss_txt})\n"
                    f"🛡️ **Anti-Spoofing (Liveness):** {spoof_txt}\n"
                    f"🔐 **PIN Zaštita bota:** `🟢 Aktivna`\n"
                    f"⏱️ **Istek sesije:** `{cfg.get('session_timeout_minutes', 30)} min`\n"
                    f"👥 **Ovlaštenih korisnika:** `{len(cfg.get('allowed_users', []))}`\n"
                    f"🌐 **Poveznica:** `{ARGUSFACE_API_URL}`\n\n"
                    f"🕒 Ažurirano: `{time.strftime('%H:%M:%S')}`"
                )
            else:
                status_text = f"⚠️ API na računalu je vratio grešku: HTTP {resp.status_code}"
        except Exception as e:
            status_text = f"❌ API na računalu nije dostupan: {e}"

        await safe_edit_or_reply(
            query,
            status_text,
            reply_markup=get_status_inline_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "nav_webapp":
        await webapp_command(update, context)
        return

    if data == "nav_search":
        await safe_edit_or_reply(
            query,
            "🔍 **SKENIRANJE LICA U BAZI (1:N)**\n\n"
            "Pošaljite fotografiju izravno u ovaj chat.\n\n"
            "Sustav će u manje od sekunde:\n"
            "1. Detektirati sva lica i provjeriti liveness (anti-spoofing)\n"
            "2. Usporediti lica s bazom podataka ArgusFace\n"
            "3. Prikazati vam **vizualnu biometrijsku karticu s okvirom i postotkom sličnosti**!",
            reply_markup=get_back_to_main_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "nav_lock":
        authenticated_sessions.pop(chat_id, None)
        await safe_edit_or_reply(
            query,
            "🔒 **Sustav je uspješno zaključan.**\n\nZa ponovni pristup unesite svoj **sigurnosni PIN**:",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "nav_help":
        help_text = (
            "ℹ️ **UPUTE ZA KORIŠTENJE ARGUSFACE BOTA**\n\n"
            "• **Skeniranje lica:** Bilo kada pošaljite fotografiju s mobitela u chat.\n"
            "• **Usporedba 2 lica:** Naredba /compare ili gumb u izborniku.\n"
            "• **Registracija osobe:** Naredba /enroll ili gumb u izborniku.\n"
            "• **Status sustava:** Provjera stanja AI enginea i baze podataka.\n"
            "• **Zaključavanje:** /lock odmah zaključava sesiju radi sigurnosti.\n\n"
            "💡 Za izbornik uvijek možete upisati **/menu** ili **/start**."
        )
        await safe_edit_or_reply(
            query,
            help_text,
            reply_markup=get_back_to_main_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "nav_admin":
        if not is_admin(chat_id):
            await safe_edit_or_reply(query, "⛔ Nemate administratorska prava.", reply_markup=get_back_to_main_menu())
            return
        await safe_edit_or_reply(
            query,
            "⚙️ **ADMINISTRATORSKI PANEL**\n\n"
            "Odaberite akciju za upravljanje ovlaštenim korisnicima i sigurnosnim postavkama:",
            reply_markup=get_admin_inline_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data in ("nav_search_persons", "admin_search_persons"):
        context.user_data["awaiting_person_search"] = True
        await safe_edit_or_reply(
            query,
            "🗂️ **Pretraga baze registriranih osoba**\n\n"
            "Upišite ime ili dio imena osobe koju želite provjeriti u bazi (ili pošaljite `sve` za pregled baze):\n\n"
            "💡 _Možete u bilo kojem trenutku poslati ime osobe, ili koristiti brzu naredbu:_ `/trazi <ime>`",
            reply_markup=get_back_to_main_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "admin_list_users":
        if not is_admin(chat_id):
            await safe_edit_or_reply(query, "⛔ Nemate administratorska prava.", reply_markup=get_back_to_main_menu())
            return
        cfg = get_remote_bot_config(force=True)
        users = cfg.get("allowed_users", [])
        if not users:
            txt = "ℹ️ Popis ovlaštenih korisnika je trenutno prazan."
        else:
            lines = [f"👥 **Ovlašteni korisnici ({len(users)}):**\n"]
            for idx, u in enumerate(users):
                role_icon = "👑 Admin" if u.get("role") == "admin" else "👤 Korisnik"
                uname = u.get("name", "N/A")
                cid = u.get("chat_id")
                lines.append(f"{idx+1}. {uname} (`{cid}`) — {role_icon}")
            txt = "\n".join(lines)
        await safe_edit_or_reply(
            query,
            txt,
            reply_markup=get_back_to_admin_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "admin_pin_info":
        if not is_admin(chat_id):
            await safe_edit_or_reply(query, "⛔ Nemate administratorska prava.", reply_markup=get_back_to_main_menu())
            return
        cfg = get_remote_bot_config(force=True)
        pin = cfg.get("pin", "121977")
        timeout = cfg.get("session_timeout_minutes", 30)
        txt = (
            "🔑 **SIGURNOSNI PIN I SESIJE**\n\n"
            f"• **Trenutni PIN:** `{pin}`\n"
            f"• **Timeout neaktivnosti:** `{timeout} min`\n"
            f"• **Anti-bruteforce zaštita:** `3 pokušaja -> 60s blokada`\n\n"
            "Za promjenu PIN-a, koristite donji izbornik **'⚙️ Admin panel' -> '🔑 Promijeni PIN'**."
        )
        await safe_edit_or_reply(
            query,
            txt,
            reply_markup=get_back_to_admin_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "admin_add_info":
        await safe_edit_or_reply(
            query,
            "➕ **DODAVANJE KORISNIKA**\n\n"
            "Za dodavanje novog korisnika, upotrijebite opciju **'➕ Dodaj korisnika'** u donjem administratorskom izborniku "
            "ili pričekajte da vam korisnik pošalje zahtjev za pristup (stisne 'Zatraži pristup').",
            reply_markup=get_back_to_admin_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    if data == "admin_del_info":
        await safe_edit_or_reply(
            query,
            "❌ **UKLANJANJE KORISNIKA**\n\n"
            "Za uklanjanje korisnika, upotrijebite opciju **'❌ Ukloni korisnika'** u donjem administratorskom izborniku.",
            reply_markup=get_back_to_admin_menu(),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

# =========================================================================
# MAIN APP ENTRYPOINT
# =========================================================================

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "unesite_vas_token_ovdje":
        print("[GREŠKA] TELEGRAM_BOT_TOKEN nije postavljen u .env datoteci!")
        print("Molimo otvorite .env datoteku i unesite token koji ste dobili od @BotFather-a.")
        sys.exit(1)

    print("=======================================================")
    print("      ArgusFace Studio - 24/7 Telegram Bot Servis      ")
    print("=======================================================")
    print(f"[*] Spajam se na ArgusFace API: {ARGUSFACE_API_URL}")

    cfg = get_remote_bot_config()
    print(f"[*] Sigurnosni PIN: {cfg.get('pin', 'N/A')}")
    print(f"[*] Ovlaštenih korisnika: {len(cfg.get('allowed_users', []))}")
    print(f"[*] Administratora: {len(cfg.get('admin_chat_ids', []))}")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Compare conversation handler (1:1)
    compare_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(compare_start, pattern="^nav_compare$"),
            MessageHandler(filters.Regex("^⚖️ Usporedi 2 slike$"), compare_start),
            MessageHandler(filters.Regex("(?i).*usporedi.*2.*slike.*"), compare_start),
            CommandHandler("compare", compare_start)
        ],
        states={
            WAITING_PHOTO_1: [
                MessageHandler(filters.PHOTO, compare_photo_1),
                MessageHandler(filters.Regex("^❌ Odustani$"), compare_cancel)
            ],
            WAITING_PHOTO_2: [
                MessageHandler(filters.PHOTO, compare_photo_2),
                MessageHandler(filters.Regex("^❌ Odustani$"), compare_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", compare_cancel),
            MessageHandler(filters.Regex("^❌ Odustani$"), compare_cancel)
        ]
    )

    # Person enrollment conversation handler (Dodaj novu osobu i 1-3 fotografije)
    enroll_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(enroll_start, pattern="^nav_enroll$"),
            CallbackQueryHandler(enroll_start, pattern="^nav_enroll_for:"),
            MessageHandler(filters.Regex("^➕ Registriraj osobu$"), enroll_start),
            MessageHandler(filters.Regex("^➕ Dodaj novu osobu$"), enroll_start),
            CommandHandler("enroll", enroll_start)
        ],
        states={
            ENROLL_NAME: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), enroll_name),
                MessageHandler(filters.Regex("^❌ Odustani$"), enroll_cancel)
            ],
            ENROLL_ROLE: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), enroll_role),
                MessageHandler(filters.Regex("^❌ Odustani$"), enroll_cancel)
            ],
            ENROLL_NOTES: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), enroll_notes),
                MessageHandler(filters.Regex("^❌ Odustani$"), enroll_cancel)
            ],
            ENROLL_PHOTOS: [
                MessageHandler(filters.PHOTO, enroll_photo_received),
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), enroll_photo_text_handler),
                MessageHandler(filters.Regex("^❌ Odustani$"), enroll_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", enroll_cancel),
            MessageHandler(filters.Regex("^❌ Odustani$"), enroll_cancel),
            MessageHandler(filters.Regex("^🔙 (Povratak u glavni meni|Glavni izbornik)$"), enroll_cancel),
            CommandHandler("menu", enroll_cancel),
            CommandHandler("start", enroll_cancel)
        ]
    )

    # Admin: Add user conversation
    admin_add_user_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Dodaj korisnika$"), admin_add_user_start)
        ],
        states={
            ADMIN_ADD_ID: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), admin_add_user_id),
                MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
            ],
            ADMIN_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), admin_add_user_name),
                MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
            ],
            ADMIN_ADD_ROLE: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), admin_add_user_role),
                MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
        ]
    )

    # Admin: Remove user conversation
    admin_remove_user_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^❌ Ukloni korisnika$"), admin_remove_user_start)
        ],
        states={
            ADMIN_REMOVE_ID: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), admin_remove_user_finish),
                MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
        ]
    )

    # Admin: Change PIN conversation
    admin_change_pin_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🔑 Promijeni PIN$"), admin_change_pin_start)
        ],
        states={
            ADMIN_PIN_NEW: [
                MessageHandler(filters.TEXT & ~filters.Regex("^❌ Odustani$"), admin_change_pin_finish),
                MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            MessageHandler(filters.Regex("^❌ Odustani$"), admin_cancel)
        ]
    )

    # Register conversations
    app.add_handler(compare_conv_handler)
    app.add_handler(enroll_conv_handler)
    app.add_handler(admin_add_user_conv)
    app.add_handler(admin_remove_user_conv)
    app.add_handler(admin_change_pin_conv)

    # Interactive inline button callback query handler (Request access & 1-tap approval)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("app", webapp_command))
    app.add_handler(CommandHandler("webapp", webapp_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("admin", admin_panel_open))

    app.add_handler(CommandHandler(["trazi", "osobe", "search"], search_persons_command))

    # Menu button handlers
    app.add_handler(MessageHandler(filters.Regex("^📊 Status sustava$"), status_command))
    app.add_handler(MessageHandler(filters.Regex("^📱 Mini Web App$"), webapp_command))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Pomoć$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^🔍 Provjeri u bazi$"), search_button_prompt))
    app.add_handler(MessageHandler(filters.Regex("^🗂️ Baza registriranih osoba$"), search_persons_button_prompt))
    app.add_handler(MessageHandler(filters.Regex("^🔒 Zaključaj$"), lock_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Admin panel$"), admin_panel_open))
    app.add_handler(MessageHandler(filters.Regex("^👥 Popis (bot )?korisnika$"), admin_list_users))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Povratak u glavni meni$"), admin_back_to_main))

    # Direct photo upload (1:N search)
    app.add_handler(MessageHandler(filters.PHOTO, handle_direct_photo_search))

    # General text messages (PIN input, navigation, etc.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_general_text))

    print("[*] Telegram Bot je uspješno pokrenut i sluša poruke...")
    app.run_polling()

if __name__ == "__main__":
    main()
