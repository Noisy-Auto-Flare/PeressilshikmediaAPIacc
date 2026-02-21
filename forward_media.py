import os
import logging
import sys
from typing import List, Union

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel, MessageMediaWebPage, MessageMediaPoll

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MODE = os.getenv("MODE", "copy")
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() in ("1","true","yes")

SOURCE_CHAT_RAW = os.getenv("SOURCE_CHAT")
TARGET_CHAT_RAW = os.getenv("TARGET_CHAT")

PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = int(os.getenv("PROXY_PORT") or 0)
PROXY_LOGIN = os.getenv("PROXY_LOGIN")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

if not API_ID or not API_HASH or not SOURCE_CHAT_RAW or not TARGET_CHAT_RAW:
    print("Ошибка: проверь .env")
    sys.exit(1)

# Логи
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("forwarder.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

proxy = None
if PROXY_ENABLED and PROXY_HOST and PROXY_PORT:
    proxy = ("socks5", PROXY_HOST, PROXY_PORT, True, PROXY_LOGIN, PROXY_PASSWORD)
    logger.info("Прокси включен: %s:%s", PROXY_HOST, PROXY_PORT)
else:
    logger.info("Прокси отключен")

client = TelegramClient("media_forwarder", API_ID, API_HASH, proxy=proxy)

# -------------------- Функции --------------------

def is_valid_media(msg):
    if not msg or not msg.media:
        return False
    if isinstance(msg.media, (MessageMediaWebPage, MessageMediaPoll)):
        return False
    return True

async def process_message(msg, target, mode="copy"):
    if mode == "forward":
        await client.forward_messages(target, msg)
    else:
        if msg.media:
            await client.send_file(target, msg.media, caption=msg.text or "")
        else:
            await client.send_message(target, msg.text)

async def resolve_entity(name_or_id):
    """
    Попробовать получить input_entity, если не найден → поиск в get_dialogs()
    """
    try:
        entity = await client.get_input_entity(name_or_id)
        return entity
    except:
        logger.warning("Entity %s не найден через get_input_entity(), ищем в диалогах...", name_or_id)
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if str(d.id) == name_or_id or d.name == name_or_id:
                logger.info("Найден в диалогах: %s (%s)", d.name, d.id)
                return d.entity
    raise ValueError(f"Не удалось найти entity {name_or_id}")

# -------------------- Основная логика --------------------

async def main():
    await client.start()
    me = await client.get_me()
    logger.info("Авторизован как %s", me.username or me.first_name)

    # Разбиваем строки на списки
    sources = [s.strip() for s in SOURCE_CHAT_RAW.split(",") if s.strip()]
    targets = [t.strip() for t in TARGET_CHAT_RAW.split(",") if t.strip()]

    if len(sources) != len(targets):
        logger.error("Количество источников и целей не совпадает")
        return

    # Разрешаем entities
    sources_entities = [await resolve_entity(s) for s in sources]
    targets_entities = [await resolve_entity(t) for t in targets]

    # Перебор пар
    for src, tgt in zip(sources_entities, targets_entities):
        logger.info("Источник: %s, Цель: %s", src, tgt)
        # История
        count = 0
        async for msg in client.iter_messages(src, reverse=True):
            if not is_valid_media(msg):
                continue
            try:
                await process_message(msg, tgt, mode=MODE)
                count += 1
            except Exception as e:
                logger.error("Ошибка %s: %s", msg.id, e)
        logger.info("История обработана: %s сообщений", count)

        # Подписка на новые сообщения
        @client.on(events.NewMessage(chats=src))
        async def handler(event):
            msg = event.message
            if not is_valid_media(msg):
                return
            try:
                await process_message(msg, tgt, mode=MODE)
                logger.info("Новое сообщение ID %s", msg.id)
            except Exception as e:
                logger.error("Ошибка нового сообщения %s: %s", msg.id, e)

    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        with client:
            client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем")