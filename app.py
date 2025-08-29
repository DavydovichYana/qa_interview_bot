# app.py
import asyncio
import random
from typing import Dict, Set

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.parse_mode import ParseMode

from settings import TELEGRAM_TOKEN, CHANNEL_URL, ADMIN_IDS, ENV
from packs_loader import load_packs
from quiz_engine import QuizEngine

# Загружаем YAML-пакеты один раз при старте
packs = load_packs("data/packs")
engine = QuizEngine(packs)

# Буфер для мультивыбора: user_id -> set букв ('a','b',...)
MULTI_BUF: Dict[int, Set[str]] = {}

def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(int(x) for x in ADMIN_IDS)
    except Exception:
        return False

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

def build_mixed_pack(levels=("junior", "advanced")) -> dict:
    """Собрать единый 'смешанный' пакет из указанных уровней."""
    mixed_questions = []
    for _, data in packs.items():
        if data.get("pack", {}).get("level") in levels:
            mixed_questions.extend(data.get("questions", []))
    random.shuffle(mixed_questions)
    return {
        "pack": {
            "code": "mixed",
            "title": "Смешанный",
            "level": "mixed",
            "description": "Вопросы вперемешку из junior и advanced",
        },
        "questions": mixed_questions,
    }

# === НОВОЕ: клавиатуры с ответами ===
def build_single_kb(q: dict):
    kb = InlineKeyboardBuilder()
    for letter, _ in q["options"].items():
        kb.button(text=f"{letter.upper()}", callback_data=f"ans:{letter}")
    kb.adjust(4)  # красиво в одну строку по 4 кнопки (или убери)
    return kb.as_markup()

def build_multi_kb(q: dict, selected: Set[str] | None):
    selected = selected or set()
    kb = InlineKeyboardBuilder()
    # кнопки вида: "☑️ A" / "▫️ A"
    for letter, _ in q["options"].items():
        mark = "☑️" if letter in selected else "▫️"
        kb.button(text=f"{mark} {letter.upper()}", callback_data=f"toggle:{letter}")
    kb.adjust(4)  # 4 в ряд (A B C D)

    # нижний ряд управления
    kb.button(text="✅ Готово", callback_data="multi:submit")
    kb.button(text="♻️ Сброс", callback_data="multi:reset")
    kb.adjust(4, 2)  # первый ряд 4, второй ряд 2
    return kb.as_markup()

async def send_question(chat_id: int, user_id: int, message_to_edit: Message | None = None):
    """Отправляет (или редактирует) текущий вопрос с подходящей клавиатурой и прогрессом."""
    q = engine.get_current(user_id)

    # прогресс: текущий индекс (0-based) + 1 / всего вопросов
    s = engine.sessions[user_id]
    curr = s["idx"] + 1
    total = len(s["questions"])

    text = f"*Вопрос {curr}/{total}*\n" + engine.render_question(q)

    # клавиатура
    if q["type"] == "single":
        markup = build_single_kb(q)
    elif q["type"] == "multi":
        MULTI_BUF.setdefault(user_id, set())
        markup = build_multi_kb(q, MULTI_BUF[user_id])
    else:
        markup = None  # free

    if message_to_edit:
        try:
            await message_to_edit.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=markup)

async def _remove_keyboard_safe(msg: Message):
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:
        # Уже убрали/сообщение недоступно — просто игнорируем
        pass

async def handle_result(m: Message, user_id: int, res: dict):
    """Единая обработка результата engine.check(...)."""
    await m.answer(res["feedback"])
    if res["done"]:
        await m.answer(res["summary"])
        sticker_id = res.get("sticker_id")
        if sticker_id:
            await m.answer_sticker(sticker_id)
        await m.answer("Продолжим? 👇", reply_markup=build_post_results_kb(CHANNEL_URL))
    else:
        await send_question(m.chat.id, user_id)

def render_answered_question(q: dict, user_answers: list[str], curr: int, total: int) -> str:
    """Форматируем отредактированное сообщение с прогрессом и пометками вариантов."""
    correct = set(a.lower() for a in (q["answer"] if isinstance(q["answer"], list) else [q["answer"]]))
    user = set(a.lower() for a in user_answers)

    lines = [f"*Вопрос {curr}/{total}*", f"🔎 *Q:* {q['text']}\n"]
    for letter, text in q["options"].items():
        if letter in correct and letter in user:
            mark = "✅"
        elif letter in correct:
            mark = "✅"
        elif letter in user:
            mark = "❌"
        else:
            mark = "▫️"
        lines.append(f"{mark} {letter.upper()}) {text}")
    return "\n".join(lines)

# === aiogram runtime ===
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)
dp = Dispatcher()

async def main():
    # 👉 Авто-сброс вебхука перед запуском long polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"[warn] delete_webhook failed: {e}")

    # /start — сначала выбираем уровень
    @dp.message(F.text == "/start")
    async def cmd_start(m: Message):
        if not packs:
            await m.answer("Технические неполадки 🤖 \n Выбери другой уровень.")
            return
        await m.answer(
            "Коллега, привет!👋\n\n🧑‍💻 Давай проверим твои знания для себеседования на QA?\n"
            "🎓 Тебе предстоит ответить на 10 вопросов. \n📊 Выбери уровень сложности:",
            reply_markup=build_levels_kb()
        )

    # /version — узнаем среду: прод или stage
    @dp.message(F.text == "/version")
    async def version(m: Message):
        if is_admin(m.from_user.id):
            await m.answer(f"🤖 Окружение: *{ENV}* (админ-режим)", parse_mode=ParseMode.MARKDOWN)
        else:
            await m.answer("Бот работает ✅")

    # Выбор уровня: сразу запускаем раунд
    @dp.callback_query(F.data.startswith("level:"))
    async def choose_level(c: CallbackQuery):
        level = c.data.split(":", 1)[1]

        # Определяем код пакета по выбранному уровню
        if level == "random":
            packs["mixed"] = build_mixed_pack(("junior", "advanced"))
            engine.packs = packs
            code = "mixed"
        elif level == "junior":
            code = pick_random_pack(["junior"])
        elif level == "advanced":
            code = pick_random_pack(["advanced"])
        else:
            code = None

        if not code:
            await c.message.answer("Для выбранного уровня пока нет вопросов 🙃 Попробуй снова: /start")
            await c.answer()
            return

        # Стартуем сессию (внутри выберется 10 случайных вопросов)
        engine.start_session(c.from_user.id, code)

        # Отправляем первый вопрос с кнопками при необходимости
        await send_question(c.message.chat.id, c.from_user.id)
        await c.answer()

    # Дежурные команды
    @dp.message(F.text == "/cancel")
    async def cancel(m: Message):
        engine.sessions.pop(m.from_user.id, None)
        MULTI_BUF.pop(m.from_user.id, None)
        await m.answer("Сессию остановили. Напиши /start, чтобы начать заново.")

    @dp.message(F.text == "/startover")
    async def startover(m: Message):
        engine.sessions.pop(m.from_user.id, None)
        MULTI_BUF.pop(m.from_user.id, None)
        await m.answer("Ок, начнём заново ⚒️. Выбери уровень:", reply_markup=build_levels_kb())

    @dp.callback_query(F.data == "menu:quiz")
    async def open_quiz_menu(c: CallbackQuery):
        await c.message.answer("Выбери уровень сложности:", reply_markup=build_levels_kb())
        await c.answer()

    # === НОВОЕ: ответы кнопками ===
    @dp.callback_query(F.data.startswith("ans:"))
    async def on_single_answer(c: CallbackQuery):
        if not engine.has_active(c.from_user.id):
            await c.answer();
            return

        letter = c.data.split(":", 1)[1]
        # Берём вопрос и прогресс ДО инкремента
        q = engine.get_current(c.from_user.id)
        s = engine.sessions[c.from_user.id]
        curr = s["idx"] + 1
        total = len(s["questions"])

        res = engine.check(c.from_user.id, letter)

        try:
            await c.message.edit_text(render_answered_question(q, [letter], curr, total))
        except Exception:
            pass

        MULTI_BUF.pop(c.from_user.id, None)
        await handle_result(c.message, c.from_user.id, res)
        await c.answer("Ответ принят")

    @dp.callback_query(F.data.startswith("toggle:"))
    async def on_multi_toggle(c: CallbackQuery):
        if not engine.has_active(c.from_user.id):
            await c.answer()
            return
        letter = c.data.split(":", 1)[1]
        sel = MULTI_BUF.setdefault(c.from_user.id, set())
        if letter in sel:
            sel.remove(letter)
        else:
            sel.add(letter)

        q = engine.get_current(c.from_user.id)
        await c.message.edit_reply_markup(reply_markup=build_multi_kb(q, sel))
        await c.answer()

    @dp.callback_query(F.data == "multi:reset")
    async def on_multi_reset(c: CallbackQuery):
        if not engine.has_active(c.from_user.id):
            await c.answer();
            return
        MULTI_BUF[c.from_user.id] = set()
        q = engine.get_current(c.from_user.id)
        await c.message.edit_reply_markup(reply_markup=build_multi_kb(q, MULTI_BUF[c.from_user.id]))
        await c.answer("Сброшено")

    @dp.callback_query(F.data == "multi:submit")
    async def on_multi_submit(c: CallbackQuery):
        if not engine.has_active(c.from_user.id):
            await c.answer();
            return

        sel = sorted(MULTI_BUF.get(c.from_user.id, set()))
        q = engine.get_current(c.from_user.id)
        s = engine.sessions[c.from_user.id]
        curr = s["idx"] + 1
        total = len(s["questions"])

        res = engine.check(c.from_user.id, ",".join(sel))

        try:
            await c.message.edit_text(render_answered_question(q, sel, curr, total))
        except Exception:
            pass

        MULTI_BUF.pop(c.from_user.id, None)
        await handle_result(c.message, c.from_user.id, res)
        await c.answer("Ответ отправлен")

    # === Текстовые ответы: только для free ===
    @dp.message()
    async def any_text(m: Message):
        if not engine.has_active(m.from_user.id):
            await m.answer("🧩 Сначала выбери уровень: /start")
            return

        # Если текущий вопрос НЕ free, просим нажать кнопку
        q = engine.get_current(m.from_user.id)
        if q["type"] != "free":
            await m.answer("Пожалуйста, выбери вариант на кнопках ниже 👇")
            return

        # free — принимаем текст
        res = engine.check(m.from_user.id, m.text or "")
        await handle_result(m, m.from_user.id, res)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
