"""Explicit task-local output secrets, captured independently by each stream.

Only supplied values are matched. A running process keeps its redactor after
the caller's scope closes; finished streams release the values. No persistence,
network lookup, signing or process-global credential state is involved.
"""
import codecs
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable

_OUTPUT_SECRETS: ContextVar[tuple[str, ...]] = ContextVar('output_secrets', default=())


@contextmanager
def secret_output_scope(values: Iterable[str]):
    secrets = tuple(dict.fromkeys(variant for value in values if isinstance(value, str) and value
                                  for variant in (value, json.dumps(value)[1:-1],
                                                  json.dumps(value, ensure_ascii=False)[1:-1])))
    token = _OUTPUT_SECRETS.set(tuple(dict.fromkeys((*_OUTPUT_SECRETS.get(), *secrets))))
    try:
        yield
    finally:
        _OUTPUT_SECRETS.reset(token)


class StreamingSecretRedactor:
    def __init__(self, values: tuple[str, ...]):
        self._values = tuple(sorted(values, key=len, reverse=True))
        self._first = {initial: tuple(secret for secret in self._values if secret[0] == initial)
                       for initial in {secret[0] for secret in self._values}}
        self._pending = ''
        self._closed = False

    def redact_text(self, value: str) -> str:
        for secret in self._values:
            value = value.replace(secret, '[REDACTED]')
        return value

    def feed(self, text: str, *, final: bool = False) -> str:
        if self._closed:
            return ''
        remaining = self._pending + text
        output = []
        position = 0
        while position < len(remaining):
            candidates = self._first.get(remaining[position], ())
            if not final and any(len(secret) > len(remaining) - position and secret.startswith(remaining[position:]) for secret in candidates):
                break
            match = next((secret for secret in candidates if remaining.startswith(secret, position)), None)
            if match is not None:
                output.append('[REDACTED]')
                position += len(match)
            else:
                output.append(remaining[position])
                position += 1
        self._pending = remaining[position:]
        if final:
            self._values = ()
            self._first.clear()
            self._pending = ''
            self._closed = True
        return ''.join(output)

    def finish(self) -> str:
        return self.feed('', final=True)


def capture_output_redactor() -> StreamingSecretRedactor | None:
    values = _OUTPUT_SECRETS.get()
    return StreamingSecretRedactor(values) if values else None


def iter_redacted_pipe(pipe, redactor: StreamingSecretRedactor | None):
    """Decode/filter before byte budgets, with a caller-captured stream scope."""
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace') if redactor else None
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            if redactor is not None:
                chunk = redactor.feed(decoder.decode(chunk)).encode('utf-8')
            if chunk:
                yield chunk
    except (ValueError, OSError):
        pass
    if redactor is not None:
        tail = redactor.feed(decoder.decode(b'', final=True)) + redactor.finish()
        if tail:
            yield tail.encode('utf-8')
