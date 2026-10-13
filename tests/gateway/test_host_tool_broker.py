"""Bounded current-Run tool request/result exchange, without model or network I/O."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest


def broker(events, **kwargs):
    from gateway.host_tools import HostToolBroker
    return HostToolBroker("run-a", {"facts", "prepare"}, events.put,
                          serial_tools={"prepare"}, **kwargs)


def test_host_result_reaches_original_call_and_duplicate_reply_is_idempotent():
    events = Queue()
    host = broker(events)
    with ThreadPoolExecutor(max_workers=1) as worker:
        waiting = worker.submit(host.call, "prepare", {"quantity": "1"})
        request = events.get(timeout=2)
        assert request["event"] == "host_tool.request"
        assert request["name"] == "prepare"
        reply = {"callId": request["callId"], "status": "ready", "data": {"actionId": "a"}}
        host.resolve(request["callId"], request["requestHash"], reply)
        assert waiting.result(timeout=2) == reply
        assert host.resolve(request["callId"], request["requestHash"], reply) is False
        with pytest.raises(ValueError):
            host.resolve(request["callId"], request["requestHash"], {**reply, "status": "different"})
    host.close()


def test_host_rejects_unknown_tools_nonfinite_or_oversized_payloads_without_publishing():
    events = Queue()
    host = broker(events)
    for name, args in [("terminal", {}), ("facts", {"bad": float("nan")}),
                       ("facts", {"large": "x" * 8193})]:
        result = host.call(name, args)
        assert result["status"] == "error"
    assert events.empty()
    host.close()


def test_conflicting_scope_or_hash_cannot_answer_a_pending_call():
    events = Queue()
    host = broker(events)
    with ThreadPoolExecutor(max_workers=1) as worker:
        waiting = worker.submit(host.call, "facts", {})
        request = events.get(timeout=2)
        with pytest.raises(LookupError):
            host.resolve("other-run-call", request["requestHash"], {"status": "ready"})
        with pytest.raises(ValueError):
            host.resolve(request["callId"], "wrong-hash", {"status": "ready"})
        host.close()
        result = waiting.result(timeout=2)
        assert result["status"] == "error" and result["error"]["code"] == "HOST_CALL_CANCELLED"


def test_timeout_reports_original_call_id_and_rejects_late_result():
    events = Queue()
    host = broker(events, timeout=0.1)
    result = host.call("prepare", {})
    request = events.get_nowait()
    assert result["callId"] == request["callId"]
    assert result["error"]["code"] == "HOST_CALL_UNKNOWN"
    with pytest.raises(LookupError):
        host.resolve(request["callId"], request["requestHash"], {"status": "ready"})
    host.close()


def test_two_read_slots_and_serial_preparation_are_released_on_stop():
    events = Queue()
    host = broker(events)
    with ThreadPoolExecutor(max_workers=3) as worker:
        futures = [worker.submit(host.call, "facts", {"number": i}) for i in range(3)]
        events.get(timeout=2)
        events.get(timeout=2)
        host.close()
        assert all(f.result(timeout=2)["status"] == "error" for f in futures)
        assert events.empty()


def test_unbound_plugin_call_never_falls_back_to_another_channel():
    from gateway.host_tools import call_current_host_tool, host_tool_scope
    assert call_current_host_tool("prepare", {})["status"] == "error"
    events = Queue()
    host = broker(events)
    host.close()
    with host_tool_scope(host):
        result = call_current_host_tool("prepare", {})
    assert result["status"] == "error"
    assert events.empty()
