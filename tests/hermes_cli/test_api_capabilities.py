"""A loaded plugin can report actual runtime readiness without adding model tools."""
from hermes_cli.plugins import PluginManager
from tests.hermes_cli.test_plugins import _make_plugin_dir


def test_only_loaded_plugins_report_json_capabilities(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugins = tmp_path / "plugins"
    _make_plugin_dir(plugins, "business", register_body=(
        "ctx.register_api_capability('business_v1', "
        "lambda tools: {'ready': 'business_read' in tools, 'revision': 'one'})"
    ))
    _make_plugin_dir(plugins, "disabled", auto_enable=False, register_body=(
        "ctx.register_api_capability('disabled_v1', lambda tools: {'ready': True})"
    ))
    manager = PluginManager()
    manager.discover_and_load()
    assert manager.api_capabilities({"business_read"}) == {"business_v1": {"ready": True, "revision": "one"}}
    assert manager.api_capabilities(set())["business_v1"]["ready"] is False


def test_failed_probes_do_not_expose_exception_details_or_erase_other_capabilities(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _make_plugin_dir(tmp_path / "plugins", "broken", register_body=(
        "ctx.register_api_capability('broken_v1', lambda tools: 1 / 0)"
    ))
    manager = PluginManager()
    manager.discover_and_load()
    assert manager.api_capabilities(set()) == {"broken_v1": {"ready": False, "reason": "probe_unavailable"}}
