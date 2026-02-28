"""
Modules/news_module.py — модуль новостей и погоды для тамагочи
✅ Источники: Forbes (финансы), StopGame (игры), RIA (политика/финансы)
✅ AI: Groq API с эмоциональными реакциями
✅ Погода: Open-Meteo (Ростов-на-Дону)
✅ Локальный fallback при ошибке API
✅ Скрытые логи (только DEBUG)

Зависимости:
  pip install httpx beautifulsoup4 python-dotenv
"""

import re
import json
import logging
import os
import random
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup
from typing import Set, List, Optional
from urllib.parse import urljoin

# ── Загрузка .env ───────────────────────────────────────────────────────────
load_dotenv()
logger = logging.getLogger(__name__)

# ── Groq API ────────────────────────────────────────────────────────────────
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("groq_api_key") or ""

if GROQ_API_KEY:
    logger.debug(f"✅ Groq API ключ загружен ({GROQ_MODEL})")

# ── Источники новостей ─────────────────────────────────────────────────────
SOURCES = {
    "forbes": {
        "url": "https://www.forbes.ru/finansy/",
        "domain": "forbes.ru",
        "keywords": ['финанс', 'экономика', 'банк', 'инвест', 'бизнес', 'компани',
                    'рынок', 'акции', 'доход', 'прибыль', 'кризис', 'курс',
                    'налог', 'бюджет', 'доллар', 'рубль', 'евро'],
    },
    "stopgame": {
        "url": "https://stopgame.ru/news",
        "domain": "stopgame.ru",
    },
    "ria_finance": {
        "url": "https://ria.ru/",
        "domain": "ria.ru",
        "keywords": ['финанс', 'экономика', 'банк', 'рубль', 'доллар', 'евро',
                    'курс', 'инфляция', 'ставка', 'бюджет', 'налог', 'цена',
                    'рынок', 'акции', 'инвест', 'прибыль', 'бизнес'],
    },
    "ria_politics": {
        "url": "https://ria.ru/politics/",
        "domain": "ria.ru",
        "keywords": ['политика', 'президент', 'правительство', 'закон', 'выбор',
                    'министр', 'депутат', 'госдума', 'сенат', 'дипломат',
                    'совет', 'указ', 'постановление', 'реформа'],
    },
}

# ── Погода: Ростов-на-Дону ─────────────────────────────────────────────────
ROSTOV_LAT = 47.2357
ROSTOV_LON = 39.7015
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

# ── История уникальности ───────────────────────────────────────────────────
_seen_news: Set[str] = set()
MAX_SEEN = 200

# ── Игнорируемые темы (военные) ────────────────────────────────────────────
IGNORE_KEYWORDS = [
    'пво сбила', 'беспилотник сбит', 'воздушная тревога',
    'обстрел города', 'ракетный удар', 'спецоперация',
]


# ── Утилиты ────────────────────────────────────────────────────────────────

def _should_ignore(title: str) -> bool:
    """Проверяет, нужно ли игнорировать новость"""
    t = title.lower()
    return any(kw in t for kw in IGNORE_KEYWORDS)


def _is_duplicate(title: str) -> bool:
    """Проверяет дубликаты"""
    normalized = " ".join(title.lower().split())
    if normalized in _seen_news:
        return True
    _seen_news.add(normalized)
    if len(_seen_news) > MAX_SEEN:
        _seen_news.pop()
    return False


def _normalize_url(base: str, href: str) -> Optional[str]:
    """Приводит URL к абсолютному"""
    if not href:
        return None
    clean = href.split("?")[0].split("#")[0]
    if clean.startswith("http"):
        return clean
    return urljoin(base, clean)


# ── ✅ Парсер Forbes.ru/finansy ────────────────────────────────────────────

async def fetch_forbes(count: int) -> List[dict]:
    """Парсит новости с Forbes.ru/finansy"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    config = SOURCES["forbes"]
    base_url = "https://www.forbes.ru"
    
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            r = await client.get(config["url"], headers=headers)
            if r.status_code != 200:
                return []
            r.raise_for_status()
    except Exception as e:
        logger.debug(f"[Forbes] HTTP Error: {e}")
        return []
    
    soup = BeautifulSoup(r.text, 'html.parser')
    items = []
    seen_urls: Set[str] = set()
    
    # Широкий поиск + фильтрация по URL
    for a in soup.find_all("a", href=True, string=True):
        if len(items) >= count:
            break
        
        title = a.get_text(strip=True)
        href = a["href"]
        
        # Базовые фильтры
        if not title or len(title) < 15 or len(title) > 250:
            continue
        if _is_duplicate(title) or _should_ignore(title):
            continue
        if any(bad in title.lower() for bad in ['реклама', 'партнёр', 'спонсор', 'promo', 'подписка']):
            continue
        
        url = _normalize_url(base_url, href)
        if not url or config["domain"] not in url or url in seen_urls:
            continue
        # Только статьи из /news/ или /finansy/
        if '/news/' not in url and '/finansy/' not in url:
            continue
        
        # Фильтр по ключевым словам (финансы)
        if config.get("keywords"):
            text_lower = title.lower()
            if not any(kw in text_lower for kw in config["keywords"]):
                continue
        
        seen_urls.add(url)
        items.append({"title": title, "url": url, "summary": "", "source": "forbes"})
        logger.debug(f"[Forbes] ✅ {title[:50]}...")
    
    logger.info(f"[Forbes] Найдено: {len(items)} новостей")
    return items[:count]


# ── ✅ Парсер StopGame.ru ─────────────────────────────────────────────────

async def fetch_stopgame(count: int) -> List[dict]:
    headers = {"User-Agent": "Mozilla/5.0 TamagotchiBot/1.0"}
    config = SOURCES["stopgame"]
    base_url = "https://stopgame.ru"
    
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(config["url"], headers=headers)
            r.raise_for_status()
    except Exception as e:
        logger.debug(f"[StopGame] HTTP Error: {e}")
        return []
    
    soup = BeautifulSoup(r.text, 'html.parser')
    items = []
    seen_urls: Set[str] = set()

    # 🔍 ВРЕМЕННЫЙ ДЕБАГ — убери после проверки
    for a in soup.find_all("a", href=True, string=True)[:40]:
        print(f"HREF: {a['href']!r:50} | TEXT: {a.get_text(strip=True)[:50]!r}")
    
    for a in soup.find_all("a", href=True, string=True):
        if len(items) >= count:
            break
        
        title = a.get_text(strip=True)
        href = a["href"]
        
        if not title or len(title) < 20 or len(title) > 250:
            continue
        if _is_duplicate(title):
            continue
        
        url = _normalize_url(base_url, href)
        if not url or config["domain"] not in url or url in seen_urls:
            continue
        if any(bad in title.lower() for bad in ['реклама', 'vk.com', 't.me', 'youtube']):
            continue
        
        seen_urls.add(url)
        items.append({"title": title, "url": url, "summary": "", "source": "stopgame"})
        logger.debug(f"[StopGame] ✅ {title[:50]}...")
    
    logger.info(f"[StopGame] Найдено: {len(items)} новостей")
    return items[:count]

# ── ✅ Парсер RIA (универсальный для finance/politics) ─────────────────────

async def fetch_ria_finance(count: int) -> List[dict]:
    """Парсит RIA.ru — финансы/экономика"""
    return await _fetch_ria_generic(count, "ria_finance")


async def fetch_ria_politics(count: int) -> List[dict]:
    """Парсит RIA.ru/politics — политика"""
    return await _fetch_ria_generic(count, "ria_politics")


async def _fetch_ria_generic(count: int, source_key: str) -> List[dict]:
    """Общий парсер для RIA источников"""
    headers = {"User-Agent": "Mozilla/5.0 TamagotchiBot/1.0"}
    config = SOURCES[source_key]
    base_url = config["url"]
    keywords = config.get("keywords", [])
    
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(base_url, headers=headers)
            r.raise_for_status()
    except Exception as e:
        logger.debug(f"[{source_key}] HTTP Error: {e}")
        return []
    
    soup = BeautifulSoup(r.text, 'html.parser')
    items = []
    seen_urls: Set[str] = set()
    
    for a in soup.find_all("a", href=True, string=True):
        if len(items) >= count:
            break
        
        title = a.get_text(strip=True)
        href = a["href"]
        
        if not title or len(title) < 20 or len(title) > 250:
            continue
        if _is_duplicate(title) or _should_ignore(title):
            continue
        
        url = _normalize_url(base_url, href)
        if not url or config["domain"] not in url or url in seen_urls:
            continue
        
        # Фильтр по ключевым словам
        if keywords:
            text_lower = title.lower()
            if not any(kw in text_lower for kw in keywords):
                continue
        
        seen_urls.add(url)
        items.append({"title": title, "url": url, "summary": "", "source": source_key})
    
    logger.info(f"[{source_key}] Найдено: {len(items)} новостей")
    return items[:count]


# ── 🌤️ Погода (Open-Meteo) ────────────────────────────────────────────────

async def fetch_weather() -> dict:
    """Получает погоду для Ростова-на-Дону"""
    params = {
        "latitude": ROSTOV_LAT,
        "longitude": ROSTOV_LON,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "timezone": "Europe/Moscow",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(WEATHER_API, params=params)
        r.raise_for_status()
        data = r.json()
    
    current = data["current"]
    code = current["weather_code"]
    
    return {
        "temp": current["temperature_2m"],
        "feels_like": current["apparent_temperature"],
        "humidity": current["relative_humidity_2m"],
        "wind": current["wind_speed_10m"],
        "weather_code": code,
        "is_sunny": code in [0, 1],
        "is_rain": code in [51, 53, 55, 61, 63, 65, 80, 81, 82, 95],
    }


# ── 🎭 Локальный AI fallback — КРЕАТИВНЫЕ реакции ─────────────────────────

_CREATIVE_REACTIONS = {
    "positive": [
        "Ура! Это просто потрясающе! 🎉 Хочу танцевать!",
        "Ого! Мир становится лучше! ✨",
        "Как здорово! Теперь у меня есть повод для радости! 🌟",
        "Вау! Это вдохновляет! Хочу свернуть горы! 💪",
        "Супер! Прямо зарядился позитивом! ⚡",
        "Обожаю такие новости! 🥰",
        "Это лучшая новость за сегодня! 🏆",
    ],
    "negative": [
        "Ой... как же это грустно... 💔 Хочется обнимашек",
        "Эх... мир иногда бывает таким сложным... 😔",
        "Бедняжка... надеюсь, всё наладится... 🫂",
        "Как жаль... хочется помочь, но я всего лишь котик... 🐾",
        "Ох... это тяжело слышать... 💙",
        "Грустно... но мы справимся! Вместе! ✊",
        "Не хочу, чтобы так было... 🥺",
    ],
    "neutral": [
        "Хм... интересно, что будет дальше? 🤔",
        "Запомню это... может пригодиться! 📝",
        "Любопытно... расскажи ещё! 👂",
        "Ого, новость! Надо обдумать... 🧠",
        "Звучит важно... спасибо, что поделился! 🙏",
        "Принято к сведению! 📋",
    ],
}


def _local_ai_reaction(text: str, prompt_type: str = "news") -> dict:
    """Локальная реакция с КРЕАТИВНЫМИ ответами (fallback при ошибке Groq)"""
    t = text.lower()
    
    if prompt_type == "weather":
        if "солнечно" in t or any(f"{x}°c" in t for x in range(22, 30)):
            return {
                "reaction": random.choice(_CREATIVE_REACTIONS["positive"][:3]),
                "mood_change": random.randint(12, 18),
                "is_positive": True
            }
        elif "дожд" in t or "снег" in t:
            return {
                "reaction": random.choice(_CREATIVE_REACTIONS["negative"][:3]),
                "mood_change": random.randint(-12, -6),
                "is_positive": False
            }
        elif any(f"{x}°c" in t for x in range(-10, 5)):
            return {
                "reaction": "Брр, холодно! Хочу под одеялко и горячий чай! ❄️☕",
                "mood_change": random.randint(-10, -5),
                "is_positive": False
            }
        else:
            return {
                "reaction": random.choice(_CREATIVE_REACTIONS["neutral"]),
                "mood_change": random.randint(2, 6),
                "is_positive": True
            }
    
    # Для новостей — эмоциональная логика
    positive = [
        'рост', 'успех', 'победа', 'помощ', 'развит', 'инвест', 'доход', 'прибыль',
        'спас', 'нашёл', 'откры', 'снизил', 'поддерж', 'хорош', 'рад', 'рекорд', 'выгод',
        'прорыв', 'достиж', 'благодар', 'праздник', 'подар', 'запусти', 'стартов'
    ]
    negative = [
        'паден', 'кризис', 'убыток', 'потер', 'авар', 'смерт', 'конфликт', 'войн',
        'угроз', 'проблем', 'ошиб', 'отказ', 'подорож', 'инфляц', 'сокращ', 'запрет', 'крах',
        'трагед', 'катастроф', 'преступ', 'нападен'
    ]
    
    pos = sum(2 if kw in t else 0 for kw in positive)
    neg = sum(2 if kw in t else 0 for kw in negative)
    
    # Добавляем вариативность
    if '!' in text:
        pos += 1
    if '?' in text:
        neg += 1
    
    if pos > neg + 2:
        return {
            "reaction": random.choice(_CREATIVE_REACTIONS["positive"]),
            "mood_change": random.randint(10, 20),
            "is_positive": True
        }
    elif neg > pos + 2:
        return {
            "reaction": random.choice(_CREATIVE_REACTIONS["negative"]),
            "mood_change": random.randint(-20, -8),
            "is_positive": False
        }
    else:
        # Нейтральные — но с небольшой случайной окраской
        if random.random() < 0.6:
            return {
                "reaction": random.choice(_CREATIVE_REACTIONS["neutral"]),
                "mood_change": random.randint(3, 8),
                "is_positive": True
            }
        else:
            return {
                "reaction": random.choice(_CREATIVE_REACTIONS["negative"][-2:]),
                "mood_change": random.randint(-6, -2),
                "is_positive": False
            }


# ── ✅ Groq API — эмоциональный промпт ─────────────────────────────────────

async def analyze_with_groq(text: str, prompt_type: str = "news") -> dict:
    """Анализ через Groq API с КРЕАТИВНЫМ промптом"""
    
    if not GROQ_API_KEY:
        logger.debug("[Groq] Нет ключа → локальный AI")
        return _local_ai_reaction(text, prompt_type)
    
    # 🎭 ПРОМПТ для ярких, эмоциональных реакций
    system_prompt = (
        "Ты — игривый, эмоциональный питомец-тамагочи. Твоя задача — реагировать на новости ЖИВО и КРЕАТИВНО!\n\n"
        "ОТВЕЧАЙ ТОЛЬКО В ФОРМАТЕ JSON (без markdown, без пояснений):\n"
        '{\n'
        '  "reaction": "1 предложение от первого лица, ЭМОЦИОНАЛЬНОЕ и МИЛОЕ",\n'
        '  "mood_change": число_от_-20_до_20,\n'
        '  "is_positive": true_или_false\n'
        '}\n\n'
        "🎯 ПРАВИЛА РЕАКЦИЙ:\n"
        "• Будь живым: используй 'Ура!', 'Ой...', 'Вау!', 'Хм...', 'Обожаю!', 'Не хочу...'\n"
        "• Добавляй эмоции: '🎉', '💔', '✨', '🥰', '😢', '💪'\n"
        "• Говори как маленький зверёк: просто, искренне, с душой\n"
        "• НЕ будь нейтральным! Питомец ДОЛЖЕН реагировать!\n\n"
        "📊 ШКАЛА НАСТРОЕНИЯ:\n"
        "• Очень позитив (+12..+20): 'Ура! Это потрясающе! 🎉', 'Обожаю такие новости! ✨'\n"
        "• Позитив (+5..+11): 'Как здорово! 🌟', 'Зарядился позитивом! ⚡'\n"
        "• Негатив (-5..-11): 'Ой, как грустно... 💙', 'Надеюсь, всё наладится 🫂'\n"
        "• Очень негативно (-12..-20): 'Бедняжка... 💔', 'Не хочу, чтобы так было... 🥺'\n"
        "• ⚠️ mood_change НЕ должен быть 0! Всегда выбирай сторону!\n"
        "• is_positive = true ТОЛЬКО если mood_change > 0\n\n"
        "💡 ПРИМЕРЫ ОТВЕТОВ:\n"
        '{"reaction": "Ура! Теперь смогу купить вкусняшку! 🎉", "mood_change": 15, "is_positive": true}\n'
        '{"reaction": "Ой... как же это грустно... 💔", "mood_change": -12, "is_positive": false}\n'
        '{"reaction": "Хм... интересно, что будет дальше? 🤔", "mood_change": 4, "is_positive": true}'
    )
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Проанализируй новость:\n\n{text}"}
        ],
        "temperature": 0.9,  # ✅ Выше = креативнее
        "max_tokens": 180,
        "response_format": {"type": "json_object"},  # ✅ Гарантирует JSON
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(GROQ_API_URL, json=payload, headers=headers)
            
            # Обработка ошибок — ТОЛЬКО debug логи
            if r.status_code in [401, 403, 429]:
                logger.debug(f"[Groq] {r.status_code} → локальный AI")
                return _local_ai_reaction(text, prompt_type)
            if r.status_code != 200:
                logger.debug(f"[Groq] HTTP {r.status_code} → локальный AI")
                return _local_ai_reaction(text, prompt_type)
            
            data = r.json()
            raw = data["choices"][0]["message"]["content"].strip()
            
    except Exception as e:
        logger.debug(f"[Groq] Error: {e}")
        return _local_ai_reaction(text, prompt_type)
    
    # Парсинг JSON
    try:
        json_match = re.search(r'\{[\s\S]*\}', raw)
        result = json.loads(json_match.group() if json_match else raw)
        
        mood = int(result.get("mood_change", 0))
        mood = max(-20, min(20, mood))
        
        # Если AI вернул 0 — заменяем на ненулевое
        if mood == 0:
            mood = random.choice([-5, -3, 3, 5, 8])
        
        is_pos = bool(result.get("is_positive", mood > 0))
        if mood > 0:
            is_pos = True
        elif mood < 0:
            is_pos = False
        
        reaction = str(result.get("reaction", "Хмм...")).strip()
        reaction = reaction[:130] if len(reaction) > 130 else reaction
        
        return {"reaction": reaction, "mood_change": mood, "is_positive": is_pos}
        
    except Exception as e:
        logger.debug(f"[Groq] Parse error → локальный AI")
        return _local_ai_reaction(text, prompt_type)


# ── 🎯 MAIN функции (экспортируются в bot.py) ─────────────────────────────

async def get_news_with_reaction(count: int = 1, source: str = "forbes") -> List[dict]:
    """
    Получает новости и анализирует через AI.
    
    Args:
        count: количество новостей (1-10)
        source: "forbes", "stopgame", "ria_finance", "ria_politics" или "mix"
    
    Returns:
        Список: [{"title", "url", "summary", "source", "reaction", "mood_change", "is_positive"}, ...]
    """
    count = max(1, min(count, 10))
    
    fetchers = {
        "forbes": fetch_forbes,
        "stopgame": fetch_stopgame,
        "ria_finance": fetch_ria_finance,
        "ria_politics": fetch_ria_politics,
    }
    
    if source == "mix":
        news = []
        del fetchers["stopgame"]  # Убираем StopGame из микса, так как там часто новости не по теме
        for name, fetcher in fetchers.items():
            try:
                items = await fetcher(max(1, count // 4))
                news.extend(items)
            except Exception as e:
                logger.debug(f"[{name}] Error: {e}")
        news = news[:count]
    else:
        fetcher = fetchers.get(source, fetch_forbes)
        news = await fetcher(count)
    
    if not news:
        logger.debug(f"[{source}] Нет новостей")
        return []
    
    # Анализ через AI
    results = []
    for n in news:
        try:
            context = f"Заголовок: {n['title']}"
            ai = await analyze_with_groq(context, prompt_type="news")
            results.append({**n, **ai})
        except Exception as e:
            logger.debug(f"[AI] Error: {e}")
            ai = _local_ai_reaction(n["title"], prompt_type="news")
            results.append({**n, **ai})
    
    return results


async def get_weather_reaction() -> dict:
    """
    Получает погоду и анализирует через AI.
    
    Returns:
        dict: {"temp", "feels_like", "humidity", "wind", "weather_code",
               "is_sunny", "is_rain", "reaction", "mood_change", "is_positive"}
    """
    weather = await fetch_weather()
    context = (
        f"Температура: {weather['temp']}°C, "
        f"Погода: {'солнечно' if weather['is_sunny'] else 'дождь' if weather['is_rain'] else 'облачно'}"
    )
    ai = await analyze_with_groq(context, prompt_type="weather")
    return {**weather, **ai}


# ── Утилита: очистка истории ──────────────────────────────────────────────

def clear_news_history():
    """Очищает историю просмотренных новостей"""
    global _seen_news
    _seen_news.clear()
    logger.debug("[CLEANUP] История очищена")