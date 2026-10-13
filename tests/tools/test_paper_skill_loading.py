"""Real native loads under a host proposal policy; no secret or model I/O."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import tools.skills_tool as skills
from tools.execution_scope import proposal_only_scope, execution_scope_error


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    directory = root / "paper-help"
    (directory / "references").mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: paper-help\ndescription: Paper help\n"
        "metadata:\n  hermes:\n    requires_tools: [paper_read]\n"
        "required_environment_variables:\n  - name: FAKE_SECRET\n"
        "required_credential_files: [fake-credential]\n---\n"
        "# Help\nPath: ${HERMES_SKILL_DIR}\n"
        f"!\u0060printf ran > {tmp_path / 'executed'}\u0060\n"
    )
    (directory / "references" / "usage.md").write_text("# Complete reference\nRead all of me.\n")
    monkeypatch.setattr(skills, "SKILLS_DIR", root)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [])
    monkeypatch.setattr(skills, "_get_disabled_skill_names", lambda: set())
    monkeypatch.setattr(skills, "_is_skill_disabled", lambda name: False)
    from tools.registry import registry
    monkeypatch.setitem(registry._tools, "paper_read", SimpleNamespace(toolset="api_host_tools"))
    monkeypatch.setattr(skills, "_skill_security_allows_view",
                        lambda *a, **kw: SimpleNamespace(allowed=True, reason="test verified", archive=kw.get("archive")))
    monkeypatch.setenv("SKILL_SECURITY_GATE_ENABLED", "true")
    monkeypatch.setattr("agent.skill_preprocessing.load_skills_config", lambda: {"inline_shell": True})
    def no_secret_read():
        raise AssertionError("Paper loading must not read secret environment")
    monkeypatch.setattr(skills, "load_env", no_secret_read)
    skills._SKILLS_CACHE.clear()
    return directory


def test_paper_full_load_preserves_path_but_never_executes_or_sets_up_credentials(bundle):
    with proposal_only_scope(True, host_tools={"paper_read"}):
        result = json.loads(skills.skill_view("paper-help"))
    assert result.get("success") is True, result
    assert str(bundle) in result["content"]
    assert not (bundle.parent.parent / "executed").exists()
    assert result["setup_needed"] is False
    assert "references/usage.md" in result["linked_files"]["references"]


def test_paper_reference_reads_remain_complete_and_cannot_escape(bundle):
    outside = bundle.parent / "secret.md"
    outside.write_text("outside-scope")
    with proposal_only_scope(True, host_tools={"paper_read"}):
        result = json.loads(skills.skill_view("paper-help", file_path="references/usage.md"))
        (bundle / "references" / "escape.md").symlink_to(outside)
        escaped = json.loads(skills.skill_view("paper-help", file_path="references/escape.md"))
    assert result["content"] == "# Complete reference\nRead all of me.\n"
    assert escaped["success"] is False
    assert "outside-scope" not in json.dumps(escaped)


def test_skill_view_is_admitted_as_read_only_but_execution_tools_remain_blocked():
    with proposal_only_scope(True):
        assert execution_scope_error("skill_view") is None
        assert execution_scope_error("terminal") is not None
        assert execution_scope_error("execute_code") is not None


def test_required_tools_filter_both_listing_and_direct_load(bundle):
    with proposal_only_scope(True):
        listing = json.loads(skills.skills_list())
        direct = json.loads(skills.skill_view("paper-help"))
    assert listing["skills"] == []
    assert direct["success"] is False
    assert "unavailable" in direct["error"].lower()


def test_disabled_skill_cannot_be_loaded_in_paper(bundle, monkeypatch):
    monkeypatch.setattr(skills, "_is_skill_disabled", lambda name: True)
    with proposal_only_scope(True):
        result = json.loads(skills.skill_view("paper-help"))
    assert result["success"] is False
    assert "disabled" in result["error"]


def test_native_toolset_conditions_match_prompt_eligibility(bundle):
    content = (bundle / 'SKILL.md').read_text()
    (bundle / 'SKILL.md').write_text(content.replace('requires_tools: [paper_read]',
        'requires_tools: [paper_read]\n    requires_toolsets: [skills]'))
    skills._SKILLS_CACHE.clear()
    with proposal_only_scope(True, host_tools={'paper_read'}):
        assert json.loads(skills.skill_view('paper-help'))['success'] is True
        assert [s['name'] for s in json.loads(skills.skills_list())['skills']] == ['paper-help']
    (bundle / 'SKILL.md').write_text(content.replace('requires_tools: [paper_read]',
        'requires_tools: [paper_read]\n    fallback_for_toolsets: [skills]'))
    skills._SKILLS_CACHE.clear()
    with proposal_only_scope(True, host_tools={'paper_read'}):
        assert json.loads(skills.skill_view('paper-help'))['success'] is False
        assert json.loads(skills.skills_list())['skills'] == []
