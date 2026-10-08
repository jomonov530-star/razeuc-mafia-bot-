from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeDefault
from aiogram.types import CallbackQuery
from aiogram.types import ErrorEvent, Message

from app.config import get_settings
from app.credit import CreditService
from app.keep_alive import keep_alive
from app import premium_emoji
from app.database import SessionLocal, init_db
from app.game_engine import GameEngine
from app.keyboards import mandatory_sub_keyboard
from app.handlers import admin, callbacks, clan, economy, emoji_debug, game, hero, language, para, profile, roles, settings as settings_handler, start, top, monitoring
from app.scheduler import scheduler, shutdown_scheduler, start_scheduler


class DebugLogMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[..., Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            from_user = getattr(event, 'from_user', None)
            uid = getattr(from_user, 'id', None) if from_user else None
            # message text or callback data
            payload = getattr(event, 'text', None) or getattr(event, 'data', None) or str(event)
            logging.info('DEBUG_INCOMING %s from=%s payload=%s', type(event).__name__, uid, payload)
        except Exception:
            logging.exception('Failed to log debug event')
        return await handler(event, data)


class PremiumBlockMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            engine: GameEngine = data["engine"]
            if await engine.is_premium_user_blocked(event.from_user.id):
                try:
                    await event.answer(
                        "🚫 Siz botdan bloklangansiz. Murojaat uchun adminga yozing.",
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
                return None
        return await handler(event, data)


class PremiumBlockCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            engine: GameEngine = data["engine"]
            if await engine.is_premium_user_blocked(event.from_user.id):
                await event.answer("🚫 Siz botdan bloklangansiz.", show_alert=True)
                return None
        return await handler(event, data)


class CreditBlockMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            engine: GameEngine = data["engine"]
            if await engine.is_credit_blocked(event.from_user.id):
                try:
                    await event.answer("🚫 Kredit qarzi muddatida so'ndirilmagani uchun botdan bloklangansiz.")
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
                return None
        return await handler(event, data)


class CreditBlockCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            engine: GameEngine = data["engine"]
            if await engine.is_credit_blocked(event.from_user.id):
                await event.answer("🚫 Kredit qarzi sabab botdan bloklangansiz.", show_alert=True)
                return None
        return await handler(event, data)


class MandatorySubMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            engine: GameEngine = data["engine"]
            bot = event.bot
            is_sub = await engine.check_user_news_subscription(bot, event.from_user.id)
            if not is_sub:
                if event.chat.type == "private":
                    news_url = await engine.get_news_channel_url()
                    try:
                        await event.answer(
                            "⚠️ <b>O'yinni davom ettirish uchun rasmiy kanalimizga obuna bo'ling!</b>\n\n"
                            "📢 Bizning news kanalimizda eng so'nggi yangiliklar, aksiyalar va sovg'alar e'lon qilib boriladi.\n\n"
                            "<i>Obuna bo'lgach, \"✅ Obunani tekshirish\" tugmasini bosing.</i>",
                            reply_markup=mandatory_sub_keyboard(news_url or "https://t.me/WorldMafiaNews"),
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
                    return None
        return await handler(event, data)


class MandatorySubCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            if event.data == "check_subscription" or (event.data and event.data.startswith("owner:")):
                return await handler(event, data)

            engine: GameEngine = data["engine"]
            bot = event.bot
            is_sub = await engine.check_user_news_subscription(bot, event.from_user.id)
            if not is_sub:
                news_url = await engine.get_news_channel_url()
                if event.message and event.message.chat.type == "private":
                    await event.answer("⚠️ Botdan foydalanish uchun rasmiy kanalga obuna bo'ling!", show_alert=True)
                    try:
                        await event.message.edit_text(
                            "⚠️ <b>O'yinni davom ettirish uchun rasmiy kanalimizga obuna bo'ling!</b>\n\n"
                            "📢 Bizning news kanalimizda eng so'nggi yangiliklar, aksiyalar va sovg'alar e'lon qilib boriladi.\n\n"
                            "<i>Obuna bo'lgach, \"✅ Obunani tekshirish\" tugmasini bosing.</i>",
                            reply_markup=mandatory_sub_keyboard(news_url or "https://t.me/WorldMafiaNews"),
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
                else:
                    await event.answer(
                        "⚠️ O'yinda qatnashish uchun rasmiy kanalga obuna bo'ling!\nShaxsiy botimizga kiring va obunani tasdiqlang.",
                        show_alert=True,
                    )
                return None
        return await handler(event, data)


class DeleteGroupCommandMiddleware(BaseMiddleware):
    @staticmethod
    def _is_group_command(message: Message) -> bool:
        if message.chat.type not in {"group", "supergroup"}:
            return False

        entities = list(message.entities or []) + list(message.caption_entities or [])
        if any(entity.type == "bot_command" and entity.offset == 0 for entity in entities):
            return True

        text = message.text or message.caption or ""
        return text.lstrip().startswith("/")

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        should_delete = self._is_group_command(event)
        try:
            return await handler(event, data)
        finally:
            if should_delete:
                try:
                    await event.delete()
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass


class ChatRestrictionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.chat.type != "private" and event.from_user:
            engine: GameEngine = data["engine"]
            allowed = await engine.check_chat_write_permission(
                event.bot, event.chat.id, event.from_user.id
            )
            if not allowed:
                try:
                    await event.delete()
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
                return None
        return await handler(event, data)


async def global_error_handler(event: ErrorEvent) -> bool:
    exc = event.exception
    if isinstance(exc, TelegramForbiddenError):
        logging.warning("Telegram forbidden (bot kicked/blocked): %s", exc)
        return True
    if isinstance(exc, TelegramBadRequest):
        msg = str(exc).lower()
        ignorable = (
            "message to be replied not found",
            "message to delete not found",
            "message to edit not found",
            "message can't be deleted",
            "message is not modified",
            "chat not found",
            "have no rights to send a message",
            "not enough rights",
            "user is deactivated",
            "bot was blocked by the user",
            "query is too old",
        )
        if any(s in msg for s in ignorable):
            logging.warning("Ignoring Telegram error: %s", exc)
            return True
    if isinstance(exc, TelegramRetryAfter):
        logging.warning("Telegram rate-limit: retry after %s", getattr(exc, "retry_after", "?"))
        return True
    return False


async def set_commands(bot: Bot) -> None:
    private_commands = [
        BotCommand(command="start", description="O'yinni boshlash"),
        BotCommand(command="profile", description="Profilingizni ko'rish (Shaxsiy chatda)"),
        BotCommand(command="clan", description="Clan/Guild menyusi"),
        BotCommand(command="roles", description="O'yin rollarini ko'rish"),
    ]
    group_commands = [
        BotCommand(command="start", description="O'yinni boshlash"),
        BotCommand(command="game", description="Ro'yxatdan o'tishni boshlash"),
        BotCommand(command="turnir", description="Turnir o'yinini boshlash"),
        BotCommand(command="leave", description="O'yindan chiqish"),
        BotCommand(command="extend", description="Ro'yxat vaqtini uzaytirish"),
        BotCommand(command="stop", description="O'yinni to'xtatish"),
        BotCommand(command="teamgame", description="Turnir o'yini"),
        BotCommand(command="lastwords", description="O'lim oldi so'zi"),
        BotCommand(command="settings", description="Guruh va o'yin turi sozlamalari"),
        BotCommand(command="settimeout", description="Ro'yxat vaqtini sozlash"),
        BotCommand(command="setnight", description="Tun vaqtini sozlash"),
        BotCommand(command="setdiscussion", description="Kun muhokamasini sozlash"),
        BotCommand(command="setvoting", description="Ovoz berish vaqtini sozlash"),
        BotCommand(command="setminplayers", description="Minimal o'yinchilarni sozlash"),
        BotCommand(command="lang", description="Tilni o'zgartirish"),
        BotCommand(command="profile", description="Profilingiz"),
        BotCommand(command="clan", description="Clan/Guild menyusi"),
        BotCommand(command="shop", description="Do'kon"),
        BotCommand(command="give", description="Almaz berish"),
        BotCommand(command="gsend", description="Premium guruh reytingi"),
        BotCommand(command="roles", description="Rollar"),
        BotCommand(command="top", description="TOP reyting"),
        BotCommand(command="commands", description="Buyruqlar"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    await init_db()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(premium_emoji.PremiumEmojiMiddleware())
    await premium_emoji.load(SessionLocal)
    me = await bot.get_me()
    if me.username:
        settings.bot_username = me.username
        logging.info("Using bot username from Telegram: @%s", me.username)
    dp = Dispatcher()
    # attach debug middleware to capture incoming messages and callbacks
    dp.message.middleware(DebugLogMiddleware())
    dp.callback_query.middleware(DebugLogMiddleware())
    dp.message.middleware(PremiumBlockMessageMiddleware())
    dp.callback_query.middleware(PremiumBlockCallbackMiddleware())
    dp.message.middleware(CreditBlockMessageMiddleware())
    dp.callback_query.middleware(CreditBlockCallbackMiddleware())
    dp.message.middleware(MandatorySubMessageMiddleware())
    dp.callback_query.middleware(MandatorySubCallbackMiddleware())
    dp.message.middleware(DeleteGroupCommandMiddleware())
    dp.message.middleware(ChatRestrictionMiddleware())
    dp.errors.register(global_error_handler)

    engine = GameEngine(settings=settings, session_factory=SessionLocal)
    await engine.cleanup_stale_games_on_startup()

    dp.include_router(start.router)
    dp.include_router(language.router)
    dp.include_router(game.router)
    dp.include_router(roles.router)
    dp.include_router(profile.router)
    dp.include_router(clan.router)
    dp.include_router(economy.router)
    dp.include_router(hero.router)
    dp.include_router(para.router)
    dp.include_router(settings_handler.router)
    dp.include_router(top.router)
    dp.include_router(callbacks.router)
    dp.include_router(admin.router)
    dp.include_router(emoji_debug.router)
    dp.include_router(monitoring.router)

    start_scheduler()
    scheduler.add_job(
        engine.registration_watchdog,
        "interval",
        seconds=5,
        args=[bot],
        id="registration_watchdog",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=15,
    )
    scheduler.add_job(
        engine.premium_reset_watchdog,
        "interval",
        seconds=60,
        id="premium_reset_watchdog",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        engine.send_pending_diamond_logs,
        "interval",
        seconds=30,
        args=[bot],
        id="diamond_log_watchdog",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        engine.process_due_scheduled_broadcasts,
        "interval",
        seconds=60,
        args=[bot],
        id="scheduled_broadcast_watchdog",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        engine.run_weekly_top_reward_distribution,
        "cron",
        day_of_week="sun",
        hour=23,
        minute=59,
        args=[bot],
        id="weekly_top_reward_watchdog",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    credit_service = CreditService(SessionLocal)
    scheduler.add_job(
        credit_service.daily_watchdog,
        "cron",
        hour=5,
        minute=0,
        args=[bot],
        id="credit_daily_watchdog",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    await set_commands(bot)

    keep_alive()

    try:
        await dp.start_polling(
            bot,
            engine=engine,
            settings=settings,
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
        )
    finally:
        shutdown_scheduler()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
