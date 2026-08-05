from __future__ import annotations

from .config import load_ai_config


SYSTEM_INSTRUCTION = (
    "你是 ComiTrans 本地漫画翻译客户端的诊断助手。"
    "请结合用户提供的环境信息、报错信息和最近日志，分析问题原因，并给出具体的修复步骤。"
    "回答使用中文，保持简洁、可操作。不要虚构不存在的日志或配置。"
)


class AiDiagnosis:
    def __init__(self, diagnostics):
        self._diagnostics = diagnostics
        self._history = []

    def diagnose(self, user_text: str) -> str:
        config = load_ai_config()
        api_key = config.get("api_key", "")
        api_base_url = config.get("api_base_url", "")
        model = config.get("translation_model", "")

        if not api_key or not api_base_url or not model:
            raise RuntimeError("请先在 API 配置页填写 API Key、Base URL 和翻译模型。")

        context = self._diagnostics.build_prompt()
        messages = [
            {"role": "system", "content": f"{SYSTEM_INSTRUCTION}\n\n{context}"},
        ]
        messages.extend(self._history)
        messages.append({"role": "user", "content": user_text})

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=api_base_url, timeout=90)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        answer = response.choices[0].message.content.strip()

        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": answer})
        if len(self._history) > 40:
            self._history = self._history[-40:]
        return answer

    def clear_context(self) -> None:
        self._history.clear()
