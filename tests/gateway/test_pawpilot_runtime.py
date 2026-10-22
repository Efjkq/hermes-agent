"""Versioned business proxies preserve existing owner tools and native delivery."""
import json
from unittest.mock import patch
import pytest
from aiohttp.test_utils import TestClient, TestServer
from gateway.interactive_messages import InteractionContext, current_message_scope, is_proposal_context
from tests.gateway.test_api_server_interactive_messages import _interactive_app, settle
from tests.gateway.test_api_server_runs import _make_adapter
from tests.gateway.test_api_host_tools import host_plugin, HostAgent


def test_v2_context_does_not_invent_a_page_account_or_proposal_policy():
    value=InteractionContext.model_validate({"version":2,"execution_policy":"pawpilot","host_tools":[]})
    assert not is_proposal_context(value.model_dump(exclude_none=True))
    assert value.account_id is None
    with pytest.raises(ValueError):
        InteractionContext.model_validate({"version":1,"mode":"paper"})
    with pytest.raises(ValueError):
        InteractionContext.model_validate({"version":2,"execution_policy":"pawpilot","account_id":"ui-account"})

@pytest.mark.asyncio
async def test_v2_native_host_round_trip_keeps_normal_execution_policy(host_plugin):
    adapter,agent=_make_adapter("test-key"),HostAgent()
    headers={"Authorization":"Bearer test-key"}
    with patch.object(adapter,"_create_agent",return_value=agent):
        async with TestClient(TestServer(_interactive_app(adapter))) as client:
            response=await client.post('/v1/runs',headers=headers,json={"input":"Hello","interaction_context":{"version":2,"execution_policy":"pawpilot","host_tools":[host_plugin]}})
            assert response.status==202,await response.text()
            run_id=(await response.json())["run_id"]
            stream=await client.get(f'/v1/runs/{run_id}/events',headers=headers)
            while True:
                line=await stream.content.readline()
                if line.startswith(b'data:'):
                    event=json.loads(line[5:])
                    if event.get('event')=='host_tool.request':break
            reply=await client.post(f'/v1/runs/{run_id}/host-tools/{event["callId"]}/result',headers=headers,json={"requestHash":event["requestHash"],"result":{"status":"ready","data":{"ok":True}}})
            assert reply.status==200
            await settle(adapter,run_id)
            assert adapter._create_agent.call_args.kwargs['proposal_only'] is False
            assert agent.result['data']['ok'] is True
            stream.release()

def test_v2_host_catalog_adds_only_bound_proxies_and_keeps_owner_tools(host_plugin):
    from tools.registry import registry
    from tools.execution_scope import execution_scope_error
    assert not registry.get_definitions({host_plugin},quiet=True)
    with current_message_scope(lambda *args:None,{"version":2,"execution_policy":"pawpilot","host_tools":[host_plugin]}):
        assert registry.get_definitions({host_plugin},quiet=True)[0]['function']['name']==host_plugin
        assert execution_scope_error('terminal') is None
    assert not registry.get_definitions({host_plugin},quiet=True)

def test_trusted_delivery_envelope_uses_original_message_id_without_model_copying():
    from gateway.host_tools import host_tool_scope, call_current_host_tool
    class Broker:
        def call(self,name,args):
            return {"status":"ready","publish":{"messageId":"original-card","message":{"text":"Review draft","reply_markup":{"inline_keyboard":[[{"text":"Review","callback_data":"tc:original:review"}]]}},"metadata":{"preparedActions":["original-action"]}}}
    delivered=[]
    def deliver(message,message_id,context,metadata):
        delivered.append((message,message_id,metadata))
        return {"success":True,"publication":{"status":"registered"}}
    with host_tool_scope(Broker()),current_message_scope(deliver,{"version":2,"execution_policy":"pawpilot"}):
        first=call_current_host_tool('prepare',{})
        second=call_current_host_tool('prepare',{})
    assert first['publication']['status']=='registered'
    assert second['publication']['messageId']=='original-card'
    assert [item[1] for item in delivered]==['original-card','original-card']
    assert delivered[0][2]=={"preparedActions":["original-action"]}


def test_v2_bound_proxy_skill_is_listed_and_readable_only_in_its_run(host_plugin, tmp_path, monkeypatch):
    import tools.skills_tool as skills
    monkeypatch.setenv("SKILL_SECURITY_GATE_ENABLED", "false")
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [])
    monkeypatch.setattr(skills, "_get_disabled_skill_names", lambda: set())
    folder = tmp_path / "bound-task"
    folder.mkdir()
    content = ("---\nname: bound-task\ndescription: Read a bound business task.\n"
               "metadata:\n  hermes:\n    requires_tools:\n      - " + host_plugin + "\n---\nUse the bound operation.\n")
    (folder / "SKILL.md").write_text(content)
    skills._SKILLS_CACHE.clear()
    try:
        assert not json.loads(skills.skill_view("bound-task"))["success"]
        context = {"version": 2, "execution_policy": "pawpilot", "host_tools": [host_plugin]}
        with current_message_scope(lambda *args: None, context):
            listing = json.loads(skills.skills_list())
            assert any(item["name"] == "bound-task" for item in listing["skills"]), listing
            viewed = json.loads(skills.skill_view("bound-task"))
            assert viewed["success"], viewed
            assert viewed["content"] == content
        assert not json.loads(skills.skill_view("bound-task"))["success"]
    finally:
        skills._SKILLS_CACHE.clear()
