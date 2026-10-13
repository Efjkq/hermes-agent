"""Host-bound proposal sessions reuse Agent research without arbitrary execution.

This does not sandbox a shell: shell/code/browser/delegation/background jobs and
unknown plugin/MCP tools are unavailable in this scope. Financial execution
belongs to the host's independently authenticated human-confirmation path.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json

PROPOSAL_ONLY_TOOL_NAMES = frozenset({
    "web_search", "web_extract", "x_search",
    "memory", "session_search", "todo", "skills_list", "send_message", "clarify",
})
_policy = ContextVar("host_tool_execution_policy", default=None)

@contextmanager
def proposal_only_scope(enabled: bool):
    token = _policy.set("proposal_only" if enabled else None)
    try:
        yield
    finally:
        _policy.reset(token)

def execution_scope_error(name: str):
    if _policy.get() == "proposal_only" and name not in PROPOSAL_ONLY_TOOL_NAMES:
        return json.dumps({"error": "This proposal-only conversation cannot execute arbitrary tools. Prepare a host card for the user's separate review and confirmation.", "error_type": "proposal_only", "tool": name})
    return None
