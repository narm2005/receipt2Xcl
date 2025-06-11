from typing import List, Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import Field
import requests


class ChatDeepSeek(BaseChatModel):
    """LangChain-compatible ChatModel for DeepSeek"""

    api_key: str = Field(..., description="DeepSeek API Key")
    model: str = "deepseek-chat"
    temperature: float = 0.7
    api_url: str = "https://api.deepseek.com/v1/chat/completions"

    def _convert_messages(self, messages: List[BaseMessage]) -> List[dict]:
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "system"
        }
        return [
            {
                "role": role_map.get(m.type, m.type),
                "content": m.content
            } for m in messages
        ]

    def _chat(self, messages: List[dict]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }

        response = requests.post(self.api_url, headers=headers, json=payload)
        if response.status_code != 200:
            raise ValueError(f"DeepSeek API error {response.status_code}: {response.text}")

        return response.json()["choices"][0]["message"]["content"]

    def _generate(self, messages: List[BaseMessage], **kwargs: Any) -> ChatResult:
        formatted = self._convert_messages(messages)
        output = self._chat(formatted)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=output))])

    @property
    def _llm_type(self) -> str:
        return "chat-deepseek"
