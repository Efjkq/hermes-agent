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
    assert "runId" not in result
    with pytest.raises(LookupError):
        host.resolve(request["callId"], request["requestHash"], {"status": "ready"})
    host.close()


@pytest.mark.parametrize("outcome", ["timeout", "publish_failure", "stop", "already_stopped"])
def test_uncertain_host_outcome_preserves_original_platform_run_identity(outcome):
    from gateway.host_tools import HostCallInactive, HostToolBroker
    events = Queue()
    release_publish = threading.Event()

    def publish(event):
        events.put(event)
        if outcome == "stop":
            # Keep the worker in publication until Stop has installed its reply;
            # coordinator scheduling must not race the broker's 50ms deadline.
            assert release_publish.wait(timeout=2), "Stop did not release publication"
        if outcome == "publish_failure":
            raise RuntimeError("Delivery outcome is unknown")

    host = HostToolBroker("native-run", {"prepare"}, publish,
                          recovery_run_id="platform-original-run", timeout=0.05)
    arguments = {"runId": "model-forged-run", "context_id": "model-forged-context"}
    request = None
    if outcome == "stop":
        with ThreadPoolExecutor(max_workers=1) as worker:
            waiting = worker.submit(host.call, "prepare", arguments)
            request = events.get(timeout=2)
            host.close()
            release_publish.set()
            result = waiting.result(timeout=2)
    else:
        if outcome == "already_stopped":
            host.close()
        result = host.call("prepare", arguments)
        if outcome != "already_stopped":
            request = events.get_nowait()

    code = "HOST_CALL_CANCELLED" if outcome in {"stop", "already_stopped"} else "HOST_CALL_UNKNOWN"
    assert result == {"status": "error", "error": {"code": code},
                      "callId": result["callId"], "runId": "platform-original-run"}
    if request is not None:
        assert result["callId"] == request["callId"]
        assert request["run_id"] == "native-run"
        with pytest.raises(HostCallInactive):
            host.resolve(request["callId"], request["requestHash"], {"status": "ready"})
    else:
        assert events.empty()
    host.close()


def test_timeout_is_inactive_before_pending_cleanup():
    from gateway.host_tools import HostCallInactive
    events = Queue()
    host = broker(events, timeout=0.01)
    result_attempts = []
    class TimeoutInterleave:
        """Force the late reply between the timeout and finally locks."""
        def __init__(self):
            self.lock = threading.Lock()
            self.interleaved = False
        def __enter__(self):
            self.lock.acquire()
        def __exit__(self, *_):
            self.lock.release()
            if not self.interleaved and host._settled and host._pending:
                self.interleaved = True
                request = events.queue[0]
                try:
                    result_attempts.append(host.resolve(request["callId"], request["requestHash"], {"status":"ready"}))
                except HostCallInactive:
                    result_attempts.append("inactive")
    host._lock = TimeoutInterleave()
    outcome = host.call("prepare", {})
    assert outcome["error"]["code"] == "HOST_CALL_UNKNOWN"
    assert result_attempts == ["inactive"]
    request = events.get_nowait()
    with pytest.raises(HostCallInactive):
        host.resolve(request["callId"], request["requestHash"], {"status":"ready"})
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

def test_host_preserves_number_bytes_for_a_json_consumer_with_integer_number_spelling():
    import hashlib
    events = Queue()
    host = broker(events)
    with ThreadPoolExecutor(max_workers=1) as worker:
        waiting = worker.submit(host.call, "facts", {"number": 50.0})
        request = events.get(timeout=2)
        host.close()
        waiting.result(timeout=2)
    # JavaScript parses 50.0 as 50. The original bytes must remain available
    # to verify the same request digest rather than misrejecting valid inputs.
    consumer_json = request.get("argumentsJson", '{"number":50}')
    assert hashlib.sha256(("facts\n" + consumer_json).encode()).hexdigest() == request["requestHash"]
    assert json.loads(consumer_json) == request["arguments"]
