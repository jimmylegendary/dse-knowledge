"""Owner-only runtime configuration; secret values never appear in repr or health."""
from __future__ import annotations
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise ValueError('Configuration cannot be a symlink')
    st = path.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError('Configuration must be owner-only')
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not key.replace('_', '').isalnum():
            raise ValueError('Invalid configuration line')
        values[key] = value.strip().strip('"').strip("'")
    return values


@dataclass(repr=False)
class Settings:
    values: dict[str, str] = field(default_factory=dict)
    admin: bool = False

    def __repr__(self):
        return 'Settings(<redacted>)'

    @classmethod
    def load(cls, *, admin: bool = False) -> 'Settings':
        root = Path(os.environ.get('DSE_CONFIG_DIR', str(Path.home()/'.config/dse-knowledge')))
        if root.exists():
            st = root.stat()
            if root.is_symlink() or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError('Configuration directory must be owner-only')
        values = {}
        db_file = 'database.env' if admin else 'runtime-database.env'
        for name in (db_file, 'llm.env', 'embedding.env', 'app.env'):
            p = root/name
            if p.exists():
                values.update(read_env(p))
        values.update({k:v for k,v in os.environ.items() if k.startswith(('DSE_', 'EMBEDDING_', 'CHAT_', 'CODEX_')) or (admin and k.startswith('SUPABASE_DB_'))})
        return cls(values, admin=admin)

    def get(self, key: str, default: str = '') -> str:
        return self.values.get(key, default)

    def require(self, key: str) -> str:
        value = self.get(key)
        if not value:
            raise ValueError(f'Missing setting: {key}')
        return value

    @property
    def data_root(self) -> Path:
        return Path(self.get('DSE_DATA_ROOT', str(Path.home()/'.local/share/dse-knowledge')))

    @property
    def artifact_root(self) -> Path:
        return Path(self.get('DSE_ARTIFACT_ROOT', str(self.data_root/'artifacts')))

    @property
    def codex_workdir(self) -> Path:
        return Path(self.get('CODEX_WORKDIR', str(self.data_root/'codex-runtime')))

    @property
    def schema(self) -> str:
        schema = self.get('SUPABASE_DB_SCHEMA', 'dse_knowledge')
        if schema != 'dse_knowledge':
            raise ValueError('Pilot requires dse_knowledge schema')
        return schema

    def db_kwargs(self) -> dict:
        if self.get('SUPABASE_DB_SSLMODE', 'verify-full') != 'verify-full':
            raise ValueError('Database requires verify-full')
        if not self.admin and not self.require('SUPABASE_DB_USER').startswith('dse_knowledge_app.'):
            raise ValueError('Runtime requires dedicated dse_knowledge_app role')
        return dict(host=self.require('SUPABASE_DB_HOST'), port=int(self.get('SUPABASE_DB_PORT','5432')),
                    dbname=self.get('SUPABASE_DB_NAME','postgres'), user=self.require('SUPABASE_DB_USER'),
                    password=self.require('SUPABASE_DB_PASSWORD'), sslmode='verify-full',
                    sslrootcert=self.require('SUPABASE_DB_SSLROOTCERT'), connect_timeout=15,
                    options='-c statement_timeout=30000 -c search_path=dse_knowledge,extensions,public')
