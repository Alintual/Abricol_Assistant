import httpx
from typing import List, Dict, Optional

from .config import settings


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is empty. Set it in your .env file.")
        self.api_key = api_key
        # Нормализуем базовый URL (иногда встречается platform.deepseek.com)
        normalized = base_url.strip().rstrip("/")
        if "platform.deepseek.com" in normalized:
            normalized = "https://api.deepseek.com"
        self.base_url = normalized
        self.model = model

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = 600,
    ) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        # DeepSeek совместим с OpenAI API: корректный путь "/v1/chat/completions"
        url = f"{self.base_url.rstrip('/')}" + "/v1/chat/completions"

        final_messages: List[Dict[str, str]] = []
        if system_prompt:
            final_messages.append({"role": "system", "content": system_prompt})
        final_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": final_messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Вернём читаемое сообщение об ошибке для 401/403/4xx
                try:
                    err_json = resp.json()
                except Exception:
                    err_json = {"error": resp.text}
                detail = err_json.get("error") or err_json
                raise RuntimeError(f"DeepSeek API error {resp.status_code}: {detail}") from e
            data = resp.json()
            
            # Логирование для отладки
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"DeepSeek API response: messages count={len(final_messages)}, system_prompt={'present' if system_prompt else 'absent'}")
            
            response_content = data["choices"][0]["message"]["content"].strip()
            logger.debug(f"DeepSeek response length: {len(response_content)} chars")
            return response_content


deepseek = DeepSeekClient(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    model=settings.deepseek_model,
)


