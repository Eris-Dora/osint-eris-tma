from typing import Dict, Any, List
from .llm_router import LLMRouter

# Оперативная память диалогов по user_id
CHAT_MEMORY: Dict[int, List[Dict[str, str]]] = {}


class GeminiOSINTAnalyst:
    """Отвечает только за промпты, память диалога и сборку OSINT-досье."""

    @classmethod
    def save_to_memory(cls, user_id: int, role: str, text: str) -> None:
        if user_id not in CHAT_MEMORY:
            CHAT_MEMORY[user_id] = []
        CHAT_MEMORY[user_id].append({"role": role, "text": text[:1500]})
        if len(CHAT_MEMORY[user_id]) > 14:
            CHAT_MEMORY[user_id] = CHAT_MEMORY[user_id][-14:]

    @classmethod
    def clear_memory(cls, user_id: int) -> None:
        CHAT_MEMORY.pop(user_id, None)

    @classmethod
    async def chat_with_user(cls, user_id: int, user_message: str) -> Dict[str, str]:
        """Ведет диалог с пользователем на выбранной им модели."""
        cls.save_to_memory(user_id, "Пользователь", user_message)

        history_lines = [f"{msg['role']}: {msg['text']}" for msg in CHAT_MEMORY.get(user_id, [])]
        conversation_context = "\n\n".join(history_lines)

        prompt = (
            "Ты — ASTRA OSINT AI, умный, дружелюбный и профессиональный кибер-аналитик и ассистент в Telegram. "
            "Ты умеешь общаться на любые темы, отвечать на вопросы по прошлым результатам поиска и помогать с OSINT-разведкой. "
            "Отвечай четко, живо, на русском языке. Пиши чистым текстом с буллитами (•) и эмодзи.\n\n"
            f"История вашего диалога:\n{conversation_context}\n\n"
            "Ответь на последнее сообщение пользователя:"
        )

        res = await LLMRouter.generate(prompt=prompt, user_id=user_id, use_search=True, temp=0.5)
        if res["text"]:
            cls.save_to_memory(user_id, "ASTRA AI", res["text"])
            return {"reply": res["text"], "model_title": res.get("model_title", "AI")}

        return {
            "reply": f"⚠️ Ответ от API не получен.\nДетали от сервера: {res['error']}",
            "model_title": res.get("model_title", "AI"),
        }

    @classmethod
    async def analyze_and_ground(
        cls, query: str, existing_results: List[Dict[str, Any]], user_id: int = 0
    ) -> Dict[str, Any]:
        """Строит краткое OSINT-досье по найденным результатам."""
        context_lines = [
            f"{idx}. [{item.get('source', 'Web')}] {item.get('title', '')} — {item.get('url', '')} ({item.get('snippet', '')[:120]})"
            for idx, item in enumerate(existing_results[:12], 1)
        ]
        context_block = "\n".join(context_lines) if context_lines else "Предварительных ссылок нет."

        prompt = (
            f"Ты — профессиональный OSINT-аналитик. Исследуй объект/запрос: «{query}».\n"
            f"Найди всю информацию: профили в соцсетях (Instagram, Telegram, VK, TikTok, X, YouTube, GitHub), "
            f"упоминания в СМИ, форумах, биографию или доменную информацию.\n\n"
            f"Уже найденные системой ссылки:\n{context_block}\n\n"
            f"Напиши краткое, четкое и структурированное OSINT-досье на русском языке (4-6 пунктов с буллитами •):\n"
            f"• Кто или что это (основная суть / род деятельности / описание объекта).\n"
            f"• Обнаруженные соцсети, аккаунты и никнеймы.\n"
            f"• Ключевые упоминания, проекты, связанные ресурсы или факты.\n"
            f"Пиши без воды и без вводных фраз."
        )

        res = await LLMRouter.generate(prompt=prompt, user_id=user_id, use_search=True, temp=0.2)
        return {
            "ai_summary": res["text"],
            "grounded_results": res["grounded"],
        }
