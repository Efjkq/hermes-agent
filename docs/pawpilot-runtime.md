# PawPilot host interaction v2

The authenticated API host may request `tool_disclosure: "compact"` for a new
PawPilot session. The host must freeze this choice with the session instructions;
changing a page, button or policy release must not change its tool array or prefix.
Existing sessions default to full disclosure. This is presentation, not permission.

Common terminal/process/read/Skill/Clarify tools and bound business proxies remain
direct. Auxiliary core schemas use the existing tool_search/describe/call bridge.
The full authorized catalog still feeds Skill visibility and agent dispatch,
including per-session memory/TODO handlers. Owner always-visible choices win;
`tools.tool_search.enabled: off` retains its original meaning. An explicit
`tools.tool_search.defer_core_tools` list offers the same opt-in classification
without changing core-tool eagerness by default. Unconfigured tools are not granted.
The tool-definition cache includes the disclosure scope.

`workflow_resources` is a version-2-only list of at most eight installed Skill
`{name,file_path}` references. It complements the existing workflow_skills hint.
Both pass through skill_view with preprocessing disabled and retain native disabled,
security and path checks. Combined text is bounded to 64 KiB and staged only on the
current-turn API sidecar, leaving saved user text and the cached system prefix alone.
Missing/disabled references fail explicitly. No shell preprocessing or business action
is performed by loading a reference.

Native capabilities advertise `workflow_resource_loading` and `compact_host_tools`;
the host must negotiate both and the exact business bundle before enabling the profile.
Tests run through scripts/run_tests.sh with one worker. Source tests are not proof of
image packaging or a deployed tenant rollout.
