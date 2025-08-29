from typing import Dict, Any, Tuple, List
import re
from tags_map_loader import load_tags_map, render_tags
TAGS_MAP = load_tags_map()

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _split_letters(s: str) -> List[str]:
    parts = re.split(r"[,\s;]+", (s or "").strip())
    return [p.lower() for p in parts if p]

def _format_correct_answer(q: Dict[str, Any]) -> str:
    """Вернём человекочитаемый правильный ответ (для single/multi/free)."""
    t = q["type"]
    if t in ("single", "multi"):
        ans = q["answer"]
        if isinstance(ans, str):
            ans = [ans]
        # сопоставим буквы с текстами
        opts = q.get("options", {})
        pairs = [f"{a}) {opts.get(a, '')}" for a in ans]
        return ", ".join(pairs)
    # free — покажем первый вариант
    first = q.get("answer", [])
    if isinstance(first, list) and first:
        return first[0]
    if isinstance(first, str):
        return first
    return ""

class QuizEngine:
    def __init__(self, packs: Dict[str, Any]):
        self.packs = packs
        self.sessions: Dict[int, Dict[str, Any]] = {}  # user_id -> session

    def start_session(self, user_id: int, pack_code: str) -> None:
        pack = self.packs[pack_code]
        from packs_loader import pick_questions
        questions = pick_questions(pack, n=10)
        self.sessions[user_id] = {
            "questions": questions,
            "idx": 0,
            "score": 0.0,              # может включать частичный зачёт
            "correct_count": 0,        # количество полностью верных
            "errors_by_tag": {},
            "wrong_items": [],         # список неверных вопросов для финального отчёта
            "done": False,
        }

    def has_active(self, user_id: int) -> bool:
        s = self.sessions.get(user_id)
        return bool(s and not s.get("done"))

    def get_current(self, user_id: int) -> Dict[str, Any]:
        s = self.sessions[user_id]
        return s["questions"][s["idx"]]

    def render_question(self, q: Dict[str, Any]) -> str:
        """Форматируем вопрос: смайл у Q, пустая строка перед вариантами, жирные буквы."""
        t = q["type"]
        header = f"🔎 *Q:* {q['text']}"
        if t in ("single", "multi"):
            # жирные буквы a/b/c/d
            opts = "\n".join([f"**{k})** {v}" for k, v in q["options"].items()])
            hint = "_Один вариант_" if t == "single" else "_Выбери один или несколько вариантов_"
            return f"{header}\n\n{opts}\n\n{hint}"
        return f"{header}\n\n_Свободный ответ_"

    def _score_single(self, q: Dict[str, Any], answer_text: str) -> Tuple[float, bool]:
        ok = _norm(answer_text) == _norm(q["answer"])
        return (1.0 if ok else 0.0, ok)

    def _score_multi(self, q: Dict[str, Any], answer_text: str) -> Tuple[float, bool]:
        correct = set(_norm(x) for x in q["answer"])
        user = set(_split_letters(answer_text))
        if not user:
            return (0.0, False)
        if user == correct:
            return (1.0, True)
        # частичный зачёт
        precision = len(user & correct) / len(correct)
        wrong_penalty = len(user - correct) / max(1, len(correct))
        partial = max(0.0, precision - 0.3 * wrong_penalty)
        return (round(partial, 2), False)

    def _score_free(self, q: Dict[str, Any], answer_text: str) -> Tuple[float, bool]:
        user = _norm(answer_text)
        if not user:
            return (0.0, False)
        variants = [_norm(v) for v in q.get("answer", [])]
        if user in variants:
            return (1.0, True)
        for v in variants:
            words = [w for w in v.split() if w]
            if words and all(w in user for w in words):
                return (1.0, True)
        return (0.0, False)

    def _encouragement(self, correct: int, total: int) -> Dict[str, str]:
        """
        Подбираем вдохновляющий текст и стикер по диапазону:
        0-3, 4-6, 7-8, 9-10. Стикеры можно заменить на свои file_id.
        """
        ranges = [
            {"min": 0, "max": 3, "text": "Тебе надо основательно подойти к изучению теории тестирования. Давай начнём с базовых тем! 💪📚", "sticker": "CAACAgIAAxkBAAERxAVoruSaNwdfSIynm8NFln8UDZsKJQACyTQAAxS5Sqpht736pBnMNgQ"},  # 🔁 подставь file_id
            {"min": 4, "max": 6, "text": "Неплохо! База есть, но есть куда расти. Добьём пробелы и прокачаемся на задачах посложнее 🚀", "sticker": "CAACAgIAAxkBAAERxAloruS951hk2J97bezr_ps4s-d_eQACoy8AAhKPuEoGYuyE0fo69TYE"},
            {"min": 7, "max": 8, "text": "Отличный результат! Видно, что ты хорошо владеешь базой. Чуть больше практики - и будешь отвечать на все вопросы 10/10! 🔥", "sticker": "CAACAgIAAxkBAAERw-xoruN9Kf9UUQdv3ZHkFYCnchd8nwACazEAArDOuUpGWRrkBQc6UTYE"},
            {"min": 9, "max": 10, "text": "Вау! Такой результат впечатляет - будь уверен, в теории тебе нет равных 🏆", "sticker": "CAACAgIAAxkBAAERw-horuNhMmhqUdkOs-AclZbmMyzMAgAC_zkAAmpPuUrklarETKG26DYE"},
        ]
        for r in ranges:
            if r["min"] <= correct <= r["max"]:
                return {"text": r["text"], "sticker": r["sticker"]}
        return {"text": "", "sticker": ""}

    def check(self, user_id: int, answer_text: str) -> Dict[str, Any]:
        s = self.sessions[user_id]
        q = s["questions"][s["idx"]]
        qtype = q["type"]

        if qtype == "single":
            add, ok = self._score_single(q, answer_text)
        elif qtype == "multi":
            add, ok = self._score_multi(q, answer_text)
        else:
            add, ok = self._score_free(q, answer_text)

        s["score"] += add
        if ok:
            s["correct_count"] += 1
        else:
            # статистика ошибок + запоминаем неверный вопрос
            for tag in q.get("tags", []):
                s["errors_by_tag"][tag] = s["errors_by_tag"].get(tag, 0) + 1
            s["wrong_items"].append({
                "text": q["text"],
                "correct": _format_correct_answer(q),
                "explanation": q.get("explanation", "")
            })

        feedback = f"{'✅ Верно' if ok else '❌ Неверно'} (+{add:.2f})\nℹ️ {q.get('explanation','')}"
        s["idx"] += 1

        if s["idx"] >= len(s["questions"]):
            s["done"] = True
            total = len(s["questions"])
            correct = s["correct_count"]
            pct = round(100 * correct / total)
            # дружелюбная итого без упоминания пакета
            header = f"🏁 *Итоги тестирования:* {correct}/{total} ({pct}%)"
            # вдохновляющий текст
            mood = self._encouragement(correct, total)
            mood_text = mood["text"]
            sticker_id = mood["sticker"]

            # топ-3 проблемных тега (оставим как подсказку)
            hardest = sorted(s["errors_by_tag"].items(), key=lambda kv: kv[1], reverse=True)[:7]
            raw_tags = [t for t, _ in hardest]
            topics_line = f"*❗️Темы для прокачки*: {render_tags(raw_tags, TAGS_MAP)}"

            # список неверных с правильными ответами
            if s["wrong_items"]:
                lines = ["\n*👇 Ошибки:*"]
                for i, item in enumerate(s["wrong_items"], 1):
                    right = f" `{item['correct']}`" if item["correct"] else "—"
                    expl = f"\n   _{item['explanation']}_ " if item["explanation"] else ""
                    # добавляем \n в конце, чтобы был отступ
                    lines.append(f"*{i}) {item['text']}*\n   *👉 Правильно:* {right}{expl}\n")
                mistakes_md = "\n".join(lines)
            else:
                mistakes_md = ""

            summary = "\n".join([header, topics_line, "", mood_text, mistakes_md]).strip()
            return {"feedback": feedback, "done": True, "summary": summary, "sticker_id": sticker_id}

        # ещё есть вопросы
        return {"feedback": feedback, "done": False, "next": s["questions"][s["idx"]]}
