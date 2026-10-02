"""Contratos de proveedores del pipeline.

Las implementaciones locales se usan durante la primera fase. Cada contrato está
deliberadamente desacoplado de AWS, del ERP concreto y del proveedor de IA para
que los sustituyamos sin modificar el dominio ni el frontend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypedDict


class QualityReport(TypedDict, total=False):
    status: str
    score: float
    decision: str
    metrics: dict[str, float | int | str]
    reasons: list[str]
    warnings: list[str]
    blocking_reasons: list[str]
    provider: str


class ObjectStore(Protocol):
    root: Path

    def put(self, key: str, content: bytes) -> str: ...

    def put_json(self, key: str, payload: dict[str, object]) -> str: ...


class DocumentQualityAnalyzer(Protocol):
    name: str

    def analyze(self, content: bytes, content_type: str, filename: str) -> QualityReport: ...


class DocumentConnector(Protocol):
    name: str

    def health(self) -> dict[str, object]: ...

    def import_document(self, document_type: str, payload: dict[str, object]) -> dict[str, object]: ...


class AuthIdentity(TypedDict):
    user_id: str
    email: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]


class AuthProvider(Protocol):
    name: str

    def authenticate(self, token: str) -> AuthIdentity | None: ...

    def login(self, email: str, password: str, tenant_id: str | None = None) -> dict[str, object]: ...
