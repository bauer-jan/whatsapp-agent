"""Task edits preserve unrelated schedules and concurrent updates."""
import pytest
from tools import whatsapp_admin as admin
from utils.persona_loader import PersonaLoader


def test_named_edits_preserve_current_state_and_deleted_tasks_stay_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, '_persona_dir', tmp_path)
    path = tmp_path / 'HEARTBEAT.md'
    path.write_text('# Tasks\n- Hourly [every 60 min]: Existing task\n\n## Rules\n- Preserve rules.\n')
    assert 'Saved task' in admin.set_heartbeat_task('Joke', 1, 'Send a joke')
    assert 'Removed task' in admin.remove_heartbeat_task('Joke')
    # A new monitor edits current state, never a remembered complete schedule.
    assert 'Saved task' in admin.set_heartbeat_task('Source monitor', 1, 'Query the source status')
    assert 'joke' not in path.read_text().lower()
    assert 'Existing task' in path.read_text() and '- Preserve rules.' in path.read_text()
    admin.set_heartbeat_task('Source monitor', 2, 'Check source again')
    loader=PersonaLoader(persona_dir=str(tmp_path))
    loader.ensure_persona_files()
    tasks=loader.load_heartbeat_tasks()
    assert {t.name for t in tasks} == {'Hourly', 'Source monitor'}
    assert next(t for t in tasks if t.name=='Source monitor').interval_minutes == 2
    admin.remove_heartbeat_task('source MONITOR')
    assert [t.name for t in loader.load_heartbeat_tasks()] == ['Hourly']
    assert admin.update_heartbeat not in admin.ALL_ADMIN_TOOLS


@pytest.mark.parametrize('name,interval,description', [('Bad\nName',1,'x'),('Task',0,'x'),('Task',1,'x\ny'),('[]',1,'x')])
def test_invalid_named_edit_does_not_overwrite_schedule(tmp_path,monkeypatch,name,interval,description):
    monkeypatch.setattr(admin,'_persona_dir',tmp_path)
    path=tmp_path/'HEARTBEAT.md'
    path.write_text('- Existing [every 60 min]: Keep me\n')
    assert admin.set_heartbeat_task(name,interval,description).startswith('Error:')
    assert path.read_text()=='- Existing [every 60 min]: Keep me\n'


def test_parallel_task_edits_preserve_each_others_additions(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(admin, '_persona_dir', tmp_path)
    (tmp_path / 'HEARTBEAT.md').write_text('- Hourly [every 60 min]: Keep me\n')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: admin.set_heartbeat_task(f'Task {n}', 5, 'Synthetic task'), range(8)))
    assert all(result.startswith('Saved task') for result in results)
    tasks = PersonaLoader(persona_dir=str(tmp_path)).load_heartbeat_tasks()
    assert {t.name for t in tasks} == {'Hourly'} | {f'Task {n}' for n in range(8)}
