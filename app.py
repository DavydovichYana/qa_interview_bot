# app.py
import asyncio
import random
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from settings import TELEGRAM_TOKEN, CHANNEL_URL

from settings import TELEGRAM_TOKEN
from packs_loader import load_packs
from quiz_engine import QuizEngine

# Загружаем YAML-пакеты один раз при старте
packs = load_packs("data/packs")
engine = QuizEngine(packs)


def build_levels_kb():
    """Клавиатура выбора уровня."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🐣 Для начинающих", callback_data="level:junior")
    kb.button(text="🚀 Для продвинутых", callback_data="level:advanced")
    kb.button(text="🎲 Рандом", callback_data="level:random")
    kb.adjust(1)
    return kb.as_markup()

def build_post_results_kb(channel_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🧪 Квиз", callback_data="menu:quiz")
    kb.button(text="🧠 QA Mind", url=channel_url)  # внешняя ссылка
    kb.adjust(2)
    return kb.as_markup()


def pick_random_pack(levels: list[str]) -> str | None:
    """Вернуть код случайного пакета, чей pack.level находится в списке levels."""
    candidates = [code for code, data in packs.items() if data["pack"].get("level") in levels]
    return random.choice(candidates) if candidates else None


async def main():
    bot = Bot(
        token=TELEGRAM_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # 👉 Авто-сброс вебхука перед запуском long polling
    try:
        # drop_pending_updates=True очистит очередь апдейтов, накопленную для вебхука
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        # не критично, просто залогируем
        print(f"[warn] delete_webhook failed: {e}")

    # /start — сначала выбираем уровень
    @dp.message(F.text == "/start")
    async def cmd_start(m: Message):
        if not packs:
            await m.answer("Технические неполадки 🤖 \n Выбери другой уровень.")
            return
        await m.answer("Коллега, привет!👋\n\n🧑‍💻 Давай проверим твои знания для себеседования на QA?\n🎓 Тебе предстоит ответить на 10 вопросов. \n📊 Выбери уровень сложности:", reply_markup=build_levels_kb())

    # Выбор уровня: сразу запускаем раунд
    @dp.callback_query(F.data.startswith("level:"))
    async def choose_level(c: CallbackQuery):
        level = c.data.split(":", 1)[1]

        # Определяем код пакета по выбранному уровню
        if level == "random":
            code = random.choice(list(packs.keys())) if packs else None
        elif level == "junior":
            code = pick_random_pack(["junior"])
        elif level == "advanced":
            code = pick_random_pack(["advanced"])
        else:
            code = None  # на всякий случай

        if not code:
            await c.message.answer("Для выбранного уровня пока нет вопросов 🙃 Попробуй снова: /start")
            await c.answer()
            return

        # Стартуем сессию (внутри выберется 10 случайных вопросов)
        engine.start_session(c.from_user.id, code)

        # Отправляем первый вопрос — без упоминания пакета
        q = engine.get_current(c.from_user.id)
        await c.message.answer(engine.render_question(q))
        await c.answer()

    # Дежурные команды
    @dp.message(F.text == "/cancel")
    async def cancel(m: Message):
        engine.sessions.pop(m.from_user.id, None)
        await m.answer("Сессию остановили. Напиши /start, чтобы начать заново.")

    @dp.message(F.text == "/startover")
    async def startover(m: Message):
        engine.sessions.pop(m.from_user.id, None)
        await m.answer("Ок, начнём заново ⚒️. Выбери уровень:", reply_markup=build_levels_kb())

    @dp.callback_query(F.data == "menu:quiz")
    async def open_quiz_menu(c: CallbackQuery):
        await c.message.answer("Выбери уровень сложности:", reply_markup=build_levels_kb())
        await c.answer()

    # Обработка ответов на вопросы
    @dp.message()
    async def any_text(m: Message):
        if not engine.has_active(m.from_user.id):
            await m.answer("🧩 Сначала выбери уровень: /start")
            return
        res = engine.check(m.from_user.id, m.text or "")
        await m.answer(res["feedback"])
        if res["done"]:
            await m.answer(res["summary"])
            # стикер (опционально). В quiz_engine по умолчанию пустые строки — не отправятся.
            sticker_id = res.get("sticker_id")
            if sticker_id:
                await m.answer_sticker(sticker_id)
            await m.answer(
                "Продолжим? 👇",
                reply_markup=build_post_results_kb(CHANNEL_URL)
            )
        else:
            await m.answer(engine.render_question(res["next"]))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
