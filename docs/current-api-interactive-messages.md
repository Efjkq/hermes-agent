# Current API conversation messages

Native `/v1/runs` can publish `message.interactive` text with Telegram-compatible `reply_markup.inline_keyboard` rows. `callback_data` is 1–64 UTF-8 bytes; URLs are HTTP(S) without embedded credentials. Host metadata describes proposals, not executed actions. The authenticated host must validate owner, run, account, target version and human confirmation before executing anything.

The `api_interactions` toolset exposes a current-conversation `send_message` wrapper and scoped clarification. Delivery cannot fall back to another channel when the stream is detached or stopped. `/v1/runs/:id/clarify` only answers the active question in the matching profile/run; run status includes its current pending ID. Resolution events contain an ID/reason, not the answer. Stop clears pending waits and awaits the actual worker before releasing its hosted lease. Ordinary Chat and Telegram defaults are unchanged.

Optional `interaction_context` is frozen host data, bounded to 32 KiB, exposed via `send_message(action=context)` rather than rewriting prompts or past history. Hosts should treat model-produced card metadata as untrusted proposals.

For `mode=paper`, proposal-only tools are fixed at Agent construction and intersect the configured toolkit. Research, memory, history, todo, skills listing and current messages may remain available. Arbitrary shell/code/browser, credential/file reads, skill mutation, delegate/cron, tool-search bridges and unknown plugin/MCP execution are unavailable. Dispatcher and registry enforce this in the worker scope; normal/live runs keep their existing toolkit. This is removal of execution entry points, not a shell sandbox; restoring arbitrary execution needs a separately scoped credential/identity design. Trusted operator-installed hook implementations remain a host trust boundary.

Paper schemas are read before tool-search assembly so `send_message` remains visible without making it globally core. Capability consumers must require `interactive_messages` plus `paper_proposal_only` before enabling host trade proposals. Source tests do not prove hosted model behavior, external Telegram delivery or deployment.

Validation: `scripts/run_tests.sh tests/gateway/test_api_server_interactive_messages.py tests/gateway/test_api_server_native_runs.py tests/gateway/test_api_server_toolset.py tests/tools/test_send_message_react.py tests/tools/test_clarify_gateway.py -j 1 --file-retries 0`.

Paper tool schemas are frozen for the Run and skip native between-turn MCP discovery. Vision/video tools remain unavailable until media sources can be bound to authenticated host input; normal Agent tool behavior is unchanged.
