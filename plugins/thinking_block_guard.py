"""
ThinkingBlockGuard — LiteLLM callback that strips thinking blocks
when the router switches between kiro-gateway and Bedrock backends.

Prevents 'Invalid signature in thinking block' errors when mixing
providers in the same model group with weight-based routing.

How it works:
  1. After LiteLLM router selects a deployment, this hook fires
  2. It identifies the backend (kiro or bedrock) from api_base
  3. It tracks the last backend used per conversation (in-memory)
  4. If the backend changed, it strips thinking/redacted_thinking
     blocks from assistant messages — their signatures are
     provider-bound and would cause 400 errors on the new backend
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

from litellm.integrations.custom_logger import CustomLogger
from litellm.types.utils import CallTypes

logger = logging.getLogger(__name__)


class ThinkingBlockGuard(CustomLogger):

    KIRO_MARKER = "kiro-gateway"
    THINKING_TYPES = frozenset(("thinking", "redacted_thinking"))
    MAX_CACHE_SIZE = 10_000

    def __init__(self) -> None:
        super().__init__()
        # conversation_key -> backend identifier ("kiro" | "bedrock")
        self._last_backend: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _conversation_key(messages: List[dict]) -> str:
        """Derive a stable key for a conversation.

        Uses the first user message content as an anchor — this is
        typically stable across multi-turn requests in the same
        conversation (Claude Code keeps the original user prompt).
        """
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # content blocks — grab first text block
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
        """Return 'kiro' or 'bedrock' based on the selected deployment."""
        api_base = (
            kwargs.get("litellm_metadata", {}).get("api_base")
            or kwargs.get("metadata", {}).get("api_base")
            or ""
        )
        return "kiro" if self.KIRO_MARKER in str(api_base) else "bedrock"

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
        """Remove thinking blocks in-place. Returns count of blocks removed."""
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

    def _evict_cache(self) -> None:
        if len(self._last_backend) > self.MAX_CACHE_SIZE:
            keys = list(self._last_backend.keys())
            for k in keys[: self.MAX_CACHE_SIZE // 2]:
                del self._last_backend[k]

    # ------------------------------------------------------------------
    # Hook
    # ------------------------------------------------------------------

    async def async_pre_call_deployment_hook(
        self,
        kwargs: Dict[str, Any],
        call_type: Optional[CallTypes],
    ) -> Optional[dict]:
        messages = kwargs.get("messages")
        if not messages:
            return None  # nothing to do

        conv_key = self._conversation_key(messages)
        current = self._backend_id(kwargs)
        previous = self._last_backend.get(conv_key)

        if previous and previous != current and self._has_thinking(messages):
            removed = self._strip_thinking(messages)
            logger.warning(
                "ThinkingBlockGuard: backend switched %s→%s for conv %s, "
                "stripped %d thinking block(s)",
                previous,
                current,
                conv_key,
                removed,
            )

        self._last_backend[conv_key] = current
        self._evict_cache()
        return kwargs


# LiteLLM imports this instance via the callbacks config
thinking_block_guard = ThinkingBlockGuard()
