"""Validated current-conversation messages; delivery belongs to the caller's run.

This is a display transport, not an action executor. A callback_data value is
untrusted input until the hosting application's authenticated action registry
resolves it. ContextVars preserve the same delivery scope in tool workers.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Callable, Literal, Optional
from urllib.parse import urlsplit
from uuid import uuid4
import json
from tools.execution_scope import proposal_only_scope

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InlineButton(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=256)
    callback_data: Optional[str] = None
    url: Optional[str] = None
    style: Optional[Literal["primary", "success", "danger"]] = None

    @model_validator(mode="after")
    def valid_action(self):
        if (self.callback_data is not None) == (self.url is not None):
            raise ValueError("A button must have exactly one action")
        if self.callback_data is not None and not 1 <= len(self.callback_data.encode("utf-8")) <= 64:
            raise ValueError("callback_data must contain 1–64 UTF-8 bytes")
        if self.url is not None:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Only HTTP(S) links without credentials are supported")
        return self


class InlineKeyboard(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    inline_keyboard: list[list[InlineButton]] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def bounded_rows(self):
        if any(not 1 <= len(row) <= 8 for row in self.inline_keyboard):
            raise ValueError("Each keyboard row must contain 1–8 buttons")
        if sum(map(len, self.inline_keyboard)) > 64:
            raise ValueError("Too many keyboard buttons")
        return self


class InteractionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1, 2]
    mode: Optional[Literal["paper", "live"]] = None
    account_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    market_key: Optional[str] = Field(default=None, min_length=1, max_length=512)
    context_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    host_data: Optional[dict] = None
    host_tools: list[str] = Field(default_factory=list, max_length=8)
    serial_host_tools: list[str] = Field(default_factory=list, max_length=8)
    execution_policy: Optional[Literal["proposal_only", "pawpilot"]] = None

    @model_validator(mode="after")
    def bounded_host_data(self):
        if self.version == 1 and (self.mode is None or self.account_id is None or self.execution_policy == "pawpilot"):
            raise ValueError("Legacy interaction requires its original account scope")
        if self.version == 2 and (self.execution_policy != "pawpilot" or self.mode is not None or self.account_id is not None or self.market_key is not None):
            raise ValueError("Version 2 separates page context from execution policy")
        if self.host_tools or self.serial_host_tools:
            if (self.version != 2 and not is_proposal_context(self.model_dump())) or len(set(self.host_tools)) != len(self.host_tools):
                raise ValueError("Host tools require a unique proposal-only manifest")
            if any(not name.isidentifier() or len(name) > 64 for name in self.host_tools):
                raise ValueError("Invalid host tool name")
            if not set(self.serial_host_tools) <= set(self.host_tools):
                raise ValueError("Unknown serialized host tool")
        if self.host_data is not None:
            encoded = json.dumps(self.host_data, allow_nan=False, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > 32768:
                raise ValueError("Host context is too large")
        return self


def is_proposal_context(context: Optional[dict]) -> bool:
    """Paper's legacy policy and explicit Live policy share the same restrictions."""
    return bool(context and (context.get("mode") == "paper" or
                             context.get("execution_policy") == "proposal_only"))


_delivery: ContextVar[Optional[Callable[[dict, str, Optional[dict], Optional[dict]], Optional[dict]]]] = ContextVar(
    "current_interactive_delivery", default=None,
)
_context: ContextVar[Optional[dict]] = ContextVar("current_interaction_context", default=None)


@contextmanager
def current_message_scope(deliver: Callable, context: Optional[dict] = None, *, available_tools=None):
    delivery_token = _delivery.set(deliver)
    context_token = _context.set(deepcopy(context))
    try:
        from tools.execution_scope import host_tool_scope
        with host_tool_scope((context or {}).get("host_tools", ()) if (context or {}).get("version") == 2 else ()), proposal_only_scope(is_proposal_context(context),
                                 host_tools=(context or {}).get("host_tools", ()),
                                 available_tools=available_tools):
            yield
    finally:
        _context.reset(context_token)
        _delivery.reset(delivery_token)


def current_interaction_context() -> Optional[dict]:
    return deepcopy(_context.get())


def send_current_message(text: str, reply_markup=None, metadata=None, *, _message_id=None) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        return {"error": "Current conversation message must contain 1–4096 characters"}
    message = {"text": text}
    if reply_markup is not None:
        try:
            message["reply_markup"] = InlineKeyboard.model_validate(reply_markup).model_dump(exclude_none=True)
        except (ValueError, TypeError):
            return {"error": "Invalid inline keyboard: expected bounded text, safe links or 1–64 byte callback_data"}
    if metadata is not None:
        try:
            if not isinstance(metadata, dict):
                raise ValueError("Expected an object")
            encoded = json.dumps(metadata, allow_nan=False, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > 32768:
                raise ValueError("Metadata too large")
            metadata = json.loads(encoded)
        except (ValueError, TypeError, RecursionError):
            return {"success": False, "code": "HOST_METADATA_INVALID",
                    "error": "Host metadata must be a finite JSON object of at most 32768 bytes",
                    "publication": {"status": "not_attempted"},
                    "failure": {"category": "invalid_request", "recovery": "correct_request",
                                "retrySameInput": False, "fields": [{"path": "metadata", "code": "invalid_type",
                                "message": "Pass a finite JSON object, not a JSON-encoded string. Correct the object before publishing again."}]}}
    deliver = _delivery.get()
    if deliver is None:
        return {"error": "No current conversation delivery is available in this execution context"}
    message_id = _message_id or f"msg_{uuid4().hex}"
    if not isinstance(message_id,str) or not 1 <= len(message_id) <= 200:
        return {"success":False,"code":"INVALID_MESSAGE_ID"}
    # The caller owns delivery; do not fall back to another channel on failure.
    try:
        receipt = deliver(deepcopy(message), message_id, current_interaction_context(), deepcopy(metadata))
        if isinstance(receipt, dict):
            if receipt.get("success") is not True:
                return receipt
            message_id = receipt.get("message_id", message_id)
    except Exception:
        return {"error": "Current conversation delivery is unavailable; no other channel was used"}
    return {"success": True, "message_id": message_id, "message": message,
            **({key: receipt[key] for key in ("publication", "duplicate") if key in receipt}
               if isinstance(receipt, dict) else {}),
            **({"metadata": metadata} if metadata is not None else {}),
            **({"context": current_interaction_context()} if _context.get() is not None else {})}
