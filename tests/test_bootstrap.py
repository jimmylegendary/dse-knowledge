import importlib.util
import stat
from contextlib import contextmanager
from pathlib import Path

import pytest
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'bootstrap-database.py'
spec = importlib.util.spec_from_file_location('bootstrap_database', SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

ADMIN = {
    'SUPABASE_DB_HOST': 'pooler.example.invalid', 'SUPABASE_DB_PORT': '5432',
    'SUPABASE_DB_NAME': 'postgres', 'SUPABASE_DB_USER': 'postgres.projectref1234567890',
    'SUPABASE_DB_PASSWORD': 'admin-placeholder', 'SUPABASE_DB_SSLMODE': 'verify-full',
    'SUPABASE_DB_SSLROOTCERT': '/tmp/placeholder-ca.pem', 'SUPABASE_DB_SCHEMA': 'dse_knowledge',
}
RUNTIME = {
    'SUPABASE_DB_HOST': ADMIN['SUPABASE_DB_HOST'], 'SUPABASE_DB_PORT': '5432',
    'SUPABASE_DB_NAME': 'postgres', 'SUPABASE_DB_USER': 'dse_knowledge_app.projectref1234567890',
    'SUPABASE_DB_PASSWORD': 'runtime-placeholder', 'SUPABASE_DB_SSLMODE': 'verify-full',
    'SUPABASE_DB_SSLROOTCERT': ADMIN['SUPABASE_DB_SSLROOTCERT'],
    'SUPABASE_DB_SCHEMA': 'dse_knowledge',
}
ADMIN_USER = ADMIN['SUPABASE_DB_USER']
ADMIN_DB_ROLE = 'postgres'


class FakeSettings:
    def __init__(self, values=None, *, admin=False):
        self.values = dict(values or ADMIN)
        self.admin = admin

    @classmethod
    def load(cls, *, admin=False):
        assert admin is True
        return cls(ADMIN, admin=True)

    def get(self, key, default=''):
        return self.values.get(key, default)

    def require(self, key):
        value = self.get(key)
        if not value:
            raise ValueError('Missing setting')
        return value

    @property
    def schema(self):
        if self.get('SUPABASE_DB_SCHEMA', 'dse_knowledge') != 'dse_knowledge':
            raise ValueError('Wrong schema')
        return 'dse_knowledge'

    def db_kwargs(self):
        if self.get('SUPABASE_DB_SSLMODE', 'verify-full') != 'verify-full':
            raise ValueError('Wrong TLS mode')
        user = self.require('SUPABASE_DB_USER')
        if not self.admin and not user.startswith('dse_knowledge_app.'):
            raise ValueError('Wrong runtime role')
        return {
            'host': self.require('SUPABASE_DB_HOST'), 'port': int(self.get('SUPABASE_DB_PORT', '5432')),
            'dbname': self.get('SUPABASE_DB_NAME', 'postgres'), 'user': user,
            'password': self.require('SUPABASE_DB_PASSWORD'), 'sslmode': 'verify-full',
            'sslrootcert': self.require('SUPABASE_DB_SSLROOTCERT'),
        }


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, *, role_row=None, membership_rows=None, admin_user=ADMIN_DB_ROLE,
                 table_count=15, runtime_user='', profile='good'):
        self.role_row = role_row
        self.membership_rows = ([("dse_knowledge_app", admin_user, True, False, False)]
                                if membership_rows is None else membership_rows)
        self.admin_user = admin_user
        self.table_count = table_count
        self.runtime_user = runtime_user
        self.profile = profile
        self.statements = []
        self.closed = False
        self.read_only = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, query, params=()):
        self.statements.append((query, params))
        if not isinstance(query, str):
            return FakeCursor()
        if query.strip() == 'SELECT current_user':
            return FakeCursor([(self.admin_user,)])
        if 'FROM pg_auth_members' in query:
            return FakeCursor(self.membership_rows)
        if 'FROM pg_roles' in query:
            return FakeCursor([self.role_row] if self.role_row else [])
        if 'information_schema.tables' in query:
            return FakeCursor([(self.table_count,)])
        if query == 'SET TRANSACTION READ ONLY':
            self.read_only = True
            return FakeCursor()
        if 'current_setting' in query and 'current_user' in query:
            mode = 'on' if self.read_only and self.profile != 'not_read_only' else 'off'
            return FakeCursor([(self.runtime_user, self.runtime_user, 'postgres', mode)])
        if 'FROM pg_catalog.pg_class' in query:
            insert = self.profile != 'missing_insert'
            return FakeCursor([(f'table-{n}', True, insert, True, True) for n in range(self.table_count)])
        if 'FROM pg_catalog.pg_namespace' in query:
            app_create = self.profile == 'schema_create'
            auth_usage = self.profile == 'auth_usage'
            return FakeCursor([
                ('dse_knowledge', True, app_create), ('extensions', True, False),
                ('public', False, False), ('auth', auth_usage, False), ('storage', False, False),
            ])
        if 'has_database_privilege' in query:
            return FakeCursor([(self.profile == 'database_create',)])
        return FakeCursor()


class FakeStore:
    def __init__(self, settings):
        self.settings = settings
        self.migrations = []

    def migrate(self, path):
        self.migrations.append(Path(path))


def write_runtime(path, values=None):
    values = dict(values or RUNTIME)
    path.write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
    path.chmod(0o600)


def setup_bootstrap(monkeypatch, tmp_path, *, role_row=None, membership_rows=None,
                    admin_user=ADMIN_DB_ROLE, runtime_profile='good',
                    runtime_db_role='dse_knowledge_app'):
    config_dir = tmp_path / 'private-config'
    config_dir.mkdir(mode=0o700)
    monkeypatch.setenv('DSE_CONFIG_DIR', str(config_dir))
    monkeypatch.setattr(bootstrap, 'Settings', FakeSettings)
    stores = []

    class StoreFactory(FakeStore):
        def __init__(self, settings):
            super().__init__(settings)
            stores.append(self)

    monkeypatch.setattr(bootstrap, 'Store', StoreFactory)
    admin_connection = FakeConnection(role_row=role_row, membership_rows=membership_rows,
                                      admin_user=admin_user)
    runtime_connection = FakeConnection(
        runtime_user=runtime_db_role, profile=runtime_profile)
    connect_kwargs = []

    def connect(**kwargs):
        connect_kwargs.append(kwargs)
        if kwargs.get('user', '').startswith('dse_knowledge_app.'):
            return runtime_connection
        return admin_connection

    monkeypatch.setattr(bootstrap.psycopg, 'connect', connect)
    monkeypatch.setattr(bootstrap.secrets, 'token_urlsafe', lambda _size: 'runtime-placeholder')
    return config_dir, admin_connection, runtime_connection, stores, connect_kwargs


def test_new_role_is_verified_through_dedicated_read_only_runtime_login(monkeypatch, tmp_path):
    config_dir, admin, runtime, stores, connect_kwargs = setup_bootstrap(monkeypatch, tmp_path)

    result = bootstrap.run_bootstrap()

    runtime_file = config_dir / 'runtime-database.env'
    assert stat.S_IMODE(runtime_file.lstat().st_mode) == 0o600
    assert result['status'] == 'ready' and result['runtime_config'] == 'created'
    assert any(kwargs['user'] == RUNTIME['SUPABASE_DB_USER'] for kwargs in connect_kwargs)
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)
    assert runtime.closed and len(stores) == 1
    assert not any(isinstance(query, sql.Composed) and 'DROP ROLE' in repr(query)
                   for query, _ in admin.statements)


def test_new_role_that_fails_runtime_probe_is_removed(monkeypatch, tmp_path):
    config_dir, admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, runtime_profile='missing_insert')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_privilege_check_failed'
    assert not (config_dir / 'runtime-database.env').exists()
    assert any(isinstance(query, sql.Composed) and 'DROP ROLE' in repr(query)
               for query, _ in admin.statements)


@pytest.mark.parametrize('field,value,reason', [
    ('SUPABASE_DB_HOST', 'other-pooler.example.invalid', 'runtime_database_target_mismatch'),
    ('SUPABASE_DB_SSLROOTCERT', '/tmp/other-ca.pem', 'runtime_database_target_mismatch'),
    ('SUPABASE_DB_USER', 'dse_knowledge_app.otherprojectref', 'runtime_database_role_mismatch'),
    ('SUPABASE_DB_SSLMODE', 'require', 'runtime_config_invalid'),
])
def test_existing_role_is_not_ready_when_runtime_config_does_not_match(monkeypatch, tmp_path,
                                                                        field, value, reason):
    role = (True, False, False, False, False, False)
    config_dir, admin, runtime, _stores, connect_kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role)
    values = dict(RUNTIME, **{field: value})
    write_runtime(config_dir / 'runtime-database.env', values)

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == reason
    assert not runtime.statements
    assert not any(kwargs['user'] == RUNTIME['SUPABASE_DB_USER'] for kwargs in connect_kwargs)
    assert not any(isinstance(query, sql.Composed) for query, _ in admin.statements)


def test_existing_role_noop_requires_runtime_login_and_all_app_table_privileges(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, runtime_profile='missing_insert')
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_privilege_check_failed'
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)


@pytest.mark.parametrize('profile', ['schema_create', 'database_create', 'auth_usage'])
def test_runtime_login_rejects_ddl_and_system_schema_privileges(monkeypatch, tmp_path, profile):
    role = (True, False, False, False, False, False)
    config_dir, _admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, runtime_profile=profile)
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_privilege_check_failed'


def test_runtime_privilege_probe_must_be_read_only(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, runtime_profile='not_read_only')
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_login_identity_mismatch'
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)


@pytest.mark.parametrize('membership_rows', [
    [('postgres.projectref1234567890', 'dse_knowledge_app', False, False, False)],
    [('dse_knowledge_app', 'other_admin', True, False, False)],
    [('dse_knowledge_app', ADMIN_DB_ROLE, True, True, False)],
    [('dse_knowledge_app', ADMIN_DB_ROLE, True, False, True)],
    [('dse_knowledge_app', ADMIN_DB_ROLE, False, False, False)],
    [('dse_knowledge_app', ADMIN_DB_ROLE, True, False, False),
     ('dse_knowledge_app', 'other_admin', True, False, False)],
])
def test_existing_role_with_unsafe_membership_is_not_reported_ready(monkeypatch, tmp_path,
                                                                     membership_rows):
    role = (True, False, False, False, False, False)
    config_dir, admin, runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, membership_rows=membership_rows)
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'existing_app_role_membership_risk'
    assert not runtime.statements
    assert any('pg_auth_members' in query for query, _ in admin.statements if isinstance(query, str))


def test_existing_role_allows_only_creator_admin_option_without_inherit_or_set(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    creator_membership = [('dse_knowledge_app', ADMIN_DB_ROLE, True, False, False)]
    config_dir, _admin, runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, membership_rows=creator_membership)
    write_runtime(config_dir / 'runtime-database.env')

    result = bootstrap.run_bootstrap()

    assert result['no_op'] is True
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)


def test_runtime_identity_uses_native_role_not_pooler_routing_username(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, runtime, _stores, connect_kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, runtime_db_role='dse_knowledge_app')
    write_runtime(config_dir / 'runtime-database.env')

    result = bootstrap.run_bootstrap()

    assert result['no_op'] is True
    assert any(kwargs['user'] == RUNTIME['SUPABASE_DB_USER'] for kwargs in connect_kwargs)
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)


def test_runtime_identity_rejects_unexpected_database_role(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, runtime_db_role='another_app_role')
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_login_identity_mismatch'


def test_existing_role_without_memberships_is_safe(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, membership_rows=[])
    write_runtime(config_dir / 'runtime-database.env')

    result = bootstrap.run_bootstrap()

    assert result['no_op'] is True


def test_existing_role_rejects_unexpected_bootstrap_current_user(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role, membership_rows=[], admin_user='unexpected_admin')
    write_runtime(config_dir / 'runtime-database.env')

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'existing_app_role_membership_risk'
    assert not runtime.statements


def test_existing_role_and_valid_runtime_config_are_read_only_noop(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, admin, runtime, _stores, connect_kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role)
    runtime_file = config_dir / 'runtime-database.env'
    write_runtime(runtime_file)
    before = runtime_file.lstat()

    result = bootstrap.run_bootstrap()

    after = runtime_file.lstat()
    assert result['no_op'] is True and result['runtime_config'] == 'existing'
    assert (before.st_dev, before.st_ino, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_mtime_ns)
    assert any(kwargs['user'] == RUNTIME['SUPABASE_DB_USER'] for kwargs in connect_kwargs)
    assert any(query == 'SET TRANSACTION READ ONLY' for query, _ in runtime.statements)
    assert all(query == 'SET TRANSACTION READ ONLY' or query.lstrip().startswith('SELECT')
               for query, _ in runtime.statements if isinstance(query, str))
    assert not any(isinstance(query, sql.Composed) for query, _ in admin.statements)


def test_existing_role_without_runtime_file_fails_without_password_rotation(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    _config_dir, admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role)

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_config_missing_for_existing_role'
    assert not any(isinstance(query, sql.Composed) for query, _ in admin.statements)


def test_runtime_file_without_role_is_never_overwritten(monkeypatch, tmp_path):
    config_dir, admin, _runtime, _stores, _kwargs = setup_bootstrap(monkeypatch, tmp_path)
    runtime = config_dir / 'runtime-database.env'
    write_runtime(runtime)
    before = runtime.lstat()

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    after = runtime.lstat()
    assert error.value.reason == 'runtime_config_exists_without_role'
    assert (before.st_dev, before.st_ino, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_mtime_ns)
    assert not any(isinstance(query, sql.Composed) for query, _ in admin.statements)


def test_symlinked_runtime_path_is_rejected(monkeypatch, tmp_path):
    role = (True, False, False, False, False, False)
    config_dir, _admin, _runtime, _stores, _kwargs = setup_bootstrap(
        monkeypatch, tmp_path, role_row=role)
    target = config_dir / 'target'
    target.write_text('placeholder-not-a-credential')
    (config_dir / 'runtime-database.env').symlink_to(target)

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.run_bootstrap()

    assert error.value.reason == 'runtime_config_not_regular_private_file'


def test_cli_output_omits_database_account_project_and_password(monkeypatch, tmp_path, capsys):
    setup_bootstrap(monkeypatch, tmp_path)

    assert bootstrap.main() == 0

    output = capsys.readouterr().out
    assert 'runtime-placeholder' not in output
    assert 'admin-placeholder' not in output
    assert 'projectref1234567890' not in output
    assert 'dse_knowledge_app' not in output
