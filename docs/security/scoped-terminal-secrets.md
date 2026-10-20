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
