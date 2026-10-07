import pytest

from app.services.codex_process_identity import explicit_resume

SESSION = '12345678-1234-1234-1234-123456789abc'


@pytest.mark.parametrize('arguments,expected',[
    ([b'resume',SESSION.encode()],True),
    ([b'--cd',b'/tmp/repo',b'--config',b'effort="high"',b'--model',b'fixture',
      b'--dangerously-bypass-approvals-and-sandbox',b'resume',SESSION.encode(),b'Continue'],True),
    ([b'--',b'resume',SESSION.encode()],False),
    ([b'--model',SESSION.encode(),b'resume',b'other'],False),
    ([b'--config',b'resume',SESSION.encode()],False),
    ([b'resume',SESSION.encode(),b'--last'],False),
    ([b'resume',SESSION.encode(),b'--',b'resume',SESSION.encode()],False),
    ([b'resume',b'--last'],False),
    ([b'exec',b'resume',SESSION.encode()],False),
    ([b'--unsupported',b'resume',SESSION.encode()],False),
])
def test_exact_resume_selector(arguments,expected):
    assert explicit_resume([b'/opt/tools/codex',*arguments,b''],SESSION) is expected


def test_resume_refuses_a_different_executable_or_noncanonical_identity():
    assert not explicit_resume([b'other',b'resume',SESSION.encode()],SESSION)
    assert not explicit_resume([b'codex',b'resume',SESSION.upper().encode()],SESSION.upper())


@pytest.mark.parametrize('arguments,accepted',[
    ([b'resume',SESSION.encode()],True),
    ([b'--',b'resume',SESSION.encode()],False),
    ([b'--model',SESSION.encode(),b'resume',b'other'],False),
    ([b'resume',SESSION.encode(),b'--last'],False),
])
def test_real_owner_identity_helper_uses_exact_resume_parser(monkeypatch,arguments,accepted):
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from app.services import owner_observation_pause as pause
    monkeypatch.setattr(pause.activity,'_process',lambda _pid: ('S','fixture-start'))
    monkeypatch.setattr(pause.activity,'_process_started_at',lambda _start: datetime.now(timezone.utc)-timedelta(minutes=2))
    monkeypatch.setattr(pause,'Path',lambda _path: SimpleNamespace(read_bytes=lambda:b'\0'.join([b'codex',*arguments,b''])))
    slot=SimpleNamespace(provider='codex-cli',launch_options={'session_id':SESSION})
    session=SimpleNamespace(pid=12,created_at=datetime.utcnow(),cwd='/tmp/fixture')
    workspace=SimpleNamespace(leased_owner_pid=11,leased_owner_proc_start='fixture-start')
    if accepted: assert pause._process_identity(slot,session,workspace)=='fixture-start'
    else:
        with pytest.raises(ValueError,match='owner_native_identity_changed'): pause._process_identity(slot,session,workspace)
