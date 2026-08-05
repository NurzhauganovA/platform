"""Вход и права."""

from __future__ import annotations

from platform_api.auth.dependencies import (
    CurrentUser,
    Db,
    require_roles,
    requires_admin,
    requires_money,
    requires_read,
    requires_sourcing,
)
from platform_api.auth.service import AuthError, Identity

__all__ = [
    "AuthError",
    "CurrentUser",
    "Db",
    "Identity",
    "require_roles",
    "requires_admin",
    "requires_money",
    "requires_read",
    "requires_sourcing",
]
