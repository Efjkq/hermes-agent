"""Native HTTP host exchange and restricted tool schemas, without model I/O."""
import asyncio
import json
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from tools.registry import registry
from tests.gateway.test_api_server_interactive_messages import _interactive_app, context, settle
from tests.gateway.test_api_server_runs import _make_adapter


@pytest.fixture
def host_plugin(monkeypatch):
    from tools.registry import ToolRegistry
    isolated = ToolRegistry()
    isolated.register(name="test_host_read", toolset="api_host_tools",
        schema={"name": "test_host_read", "parameters": {"type": "object", "properties": {}}},
        handler=lambda *a, **kw: pytest.fail("Native fallback must never execute"))
    monkeypatch.setitem(registry._tools, "test_host_read", isolated._tools["test_host_read"])
    monkeypatch.setattr("hermes_cli.tools_config._get_platform_tools", lambda *a: ["api_host_tools", "skills"])
    return "test_host_read"


class HostAgent:
    session_prompt_tokens = session_completion_tokens = session_total_tokens = 0
    valid_tool_names = {"test_host_read", "skills_list", "skill_view"}

    def run_conversation(self, **kwargs):
        from model_tools import handle_function_call
        self.result = json.loads(handle_function_call("test_host_read", {}))
        return {"final_response": "done"}


@pytest.mark.asyncio
async def test_authenticated_native_result_resolves_one_original_run(host_plugin):
    adapter, agent = _make_adapter("test-key"), HostAgent()
    headers = {"Authorization": "Bearer test-key"}
    with patch.object(adapter, "_create_agent", return_value=agent):
        async with TestClient(TestServer(_interactive_app(adapter))) as client:
            response = await client.post("/v1/runs", headers=headers, json={
                "input": "Read", "interaction_context": {**context(), "host_tools": [host_plugin]}})
            assert response.status == 202, await response.text()
            run_id = (await response.json())["run_id"]
            stream = await client.get(f"/v1/runs/{run_id}/events", headers=headers)
            while True:
                line = await asyncio.wait_for(stream.content.readline(), 5)
                if line.startswith(b"data:"):
                    event = json.loads(line[5:])
                    if event.get("event") == "host_tool.request":
                        break
            route = f"/v1/runs/{run_id}/host-tools/{event['callId']}/result"
            reply = {"requestHash": event["requestHash"], "result": {"status": "ready", "data": {"balance": "100"}}}
            assert (await client.post(route, json=reply)).status == 401
            assert (await client.post(route, headers=headers, json={**reply, "requestHash": "wrong"})).status == 409
            assert (await client.post(route.replace(run_id, "other-run"), headers=headers, json=reply)).status == 404
            assert (await client.post(route, headers=headers, json=reply)).status == 200
            await settle(adapter, run_id)
            assert agent.result["data"]["balance"] == "100"
            assert agent.result["callId"] == event["callId"]
            stream.release()


@pytest.mark.asyncio
async def test_host_runs_require_configured_auth_and_registered_owner_tool(host_plugin):
    for key, name in [("", host_plugin), ("test-key", "terminal")]:
        adapter = _make_adapter(key)
        async with TestClient(TestServer(_interactive_app(adapter))) as client:
            response = await client.post("/v1/runs", headers={"Authorization": "Bearer test-key"},
                json={"input": "Read", "interaction_context": {**context(), "host_tools": [name]}})
            assert response.status == 400
            assert not adapter._active_run_tasks


def test_scoped_schema_cache_cannot_restore_broad_tools(host_plugin):
    from model_tools import get_tool_definitions
    from tools.execution_scope import proposal_only_scope
    with proposal_only_scope(True, host_tools=[host_plugin], available_tools=[host_plugin, "skills_list"]):
        first = get_tool_definitions(enabled_toolsets=["api_host_tools", "skills"], quiet_mode=True)
    with proposal_only_scope(True, available_tools=["skill_view"]):
        second = get_tool_definitions(enabled_toolsets=["api_host_tools", "skills"], quiet_mode=True)
    assert {t["function"]["name"] for t in first} == {host_plugin, "skills_list"}
    assert {t["function"]["name"] for t in second} == {"skill_view"}

@pytest.mark.asyncio
async def test_stop_releases_host_wait_without_native_or_channel_fallback(host_plugin):
    adapter, agent = _make_adapter("test-key"), HostAgent()
    headers = {"Authorization": "Bearer test-key"}
    with patch.object(adapter, "_create_agent", return_value=agent):
        async with TestClient(TestServer(_interactive_app(adapter))) as client:
            response = await client.post("/v1/runs", headers=headers, json={"input": "Read",
                "interaction_context": {**context(), "host_tools": [host_plugin]}})
            run_id = (await response.json())["run_id"]
            stream = await client.get(f"/v1/runs/{run_id}/events", headers=headers)
            while True:
                line = await asyncio.wait_for(stream.content.readline(), 5)
                if line.startswith(b"data:") and json.loads(line[5:]).get("event") == "host_tool.request":
                    break
            task = adapter._active_run_tasks[run_id]
            assert (await client.post(f"/v1/runs/{run_id}/stop", headers=headers)).status == 200
            await asyncio.wait_for(task, 2)
            assert agent.result["error"]["code"] == "HOST_CALL_CANCELLED"
            assert run_id not in adapter._run_host_tools
            stream.release()
