import io
import json
import signal
import ssl
import subprocess
import threading
import urllib.error
import urllib.request

import pytest


def test_codex_application_slots_bound_parallel_processes_and_release(tmp_path):
    from contextlib import ExitStack
    from dse_knowledge.providers import _generation_slot,ProviderError
    with ExitStack() as stack:
        for _ in range(4):stack.enter_context(_generation_slot(tmp_path,wait_seconds=.01))
        with pytest.raises(ProviderError,match='codex_capacity_busy'):
            with _generation_slot(tmp_path,wait_seconds=.01):pass
    with _generation_slot(tmp_path,wait_seconds=.01):pass

@pytest.mark.parametrize('failure_at',['fstat','flock'])
def test_generation_slot_closes_fd_when_post_open_syscall_fails(tmp_path,monkeypatch,failure_at):
    from dse_knowledge.providers import _generation_slot,ProviderError
    real_fstat=providers.os.fstat
    opened=[]
    def tracked_fstat(fd):
        opened.append(fd)
        if failure_at=='fstat':raise OSError('injected fstat failure')
        return real_fstat(fd)
    monkeypatch.setattr(providers.os,'fstat',tracked_fstat)
    if failure_at=='flock':
        monkeypatch.setattr(providers.fcntl,'flock',lambda *args: (_ for _ in ()).throw(OSError('injected flock failure')))
    with pytest.raises(ProviderError,match='codex_capacity_lock_unavailable'):
        with _generation_slot(tmp_path,wait_seconds=.01):pass
    monkeypatch.setattr(providers.os,'fstat',real_fstat)
    assert opened
    try:real_fstat(opened[0])
    except OSError:pass
    else:
        providers.os.close(opened[0])
        pytest.fail('slot descriptor remained open after the syscall error')

def test_generation_slot_fd_keeps_capacity_lease_after_owner_death(tmp_path):
    import ctypes
    import os
    import select
    import signal
    import sys
    import time
    from pathlib import Path
    from dse_knowledge.providers import _generation_slot,ProviderError
    if not sys.platform.startswith('linux'):
        pytest.skip('child-subreaper support is Linux-specific')
    libc=ctypes.CDLL(None,use_errno=True)
    previous=ctypes.c_int()
    if libc.prctl(37,ctypes.byref(previous),0,0,0)!=0:
        pytest.skip('PR_GET_CHILD_SUBREAPER unavailable')
    if libc.prctl(36,1,0,0,0)!=0:
        pytest.skip('PR_SET_CHILD_SUBREAPER unavailable')
    worker_code='''
import subprocess,sys,time
from pathlib import Path
from dse_knowledge.providers import _generation_slot
with _generation_slot(Path(sys.argv[1]),wait_seconds=.1) as lease_fd:
    child=subprocess.Popen([sys.executable,'-c','import signal; signal.pause()'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        close_fds=True,pass_fds=(lease_fd,),start_new_session=True)
    print(child.pid,flush=True)
    while True: time.sleep(1)
'''
    env=os.environ.copy()
    source=str(Path(__file__).resolve().parents[1]/'src')
    env['PYTHONPATH']=source+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    owner=subprocess.Popen([sys.executable,'-c',worker_code,str(tmp_path)],stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
    child_pid=None
    try:
        ready,_,_=select.select([owner.stdout],[],[],3)
        assert ready,'lease owner did not report its inherited child'
        line=owner.stdout.readline()
        if not line:
            _,stderr=owner.communicate(timeout=2)
            pytest.fail('lease owner exited before spawning its child: '+stderr[-1000:])
        child_pid=int(line)
        owner.kill()
        owner.wait(timeout=2)
        from contextlib import ExitStack
        with ExitStack() as stack:
            for _ in range(3):stack.enter_context(_generation_slot(tmp_path,wait_seconds=.02))
            with pytest.raises(ProviderError,match='codex_capacity_busy'):
                with _generation_slot(tmp_path,wait_seconds=.02):pass
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=2)
        if child_pid is not None:
            try:os.killpg(child_pid,signal.SIGKILL)
            except ProcessLookupError:pass
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                try:waited,_=os.waitpid(child_pid,os.WNOHANG)
                except ChildProcessError:
                    time.sleep(.01)
                    continue
                if waited==child_pid:break
                time.sleep(.01)
            else:pytest.fail('inherited lease child was not reaped')
        libc.prctl(36,previous.value,0,0,0)

from dse_knowledge.config import Settings
from dse_knowledge import providers
from dse_knowledge.providers import ChatClient, EmbeddingClient, ProviderError


MODEL = 'google/embeddinggemma-2'
ENDPOINT = 'https://api.deepinfra.com/v1/openai/embeddings'


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return Response(self.result)


def unit_vector(position):
    values = [0.0] * 768
    values[position] = 1.0
    return values


def settings(**overrides):
    values = {
        'DSE_EMBEDDING_PROVIDER': 'deepinfra',
        'DSE_EMBEDDING_MODEL_ID': MODEL,
        'DSE_EMBEDDING_DIMENSIONS': '768',
        'DSE_EMBEDDING_API_KEY': 'private-key-sentinel',
    }
    values.update(overrides)
    return Settings(values)


def test_embedding_posts_exact_contract_and_restores_index_order():
    opener = FakeOpener({'model': MODEL, 'data': [
        {'index': 1, 'embedding': unit_vector(1)},
        {'index': 0, 'embedding': unit_vector(0)},
    ], 'usage': {'prompt_tokens': 9, 'total_tokens': 9, 'secret': 'omit'}})
    client = EmbeddingClient(settings(), opener=opener)

    result = client.embed(['document a', 'document b'], task='document')

    assert result == [unit_vector(0), unit_vector(1)]
    request, timeout = opener.requests[0]
    assert request.full_url == ENDPOINT
    assert request.get_method() == 'POST'
    assert request.get_header('Authorization') == 'Bearer private-key-sentinel'
    assert json.loads(request.data) == {
        'model': MODEL,
        'input': ['document a', 'document b'],
        'task': 'document',
        'dimensions': 768,
        'encoding_format': 'float',
    }
    assert timeout <= 30
    assert client.last_metadata['usage'] == {'prompt_tokens': 9, 'total_tokens': 9}
    assert 'private-key-sentinel' not in repr(client.last_metadata)
    assert 'secret' not in repr(client.last_metadata)


@pytest.mark.parametrize('data,reason', [
    ([{'index': 0, 'embedding': unit_vector(0)}], 'embedding_count_mismatch'),
    ([{'index': 0, 'embedding': unit_vector(0)},
      {'index': 0, 'embedding': unit_vector(1)}], 'invalid_embedding_index'),
    ([{'index': 0, 'embedding': [1.0]},
      {'index': 1, 'embedding': unit_vector(1)}], 'embedding_dimension_mismatch'),
    ([{'index': 0, 'embedding': [True] + [0.0] * 767},
      {'index': 1, 'embedding': unit_vector(1)}], 'non_numeric_embedding_value'),
    ([{'index': 0, 'embedding': [float('nan')] + [0.0] * 767},
      {'index': 1, 'embedding': unit_vector(1)}], 'non_finite_embedding_value'),
    ([{'index': 0, 'embedding': [2.0] + [0.0] * 767},
      {'index': 1, 'embedding': unit_vector(1)}], 'embedding_normalization_failed'),
])
def test_embedding_rejects_invalid_vectors(data, reason):
    client = EmbeddingClient(settings(), opener=FakeOpener({'model': MODEL, 'data': data}))

    with pytest.raises(ProviderError) as error:
        client.embed(['a', 'b'], task='search_query')

    assert error.value.reason == reason


def test_embedding_error_is_not_retried_or_echoed():
    error = urllib.error.HTTPError(ENDPOINT, 401, 'private-response-body', {},
                                   io.BytesIO(b'private-response-body'))
    opener = FakeOpener(error)
    client = EmbeddingClient(settings(), opener=opener)

    with pytest.raises(ProviderError) as raised:
        client.embed(['a'], task='document')

    assert len(opener.requests) == 1
    assert raised.value.reason == 'embedding_http_error'
    assert 'private-response-body' not in str(raised.value)
    assert 'private-key-sentinel' not in str(raised.value)


def test_default_embedding_opener_verifies_tls_and_has_no_redirect(monkeypatch):
    captured = []
    fake_opener = FakeOpener({'model': MODEL, 'data': [
        {'index': 0, 'embedding': unit_vector(0)},
    ]})

    def build_opener(*handlers):
        captured.extend(handlers)
        return fake_opener

    monkeypatch.setattr(urllib.request, 'build_opener', build_opener)
    EmbeddingClient(settings())

    https = [handler for handler in captured if isinstance(handler, urllib.request.HTTPSHandler)]
    redirects = [handler for handler in captured if isinstance(handler, urllib.request.HTTPRedirectHandler)]
    assert https and all(handler._context.verify_mode == ssl.CERT_REQUIRED for handler in https)
    assert redirects and all(handler.redirect_request(None, None, 302, 'found', {}, ENDPOINT) is None
                             for handler in redirects)


def test_chat_client_uses_read_only_cli_safe_environment_and_cleans_group(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', '/home/test-user')
    codex_home = tmp_path / 'codex-home'
    codex_home.mkdir()
    (codex_home / 'config.toml').write_text('[mcp_servers.fixture]\ncommand="unused-sentinel"\n')
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    monkeypatch.setenv('CODEX_SECRET_KEY', 'must-not-pass')
    monkeypatch.setenv('SUPABASE_DB_PASSWORD', 'must-not-pass-either')
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setattr(providers.shutil, 'which', lambda *args, **kwargs: '/usr/bin/codex')
    settings_obj = Settings({'CODEX_WORKDIR': str(tmp_path / 'work')})
    captured = {}

    class ExitedProcess:
        pid = 928374

        def __init__(self):
            self.stdout = io.BytesIO(
                b'{"type":"session_meta","payload":{"model":"gpt-6.1-sol","cli_version":"codex-cli 1.2.3","thread_id":"safe-run-id"}}\n'
                b'{"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":3,"total_tokens":12}}\n')

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(args, **kwargs):
        captured['args'] = args
        captured.update(kwargs)
        out = args[args.index('--output-last-message') + 1]
        with open(out, 'w', encoding='utf-8') as file:
            file.write('{"claims": []}')
        return ExitedProcess()

    killed = []
    monkeypatch.setattr(providers.subprocess, 'Popen', fake_popen)

    def fake_killpg(pid, sig):
        killed.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr(providers.os, 'killpg', fake_killpg)
    client = ChatClient(settings_obj)

    assert client.complete('extract only quoted evidence', {'type': 'object'}) == {'claims': []}

    args = captured['args']
    assert args[0] == '/usr/bin/codex'
    assert '--ask-for-approval' in args and args[args.index('--ask-for-approval') + 1] == 'never'
    assert args[args.index('--disable') + 1] == 'shell_tool'
    disabled = [args[i + 1] for i, value in enumerate(args[:-1]) if value == '--disable']
    assert {'shell_tool', 'multi_agent', 'apps', 'plugins'} <= set(disabled)
    assert '-c' in args and 'mcp_servers={}' in args
    assert 'plugins={}' in args and 'web_search="disabled"' in args
    assert 'project_doc_max_bytes=0' in args
    assert 'developer_instructions=' in ' '.join(args)
    assert 'skip_host_skill_discovery' in args
    assert {'skill_search', 'skill_mcp_dependency_install', 'remote_plugin', 'sleep_tool'} <= set(disabled)
    assert '--sandbox' in args and args[args.index('--sandbox') + 1] == 'read-only'
    assert '--skip-git-repo-check' in args and '--ephemeral' in args and '--json' in args
    assert captured['stdin'] == subprocess.DEVNULL
    assert captured['start_new_session'] is True
    assert len(captured['pass_fds']) == 1
    assert captured['env']['HOME'] == '/home/test-user'
    assert captured['env']['CODEX_HOME'] == str(codex_home)
    assert 'mcp_servers.fixture.enabled=false' in args
    assert 'unused-sentinel' not in repr(args)
    assert 'CODEX_SECRET_KEY' not in captured['env']
    assert 'SUPABASE_DB_PASSWORD' not in captured['env']
    assert killed[0] == (928374, signal.SIGTERM)
    assert (928374, 0) in killed
    assert captured['stdout'] == subprocess.PIPE
    assert client.last_metadata == {
        'provider': 'codex_cli', 'model': 'gpt-6.1-sol', 'cli_version': 'codex-cli 1.2.3',
        'duration_seconds': client.last_metadata['duration_seconds'],
        'usage': {'input_tokens': 9, 'output_tokens': 3, 'total_tokens': 12},
        'process_exit_code': 0, 'tool_calls': 0, 'turn_completed': True,
        'invocation_id': 'safe-run-id', 'model_reported_by_cli': True,
        'timeout_seconds': 180,
    }
    assert 'extract only quoted evidence' not in repr(client.last_metadata)


def test_chat_client_close_stops_an_active_owned_process_group(monkeypatch, tmp_path):
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setattr(providers.shutil, 'which', lambda *args, **kwargs: '/usr/bin/codex')
    entered_wait = threading.Event()
    group_stopped = threading.Event()
    group_alive = {'value': True}
    killed = []

    class WaitingProcess:
        pid = 123456

        def __init__(self):
            self.stdout = io.BytesIO(
                b'{"type":"session_meta","payload":{"model":"gpt-6.1-sol","cli_version":"codex-cli 1.2.3"}}\n'
                b'{"type":"turn.completed","usage":{"input_tokens":1}}\n')

        def wait(self, timeout=None):
            entered_wait.set()
            assert group_stopped.wait(timeout=2)
            return 143

    def fake_popen(args, **kwargs):
        with open(args[args.index('--output-last-message') + 1], 'w', encoding='utf-8') as output:
            output.write('{}')
        return WaitingProcess()

    def fake_killpg(pid, sig):
        killed.append((pid, sig))
        if sig == signal.SIGTERM and group_alive['value']:
            group_alive['value'] = False
            group_stopped.set()
            return
        if sig == 0 and not group_alive['value']:
            raise ProcessLookupError
        if not group_alive['value']:
            raise ProcessLookupError

    monkeypatch.setattr(providers.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(providers.os, 'killpg', fake_killpg)
    client = ChatClient(Settings({'CODEX_WORKDIR': str(tmp_path / 'work')}))
    failures = []

    def run():
        try:
            client.complete('bounded prompt', {'type': 'object'})
        except ProviderError as error:
            failures.append(error.reason)

    thread = threading.Thread(target=run)
    thread.start()
    assert entered_wait.wait(timeout=2)
    client.close()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert failures == ['codex_failed']
    assert killed[0] == (123456, signal.SIGTERM)


@pytest.mark.parametrize('override', [
    {'CHAT_PROVIDER': 'other'},
    {'CHAT_MODEL_ID': 'other-model'},
    {'CHAT_REASONING_EFFORT': 'high'},
    {'CHAT_TIMEOUT_SECONDS': '601'},
])
def test_chat_client_rejects_unapproved_runtime_configuration(monkeypatch, tmp_path, override):
    monkeypatch.setattr(providers.subprocess, 'Popen', lambda *_args, **_kwargs: pytest.fail('must not spawn'))
    client = ChatClient(Settings({**{'CODEX_WORKDIR': str(tmp_path / 'work')}, **override}))

    with pytest.raises(ProviderError):
        client.complete('bounded prompt', {'type': 'object'})


def run_fake_codex(monkeypatch, tmp_path, *, events, output):
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setattr(providers.shutil, 'which', lambda *args, **kwargs: '/usr/bin/codex')

    class ExitedProcess:
        pid = 777888

        def __init__(self):
            self.stdout = io.BytesIO(events)

        def wait(self, timeout=None):
            return 0

    def fake_popen(args, **kwargs):
        with open(args[args.index('--output-last-message') + 1], 'w', encoding='utf-8') as file:
            file.write(output)
        return ExitedProcess()

    monkeypatch.setattr(providers.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(providers.os, 'killpg', lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    return ChatClient(Settings({'CODEX_WORKDIR': str(tmp_path / 'work')}))


def test_chat_client_rejects_observed_tool_calls(monkeypatch, tmp_path):
    events = (
        b'{"type":"session_meta","payload":{"model":"gpt-6.1-sol"}}\n'
        b'{"type":"item.started","item":{"id":"tool-1","type":"command_execution"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":1}}\n'
    )
    client = run_fake_codex(monkeypatch, tmp_path, events=events, output='{}')

    with pytest.raises(ProviderError) as error:
        client.complete('bounded prompt', {'type': 'object'})

    assert error.value.reason == 'codex_tool_call_detected'
    assert client.last_metadata['tool_calls'] == 1
    assert client.last_metadata['turn_completed'] is True


def test_chat_client_revalidates_output_against_schema(monkeypatch, tmp_path):
    events = (
        b'{"type":"session_meta","payload":{"model":"gpt-6.1-sol"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":1}}\n'
    )
    client = run_fake_codex(monkeypatch, tmp_path, events=events, output='{}')

    with pytest.raises(ProviderError) as error:
        client.complete('bounded prompt', {
            'type': 'object', 'required': ['claims'], 'additionalProperties': False,
            'properties': {'claims': {'type': 'array'}},
        })

    assert error.value.reason == 'codex_output_schema_invalid'


def test_codex_long_reasoning_timeout_is_configurable_but_bounded():
    assert providers._codex_configuration(Settings({'CHAT_TIMEOUT_SECONDS':'360'}))[2] == 360
    with pytest.raises(ProviderError):
        providers._codex_configuration(Settings({'CHAT_TIMEOUT_SECONDS':'601'}))


def test_codex_isolation_disables_each_configured_mcp_server_without_forwarding_secrets(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text(
        'developer_instructions="host instruction sentinel"\n'
        '[mcp_servers.alpha]\nurl="https://example.test"\n'
        'bearer_token_env_var="private-token-sentinel"\n'
        '[profiles.local.mcp_servers.beta]\ncommand="private-command-sentinel"\n')
    arguments = providers._codex_isolation_arguments([config])
    assert 'mcp_servers.alpha.enabled=false' in arguments
    assert 'mcp_servers.beta.enabled=false' in arguments
    assert 'private-token-sentinel' not in repr(arguments)
    assert 'private-command-sentinel' not in repr(arguments)
    assert 'host instruction sentinel' not in repr(arguments)


def test_codex_isolation_rejects_malformed_configuration(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('[mcp_servers.invalid')
    with pytest.raises(ProviderError, match='codex_isolation_configuration_invalid'):
        providers._codex_isolation_arguments([config])
