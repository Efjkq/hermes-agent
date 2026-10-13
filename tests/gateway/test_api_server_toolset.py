"""Tests for hermes-api-server toolset and API server tool availability."""
from unittest.mock import patch, MagicMock


from toolsets import resolve_toolset, get_toolset, validate_toolset


class TestHermesApiServerToolset:
    """Tests for the hermes-api-server toolset definition."""


    def test_toolset_includes_web_tools(self):
        tools = resolve_toolset("hermes-api-server")
        assert "web_search" in tools
        assert "web_extract" in tools

    def test_toolset_includes_core_tools(self):
        tools = resolve_toolset("hermes-api-server")
        expected = [
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze", "image_generate",
            "execute_code", "delegate_task",
            "todo", "memory", "session_search", "cronjob",
        ]
        for tool in expected:
            assert tool in tools, f"Missing expected tool: {tool}"

    def test_toolset_includes_browser_tools(self):
        tools = resolve_toolset("hermes-api-server")
        for tool in ["browser_navigate", "browser_snapshot", "browser_click",
                      "browser_type", "browser_scroll", "browser_back",
                      "browser_press"]:
            assert tool in tools, f"Missing browser tool: {tool}"


class TestApiServerPlatformConfig:

    def test_default_api_server_includes_terminal_toolset(self):
        """Regression #49622: desktop-only read_terminal is registered into the
        'terminal' toolset (ships in-repo), so resolve_toolset('terminal') grows
        to include it after discovery. read_terminal is NOT in the
        hermes-api-server composite, so the old all-tools subset test dropped
        'terminal' entirely. Its static membership (terminal, process) IS in the
        composite, so it must stay enabled."""
        from tools.registry import discover_builtin_tools
        from hermes_cli.tools_config import _get_platform_tools
        discover_builtin_tools()
        assert "terminal" in _get_platform_tools({}, "api_server")


class TestApiServerAdapterToolset:
    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE", True)
    def test_create_agent_reads_config_toolsets(self):
        """API server resolves toolsets from config like all other platforms."""
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig

        adapter = APIServerAdapter(PlatformConfig())

        with patch("gateway.run._resolve_runtime_agent_kwargs") as mock_kwargs, \
             patch("gateway.run._resolve_gateway_model") as mock_model, \
             patch("gateway.run._load_gateway_config") as mock_config, \
             patch("run_agent.AIAgent") as mock_agent_cls:

            mock_kwargs.return_value = {"api_key": "test-key", "base_url": None,
                                        "provider": None, "api_mode": None,
                                        "command": None, "args": []}
            mock_model.return_value = "test/model"
            # No platform_toolsets override — should fall back to hermes-api-server default
            mock_config.return_value = {}
            mock_agent_cls.return_value = MagicMock()

            adapter._create_agent()

            mock_agent_cls.assert_called_once()
            call_kwargs = mock_agent_cls.call_args
            toolsets = call_kwargs.kwargs.get("enabled_toolsets")
            assert isinstance(toolsets, list)
            assert len(toolsets) > 0
            assert call_kwargs.kwargs.get("platform") == "api_server"


    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE", True)
    def test_native_interactive_run_constructs_stable_current_only_tool_definitions(self):
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig
        from model_tools import get_tool_definitions
        observed=[]
        def construct(**kwargs):
            observed.append(get_tool_definitions(enabled_toolsets=kwargs['enabled_toolsets'],quiet_mode=True,skip_tool_search_assembly=True))
            return MagicMock()
        adapter=APIServerAdapter(PlatformConfig())
        with patch('gateway.run._resolve_runtime_agent_kwargs',return_value={'api_key':'test-key','base_url':None,'provider':None,'api_mode':None,'command':None,'args':[]}), patch('gateway.run._resolve_gateway_model',return_value='test/model'), patch('gateway.run._load_gateway_config',return_value={}), patch('run_agent.AIAgent',side_effect=construct):
            adapter._create_agent(interactive_messages=True)
            adapter._create_agent(interactive_messages=True)
            adapter._create_agent()
        current=[d for d in observed[0] if d['function']['name']=='send_message']
        assert len(current)==1
        assert current[0]['function']['parameters']['properties']['target']['enum']==['current']
        assert observed[0]==observed[1]
        assert 'send_message' not in {d['function']['name'] for d in observed[2]}

    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE",True)
    def test_paper_agent_exposes_only_research_memory_and_current_proposals(self):
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig
        from model_tools import get_tool_definitions
        def construct(**kwargs):
            result=MagicMock()
            result.tools=get_tool_definitions(enabled_toolsets=kwargs['enabled_toolsets'],quiet_mode=True)
            return result
        adapter=APIServerAdapter(PlatformConfig())
        with patch('gateway.run._resolve_runtime_agent_kwargs',return_value={'api_key':'test-key','base_url':None,'provider':None,'api_mode':None,'command':None,'args':[]}),patch('gateway.run._resolve_gateway_model',return_value='test/model'),patch('gateway.run._load_gateway_config',return_value={}),patch('run_agent.AIAgent',side_effect=construct):
            paper=adapter._create_agent(interactive_messages=True,proposal_only=True)
            normal=adapter._create_agent(interactive_messages=True)
        assert {'memory','send_message','clarify'}.issubset(paper.valid_tool_names)
        if 'web_search' in {tool['function']['name'] for tool in normal.tools}:
            assert 'web_search' in paper.valid_tool_names
        assert not {'terminal','execute_code','browser_click','delegate_task','cronjob','read_file','skill_manage','tool_call'}.intersection(paper.valid_tool_names)
        assert 'terminal' in {tool['function']['name'] for tool in normal.tools}
