"""Create a private logical-data snapshot and run a local serialization smoke check.

This is not a full product backup: source artifact bytes and the Native Melete
store live outside the exported PostgreSQL rows and are not copied here.
"""
from __future__ import annotations

import errno
import gzip
import hashlib
import json
import os
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dse_knowledge.config import Settings
from dse_knowledge.db import Store


TABLES = (
    'schema_versions', 'materials', 'revisions', 'chunks', 'claims', 'entities',
    'edges', 'decisions', 'gaps', 'jobs', 'feedback', 'experiments', 'outbox',
    'ingest_events', 'invocations', 'claim_annotations', 'collection_batches', 'collection_items',
)
PRIMARY_KEYS = {'schema_versions': 'version', 'collection_items': ('batch_id','material_id')}
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_CLOEXEC', 0)
NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)


class BackupError(RuntimeError):
    """A backup could not be created without weakening its local safeguards."""


def _open_private_directory(path: Path) -> tuple[Path, int]:
    """Open/create a private directory while rejecting symlink path components."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    fd = os.open(absolute.anchor, DIRECTORY_FLAGS)
    parts = absolute.parts[1:]
    final_created = False
    try:
        for index, component in enumerate(parts):
            try:
                child_fd = os.open(component, DIRECTORY_FLAGS | NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child_fd = os.open(component, DIRECTORY_FLAGS | NOFOLLOW, dir_fd=fd)
                if index == len(parts) - 1:
                    final_created = True
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise BackupError(f'Backup path contains a symlink or non-directory: {absolute}') from exc
                raise
            os.close(fd)
            fd = child_fd

        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise BackupError(f'Backup path is not a directory: {absolute}')
        if info.st_uid != os.getuid():
            raise BackupError(f'Backup directory must be owned by the current user: {absolute}')
        if final_created:
            os.fchmod(fd, 0o700)
        elif stat.S_IMODE(info.st_mode) & 0o077:
            raise BackupError(f'Backup directory must be owner-only (mode 0700): {absolute}')
        elif stat.S_IMODE(info.st_mode) & 0o700 != 0o700:
            raise BackupError(f'Backup directory must be owner-readable, writable, and searchable: {absolute}')
        return absolute, fd
    except BaseException:
        os.close(fd)
        raise


def _atomic_write_new(directory_fd: int, name: str, data: bytes) -> None:
    """Publish a new mode-0600 file atomically; never replace an existing name."""
    if not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Expected a single safe filename')

    temporary = f'.{name}.{uuid.uuid4().hex}.tmp'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError('Could not finish writing backup file')
            remaining = remaining[written:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        raise
    else:
        os.close(fd)

    published = False
    try:
        # link() is an atomic create-if-absent operation on the same filesystem.
        os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        published = True
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        if published:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise


def _read_file(directory_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | NOFOLLOW | getattr(os, 'O_CLOEXEC', 0), dir_fd=directory_fd)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _sqlite_serialization_check(root: Path, directory_fd: int, name: str, tables: dict) -> tuple[str, dict[str, int]]:
    """Check exported JSON rows in a throwaway SQLite file; this is not PG restore."""
    final_name = f'{name}-restore-check.sqlite'
    temporary = f'.{final_name}.{uuid.uuid4().hex}.tmp'
    fd = os.open(
        temporary,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW | getattr(os, 'O_CLOEXEC', 0),
        0o600,
        dir_fd=directory_fd,
    )
    os.fchmod(fd, 0o600)
    os.close(fd)
    db = None
    try:
        db = sqlite3.connect(str(root / temporary))
        for table, rows in tables.items():
            key_column = PRIMARY_KEYS.get(table, 'id')
            db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.executemany(
                f'INSERT INTO {table} VALUES(?,?)',
                [(json.dumps([row[k] for k in key_column]) if isinstance(key_column,tuple) else str(row[key_column]),
                  json.dumps(row, ensure_ascii=False, default=str)) for row in rows],
            )
        db.commit()
        counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in tables}
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        expected = {table: len(rows) for table, rows in tables.items()}
        if integrity != 'ok' or counts != expected:
            raise BackupError('SQLite serialization smoke check did not match exported row counts')
    except BaseException:
        if db is not None:
            db.close()
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        raise
    else:
        db.close()

    check_fd = os.open(temporary, os.O_RDONLY | NOFOLLOW, dir_fd=directory_fd)
    try:
        os.fchmod(check_fd, 0o600)
        os.fsync(check_fd)
    finally:
        os.close(check_fd)
    published = False
    try:
        os.link(temporary, final_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        published = True
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        if published:
            try:
                os.unlink(final_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    return final_name, counts


def run_backup(settings=None, store=None, *, now: datetime | None = None) -> dict:
    """Export allow-listed logical rows to a unique private local snapshot."""
    settings = Settings.load() if settings is None else settings
    store = Store(settings) if store is None else store
    data_root, _data_fd = _open_private_directory(Path(settings.data_root))
    os.close(_data_fd)
    root, root_fd = _open_private_directory(data_root / 'backups')
    created: list[str] = []
    try:
        payload = {'format': 'dse-logical-backup/v1', 'tables': {}}
        with store.connection() as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for table in TABLES:
                rows = connection.execute(f'SELECT * FROM {table}').fetchall()
                payload['tables'][table] = [dict(row) for row in rows]

        raw = json.dumps(payload, default=str, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        archive = gzip.compress(raw, mtime=0)
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise BackupError('Backup timestamp must include a timezone')
        stamp = moment.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        name = f'pilot-{stamp}-{uuid.uuid4().hex}'
        archive_name = f'{name}.json.gz'
        _atomic_write_new(root_fd, archive_name, archive)
        created.append(archive_name)

        restored = json.loads(gzip.decompress(_read_file(root_fd, archive_name)))
        check_name, counts = _sqlite_serialization_check(root, root_fd, name, restored['tables'])
        created.append(check_name)

        report = {
            'backup': str(root / archive_name),
            'archive_sha256': hashlib.sha256(_read_file(root_fd, archive_name)).hexdigest(),
            'payload_sha256': hashlib.sha256(raw).hexdigest(),
            'rows': counts,
            'restore_check': 'sqlite_serialization_row_count_integrity_smoke_passed',
            'restore_check_file': str(root / check_name),
            'scope': {
                'included': 'Logical row serialization from the allow-listed dse_knowledge tables, including schema_versions.',
                'excluded': [
                    'Raw source artifact bytes; database rows retain metadata and paths only.',
                    'Native Melete document-store contents.',
                    'Off-host backup, replication, and retention.',
                    'PostgreSQL schema/role disaster recovery and a PostgreSQL restore test.',
                ],
                'validation': 'A local SQLite JSON serialization, row-count, and integrity smoke check only; this is not a full product backup or PostgreSQL disaster-recovery validation.',
            },
        }
        verification_name = f'{name}-verification.json'
        report['verification'] = str(root / verification_name)
        _atomic_write_new(root_fd, verification_name, json.dumps(report, indent=2, ensure_ascii=False).encode('utf-8'))
        created.append(verification_name)
        return report
    except BaseException:
        for filename in reversed(created):
            try:
                os.unlink(filename, dir_fd=root_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(root_fd)


def main() -> None:
    print(json.dumps(run_backup(), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
