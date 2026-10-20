# Ephemeral terminal passthrough

An installed `agent.secret_scope` can supply short-lived third-party credentials
even in a single-profile process. Local terminal execution excludes allowlisted
passthrough variables from shell snapshots whenever a scope is installed, as it
already does in multiplex mode. It restores the current command environment
after sourcing an older snapshot, so an old placeholder cannot override a fresh
scoped value. Exclusion is monotonic for the environment lifetime.

This does not change passthrough authorization, provider credential blocklists,
or process-global environment variables. Middleware owns its own session lifetime
and resets its ContextVar scope after execution. A command already authorized to
receive a secret can still print or exfiltrate it; snapshot exclusion is not a
sandbox or key revocation mechanism.

Regression: `scripts/run_tests.sh tests/tools/test_env_passthrough.py -j 1`.

Middleware can also install `agent.output_redaction.secret_output_scope(values)`
with the exact opaque values being delivered. Local background processes capture
independent stream filters before their reader threads start. Filtering happens
before buffers, live observers, watch notifications, process poll/log/wait and
completion messages. It handles values split across pipe/PTY chunks and EOF;
foreground head/tail truncation and spill files use the same filter. Command and
persisted watch metadata are sanitized as well. No global environment scan or
network lookup is used. Each filter releases its matching values at stream EOF,
so a running child remains protected after the caller or signing session ends.

Nonlocal background execution with an installed output scope fails before creating
an unfiltered remote log. Unscoped execution is unchanged. This filters exact
known values, not arbitrary encodings or intentional exfiltration by an authorized
command; it does not revoke an already running child's exchange permissions.

Additional regression: `scripts/run_tests.sh tests/tools/test_scoped_process_output.py tests/tools/test_process_registry.py tests/tools/test_base_environment.py -j 1`.
