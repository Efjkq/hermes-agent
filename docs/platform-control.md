# Hosted platform control

The API server's internal platform endpoints require the configured API bearer
key. Hosted confidential supervisors call them over loopback. They accept fixed
operations and never a caller-selected path, shell command or destination.

`GET /internal/platform/gateway/status` includes `processMarker` for the live
gateway and `stateProcessMarker` for the persisted status generation. A controller
must refuse populated platform health when these differ. It must not publish
stale channel connectivity after a gateway restart.

`POST /internal/platform/pairing/{operation}` supports `telegram` and `line`:

- `approve`: `{channel, code}` with an eight-character uppercase alphanumeric
  code; returns `{status: "approved", allowFrom}` or `not_found`. `incomplete`
  means a grant may already be durable; reconcile through `allow-from` before
  retrying. Codes and user names are never echoed.
- `allow-from`: `{channel}`; returns `{allowFrom}`.
- `revoke`: `{channel, mode: "account" | "requests" | "entry", entry?}`;
  returns `{changed, removedAllowFromCount, removedRequestCount, allowFrom}`.
  Entry mode removes matching pending requests as well as the grant. Other
  channels remain intact. The gateway's pairing store lock fences adapters.

These runtime grants are discovery inputs for a hosted controller. The
controller persists its authorized allowlist and rebuilds managed runtime config
from that durable source, including after encrypted restore.

`POST /internal/platform/logs/tail` accepts `{limit?, maxBytes?, cursor?}`.
It reads only `HERMES_HOME/logs/gateway.log`, with at most 5,000 lines and
1,000,000 bytes per read. It returns `{lines, cursor}`; pass the opaque cursor
back to follow. Cursors bind the opened file's device, inode and byte position,
restart on rotation or truncation, and retain incomplete lines for the next
read. Symbolic links and non-regular files refuse. The owner-authorizing
controller must stream answers without persisting or logging their contents.
