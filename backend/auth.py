"""Proveedor de identidad local preparado para sustituirse por Cognito/SSO."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .contracts import AuthIdentity


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "platform_admin": {"*"},
    "tenant_admin": {
        "document.capture", "document.review", "document.approve", "document.send",
        "document.read", "tenant.configure", "user.manage", "audit.read",
    },
    "supervisor": {"document.capture", "document.review", "document.approve", "document.send", "document.read", "audit.read"},
    "warehouse_operator": {"document.capture", "document.read"},
    "administrative": {"document.capture", "document.review", "document.read", "document.send"},
    "external_customer": {"document.read"},
    "external_supplier": {"document.read"},
}


@dataclass(frozen=True)
class LocalUser:
    id: str
    email: str
    display_name: str
    tenant_id: str
    roles: tuple[str, ...]


class LocalAuthError(Exception):
    pass


class LocalIdentityStore:
    """Esquema local que modela identidad y autorización multi-tenant."""

    def __init__(self, database: str | Path = "data/local-auth.sqlite3") -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS memberships (
                user_id TEXT NOT NULL REFERENCES users(id),
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                PRIMARY KEY (user_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS permissions (
                id TEXT PRIMARY KEY,
                permission TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS membership_roles (
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                role_id TEXT NOT NULL REFERENCES roles(id),
                PRIMARY KEY (user_id, tenant_id, role_id),
                FOREIGN KEY (user_id, tenant_id) REFERENCES memberships(user_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id TEXT NOT NULL REFERENCES roles(id),
                permission_id TEXT NOT NULL REFERENCES permissions(id),
                PRIMARY KEY (role_id, permission_id)
            );
            """
        )
        self.connection.commit()

    def seed(self, password_hash: str) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT OR IGNORE INTO tenants(id, name, status) VALUES (?, ?, 'active')",
                ("TEN-001", "Smart Magatzem Demo"),
            )
            users = [
                ("USR-001", "admin@smart-magatzem.local", "Administrador local", "tenant_admin"),
                ("USR-002", "supervisor@smart-magatzem.local", "Supervisor local", "supervisor"),
                ("USR-003", "operario@smart-magatzem.local", "Operario local", "warehouse_operator"),
            ]
            for user_id, email, display_name, role in users:
                self.connection.execute(
                    "INSERT OR IGNORE INTO users(id, email, display_name, password_hash) VALUES (?, ?, ?, ?)",
                    (user_id, email, display_name, password_hash),
                )
                self.connection.execute(
                    "INSERT OR IGNORE INTO memberships(user_id, tenant_id) VALUES (?, 'TEN-001')",
                    (user_id,),
                )
                self.connection.execute("INSERT OR IGNORE INTO roles(id, name) VALUES (?, ?)", (role, role))
                self.connection.execute(
                    "INSERT OR IGNORE INTO membership_roles(user_id, tenant_id, role_id) VALUES (?, 'TEN-001', ?)",
                    (user_id, role),
                )
            permissions = sorted({permission for values in ROLE_PERMISSIONS.values() for permission in values})
            for index, permission in enumerate(permissions, 1):
                permission_id = f"PERM-{index:03d}"
                self.connection.execute(
                    "INSERT OR IGNORE INTO permissions(id, permission) VALUES (?, ?)",
                    (permission_id, permission),
                )
            for role, role_permissions in ROLE_PERMISSIONS.items():
                self.connection.execute("INSERT OR IGNORE INTO roles(id, name) VALUES (?, ?)", (role, role))
                for permission in role_permissions:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) "
                        "SELECT ?, id FROM permissions WHERE permission = ?",
                        (role, permission),
                    )
            self.connection.commit()

    def user_by_email(self, email: str):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM users WHERE lower(email) = lower(?) AND status = 'active'", (email.strip(),)
            ).fetchone()

    def user_by_token_parts(self, user_id: str, tenant_id: str):
        with self.lock:
            return self.connection.execute(
                "SELECT u.* FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE u.id = ? AND m.tenant_id = ? AND u.status = 'active'",
                (user_id, tenant_id),
            ).fetchone()

    def identity_for_user(self, user_id: str, tenant_id: str) -> AuthIdentity | None:
        return self.identity(user_id, tenant_id)

    def create_tenant(self, user_id: str, tenant_id: str, name: str) -> dict[str, object]:
        tenant_id = tenant_id.strip().upper()
        name = name.strip()
        if not tenant_id or not name:
            raise LocalAuthError("El identificador y el nombre del tenant son obligatorios")
        if len(tenant_id) > 64 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in tenant_id):
            raise LocalAuthError("El identificador del tenant solo puede contener letras, números, guiones y guiones bajos")
        with self.lock:
            try:
                self.connection.execute("INSERT INTO tenants(id, name, status) VALUES (?, ?, 'active')", (tenant_id, name))
                self.connection.execute("INSERT INTO memberships(user_id, tenant_id) VALUES (?, ?)", (user_id, tenant_id))
                self.connection.execute(
                    "INSERT INTO membership_roles(user_id, tenant_id, role_id) VALUES (?, ?, 'tenant_admin')",
                    (user_id, tenant_id),
                )
                self.connection.commit()
            except sqlite3.IntegrityError as error:
                self.connection.rollback()
                raise LocalAuthError("El tenant ya existe o no se ha podido asignar al usuario") from error
            row = self.connection.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            return dict(row)

    def identity(self, user_id: str, tenant_id: str) -> AuthIdentity | None:
        with self.lock:
            user = self.connection.execute(
                "SELECT u.* FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE u.id = ? AND m.tenant_id = ? AND u.status = 'active'",
                (user_id, tenant_id),
            ).fetchone()
            if user is None:
                return None
            roles = [row[0] for row in self.connection.execute(
                "SELECT r.name FROM roles r JOIN membership_roles mr ON mr.role_id = r.id "
                "WHERE mr.user_id = ? AND mr.tenant_id = ? ORDER BY r.name",
                (user_id, tenant_id),
            ).fetchall()]
            permissions = [row[0] for row in self.connection.execute(
                "SELECT DISTINCT p.permission FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN membership_roles mr ON mr.role_id = rp.role_id "
                "WHERE mr.user_id = ? AND mr.tenant_id = ? ORDER BY p.permission",
                (user_id, tenant_id),
            ).fetchall()]
            return {
                "user_id": user["id"],
                "email": user["email"],
                "tenant_id": tenant_id,
                "roles": roles,
                "permissions": permissions,
            }

    def list_tenants(self, user_id: str) -> list[dict[str, object]]:
        with self.lock:
            return [dict(row) for row in self.connection.execute(
                "SELECT t.* FROM tenants t JOIN memberships m ON m.tenant_id = t.id "
                "WHERE m.user_id = ? ORDER BY t.id",
                (user_id,),
            ).fetchall()]


class LocalAuthProvider:
    """Identidad local determinista; no es un mecanismo para producción."""

    name = "local"

    def __init__(self, password: str = "demo1234", db_path: str | Path | None = None) -> None:
        self.store = LocalIdentityStore(db_path or os.getenv("LOCAL_AUTH_DB", "data/local-auth.sqlite3"))
        self.store.seed(self._hash_password(password))

    @staticmethod
    def _hash_password(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def login(self, email: str, password: str, tenant_id: str | None = None) -> dict[str, object]:
        user = self.store.user_by_email(email)
        if user is None or not hmac.compare_digest(user["password_hash"], self._hash_password(password)):
            raise LocalAuthError("credenciales no válidas")
        resolved_tenant_id = tenant_id or "TEN-001"
        if tenant_id and not self.store.identity(user["id"], tenant_id):
            raise LocalAuthError("el usuario no pertenece a ese tenant")
        identity = self.store.identity(user["id"], resolved_tenant_id)
        return {
            "access_token": f"local.{user['id']}.{resolved_tenant_id}",
            "token_type": "Bearer",
            "provider": self.name,
            "user": identity,
        }

    def authenticate(self, token: str) -> AuthIdentity | None:
        parts = token.strip().split(".")
        if len(parts) != 3 or parts[0] != "local":
            return None
        return self.store.identity(parts[1], parts[2])

    def list_tenants(self, user_id: str) -> list[dict[str, object]]:
        return self.store.list_tenants(user_id)


def has_permission(identity: AuthIdentity | None, permission: str) -> bool:
    if not identity:
        return False
    return "*" in identity["permissions"] or permission in identity["permissions"]
