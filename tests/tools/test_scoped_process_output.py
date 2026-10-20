"""Explicit secret output scopes follow a child, not the caller's lifetime."""
import json
import os
import shlex
import signal
import sys
import threading

import pytest


def test_streaming_redaction_covers_every_split_and_releases_plain_text():
    from agent.output_redaction import capture_output_redactor, secret_output_scope

    for split in range(1, len('prefix opaque-secret-long suffix\n')):
        with secret_output_scope(['opaque-secret', 'opaque-secret-long']):
            stream = capture_output_redactor()
        chunks = [stream.feed('prefix opaque-secret-long suffix\n'[:split]),
                  stream.feed('prefix opaque-secret-long suffix\n'[split:]), stream.finish()]
        assert ''.join(chunks) == 'prefix [REDACTED] suffix\n'
    with secret_output_scope(['abc-secret']):
        stream = capture_output_redactor()
    assert stream.feed('ordinary abc-sec') == 'ordinary '
    assert stream.finish() == 'abc-sec'


@pytest.mark.skipif(sys.platform == 'win32', reason='signal-controlled real child')
def test_background_outputs_stay_redacted_after_caller_scope_ends(tmp_path, monkeypatch):
    from agent.output_redaction import secret_output_scope
    from tools.process_registry import ProcessRegistry

    checkpoint = tmp_path / 'processes.json'
    monkeypatch.setattr('tools.process_registry.CHECKPOINT_PATH', checkpoint)
    registry = ProcessRegistry()
    ready = threading.Event()
    emitted = []
    def live(_session, text):
        emitted.append(text)
        if 'ready\n' in ''.join(emitted):
            ready.set()
    registry.on_output = live
    secret = 'opaque-session-key-without-vendor-prefix'
    code = """import os,signal,sys,threading
release=threading.Event()
signal.signal(signal.SIGUSR1, lambda *_: release.set())
print('ready', flush=True)
release.wait(10)
print('result:' + os.environ['TEST_OPAQUE_SECRET'], flush=True)
print(os.environ['TEST_OPAQUE_SECRET'], file=sys.stderr, flush=True)
"""
    with secret_output_scope([secret]):
        session = registry.spawn_local(f'exec {shlex.quote(sys.executable)} -c {shlex.quote(code)}', cwd=str(tmp_path), env_vars={'TEST_OPAQUE_SECRET': secret})
    try:
        assert ready.wait(10), 'child did not start'
        session.notify_on_complete = True
        session.watch_patterns = ['result:', secret]
        # The original signer/credential scope has ended; a subsequent caller
        # has different credentials, while the running child's output remains
        # protected by the values captured at spawn.
        with secret_output_scope(['different-session-secret']):
            os.kill(session.pid, signal.SIGUSR1)
            assert session._completion_event.wait(10), 'child did not finish'
        session._reader_thread.join(2)
        notifications = []
        while not registry.completion_queue.empty():
            notifications.append(registry.completion_queue.get_nowait())
        assert any(item.get('type') == 'completion' for item in notifications)
        assert any(item.get('type') == 'watch_match' for item in notifications)
        outputs = [session.output_buffer, ''.join(emitted), registry.poll(session.id),
                   registry.read_log(session.id), registry.wait(session.id, timeout=1), notifications,
                   checkpoint.read_text()]
        rendered = json.dumps(outputs)
        assert secret not in rendered
        assert '[REDACTED]' in rendered
        assert session.exit_code == 0
    finally:
        if not session.exited:
            registry.kill_process(session.id)


def test_output_scopes_do_not_affect_an_unscoped_process():
    from agent.output_redaction import capture_output_redactor, secret_output_scope

    assert capture_output_redactor() is None
    with secret_output_scope(['scope-a']):
        first = capture_output_redactor()
    with secret_output_scope(['scope-b']):
        second = capture_output_redactor()
    assert first.feed('scope-a scope-b') + first.finish() == '[REDACTED] scope-b'
    assert second.feed('scope-a scope-b') + second.finish() == 'scope-a [REDACTED]'
    assert capture_output_redactor() is None


def test_foreground_overflow_spills_only_redacted_output(tmp_path):
    from agent.output_redaction import secret_output_scope
    from tools.environments.base import _BoundedOutputCollector

    spill = tmp_path / 'overflow.log'
    with secret_output_scope(['opaque-secret']):
        output = _BoundedOutputCollector(120, spill_path=spill)
    output.append('head-' * 40 + 'opaque-sec')
    output.append('ret' + '-tail' * 40)
    output.finish()
    rendered = output.render()
    output.close_spill()
    assert 'opaque-secret' not in rendered + spill.read_text()
    assert '[REDACTED]' in spill.read_text()
    assert 'head-' in rendered and '-tail' in rendered


def test_nonlocal_background_capture_fails_before_writing_raw_logs():
    from agent.output_redaction import secret_output_scope
    from tools.process_registry import ProcessRegistry

    class Remote:
        def execute(self, *args, **kwargs):
            pytest.fail('must not start a remote raw-output capture')
    with secret_output_scope(['opaque-secret']):
        with pytest.raises(ValueError, match='local execution'):
            ProcessRegistry().spawn_via_env(Remote(), 'echo data')


@pytest.mark.parametrize('exit_code', [0, 7])
def test_execute_code_sanitizes_stdout_stderr_and_json_escaped_passphrases(monkeypatch, exit_code):
    from agent.output_redaction import secret_output_scope
    from tools.env_passthrough import register_env_passthrough, clear_env_passthrough
    from tools.code_execution_tool import execute_code

    secret = 'opaque"passphrase\\with-unicode-雪'
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('OKX_CEX_PASSPHRASE', secret)
    register_env_passthrough(['OKX_CEX_PASSPHRASE'])
    code = """import os,json,sys
value=os.environ['OKX_CEX_PASSPHRASE']
print('stdout:' + value)
print(json.dumps({'message': value}))
print('stderr:' + value, file=sys.stderr)
"""
    code += f'\nsys.exit({exit_code})\n'
    try:
        with secret_output_scope([secret]):
            result = json.loads(execute_code(code, enabled_tools=[]))
        assert result['status'] == ('error' if exit_code else 'success')
        assert result['exit_code'] == exit_code
        expected = 'stdout:[REDACTED]\n{"message": "[REDACTED]"}\n'
        if exit_code:
            expected += '\n--- stderr ---\nstderr:[REDACTED]\n'
            assert result['error'] == 'stderr:[REDACTED]\n'
        assert result['output'] == expected
        assert secret not in json.dumps(result, ensure_ascii=False)
        assert secret not in str(result)
    finally:
        clear_env_passthrough()
