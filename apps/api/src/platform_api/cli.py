"""Служебные команды платформы.

Первая учётная запись заводится отсюда, а не через открытый эндпоинт
регистрации. Регистрация в такой системе не нужна вовсе: людей в тендерном
отделе несколько, они известны поимённо, а открытая форма — это приглашение
завести себе доступ к чужим закупкам.
"""

from __future__ import annotations

import getpass
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from platform_api.auth import passwords
from platform_api.config import get_settings
from platform_api.db.models import Membership, Organization, Role, User
from platform_api.db.session import create_db_engine, create_session_factory, session_scope

app = typer.Typer(help="Служебные команды платформы", no_args_is_help=True)


def _factory() -> sessionmaker[DbSession]:
    settings = get_settings()
    return create_session_factory(create_db_engine(settings.db))


@app.command("create-user")
def create_user(
    email: Annotated[str, typer.Option("--email", prompt="Почта")],
    organization: Annotated[
        str, typer.Option("--org", help="Ключ организации", prompt="Организация (ключ)")
    ],
    role: Annotated[Role, typer.Option("--role", help="Роль в организации")] = Role.ADMIN,
    full_name: Annotated[str, typer.Option("--name", help="Имя и фамилия")] = "",
    organization_name: Annotated[
        str, typer.Option("--org-name", help="Название организации, если её ещё нет")
    ] = "",
) -> None:
    """Завести человека и, при необходимости, организацию."""
    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Пароль ещё раз: "):
        typer.secho("Пароли не совпали", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        passwords.validate_password(password)
    except passwords.WeakPasswordError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    with session_scope(_factory()) as db:
        org = db.scalars(
            select(Organization).where(Organization.slug == organization)
        ).one_or_none()
        if org is None:
            org = Organization(slug=organization, name=organization_name or organization)
            db.add(org)
            db.flush()
            typer.secho(f"Организация создана: {org.name}", fg=typer.colors.GREEN)

        user = db.scalars(select(User).where(User.email == email.lower())).one_or_none()
        if user is None:
            user = User(
                email=email.strip().lower(),
                full_name=full_name,
                password_hash=passwords.hash_password(password),
            )
            db.add(user)
            db.flush()
        else:
            typer.secho("Пользователь уже есть — обновляю пароль", fg=typer.colors.YELLOW)
            user.password_hash = passwords.hash_password(password)

        existing = db.scalars(
            select(Membership).where(
                Membership.user_id == user.id, Membership.organization_id == org.id
            )
        ).one_or_none()
        if existing is None:
            db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
        else:
            existing.role = role

        typer.secho(
            f"Готово: {user.email} в «{org.name}» с ролью {role.value}",
            fg=typer.colors.GREEN,
        )


@app.command("list-users")
def list_users() -> None:
    """Кто заведён и с какими правами."""
    with session_scope(_factory()) as db:
        rows = db.scalars(select(Membership).join(User).order_by(User.email)).all()
        if not rows:
            typer.secho("Ни одной учётной записи", fg=typer.colors.YELLOW)
            return
        for membership in rows:
            mark = "" if membership.user.is_active else "  (отключён)"
            typer.echo(
                f"  {membership.user.email:<32} {membership.organization.slug:<16} "
                f"{membership.role.value}{mark}"
            )


@app.command("reset-password")
def reset_password(email: Annotated[str, typer.Option("--email", prompt="Почта")]) -> None:
    """Сменить пароль и погасить все сессии.

    Сессии гасятся обязательно: смена пароля обычно означает, что доступ мог
    утечь, а действующая сессия переживает смену пароля и оставляет чужому
    вход открытым.
    """
    from platform_api.auth.service import revoke_all_sessions

    password = getpass.getpass("Новый пароль: ")
    try:
        passwords.validate_password(password)
    except passwords.WeakPasswordError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    with session_scope(_factory()) as db:
        user = db.scalars(select(User).where(User.email == email.lower())).one_or_none()
        if user is None:
            typer.secho("Нет такой учётной записи", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        user.password_hash = passwords.hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        revoked = revoke_all_sessions(db, user.id)
        typer.secho(f"Пароль изменён, сессий погашено: {revoked}", fg=typer.colors.GREEN)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
