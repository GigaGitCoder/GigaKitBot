"""
bot.py — Telegram-бот тамагочи с новостями, погодой и системой монет
Интегрирует контроллер БД, модуль новостей и управление питомцами
"""

import os
import asyncio
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto

from Modules.news_module import get_news_with_reaction, get_weather_reaction
from tasks import start_background_tasks
from image_utils import (
    get_status_image, get_action_image, get_low_stat_image,
    composite_cat_image
)

# ── Загрузка переменных окружения ────────────────────────────────────────────
load_dotenv()
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LOGS_GROUP_ID = int(os.getenv("LOGS_GROUP_ID", "-1003810032939"))
ADMIN_USER_IDS = json.loads(os.getenv("ADMIN_USER_IDS", "[1105938010]"))

# ── Настройка логирования ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Инициализация бота ──────────────────────────────────────────────────────
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")

# ── Инициализация БД ────────────────────────────────────────────────────────
DB_PATH = "pets.db"

def init_db():
    """Инициализирует БД если её нет"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            user_id        TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            money          INTEGER DEFAULT 100,
            satiety        INTEGER DEFAULT 100,
            energy         INTEGER DEFAULT 100,
            mood           INTEGER DEFAULT 100,
            states         JSON DEFAULT NULL,
            PetInventory   JSON DEFAULT NULL,
            UserInventory  JSON DEFAULT NULL,
            last_satiety_check    TEXT DEFAULT NULL,
            last_energy_check     TEXT DEFAULT NULL,
            last_mood_check       TEXT DEFAULT NULL,
            last_news_check       TEXT DEFAULT NULL
        );
    """)
    conn.commit()
    conn.close()
    logger.info("✅ БД инициализирована")

def get_db_connection():
    """Получает подключение к БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Пути к изображениям ────────────────────────────────────────────────────
IMAGES_DIR = Path("Images")
IMG_CAT = IMAGES_DIR / "Cat.png"
IMG_CAT_LOW_ENERGY = IMAGES_DIR / "CatLowEnergy.png"
IMG_CAT_LOW_MOOD = IMAGES_DIR / "CatLowMood.png"
IMG_CAT_LOW_SATIETY = IMAGES_DIR / "CatLowSatiety.png"

IMG_ACS_FINANCE = IMAGES_DIR / "AcsFinance.png"
IMG_ACS_GAMING = IMAGES_DIR / "AcsGaming.png"
IMG_ACS_WEATHER = IMAGES_DIR / "AcsWeather.png"

IMG_ENERGY_ICON = IMAGES_DIR / "EnergyIcon.png"
IMG_MOOD_ICON = IMAGES_DIR / "MoodIcon.png"
IMG_SATIETY_ICON = IMAGES_DIR / "SatietyIcon.png"

IMG_FOOD = IMAGES_DIR / "Food.png"
IMG_GAME = IMAGES_DIR / "Game.png"

# ── Вспомогательные функции ─────────────────────────────────────────────────

def clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    """Ограничивает значение в диапазоне"""
    return max(lo, min(hi, value))

def mood_emoji(mood: int) -> str:
    """Возвращает эмодзи в зависимости от настроения"""
    if mood >= 80: return "🤩"
    elif mood >= 60: return "😊"
    elif mood >= 40: return "😐"
    elif mood >= 20: return "😟"
    else: return "😭"

def get_status_text(pet: dict) -> str:
    """Возвращает текст статуса питомца с иконками"""
    lines = []
    
    if pet["satiety"] <= 30:
        lines.append("🍖 <b>ГОЛОДАЕТ!</b>")
    if pet["energy"] <= 20:
        lines.append("⚡ <b>ИСТОЩЕНИЕ!</b>")
    if pet["mood"] <= 50:
        lines.append("😢 <b>ГРУСТИТ!</b>")
    
    if not lines:
        lines.append(f"{mood_emoji(pet['mood'])} Всё хорошо")
    
    return "\n".join(lines)

def safe_edit_or_send(chat_id: int, msg_id: int, text: str, reply_markup=None):
    """Редактирует сообщение или отправляет новое, если редактирование невозможно (например, сообщение — фото)"""
    try:
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=reply_markup)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=reply_markup)

# ── API контроллера (обёртки для синхронных вызовов) ────────────────────────

def db_create_pet(user_id: str, name: str) -> dict:
    """Создать питомца"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            conn.close()
            return None  # Питомец уже существует
        
        cur.execute("INSERT INTO pets (user_id, name) VALUES (?, ?)", (user_id, name))
        conn.commit()
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def db_get_pet(user_id: str) -> dict:
    """Получить питомца"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def db_delete_pet(user_id: str) -> bool:
    """Удалить питомца"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM pets WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    finally:
        conn.close()

def db_update_pet_value(user_id: str, field: str, value) -> dict:
    """Обновить одно значение питомца"""
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"UPDATE pets SET {field} = ? WHERE user_id = ?", (value, user_id))
        conn.commit()
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def db_add_money(user_id: str, amount: int) -> dict:
    """Добавить деньги"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT money FROM pets WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        new_money = max(0, row["money"] + amount)
        cur.execute("UPDATE pets SET money = ? WHERE user_id = ?", (new_money, user_id))
        conn.commit()
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def db_apply_minus(user_id: str, satiety_n: int = 0, energy_n: int = 0, mood_n: int = 0) -> dict:
    """Вычесть значения (с clamp 0-100)"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        pet = cur.fetchone()
        if not pet:
            return None
        
        new_satiety = clamp(pet["satiety"] - satiety_n)
        new_energy = clamp(pet["energy"] - energy_n)
        new_mood = clamp(pet["mood"] - mood_n)
        
        cur.execute("""
            UPDATE pets SET satiety = ?, energy = ?, mood = ?
            WHERE user_id = ?
        """, (new_satiety, new_energy, new_mood, user_id))
        conn.commit()
        
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def db_get_pet_inventory(user_id: str) -> list:
    """Получить инвентарь питомца (надетые аксессуары)"""
    pet = db_get_pet(user_id)
    if not pet:
        return []
    inv = pet.get("PetInventory")
    return json.loads(inv) if inv and isinstance(inv, str) else (inv if inv else [])

def db_get_user_inventory(user_id: str) -> list:
    """Получить инвентарь пользователя"""
    pet = db_get_pet(user_id)
    if not pet:
        return []
    inv = pet.get("UserInventory")
    return json.loads(inv) if inv and isinstance(inv, str) else (inv if inv else [])

def db_add_pet_item(user_id: str, item: str) -> list:
    """Добавить аксессуар на питомца (заменить старый)"""
    # Может быть только один аксессуар
    pet = db_update_pet_value(user_id, "PetInventory", json.dumps([item]))
    inv = pet.get("PetInventory")
    return json.loads(inv) if inv and isinstance(inv, str) else (inv if inv else [])

def db_add_user_item(user_id: str, item: str) -> list:
    """Добавить предмет в инвентарь пользователя"""
    inv = db_get_user_inventory(user_id)
    inv.append(item)
    pet = db_update_pet_value(user_id, "UserInventory", json.dumps(inv))
    inv = pet.get("UserInventory")
    return json.loads(inv) if inv and isinstance(inv, str) else (inv if inv else [])

def db_remove_user_item(user_id: str, item: str) -> list:
    """Удалить предмет из инвентаря пользователя"""
    inv = db_get_user_inventory(user_id)
    if item in inv:
        inv.remove(inv)
    pet = db_update_pet_value(user_id, "UserInventory", json.dumps(inv))
    inv = pet.get("UserInventory")
    return json.loads(inv) if inv and isinstance(inv, str) else (inv if inv else [])

def db_get_states(user_id: str) -> dict:
    """Получить состояния питомца"""
    pet = db_get_pet(user_id)
    if not pet:
        return {}
    states = pet.get("states")
    return json.loads(states) if states and isinstance(states, str) else (states if states else {})

def db_set_states(user_id: str, states: dict) -> dict:
    """Установить состояния питомца"""
    return db_update_pet_value(user_id, "states", json.dumps(states))

def db_update_last_check(user_id: str, check_type: str):
    """Обновить время последней проверки"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        field = f"last_{check_type}_check"
        cur.execute(f"UPDATE pets SET {field} = ? WHERE user_id = ?", 
                   (datetime.now().isoformat(), user_id))
        conn.commit()
    finally:
        conn.close()

# ── Клавиатуры ──────────────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню"""
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📰 Новости", callback_data="news_menu"),
        InlineKeyboardButton("🍖 Покормить", callback_data="feed"),
    )
    kb.add(
        InlineKeyboardButton("🎮 Поиграть", callback_data="play"),
        InlineKeyboardButton("💤 Спать", callback_data="sleep"),
    )
    kb.add(
        InlineKeyboardButton("🏪 Магазин", callback_data="shop"),
        InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"),
    )
    kb.add(
        InlineKeyboardButton("🐾 Статус", callback_data="status"),
    )
    return kb

def news_menu_kb(user_id: None) -> InlineKeyboardMarkup:
    """Меню выбора источника новостей"""
    if user_id:
        pet_inventory = db_get_pet_inventory(user_id)

    kb = InlineKeyboardMarkup(row_width=2)
    if "finance" in pet_inventory:
        kb.add(
            InlineKeyboardButton("📰 Экономика (RIA)", callback_data="news_ria_finance"),
            InlineKeyboardButton("🏛️ Политика (RIA)", callback_data="news_ria_politics"),
        )
        kb.add(
            InlineKeyboardButton("💰 Бизнес (Forbes)", callback_data="news_forbes"),
            InlineKeyboardButton("🔄 Микс", callback_data="news_mix"),
        )
    if "gaming" in pet_inventory:  
        kb.add(
            InlineKeyboardButton("🎮 Игры (StopGame)", callback_data="news_stopgame")
        )
    if "weather" in pet_inventory:
        kb.add(
            InlineKeyboardButton("🌤️ Погода", callback_data="weather")
        )
    kb.add(
        InlineKeyboardButton("🐾 Статус", callback_data="status")
    )
    return kb

def shop_kb() -> InlineKeyboardMarkup:
    """Магазин аксессуаров"""
    accessories = [
        ("💰 Денежный свитер (100)", "buy_finance"),
        ("🎧 Геймерские наушники (100)", "buy_gaming"),
        ("☂️ Погодный зонтик (100)", "buy_weather"),
    ]
    kb = InlineKeyboardMarkup()
    for name, cb in accessories:
        kb.add(InlineKeyboardButton(name, callback_data=cb))
    kb.add(
        InlineKeyboardButton("🐾 Статус", callback_data="status")
    )
    return kb

def inventory_kb(user_id: str) -> InlineKeyboardMarkup:
    """Инвентарь с аксессуарами"""
    items = db_get_user_inventory(user_id)
    pet_inv = db_get_pet_inventory(user_id)
    
    kb = InlineKeyboardMarkup()
    
    accessory_names = {
        "finance": "💰 Денежный свитер",
        "gaming": "🎧 Геймерские наушники",
        "weather": "☂️ Погодный зонтик",
    }
    
    for item in items:
        name = accessory_names.get(item, item)
        status = "✅ надет" if pet_inv and item in pet_inv else ""
        kb.add(InlineKeyboardButton(f"{name} {status}", callback_data=f"wear_{item}"))
    
    return kb

def confirm_kb(action: str) -> InlineKeyboardMarkup:
    """Подтверждение действия"""
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}"),
        InlineKeyboardButton("❌ Нет", callback_data="cancel"),
    )
    return kb

# ── Команды ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    """Запуск бота"""
    user_id = str(message.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        msg = bot.send_message(
            message.chat.id,
            "🎉 Добро пожаловать в <b>GigaPet</b>!\n\n"
            "Введи имя своего питомца:"
        )
        bot.register_next_step_handler(msg, lambda m: create_pet(m))
    else:
        text = f"😊 У тебя уже есть питомец, ты можешь сбросить его командой /reset"
        bot.send_message(message.chat.id, text, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🐾 Статус", callback_data="status")))

def create_pet(message):
    """Создание питомца"""
    user_id = str(message.from_user.id)
    name = message.text.strip()[:20]
    
    if not name:
        bot.send_message(message.chat.id, "❌ Имя не может быть пустым!")
        return
    
    pet = db_create_pet(user_id, name)
    if not pet:
        bot.send_message(message.chat.id, "❌ Питомец уже существует!")
        return
    
    # Логируем создание питомца в группу
    if LOGS_GROUP_ID:
        try:
            username = message.from_user.username
            user_mention = f"@{username}" if username else f"id{user_id}"
            log_text = (
                f"🐾 Новый питомец создан!\n"
                f"👤 Пользователь: {user_mention} (id: {user_id})\n"
                f"🏷️ Имя питомца: <b>{name}</b>"
            )
            bot.send_message(LOGS_GROUP_ID, log_text)
        except Exception as e:
            logger.error(f"Ошибка отправки лога в группу: {e}")
    
    img_path = IMG_CAT

    text = (
        f"✨ Питомец <b>{pet['name']}</b> создан!\n\n"
        f"💰 Монеты: {pet['money']}\n"
        f"🍖 Сытость: {pet['satiety']}/100\n"
        f"⚡ Энергия: {pet['energy']}/100\n"
        f"😊 Настроение: {pet['mood']}/100"
    )
    try:
        with open(img_path, "rb") as img:
            bot.send_photo(message.chat.id, img, caption=text, 
                          reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        bot.send_message(message.chat.id, text, reply_markup=main_menu_kb())

@bot.message_handler(commands=["adm"])
def cmd_adm(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_USER_IDS:
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этой команде.")
        return
    
    bot.send_message(message.chat.id, message.chat.id)

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    """Удалить питомца"""
    user_id = str(message.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(message.chat.id, "❌ Питомца нет!")
        return
    
    msg = bot.send_message(
        message.chat.id,
        f"⚠️ Удалить питомца <b>{pet['name']}</b>?",
        reply_markup=confirm_kb("delete_pet")
    )

def db_reset_all_pets() -> int:
    """Сбросить характеристики всех питомцев (для /test)"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE pets
            SET satiety = 10, energy = 10, mood = 10, money = 500
        """)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

@bot.message_handler(commands=["test"])
def cmd_test(message):
    """Сбросить характеристики всех питомцев — только для администраторов"""
    user_id = message.from_user.id
    if user_id not in ADMIN_USER_IDS:
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этой команде.")
        return

    count = db_reset_all_pets()
    bot.send_message(
        message.chat.id,
        f"✅ Готово! Характеристики обновлены для <b>{count}</b> питомцев:\n"
        f"🍖 Сытость: 10\n"
        f"⚡ Энергия: 10\n"
        f"😊 Настроение: 10\n"
        f"💰 Монеты: 500"
    )

@bot.message_handler(commands=["status"])
def command_status(message):
    """Показать полный статус с картинкой"""
    user_id = str(message.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(message.chat.id, "❌ Питомец не найден")
        return
    
    state_icons = []

    # Определяем какую картинку отправлять
    if pet["satiety"] <= 30:
        state_icons.append("satiety")
    if pet["energy"] <= 20:
        state_icons.append("energy")
    if pet["mood"] <= 50:
        state_icons.append("mood")

    pet_inventory = db_get_pet_inventory(user_id)
    img = composite_cat_image(state_icons=state_icons, accessory=pet_inventory[0] if pet_inventory else None)

    text = (
        f"🐾 <b>{pet['name']}</b> {mood_emoji(pet['mood'])}\n\n"
        f"🍖 Сытость: {pet['satiety']}/100\n"
        f"⚡ Энергия: {pet['energy']}/100\n"
        f"😊 Настроение: {pet['mood']}/100\n"
        f"💰 Монеты: {pet['money']}\n\n"
        f"{get_status_text(pet)}"
    )
    
    try:
        bot.send_photo(message.chat.id, img, caption=text, 
                       reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        bot.send_message(message.chat.id, text, reply_markup=main_menu_kb())

# ── Callback-хендлеры ────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "menu")
def cb_menu(call: CallbackQuery):
    """Главное меню"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    text = (
        f"🐾 <b>{pet['name']}</b>\n\n"
        f"🍖 Сытость: {pet['satiety']}/100\n"
        f"⚡ Энергия: {pet['energy']}/100\n"
        f"😊 Настроение: {pet['mood']}/100\n"
        f"💰 Монеты: {pet['money']}\n\n"
        f"{get_status_text(pet)}"
    )
    
    safe_edit_or_send(call.message.chat.id, call.message.message_id, text,
                     reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data == "status")
def cb_status(call: CallbackQuery):
    """Показать полный статус с картинкой"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    state_icons = []

    # Определяем какую картинку отправлять
    if pet["satiety"] <= 30:
        state_icons.append("satiety")
    if pet["energy"] <= 20:
        state_icons.append("energy")
    if pet["mood"] <= 50:
        state_icons.append("mood")

    pet_inventory = db_get_pet_inventory(user_id)
    img = composite_cat_image(state_icons=state_icons, accessory=pet_inventory[0] if pet_inventory else None)

    text = (
        f"🐾 <b>{pet['name']}</b> {mood_emoji(pet['mood'])}\n\n"
        f"🍖 Сытость: {pet['satiety']}/100\n"
        f"⚡ Энергия: {pet['energy']}/100\n"
        f"😊 Настроение: {pet['mood']}/100\n"
        f"💰 Монеты: {pet['money']}\n\n"
        f"{get_status_text(pet)}"
    )
    
    try:
        bot.send_photo(call.message.chat.id, img, caption=text, 
                       reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        bot.send_message(call.message.chat.id, text, reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data == "feed")
def cb_feed(call: CallbackQuery):
    """Покормить питомца"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    if pet["satiety"] >= 100:
        try:
            with open(IMG_CAT, "rb") as img:
                bot.send_photo(call.message.chat.id, img,
                              caption="🍖 Твой питомец уже наелся!")
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            bot.send_message(call.message.chat.id, "🍖 Твой питомец уже наелся!")
        return
    
    if pet["money"] < 1:
        bot.send_message(call.message.chat.id, "💸 Нет денег! Нужна 1 монета")
        return
    
    # Кормим: -1 монета, +10 сытости
    pet = db_add_money(user_id, -1)
    pet = db_apply_minus(user_id, satiety_n=-10)
    
    text = (
        f"🍖 Ты покормил <b>{pet['name']}</b>!\n\n"
        f"💰 -1 монета (осталось: {pet['money']})\n"
        f"🍖 +10 сытости (осталось: {pet['satiety']}/100)"
    )
    
    # Отправляем действие с картинкой еды
    try:
        pet_inventory = db_get_pet_inventory(user_id)
        action_img = get_action_image("food", pet_inventory)
        bot.send_photo(call.message.chat.id, action_img, caption=text,
                      reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error with action image: {e}")
        try:
            with open(IMG_FOOD, "rb") as img:
                bot.send_photo(call.message.chat.id, img, caption=text,
                              reply_markup=main_menu_kb())
        except:
            bot.send_message(call.message.chat.id, text, reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data == "play")
def cb_play(call: CallbackQuery):
    """Поиграть с питомцем"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    if pet["mood"] >= 100:
        try:
            with open(IMG_CAT, "rb") as img:
                bot.send_photo(call.message.chat.id, img,
                              caption="🎮 Твой питомец уже наигрался!")
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            bot.send_message(call.message.chat.id, "🎮 Твой питомец уже наигрался!")
        return
    
    if pet["energy"] < 10:
        try:
            with open(IMG_CAT_LOW_ENERGY, "rb") as img:
                bot.send_photo(call.message.chat.id, img,
                              caption="⚡ Питомцу не хватает энергии для игры!")
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            bot.send_message(call.message.chat.id, "⚡ Питомцу не хватает энергии для игры!")
        return
    
    # Играем: -10 энергии, +10 настроения, +5 монет
    pet = db_apply_minus(user_id, energy_n=10)
    pet = db_apply_minus(user_id, mood_n=-10)  # Отрицательное значение = прибавление
    pet = db_add_money(user_id, 5)
    
    text = (
        f"🎮 Ты поиграл с <b>{pet['name']}</b>!\n\n"
        f"⚡ -10 энергии (осталось: {pet['energy']}/100)\n"
        f"😊 +10 настроения (осталось: {pet['mood']}/100)\n"
        f"💰 +5 монет (осталось: {pet['money']})"
    )
    
    # Отправляем действие с картинкой игры
    try:
        pet_inventory = db_get_pet_inventory(user_id)
        action_img = get_action_image("game", pet_inventory)
        bot.send_photo(call.message.chat.id, action_img, caption=text,
                      reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error with action image: {e}")
        try:
            with open(IMG_GAME, "rb") as img:
                bot.send_photo(call.message.chat.id, img, caption=text,
                              reply_markup=main_menu_kb())
        except:
            bot.send_message(call.message.chat.id, text, reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data == "sleep")
def cb_sleep(call: CallbackQuery):
    """Отдых питомца (восстановление энергии)"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    if pet["energy"] >= 100:
        with open(IMG_CAT, "rb") as img:
                bot.send_photo(call.message.chat.id, img,
                              caption="⚡ Питомец уже полон энергии!")
        return
    
    # Рассчитываем восстановление: 10 * (сытость / 100)
    recovery = int(10 * (pet["satiety"] / 100))
    if recovery < 1:
        recovery = 1
    
    new_energy = min(100, pet["energy"] + recovery)
    delta = new_energy - pet["energy"]
    
    pet = db_update_pet_value(user_id, "energy", new_energy)
    
    text = (
        f"💤 <b>{pet['name']}</b> поспал!\n\n"
        f"⚡ +{delta} энергии (осталось: {pet['energy']}/100)"
    )
    try:
        pet_inventory = db_get_pet_inventory(user_id)
        action_img = get_action_image("sleep", pet_inventory)
        bot.send_photo(call.message.chat.id, action_img, caption=text,
                      reply_markup=main_menu_kb())
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        bot.send_message(call.message.chat.id, text, reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data == "shop")
def cb_shop(call: CallbackQuery):
    """Магазин аксессуаров"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    pet = db_get_pet(user_id)
    
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    text = (
        f"🏪 <b>Магазин</b>\n\n"
        f"💰 У вас: {pet['money']} монет\n\n"
        f"Каждый аксессуар стоит <b>100 монет</b>"
    )
    safe_edit_or_send(call.message.chat.id, call.message.message_id, text,
                     reply_markup=shop_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def cb_buy(call: CallbackQuery):
    """Купить аксессуар"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    item = call.data.replace("buy_", "")
    
    pet = db_get_pet(user_id)
    if not pet:
        bot.send_message(call.message.chat.id, "❌ Питомец не найден")
        return
    
    if pet["money"] < 100:
        bot.send_message(call.message.chat.id, "💸 Недостаточно монет! Нужно 100")
        return
    
    # Проверяем есть ли уже такой предмет
    user_items = db_get_user_inventory(user_id)
    if item in user_items:
        bot.send_message(call.message.chat.id, "✅ Этот аксессуар уже у вас!")
        return
    
    # Покупаем
    pet = db_add_money(user_id, -100)
    db_add_user_item(user_id, item)
    
    names = {
        "finance": "💰 Денежный свитер",
        "gaming": "🎧 Геймерские наушники",
        "weather": "☂️ Погодный зонтик",
    }
    
    text = (
        f"✅ Куплено: <b>{names.get(item, item)}</b>\n\n"
        f"💰 -100 монет (осталось: {pet['money']})"
    )
    bot.send_message(call.message.chat.id, text, reply_markup=shop_kb())

@bot.callback_query_handler(func=lambda c: c.data == "inventory")
def cb_inventory(call: CallbackQuery):
    """Инвентарь с аксессуарами"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    items = db_get_user_inventory(user_id)
    
    if not items:
        bot.send_message(call.message.chat.id, "🎒 Инвентарь пуст", reply_markup=InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status")))
        return
    
    text = (
        f"🎒 <b>Инвентарь</b>\n\n"
        f"Нажми на аксессуар, чтобы надеть его:"
    )
    safe_edit_or_send(call.message.chat.id, call.message.message_id, text,
                     reply_markup=inventory_kb(user_id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("wear_"))
def cb_wear(call: CallbackQuery):
    """Надеть аксессуар"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    item = call.data.replace("wear_", "")
    
    pet_inventory = db_get_pet_inventory(user_id)

    if item in pet_inventory:
        # Снимаем
        db_update_pet_value(user_id, "PetInventory", json.dumps([]))
        with open(IMG_CAT, "rb") as img:
            bot.send_photo(call.message.chat.id, img, caption="✅ Аксессуар снят", reply_markup=(InlineKeyboardMarkup()
                            .add(InlineKeyboardButton("🐾 Статус", callback_data="status"))
                            .add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))))
    else:
        # Надеваем
        db_add_pet_item(user_id, item)
        img = composite_cat_image(accessory=item)
        bot.send_photo(call.message.chat.id, img, caption="✅ Аксессуар надет", reply_markup=((InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("📰 Новости", callback_data="news_menu"))
                         .add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))))
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status")))
    
    cb_inventory(call)

@bot.callback_query_handler(func=lambda c: c.data == "news_menu")
def cb_news_menu(call: CallbackQuery):
    """Меню новостей"""
    bot.answer_callback_query(call.id)

    pet_inventory = db_get_pet_inventory(call.from_user.id)
    
    if not pet_inventory:
        bot.send_message(call.message.chat.id, "❌ У вас нет аксессуаров! Купите их в магазине, чтобы открывать новости.", 
                          reply_markup=((InlineKeyboardMarkup()
                          .add(InlineKeyboardButton("🏪 Магазин", callback_data="shop"))
                          .add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))))
                          .add(InlineKeyboardButton("🐾 Статус", callback_data="status")))
        return
    text = "📰 Давайте почитаем что происходит в мире!\n\n📌 Выбери источник новостей:"
    safe_edit_or_send(call.message.chat.id, call.message.message_id, text,
                     reply_markup=news_menu_kb(call.from_user.id))

async def _fetch_news_and_update(user_id: str, source: str):
    """Получить новости и обновить питомца"""
    try:
        news_list = await get_news_with_reaction(count=1, source=source)
        return news_list
    except Exception as e:
        logger.error(f"❌ Ошибка новостей: {e}")
        return []

def _send_news_async(chat_id: int, user_id: str, source: str, call: CallbackQuery = None):
    """Отправить новости (обёртка для async)"""
    user_id_str = str(user_id)
    pet = db_get_pet(user_id_str)
    
    if not pet:
        bot.send_message(chat_id, "❌ Питомец не найден")
        return
    
    msg_id = call.message.message_id if call else None
    
    # Получаем новости
    try:
        news_list = asyncio.run(_fetch_news_and_update(user_id_str, source))
    except Exception as e:
        logger.error(f"Error: {e}")
        bot.send_message(chat_id, f"❌ Ошибка: {str(e)[:100]}")
        return
    
    if not news_list:
        bot.send_message(chat_id, "🤷 Новостей не найдено")
        return
    
    # Обновляем настроение
    total_mood_change = 0
    for n in news_list:
        total_mood_change += n.get("mood_change", 0)
    
    pet = db_apply_minus(user_id_str, mood_n=-total_mood_change)
    

    # Формируем текст
    source_icon = {
        "ria": "📰",
        "stopgame": "🎮",
        "forbes": "💰",
        "mix": "🔄"
    }.get(source, "📰")
    
    is_positive = total_mood_change > 0
    sign = "📈" if is_positive else "📉"
    mood_str = f"+{total_mood_change}" if total_mood_change >= 0 else str(total_mood_change)
    
    lines = [
        f"{source_icon} <b>Новости</b>\n",
        f"🐾 <b>{pet['name']}</b> {mood_emoji(pet['mood'])}\n",
    ]
    
    for n in news_list:
        title_safe = n['title'][:80]
        reaction = n['reaction']
        lines.append(f"<b>{title_safe}</b>")
        lines.append(f"<i>{reaction}</i>\n")
    
    lines.append(f"\n{sign} Настроение: {mood_str} → {pet['mood']}/100")
    
    text = "\n".join(lines)
    
    if msg_id:
        safe_edit_or_send(chat_id, msg_id, text, reply_markup=(InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("📰 Новости", callback_data="news_menu"))
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status"))))
    else:
        bot.send_message(chat_id, text, reply_markup=(InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("📰 Новости", callback_data="news_menu"))
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status"))))

@bot.callback_query_handler(func=lambda c: c.data.startswith("news_"))
def cb_news(call: CallbackQuery):
    """Получить новости"""

    pet_inventory = db_get_pet_inventory(call.message.chat.id)

    available_sources = {
        "finance": ["ria_finance", "ria_politics", "forbes", "mix"],
        "gaming": ["stopgame"],
    }

    bot.answer_callback_query(call.id)
    source = call.data.replace("news_", "")

    if not pet_inventory  or pet_inventory[0] == "weather" or source not in available_sources[pet_inventory[0]]:  # Проверяем, что источник доступен для текущего аксессуара
        safe_edit_or_send(call.message.chat.id, call.message.message_id, "❌ Этот источник недоступен. Купите соответствующий аксессуар в магазине или наденьте его.", 
                          reply_markup=(InlineKeyboardMarkup()
                          .add(InlineKeyboardButton("🏪 Магазин", callback_data="shop"))
                          .add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))))
        return
        
    safe_edit_or_send(call.message.chat.id, call.message.message_id, "⏳ Получаем новости...", reply_markup=None)
    _send_news_async(call.message.chat.id, call.from_user.id, source, call)

def _send_weather_async(chat_id: int, user_id: str, call: CallbackQuery = None):
    """Отправить погоду (обёртка для async)"""
    user_id_str = str(user_id)
    pet = db_get_pet(user_id_str)
    
    if not pet:
        bot.send_message(chat_id, "❌ Питомец не найден")
        return
    
    pet_inventory = db_get_pet_inventory(call.message.chat.id)

    bot.answer_callback_query(call.id)

    if not pet_inventory or pet_inventory[0] != "weather":  # Проверяем, что источник доступен для текущего аксессуара
        safe_edit_or_send(call.message.chat.id, call.message.message_id, "❌ Этот источник недоступен. Купите соответствующий аксессуар в магазине или наденьте его.", 
                          reply_markup=(InlineKeyboardMarkup()
                          .add(InlineKeyboardButton("🏪 Магазин", callback_data="shop"))
                          .add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))))
        return

    msg_id = call.message.message_id if call else None
    
    # Получаем погоду
    try:
        
        weather_data = asyncio.run(get_weather_reaction())
    except Exception as e:
        logger.error(f"Weather error: {e}")
        bot.send_message(chat_id, f"❌ Ошибка погоды: {str(e)[:100]}")
        return
    
    # Обновляем настроение
    pet = db_apply_minus(user_id_str, mood_n=-weather_data.get("mood_change", 0))
    
    # Формируем текст
    is_positive = weather_data.get("is_positive", False)
    sign = "📈" if is_positive else "📉"
    mood_str = f"+{weather_data.get('mood_change', 0)}" if weather_data.get('mood_change', 0) >= 0 else str(weather_data.get('mood_change', 0))
    
    emoji = "☀️" if weather_data.get("is_sunny") else "🌧️" if weather_data.get("is_rain") else "⛅"
    
    text = (
        f"{emoji} <b>Погода в Ростове-на-Дону</b>\n\n"
        f"🌡️ Температура: {weather_data.get('temp')}°C (ощущается {weather_data.get('feels_like')}°C)\n"
        f"💨 Ветер: {weather_data.get('wind')} м/с\n"
        f"💧 Влажность: {weather_data.get('humidity')}%\n\n"
        f"<b>{pet['name']}</b> говорит: <i>{weather_data.get('reaction', 'Хм...')}</i>\n\n"
        f"{sign} Настроение: {mood_str} → {pet['mood']}/100 {mood_emoji(pet['mood'])}"
    )
    
    if msg_id:
        safe_edit_or_send(chat_id, msg_id, text, reply_markup=(InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("📰 Новости", callback_data="news_menu"))
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status"))))
    else:
        bot.send_message(chat_id, text, reply_markup=(InlineKeyboardMarkup()
                         .add(InlineKeyboardButton("📰 Новости", callback_data="news_menu"))
                         .add(InlineKeyboardButton("🐾 Статус", callback_data="status"))))

@bot.callback_query_handler(func=lambda c: c.data == "weather")
def cb_weather(call: CallbackQuery):
    """Получить информацию о погоде"""
    bot.answer_callback_query(call.id)
    _send_weather_async(call.message.chat.id, call.from_user.id, call)

@bot.callback_query_handler(func=lambda c: c.data == "confirm_delete_pet")
def cb_confirm_delete(call: CallbackQuery):
    """Подтвердить удаление питомца"""
    bot.answer_callback_query(call.id)
    user_id = str(call.from_user.id)
    
    if db_delete_pet(user_id):
        bot.send_message(call.message.chat.id, "✅ Питомец удален. Используй /start для создания нового")
    else:
        bot.send_message(call.message.chat.id, "❌ Ошибка при удалении")

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(call: CallbackQuery):
    """Отмена"""
    bot.answer_callback_query(call.id)
    cb_menu(call)

# ── Основной loop ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    start_background_tasks(bot)
    logger.info("🚀 кит бот запущен...")
    bot.infinity_polling(logger_level=logging.INFO)
