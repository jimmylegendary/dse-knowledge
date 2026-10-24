from pathlib import Path
import pytest
from dse_knowledge.config import Settings, read_env


def test_secure_env_rejects_group_readable(tmp_path):
    p=tmp_path/'x.env'; p.write_text('TOKEN=x\n'); p.chmod(0o644)
    with pytest.raises(ValueError): read_env(p)


def test_repr_never_contains_secret():
    settings=Settings({'DSE_EMBEDDING_API_KEY':'sentinel-private'})
    assert 'sentinel-private' not in repr(settings)


def test_settings_defaults_and_namespaced_db():
    s=Settings({})
    assert s.get('DSE_HTTP_PORT','8080')=='8080'
    assert s.data_root.name=='dse-knowledge'
    assert s.schema=='dse_knowledge'


def test_runtime_does_not_inherit_admin_database_credentials(tmp_path,monkeypatch):
    root=tmp_path/'config';root.mkdir(mode=0o700)
    p=root/'runtime-database.env';p.write_text('SUPABASE_DB_USER=dse_knowledge_app.ref\n');p.chmod(0o600)
    monkeypatch.setenv('DSE_CONFIG_DIR',str(root))
    monkeypatch.setenv('SUPABASE_DB_USER','postgres.ref')
    assert Settings.load().get('SUPABASE_DB_USER')=='dse_knowledge_app.ref'
