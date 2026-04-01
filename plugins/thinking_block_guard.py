"""
ThinkingBlockGuard — LiteLLM callback that strips thinking blocks
when the router switches between kiro-gateway and Bedrock backends.

Uses Redis (shared across all LiteLLM pods) to track which backend
last served each conversation. When a backend switch is detected,
thinking blocks are stripped to prevent signature validation errors.
"""

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

import redis
from litellm.integrations.custom_logger import CustomLogger
from litellm.types.utils import CallTypes

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "tbg:"
REDIS_TTL = 86400  # 24h — conversations older than this are forgotten


class ThinkingBlockGuard(CustomLogger):

    KIRO_MARKER = "kiro-gateway"
    THINKING_TYPES = frozenset(("thinking", "redacted_thinking"))

    def __init__(self) -> None:
        super().__init__()
        self._redis: Optional[redis.Redis] = None

    def _get_redis(self) -> Optional[redis.Redis]:
        if self._redis is not None:
            return self._redis
        host = os.environ.get("REDIS_HOST")
        if not host:
            return None
        try:
            self._redis = redis.Redis(
                host=host,
                port=int(os.environ.get("REDIS_PORT", "6379")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self._redis.ping()
            logger.info("ThinkingBlockGuard: connected to Redis at %s", host)
            return self._redis
        except Exception as e:
            logger.warning("ThinkingBlockGuard: Redis unavailable (%s), falling back to always-strip", e)
            self._redis = None
            return None

    @staticmethod
    def _conversation_key(messages: List[dict]) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content = block.get("text", "")
                            break
                    else:
                        content = str(content[:1])
                return hashlib.sha256(
                    content[:500].encode(errors="replace")
                ).hexdigest()[:16]
        return "_no_user_msg"

    def _backend_id(self, kwargs: dict) -> str:
        api_base = (
            kwargs.get("litellm_metadata", {}).get("api_base")
            or kwargs.get("metadata", {}).get("api_base")
            or ""
        )
        return "kiro" if self.KIRO_MARKER in str(api_base) else "bedrock"

    def _get_previous(self, conv_key: str) -> Optional[str]:
        r = self._get_redis()
        if r is None:
            return None
        try:
            return r.get(f"{REDIS_KEY_PREFIX}{conv_key}")
        except Exception:
            return None

    def _set_current(self, conv_key: str, backend: str) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.set(f"{REDIS_KEY_PREFIX}{conv_key}", backend, ex=REDIS_TTL)
        except Exception:
            pass

    @classmethod
    def _has_thinking(cls, messages: List[dict]) -> bool:
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") in cls.THINKING_TYPES:
                    return True
        return False

    @classmethod
    def _strip_thinking(cls, messages: List[dict]) -> int:
        removed = 0
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            original_len = len(content)
            msg["content"] = [
                b for b in content
                if not (isinstance(b, dict) and b.get("type") in cls.THINKING_TYPES)
            ]
            removed += original_len - len(msg["content"])
        return removed

    async def async_pre_call_deployment_hook(
        self,
        kwargs: Dict[str, Any],
        call_type: Optional[CallTypes],
    ) -> Optional[dict]:
        messages = kwargs.get("messages")
        if not messages or not self._has_thinking(messages):
            # No thinking blocks — just record current backend and return
            if messages:
                conv_key = self._conversation_key(messages)
                current = self._backend_id(kwargs)
                self._set_current(conv_key, current)
            return None

        conv_key = self._conversation_key(messages)
        current = self._backend_id(kwargs)
        previous = self._get_previous(conv_key)

        should_strip = (previous is None or previous != current)

        if should_strip:
            removed = self._strip_thinking(messages)
            logger.warning(
                "ThinkingBlockGuard: %s for conv %s, stripped %d thinking block(s)",
                f"backend switched {previous}->{current}" if previous else f"no record, target={current}",
                conv_key,
                removed,
            )

        self._set_current(conv_key, current)
        return kwargs


thinking_block_guard = ThinkingBlockGuard()
