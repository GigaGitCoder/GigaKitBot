"""
tasks.py — фоновые задачи для бота (периодические проверки)
- Каждый час: снижение сытости (-10) и настроения (-5)
- Каждые 30 минут: восстановление энергии (10 * сытость%)
- Каждые 2 часа: проверка низких показателей
- Каждые 4 часа: обновление по новостям (Пока не реализовано)

Флаги предупреждений (в таблице pets):
  warned_satiety INTEGER DEFAULT 0
  warned_mood    INTEGER DEFAULT 0
  warned_energy  INTEGER DEFAULT 0

Добавить в схему БД (если ещё не добавлены):
  ALTER TABLE pets ADD COLUMN warned_satiety INTEGER DEFAULT 0;
  ALTER TABLE pets ADD COLUMN warned_mood    INTEGER DEFAULT 0;
  ALTER TABLE pets ADD COLUMN warned_energy  INTEGER DEFAULT 0;
"""

import asyncio
import logging
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


def get_db_connection():
    """Получает подключение к БД"""
    conn = sqlite3.connect("pets.db")
    conn.row_factory = sqlite3.Row
    return conn


def clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    """Ограничивает значение в диапазоне"""
    return max(lo, min(hi, value))


def ensure_warn_columns():
    """
    Добавляет колонки warned_* если их ещё нет.
    Безопасно вызывать при каждом старте бота.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for col in ("warned_satiety", "warned_mood", "warned_energy"):
            try:
                cur.execute(f"ALTER TABLE pets ADD COLUMN {col} INTEGER DEFAULT 0")
                conn.commit()
                logger.info(f"Добавлена колонка {col}")
            except sqlite3.OperationalError:
                pass  # колонка уже существует
    finally:
        conn.close()


def set_warned_flags(user_id: str, **flags):
    """
    Обновляет флаги предупреждений для пользователя.
    Пример: set_warned_flags(user_id, warned_satiety=1, warned_mood=0)
    """
    if not flags:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in flags)
        values = list(flags.values()) + [user_id]
        cur.execute(f"UPDATE pets SET {set_clause} WHERE user_id = ?", values)
        conn.commit()
    finally:
        conn.close()


def apply_hourly_decay(user_id: str):
    """
    Применяет почасовой спад:
    - Сытость: -10
    - Настроение: -5
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT satiety, mood FROM pets WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        
        new_satiety = clamp(row["satiety"] - 10)
        new_mood = clamp(row["mood"] - 5)
        
        cur.execute("""
            UPDATE pets SET satiety = ?, mood = ?, last_satiety_check = ?
            WHERE user_id = ?
        """, (new_satiety, new_mood, datetime.now().isoformat(), user_id))
        conn.commit()
        
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()


def apply_energy_recovery(user_id: str):
    """
    Восстанавливает энергию: 10 * (сытость / 100)
    Работает каждые 30 минут
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT energy, satiety FROM pets WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        
        recovery = int(10 * (row["satiety"] / 100))
        if recovery < 1:
            recovery = 1
        
        new_energy = min(100, row["energy"] + recovery)
        
        cur.execute("""
            UPDATE pets SET energy = ?, last_energy_check = ?
            WHERE user_id = ?
        """, (new_energy, datetime.now().isoformat(), user_id))
        conn.commit()
        
        cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()


def get_all_users() -> list:
    """Получить список всех user_id"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM pets")
        return [row["user_id"] for row in cur.fetchall()]
    finally:
        conn.close()


def get_users_with_low_stat(stat: str, threshold: int) -> list:
    """Получить user_id у кого низкий показатель"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = f"SELECT user_id FROM pets WHERE {stat} < ?"
        cur.execute(query, (threshold,))
        return [row["user_id"] for row in cur.fetchall()]
    finally:
        conn.close()


# ── Фоновые задачи ─────────────────────────────────────────────────────────────

async def task_hourly_decay(bot):
    """
    Задача: каждый час снижает сытость (-10) и настроение (-5) всем питомцам.
    Отправляет уведомление если показатели критически низкие.
    Повторное уведомление не отправляется, пока показатель не восстановится.
    """
    while True:
        await asyncio.sleep(3600)  # 1 час ---> 3600 секунд
        logger.info("⏰ [hourly_decay] Применяю почасовой спад...")
        users = get_all_users()
        for user_id in users:
            try:
                pet = apply_hourly_decay(user_id)
                if not pet:
                    continue

                warnings = []
                kb = InlineKeyboardMarkup()
                flag_updates = {}

                # ── Сытость достигла 0 ──────────────────────────────────────
                if pet["satiety"] == 0 and not pet.get("warned_satiety"):
                    warnings.append("🍖 <b>Питомец очень голоден!</b> Сытость: 0/100")
                    kb.add(InlineKeyboardButton("🍖 Покормить", callback_data="feed"))
                    flag_updates["warned_satiety"] = 1
                elif pet["satiety"] > 0 and pet.get("warned_satiety"):
                    # Показатель восстановился — сбрасываем флаг
                    flag_updates["warned_satiety"] = 0

                # ── Настроение достигло 0 ───────────────────────────────────
                if pet["mood"] == 0 and not pet.get("warned_mood"):
                    warnings.append("😭 <b>Питомец очень грустит!</b> Настроение: 0/100")
                    kb.add(InlineKeyboardButton("🎮 Поиграть", callback_data="play"))
                    flag_updates["warned_mood"] = 1
                elif pet["mood"] > 0 and pet.get("warned_mood"):
                    flag_updates["warned_mood"] = 0

                # Сохраняем изменённые флаги
                if flag_updates:
                    set_warned_flags(user_id, **flag_updates)

                if warnings:
                    text = f"⚠️ <b>{pet['name']}</b> нуждается в вашем внимании!\n\n" + "\n".join(warnings)
                    try:
                        await bot.send_message(int(user_id), text, reply_markup=kb)
                    except Exception as e:
                        logger.warning(f"Не удалось отправить уведомление {user_id}: {e}")
            except Exception as e:
                logger.error(f"[hourly_decay] Ошибка для {user_id}: {e}")


async def task_energy_recovery(bot):
    """
    Задача: каждые 30 минут восстанавливает энергию всем питомцам.
    Восстановление: 10 * (сытость / 100), минимум 1.
    """
    while True:
        await asyncio.sleep(1800)  # 30 минут ---> 1800 cекунд
        logger.info("⚡ [energy_recovery] Восстанавливаю энергию...")
        users = get_all_users()
        for user_id in users:
            try:
                apply_energy_recovery(user_id)
            except Exception as e:
                logger.error(f"[energy_recovery] Ошибка для {user_id}: {e}")


async def task_check_low_stats(bot):
    """
    Задача: каждые 2 часа проверяет низкие показатели и отправляет напоминание.
    Повторное уведомление не отправляется, пока показатель не восстановится выше порога.
    """
    while True:
        await asyncio.sleep(7200)  # 2 часа ---> 7200 секунд
        logger.info("🔍 [check_low_stats] Проверяю низкие показатели...")

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT user_id, name, satiety, energy, mood,
                       warned_satiety, warned_mood, warned_energy
                FROM pets
                WHERE satiety < 30 OR energy < 20 OR mood < 30
            """)
            rows = cur.fetchall()
        finally:
            conn.close()

        for row in rows:
            user_id = row["user_id"]
            pet = dict(row)
            alerts = []
            kb = InlineKeyboardMarkup()
            flag_updates = {}

            # ── Сытость ──────────────────────────────────────────────────────
            if 0 < pet["satiety"] <= 30:
                if not pet.get("warned_satiety"):
                    alerts.append(f"🍖 Сытость: {pet['satiety']}/100 — ГОЛОДАЕТ!")
                    kb.add(InlineKeyboardButton("🍖 Покормить", callback_data="feed"))
                    flag_updates["warned_satiety"] = 1
            else:
                # Выше порога — сбрасываем флаг чтобы следующее падение снова триггернуло
                if pet.get("warned_satiety"):
                    flag_updates["warned_satiety"] = 0

            # ── Настроение ───────────────────────────────────────────────────
            if 0 < pet["mood"] <= 30:
                if not pet.get("warned_mood"):
                    alerts.append(f"😟 Настроение: {pet['mood']}/100 — ГРУСТИТ!")
                    kb.add(InlineKeyboardButton("🎮 Поиграть", callback_data="play"))
                    flag_updates["warned_mood"] = 1
            else:
                if pet.get("warned_mood"):
                    flag_updates["warned_mood"] = 0

            # ── Энергия ──────────────────────────────────────────────────────
            if 0 < pet["energy"] <= 20:
                if not pet.get("warned_energy"):
                    alerts.append(f"⚡ Энергия: {pet['energy']}/100 — УСТАЛ!")
                    flag_updates["warned_energy"] = 1
            else:
                if pet.get("warned_energy"):
                    flag_updates["warned_energy"] = 0

            # Сохраняем изменённые флаги
            if flag_updates:
                set_warned_flags(user_id, **flag_updates)

            if alerts:
                text = f"⚠️ <b>{pet['name']}</b> не в порядке!\n\n" + "\n".join(alerts)
                try:
                    await bot.send_message(int(user_id), text, reply_markup=kb)
                except Exception as e:
                    logger.warning(f"Не удалось отправить уведомление {user_id}: {e}")


def start_background_tasks(bot):
    """
    Запускает все фоновые задачи в отдельных потоках через asyncio.
    Вызывается из bot.py перед запуском polling.
    """
    import threading

    # Убеждаемся, что колонки warned_* существуют в БД
    ensure_warn_columns()

    def run_task(coro_factory):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro_factory())

    tasks = [
        lambda: task_hourly_decay(bot),
        lambda: task_energy_recovery(bot),
        lambda: task_check_low_stats(bot),
    ]

    task_names = ["hourly_decay", "energy_recovery", "check_low_stats"]
    for task, name in zip(tasks, task_names):
        t = threading.Thread(target=run_task, args=(task,), daemon=True, name=name)
        t.start()
        logger.info(f"✅ Фоновая задача запущена: {name}")
