"""Compact host presentation preserves full authorized owner tool behavior."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from tools.tool_search import ToolSearchConfig


def test_explicit_disclosure_keeps_core_callable_and_default_surface_unchanged(monkeypatch):
    from model_tools import get_tool_definitions, _clear_tool_defs_cache
    config = {'enabled': 'on', 'defer_core_tools': ['cronjob', 'todo', 'write_file', 'patch', 'search_files']}
    monkeypatch.setenv('HERMES_GATEWAY_SESSION', '1')
    monkeypatch.setattr('tools.tool_search.load_config', lambda: ToolSearchConfig.from_raw(config))
    enabled = ['cronjob', 'todo', 'terminal', 'file', 'skills']
    compact = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True)
    names = {d['function']['name'] for d in compact}
    assert {'terminal', 'process', 'skill_view', 'tool_search', 'tool_describe', 'tool_call'} <= names
    assert not {'cronjob', 'todo', 'write_file', 'patch', 'search_files'} & names
    full = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True)
    assert {'cronjob', 'todo', 'write_file', 'patch', 'search_files'} <= {d['function']['name'] for d in full}
    assert len(json.dumps(compact)) < len(json.dumps(full)) * 0.8
    config.pop('defer_core_tools')
    _clear_tool_defs_cache()
    default = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True)
    assert {'cronjob', 'todo', 'write_file', 'patch', 'search_files'} <= {d['function']['name'] for d in default}


def test_deferred_core_uses_original_handler_and_cannot_reach_ungranted_toolsets(monkeypatch, tmp_path):
    from model_tools import handle_function_call
    monkeypatch.setattr('tools.tool_search.load_config', lambda: ToolSearchConfig.from_raw(
        {'enabled': 'on', 'defer_core_tools': ['write_file', 'cronjob']}))
    schema = json.loads(handle_function_call('tool_describe', {'name': 'write_file'}, enabled_toolsets=['file']))
    assert schema.get('name') == 'write_file', schema
    assert 'path' in schema['parameters']['properties']
    destination = tmp_path / 'owned.txt'
    result = json.loads(handle_function_call('tool_call', {'name': 'write_file', 'arguments': {
        'path': str(destination), 'content': 'Keep owner capabilities'}},
        task_id='compact-owner-check', enabled_toolsets=['file']))
    assert not result.get('error'), result
    assert destination.read_text() == 'Keep owner capabilities'
    denied = json.loads(handle_function_call('tool_call', {'name': 'cronjob', 'arguments': {'action': 'list'}},
        task_id='compact-owner-check', enabled_toolsets=['file']))
    assert denied.get('error'), denied


def test_explicit_always_visible_owner_choice_wins_over_deferral(monkeypatch):
    from model_tools import get_tool_definitions, _clear_tool_defs_cache
    _clear_tool_defs_cache()
    monkeypatch.setattr('tools.tool_search.load_config', lambda: ToolSearchConfig.from_raw(
        {'enabled': 'on', 'defer_core_tools': ['todo'], 'always_visible_tools': ['todo']}))
    defs = get_tool_definitions(enabled_toolsets=['todo'], quiet_mode=True)
    assert 'todo' in {d['function']['name'] for d in defs}


def test_compact_scope_does_not_leak_to_other_sessions_or_override_off(monkeypatch):
    from model_tools import get_tool_definitions, _clear_tool_defs_cache
    from tools.execution_scope import host_tool_scope
    import hermes_cli.config
    config = {'tools': {'tool_search': {'enabled': 'on'}}}
    monkeypatch.setattr(hermes_cli.config, 'load_config', lambda: config)
    _clear_tool_defs_cache()
    def names():
        return {d['function']['name'] for d in get_tool_definitions(enabled_toolsets=['todo', 'terminal'], quiet_mode=True)}
    with host_tool_scope(compact=True):
        compact = names()
    full = names()
    with host_tool_scope(compact=True):
        assert names() == compact
    assert {'terminal', 'tool_call'} <= compact and 'todo' not in compact
    assert 'todo' in full and 'tool_call' not in full
    config['tools']['tool_search']['enabled'] = 'off'
    _clear_tool_defs_cache()
    with host_tool_scope(compact=True):
        assert 'todo' in names()


def test_deferred_core_remains_visible_to_skills_and_uses_session_todo_store(monkeypatch):
    from run_agent import AIAgent
    monkeypatch.setattr('tools.tool_search.load_config', lambda: ToolSearchConfig.from_raw(
        {'enabled': 'on', 'defer_core_tools': ['todo']}))
    monkeypatch.setattr('run_agent.OpenAI', MagicMock())
    agent = AIAgent(api_key='offline-test', base_url='http://localhost:1/v1',
                    model='offline', enabled_toolsets=['todo'], quiet_mode=True,
                    skip_context_files=True, skip_memory=True)
    assert 'todo' in agent.valid_tool_names
    assert 'todo' not in {d['function']['name'] for d in agent.tools}
    call = SimpleNamespace(id='original-call', type='function', function=SimpleNamespace(
        name='tool_call', arguments=json.dumps({'name': 'todo', 'arguments': {'todos': [
            {'id': 'owned', 'content': 'Retain owner capability', 'status': 'pending'}]}})))
    messages = []
    agent._execute_tool_calls_sequential(SimpleNamespace(tool_calls=[call]), messages, 'owner-session')
    assert agent._todo_store.has_items()
    assert messages[0]['tool_call_id'] == 'original-call'
    assert 'Retain owner capability' in messages[0]['content']
