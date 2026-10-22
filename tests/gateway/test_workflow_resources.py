"""Workflow references use native visibility, disable and path checks."""
import json
import pytest
from gateway.interactive_messages import InteractionContext, load_workflow_skill_context


@pytest.fixture
def installed_methods(tmp_path, monkeypatch):
    import tools.skills_tool as skills
    monkeypatch.setenv('SKILL_SECURITY_GATE_ENABLED', 'false')
    monkeypatch.setattr(skills, 'SKILLS_DIR', tmp_path)
    monkeypatch.setattr('agent.skill_utils.get_external_skills_dirs', lambda: [])
    disabled = []
    monkeypatch.setattr('hermes_cli.config.load_config', lambda: {'skills': {'disabled': disabled}})
    for name in ['workflow', 'methods']:
        folder = tmp_path / name
        folder.mkdir()
        (folder / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Read evidence.\n---\nUse actual facts.')
    references = tmp_path / 'methods' / 'references'
    references.mkdir()
    (references / 'risk.md').write_text('Use native liquidation; unknown is not zero.')
    (references / 'costs.md').write_text('Account for fees and funding; do not invent net returns.')
    skills._SKILLS_CACHE.clear()
    yield disabled
    skills._SKILLS_CACHE.clear()


def test_workflow_and_references_arrive_together_without_another_model_turn(installed_methods):
    context = {'version': 2, 'execution_policy': 'pawpilot', 'workflow_skills': ['workflow'],
               'workflow_resources': [{'name': 'methods', 'file_path': 'references/risk.md'},
                                      {'name': 'methods', 'file_path': 'references/costs.md'}]}
    notes = load_workflow_skill_context(context, {'skill_view'}, 'task')
    assert 'Use actual facts.' in notes
    assert 'Use native liquidation; unknown is not zero.' in notes
    assert 'Account for fees and funding' in notes
    assert 'already loaded' in notes
    assert InteractionContext.model_validate(context).model_dump()['workflow_resources'] == context['workflow_resources']


def test_disabled_or_missing_reference_fails_before_claiming_workflow_is_loaded(installed_methods):
    context = {'version': 2, 'execution_policy': 'pawpilot',
               'workflow_resources': [{'name': 'methods', 'file_path': 'references/risk.md'}]}
    installed_methods.append('methods')
    with pytest.raises(RuntimeError, match='unavailable'):
        load_workflow_skill_context(context, {'skill_view'}, 'task')
    installed_methods.clear()
    context['workflow_resources'][0]['file_path'] = 'references/missing.md'
    with pytest.raises(RuntimeError, match='unavailable'):
        load_workflow_skill_context(context, {'skill_view'}, 'task')


@pytest.mark.parametrize('path', ['/etc/passwd', '../secret', 'references/../../secret', ''])
def test_workflow_resource_paths_cannot_escape_the_skill(path):
    with pytest.raises(ValueError):
        InteractionContext.model_validate({'version': 2, 'execution_policy': 'pawpilot',
            'workflow_resources': [{'name': 'methods', 'file_path': path}]})
