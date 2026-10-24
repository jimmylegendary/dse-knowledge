#!/usr/bin/env python3
"""Idempotently migrate the pilot schema and create its least-privilege app role."""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import psycopg
from psycopg import sql

from dse_knowledge.config import Settings, read_env
from dse_knowledge.db import Store


ROLE_NAME = 'dse_knowledge_app'
APP_TABLE_PRIVILEGES = 'SELECT, INSERT, UPDATE, DELETE'
APP_SEQUENCE_PRIVILEGES = 'USAGE, SELECT, UPDATE'


class BootstrapError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _config_dir() -> Path:
    return Path(os.environ.get('DSE_CONFIG_DIR', str(Path.home() / '.config' / 'dse-knowledge')))


def _secure_config_dir(path: Path) -> None:
    try:
        if path.is_symlink():
            raise OSError
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077):
            raise OSError
    except OSError:
        raise BootstrapError('config_directory_not_owner_only') from None


def _runtime_file_state(path: Path) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise BootstrapError('runtime_config_unavailable') from None
    if (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise BootstrapError('runtime_config_not_regular_private_file')
    return metadata


def _project_ref(settings) -> str:
    user = settings.require('SUPABASE_DB_USER')
    match = re.fullmatch(r'postgres\.([a-z0-9-]+)', user)
    if not match:
        raise BootstrapError('admin_database_user_missing_project_ref')
    return match.group(1)


def _runtime_values(settings, project_ref: str, password: str) -> dict[str, str]:
    try:
        host = settings.require('SUPABASE_DB_HOST')
        port = str(int(settings.get('SUPABASE_DB_PORT', '5432')))
        database = settings.get('SUPABASE_DB_NAME', 'postgres')
        ssl_root_cert = settings.require('SUPABASE_DB_SSLROOTCERT')
        schema = settings.schema
    except Exception:
        raise BootstrapError('admin_database_configuration_invalid') from None
    if settings.get('SUPABASE_DB_SSLMODE', 'verify-full') != 'verify-full':
        raise BootstrapError('database_tls_policy_invalid')
    if port != '5432' or database != 'postgres' or '\n' in host or '\r' in host:
        raise BootstrapError('admin_database_target_invalid')
    if '\n' in ssl_root_cert or '\r' in ssl_root_cert:
        raise BootstrapError('admin_database_ca_path_invalid')
    return {
        'SUPABASE_DB_HOST': host,
        'SUPABASE_DB_PORT': port,
        'SUPABASE_DB_NAME': database,
        'SUPABASE_DB_USER': f'{ROLE_NAME}.{project_ref}',
        'SUPABASE_DB_PASSWORD': password,
        'SUPABASE_DB_SSLMODE': 'verify-full',
        'SUPABASE_DB_SSLROOTCERT': ssl_root_cert,
        'SUPABASE_DB_SCHEMA': schema,
    }


def _write_private_atomic(path: Path, values: dict[str, str]) -> tuple[int, int]:
    payload_lines = []
    for key, value in values.items():
        if not re.fullmatch(r'[A-Z0-9_]+', key) or not isinstance(value, str) or '\n' in value or '\r' in value:
            raise BootstrapError('runtime_config_value_invalid')
        payload_lines.append(f'{key}={value}')
    payload = ('\n'.join(payload_lines) + '\n').encode('utf-8')
    temporary = path.parent / f'.{path.name}.{secrets.token_hex(12)}.tmp'
    fd = None
    temporary_created = False
    linked = False
    temporary_identity = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(temporary, flags, 0o600)
        temporary_created = True
        os.fchmod(fd, 0o600)
        file_stat = os.fstat(fd)
        temporary_identity = (file_stat.st_dev, file_stat.st_ino)
        with os.fdopen(fd, 'wb') as output:
            fd = None
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path, follow_symlinks=False)
        linked = True
        metadata = path.lstat()
        if (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600
                or (metadata.st_dev, metadata.st_ino) != temporary_identity):
            raise OSError
        temporary.unlink()
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return temporary_identity
    except FileExistsError:
        raise BootstrapError('runtime_config_creation_raced') from None
    except OSError:
        if linked:
            _unlink_if_same_inode(path, temporary_identity)
        raise BootstrapError('runtime_config_write_failed') from None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_created:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _unlink_if_same_inode(path: Path, expected: tuple[int, int] | os.stat_result | None) -> None:
    if expected is None:
        return
    expected_device, expected_inode = (expected if isinstance(expected, tuple)
                                       else (expected.st_dev, expected.st_ino))
    try:
        current = path.lstat()
        if (not stat.S_ISLNK(current.st_mode) and current.st_dev == expected_device
                and current.st_ino == expected_inode):
            path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _role_attributes_valid(row) -> bool:
    if row is None:
        return False
    return tuple(row) == (True, False, False, False, False, False)


def _check_role_memberships(connection, expected_admin_user: str) -> None:
    current_user = connection.execute('SELECT current_user').fetchone()
    if not current_user or current_user[0] not in {expected_admin_user, 'postgres'}:
        raise BootstrapError('existing_app_role_membership_risk')
    creator = current_user[0]
    memberships = connection.execute(
        'SELECT granted.rolname, member.rolname, membership.admin_option, '
        'membership.inherit_option, membership.set_option '
        'FROM pg_auth_members membership '
        'JOIN pg_roles granted ON granted.oid=membership.roleid '
        'JOIN pg_roles member ON member.oid=membership.member '
        'WHERE granted.rolname=%s OR member.rolname=%s', (ROLE_NAME, ROLE_NAME)
    ).fetchall()
    permitted_creator_grant = (ROLE_NAME, creator, True, False, False)
    if memberships and (len(memberships) != 1 or tuple(memberships[0]) != permitted_creator_grant):
        raise BootstrapError('existing_app_role_membership_risk')


def _runtime_settings(runtime_path: Path, admin_settings, project_ref: str, schema: str):
    try:
        runtime = Settings(read_env(runtime_path))
        kwargs = runtime.db_kwargs()
        admin_kwargs = admin_settings.db_kwargs()
        runtime_user = runtime.require('SUPABASE_DB_USER')
        runtime.require('SUPABASE_DB_PASSWORD')
        if runtime_user != f'{ROLE_NAME}.{project_ref}':
            raise BootstrapError('runtime_database_role_mismatch')
        if runtime.schema != schema:
            raise BootstrapError('runtime_database_schema_mismatch')
        if (kwargs['host'] != admin_kwargs['host']
                or kwargs['port'] != 5432 or admin_kwargs['port'] != 5432
                or kwargs['dbname'] != 'postgres' or admin_kwargs['dbname'] != 'postgres'
                or kwargs['sslrootcert'] != admin_kwargs['sslrootcert']
                or runtime.get('SUPABASE_DB_SSLMODE', 'verify-full') != 'verify-full'):
            raise BootstrapError('runtime_database_target_mismatch')
        return runtime
    except BootstrapError:
        raise
    except Exception:
        raise BootstrapError('runtime_config_invalid') from None


def _verify_runtime_login(runtime, schema: str) -> None:
    try:
        connection = psycopg.connect(**runtime.db_kwargs())
    except Exception:
        raise BootstrapError('runtime_login_failed') from None
    try:
        with connection:
            with connection.transaction():
                connection.execute('SET TRANSACTION READ ONLY')
                identity = connection.execute(
                    'SELECT current_user, session_user, current_database(), '
                    "current_setting('transaction_read_only')"
                ).fetchone()
                # The .<project-ref> suffix routes through Supavisor; PostgreSQL exposes the native role.
                if identity != (ROLE_NAME, ROLE_NAME, 'postgres', 'on'):
                    raise BootstrapError('runtime_login_identity_mismatch')
                tables = connection.execute(
                    'SELECT c.relname, has_table_privilege(current_user,c.oid,%s), '
                    'has_table_privilege(current_user,c.oid,%s), has_table_privilege(current_user,c.oid,%s), '
                    'has_table_privilege(current_user,c.oid,%s) '
                    'FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname=%s AND c.relkind IN ('r','p') ORDER BY c.relname",
                    ('SELECT', 'INSERT', 'UPDATE', 'DELETE', schema),
                ).fetchall()
                if not tables or any(row[1:] != (True, True, True, True) for row in tables):
                    raise BootstrapError('runtime_privilege_check_failed')
                schemas = connection.execute(
                    'SELECT n.nspname, has_schema_privilege(current_user,n.oid,%s), '
                    "has_schema_privilege(current_user,n.oid,%s) FROM pg_catalog.pg_namespace n "
                    "WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'",
                    ('USAGE', 'CREATE'),
                ).fetchall()
                schema_privileges = {row[0]: (row[1], row[2]) for row in schemas}
                if (schema_privileges.get(schema, (False, True))[0] is not True
                        or schema_privileges.get('extensions', (False, True))[0] is not True
                        or any(create for _name, (_usage, create) in schema_privileges.items())
                        or any(schema_privileges.get(name, (False, False))[0]
                               for name in ('auth', 'storage'))):
                    raise BootstrapError('runtime_privilege_check_failed')
                database_create = connection.execute(
                    "SELECT has_database_privilege(current_user,current_database(),%s)", ('CREATE',)
                ).fetchone()
                if not database_create or database_create[0] is not False:
                    raise BootstrapError('runtime_privilege_check_failed')
    except BootstrapError:
        raise
    except Exception:
        raise BootstrapError('runtime_privilege_check_failed') from None
    finally:
        try:
            connection.close()
        except Exception:
            pass


def _drop_created_role(settings, database: str, schema: str) -> None:
    role = sql.Identifier(ROLE_NAME)
    try:
        with psycopg.connect(**settings.db_kwargs()) as connection:
            with connection.transaction():
                connection.execute(sql.SQL('REVOKE {} ON ALL TABLES IN SCHEMA {} FROM {}').format(
                    sql.SQL(APP_TABLE_PRIVILEGES), sql.Identifier(schema), role))
                connection.execute(sql.SQL('REVOKE {} ON ALL SEQUENCES IN SCHEMA {} FROM {}').format(
                    sql.SQL(APP_SEQUENCE_PRIVILEGES), sql.Identifier(schema), role))
                connection.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE {} ON TABLES FROM {}').format(
                    sql.Identifier(schema), sql.SQL(APP_TABLE_PRIVILEGES), role))
                connection.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE {} ON SEQUENCES FROM {}').format(
                    sql.Identifier(schema), sql.SQL(APP_SEQUENCE_PRIVILEGES), role))
                connection.execute(sql.SQL('REVOKE USAGE ON SCHEMA {}, {} FROM {}').format(
                    sql.Identifier(schema), sql.Identifier('extensions'), role))
                connection.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {}').format(
                    sql.Identifier(database), role))
                connection.execute(sql.SQL('DROP ROLE {}').format(role))
    except Exception:
        raise BootstrapError('created_role_cleanup_failed') from None


def _create_app_role(connection, database: str, schema: str, password: str) -> None:
    role = sql.Identifier(ROLE_NAME)
    connection.execute(sql.SQL(
        'CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION '
        'NOBYPASSRLS PASSWORD {}').format(role, sql.Literal(password)))
    connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), role))
    connection.execute(sql.SQL('GRANT USAGE ON SCHEMA {}, {} TO {}').format(
        sql.Identifier(schema), sql.Identifier('extensions'), role))
    connection.execute(sql.SQL('GRANT {} ON ALL TABLES IN SCHEMA {} TO {}').format(
        sql.SQL(APP_TABLE_PRIVILEGES), sql.Identifier(schema), role))
    connection.execute(sql.SQL('GRANT {} ON ALL SEQUENCES IN SCHEMA {} TO {}').format(
        sql.SQL(APP_SEQUENCE_PRIVILEGES), sql.Identifier(schema), role))
    connection.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT {} ON TABLES TO {}').format(
        sql.Identifier(schema), sql.SQL(APP_TABLE_PRIVILEGES), role))
    connection.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT {} ON SEQUENCES TO {}').format(
        sql.Identifier(schema), sql.SQL(APP_SEQUENCE_PRIVILEGES), role))


def _migrate(store: Store) -> None:
    migration_paths = sorted((ROOT / 'migrations').glob('*.sql'))
    if not migration_paths:
        raise BootstrapError('migration_files_missing')
    try:
        for migration_path in migration_paths:
            store.migrate(migration_path)
    except Exception:
        raise BootstrapError('database_migration_failed') from None


def run_bootstrap() -> dict:
    try:
        settings = Settings.load(admin=True)
        settings.db_kwargs()  # validates the admin target and verify-full TLS settings
        if (settings.get('SUPABASE_DB_NAME', 'postgres') != 'postgres'
                or int(settings.get('SUPABASE_DB_PORT', '5432')) != 5432):
            raise BootstrapError('admin_database_target_invalid')
        project_ref = _project_ref(settings)
        schema = settings.schema
    except BootstrapError:
        raise
    except Exception:
        raise BootstrapError('admin_configuration_unavailable') from None

    store = Store(settings)
    _migrate(store)

    config_dir = _config_dir()
    _secure_config_dir(config_dir)
    runtime_path = config_dir / 'runtime-database.env'
    runtime_metadata = _runtime_file_state(runtime_path)
    created_inode = None
    database = settings.get('SUPABASE_DB_NAME', 'postgres')
    try:
        connection = psycopg.connect(**settings.db_kwargs())
    except Exception:
        raise BootstrapError('admin_database_connection_failed') from None
    try:
        with connection.transaction():
            role_row = connection.execute(
                'SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls '
                'FROM pg_roles WHERE rolname=%s', (ROLE_NAME,)
            ).fetchone()
            if role_row is not None:
                if not _role_attributes_valid(role_row):
                    raise BootstrapError('existing_app_role_privileges_invalid')
                _check_role_memberships(connection, settings.require('SUPABASE_DB_USER'))
                if runtime_metadata is None:
                    raise BootstrapError('runtime_config_missing_for_existing_role')
                table_count = connection.execute(
                    'SELECT count(*) FROM information_schema.tables '
                    'WHERE table_schema=%s AND table_type=%s', (schema, 'BASE TABLE')
                ).fetchone()[0]
                no_op = True
            else:
                if runtime_metadata is not None:
                    raise BootstrapError('runtime_config_exists_without_role')
                password = secrets.token_urlsafe(32)
                _create_app_role(connection, database, schema, password)
                _check_role_memberships(connection, settings.require('SUPABASE_DB_USER'))
                runtime_values = _runtime_values(settings, project_ref, password)
                created_inode = _write_private_atomic(runtime_path, runtime_values)
                table_count = connection.execute(
                    'SELECT count(*) FROM information_schema.tables '
                    'WHERE table_schema=%s AND table_type=%s', (schema, 'BASE TABLE')
                ).fetchone()[0]
                no_op = False
    except BootstrapError:
        if created_inode:
            _unlink_if_same_inode(runtime_path, created_inode)
        raise
    except Exception:
        if created_inode:
            _unlink_if_same_inode(runtime_path, created_inode)
        raise BootstrapError('database_bootstrap_failed') from None
    finally:
        try:
            connection.close()
        except Exception:
            pass

    try:
        runtime = _runtime_settings(runtime_path, settings, project_ref, schema)
        _verify_runtime_login(runtime, schema)
    except BootstrapError:
        if created_inode:
            _unlink_if_same_inode(runtime_path, created_inode)
            _drop_created_role(settings, database, schema)
        raise
    except Exception:
        if created_inode:
            _unlink_if_same_inode(runtime_path, created_inode)
            _drop_created_role(settings, database, schema)
        raise BootstrapError('runtime_verification_failed') from None
    return {'status': 'ready', 'table_count': int(table_count),
            'no_op': no_op, 'runtime_config': 'existing' if no_op else 'created'}


def main() -> int:
    try:
        result = run_bootstrap()
    except BootstrapError as error:
        print(json.dumps({'status': 'failed', 'reason': error.reason}, separators=(',', ':')), flush=True)
        return 1
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'bootstrap_failed'}, separators=(',', ':')), flush=True)
        return 1
    print(json.dumps(result, separators=(',', ':')), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
