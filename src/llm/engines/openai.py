"""OpenAI 相容的 LLM 引擎"""

from __future__ import annotations

import time
from typing import Generator, Optional

from openai import OpenAI, OpenAIError

from src.llm.base import (
    BaseLLM,
    DEFAULT_RESPONSE_MAX_CHARS,
    response_token_budget,
    validate_response_max_chars,
    with_response_length_instruction,
)
from src.utils.logging import logger


class OpenAILLM(BaseLLM):
    """OpenAI 相容的 LLM 引擎，支援 OpenAI/DashScope/vLLM/Ollama 等"""
    
    def __init__(
        self, 
        config=None, 
        parent=None,
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-plus",
        max_history: int = 10  # 最大儲存的對話輪次
    ):
        super().__init__(config, parent)
        
        if not api_key:
            raise ValueError("api_key is required")
        
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_history = max_history
        self.conversation_history = []  # 對話歷史 [{'role': 'user/assistant', 'content': '...'}]
        
        # 從配置讀取額外請求體引數（如 Ollama 的 reasoning_effort）
        llm_cfg = getattr(config, "llm", None) if config is not None else None
        extra = dict(getattr(llm_cfg, "extra_body", None) or {})
        if getattr(llm_cfg, "provider", "") == "llamacpp":
            extra.pop("reasoning_effort", None)
            extra.pop("think", None)
            extra.pop("keep_alive", None)
            extra.pop("options", None)
        self.extra_body = extra
        self.response_max_chars = validate_response_max_chars(
            getattr(llm_cfg, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
        )
        self.max_tokens = response_token_budget(self.response_max_chars)

        logger.info(
            f"LLM initialized: model={self.model}, base_url={self.base_url}"
            + (f", extra_body={self.extra_body}" if self.extra_body else "")
        )
        self._client: Optional[OpenAI] = None
    
    @property
    def client(self) -> OpenAI:
        if self._client is None:
            # 延遲建立客戶端，避免無效配置時提前報錯
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client
    
    def add_to_history(self, role: str, content: str):
        """新增訊息到對話歷史"""
        self.conversation_history.append({'role': role, 'content': content})
        
        # 保持歷史記錄在限制範圍內（保留最近的 max_history 輪對話）
        if len(self.conversation_history) > self.max_history * 2:  # *2 因為每輪有 user 和 assistant
            self.conversation_history = self.conversation_history[-self.max_history * 2:]
        
        logger.debug(f"Added to history: {role}, history length: {len(self.conversation_history)}")
    
    def clear_history(self):
        """清空對話歷史"""
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        start_time = time.perf_counter()
        system_prompt = with_response_length_instruction(
            system_prompt or self.system_prompt,
            self.response_max_chars,
        )
        
        try:
            # 新增使用者訊息到歷史
            self.add_to_history('user', message)
            
            # 構建完整的訊息列表：system + 歷史對話
            messages = [{'role': 'system', 'content': system_prompt}]
            messages.extend(self.conversation_history)
            
            logger.info(f"Sending {len(messages)} messages to LLM (including system prompt and history)")
            
            # 採用 OpenAI 相容流式介面，逐塊返回內容
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
                temperature=0.6,
                extra_body=self.extra_body or None,
            )
            
            init_time = time.perf_counter()
            logger.info(f"LLM initialization time: {init_time - start_time:.3f}s")
            
            # 收集完整的響應用於新增到歷史
            full_response = ""
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
            
            # 新增助手響應到歷史
            self.add_to_history('assistant', full_response)
            
        except OpenAIError as e:
            logger.error(f"LLM API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LLM: {e}")
            raise
