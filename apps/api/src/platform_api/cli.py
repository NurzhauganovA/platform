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

        # Сразу в сервис уведомлений, а не при следующем запуске API.
        #
        # Реестр людей сервис получает от платформы: при старте — списком, при
        # правке сотрудника — по одному. Заведённый командой оставался между
        # этими двумя случаями, и выяснялось это молча: человек писал боту
        # почту, бот отвечал «если такая почта заведена, код отправлен» —
        # ответ намеренно одинаков для известного и неизвестного адреса, иначе
        # по нему проверяют, кто у нас работает, — и код не приходил никогда.
        _tell_notify(user, role.value)


def _tell_notify(user: User, role: str) -> None:
    """Заводит человека в сервисе уведомлений. Молчит, если сервиса нет.

    Отсутствие сервиса — рабочее состояние: у разработчика он обычно не поднят,
    а учётную запись завести надо. Отказ же стоит сказать вслух: команду
    набирают руками и смотрят на ответ, а починка сводится к одной строке в
    `.env`.
    """
    from platform_api.modules import notify

    settings = get_settings()
    if not settings.notify.ready:
        typer.secho(
            "Сервис уведомлений не настроен — в бот этот человек не попадёт",
            fg=typer.colors.YELLOW,
        )
        return

    notify.enroll(
        settings,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role,
        is_active=user.is_active,
    )
    typer.secho("Отдан сервису уведомлений: боту он теперь известен", fg=typer.colors.GREEN)


@app.command("notify-doctor")
def notify_doctor(
    email: Annotated[str, typer.Option("--email", help="Кому проверить доставку")] = "",
    send: Annotated[bool, typer.Option("--send", help="Отправить проверочное сообщение")] = False,
) -> None:
    """Проходит цепочку уведомлений и говорит, где она рвётся.

    Нужна затем, что каждое звено молчит по-своему. Платформа не бросает
    наружу отказ сервиса — уведомление важно, но открытая страница важнее, —
    поэтому «не пришло» выглядит одинаково во всех случаях: сервис не поднят,
    порт виден только своей машине, ключи разошлись, человек не привязал
    Телеграм, письмо не ушло. Разбирать это по журналам трёх наборов
    контейнеров — полчаса, и половину из них уходит на выяснение, какой из них
    вообще смотреть.

    Запускать **изнутри контейнера платформы** (`make notify-check`): проверять
    надо ту сеть и те настройки, которыми ходит сама платформа. С машины адрес
    сервиса другой, и проверка с неё отвечает на вопрос, которого никто не
    задавал.
    """
    import httpx

    settings = get_settings()

    typer.echo("1. Настройки платформы")
    if not settings.notify.url.strip():
        typer.echo("   ✗ PLATFORM__NOTIFY__URL пуст — уведомления выключены совсем.")
        raise typer.Exit(code=1)
    typer.echo(f"   адрес: {settings.notify.url}")
    if not settings.notify.token.strip():
        typer.echo("   ✗ PLATFORM__NOTIFY__TOKEN пуст: сервис ответит отказом на всё.")
        raise typer.Exit(code=1)
    typer.echo(f"   ключ:  задан, {len(settings.notify.token)} знаков")

    base = settings.notify.url.rstrip("/")
    head = {"X-Service-Token": settings.notify.token}

    typer.echo("\n2. Сервис отвечает")
    try:
        alive = httpx.get(f"{base}/api/health", timeout=settings.notify.timeout_seconds)
    except httpx.HTTPError as exc:
        typer.echo(f"   ✗ не достучались: {exc}")
        typer.echo("     Сервис не поднят, либо его порт виден только самой машине.")
        typer.echo("     На Linux `host.docker.internal` ведёт на 172.17.0.1, а порт")
        typer.echo("     сервиса опубликован на 127.0.0.1 — из контейнера туда хода нет.")
        typer.echo("     Проверьте на сервере: docker ps | grep notify")
        typer.echo("     и в .env уведомлений: API_BIND=172.17.0.1, затем make up-server.")
        raise typer.Exit(code=1) from exc
    if alive.status_code != 200:
        typer.echo(f"   ✗ ответил {alive.status_code}: {alive.text[:200]}")
        raise typer.Exit(code=1)
    said = alive.json()
    typer.echo(f"   ✓ отвечает, окружение {said.get('environment', '?')}")
    typer.echo(f"     Телеграм: {'настроен' if said.get('telegram') else 'НЕТ КЛЮЧА'}")
    typer.echo(f"     почта:    {'настроена' if said.get('email') else 'НЕ НАСТРОЕНА'}")
    for trouble in said.get("problems", []):
        typer.echo(f"     ! {trouble}")

    typer.echo("\n3. Служебный ключ принят")
    try:
        counted = httpx.get(f"{base}/api/stats", headers=head, timeout=5.0)
    except httpx.HTTPError as exc:
        typer.echo(f"   ✗ не достучались: {exc}")
        raise typer.Exit(code=1) from exc
    if counted.status_code in (401, 403):
        typer.echo(
            "   ✗ сервис ключ не принял: PLATFORM__NOTIFY__TOKEN и NOTIFY__API__TOKEN разошлись."
        )
        raise typer.Exit(code=1)
    if counted.status_code >= 500:
        # Отдельная ветка: тут сервис жив, а сломано у него внутри — чаще всего
        # база. Его собственная проверка готовности этого не покажет: она
        # смотрит настройки каналов, а не базу, и отвечает «всё на месте» с
        # недоступным PostgreSQL. Поэтому спрашивается именно сводка рассылки —
        # она без базы не собирается.
        typer.echo(f"   ✗ сервис ответил {counted.status_code}: у него сломано что-то своё.")
        typer.echo("     Чаще всего база: journal смотреть у него —")
        typer.echo("     cd ../notification && make logs")
        raise typer.Exit(code=1)
    if counted.status_code != 200:
        typer.echo(f"   ✗ ответил {counted.status_code}: {counted.text[:200]}")
        raise typer.Exit(code=1)
    numbers = counted.json()
    typer.echo("   ✓ ключ принят")
    typer.echo(
        f"     людей в реестре: {numbers.get('recipients', '?')}, "
        f"работающих: {numbers.get('active', '?')}, "
        f"с Телеграмом: {numbers.get('telegram_linked', '?')}"
    )
    typer.echo(
        f"     за сутки: отправлено {numbers.get('sent_24h', '?')}, "
        f"не дошло {numbers.get('failed_24h', '?')}, "
        f"пропущено {numbers.get('skipped_24h', '?')}"
    )
    typer.echo(
        f"     сейчас: в очереди {numbers.get('pending', '?')}, "
        f"отправляется {numbers.get('sending', '?')}"
    )

    if not email:
        typer.echo("\nДальше — про конкретного человека: повторите с --email почта@fintend.kz")
        return

    typer.echo(f"\n4. Человек {email}")
    with session_scope(_factory()) as db:
        user = db.scalars(select(User).where(User.email == email.strip().lower())).one_or_none()
        if user is None:
            typer.echo("   ✗ такого сотрудника нет в базе платформы. make user заводит его.")
            raise typer.Exit(code=1)
        user_id = str(user.id)
    typer.echo(f"   id: {user_id}")

    known = httpx.get(f"{base}/api/recipients/{user_id}", headers=head, timeout=5.0)
    if known.status_code == 404:
        typer.echo("   ✗ сервис такого получателя не знает.")
        typer.echo("     Реестр выгружается при запуске платформы: make prod поднимет заново.")
        raise typer.Exit(code=1)
    if known.status_code != 200:
        typer.echo(f"   ✗ ответил {known.status_code}: {known.text[:200]}")
        raise typer.Exit(code=1)
    who = known.json()
    tg = who.get("telegram") or {}
    linked = bool(tg.get("linked"))
    typer.echo(f"   ✓ в реестре: {who.get('full_name') or '(без имени)'}")
    typer.echo(
        f"     Телеграм: {'привязан' if linked else 'НЕ ПРИВЯЗАН'}"
        + (f" ({tg.get('username') or tg.get('display_name')})" if linked else "")
    )
    if tg.get("stop_reason"):
        typer.echo(f"     ! бот остановлен человеком: {tg['stop_reason']}")
    typer.echo(
        f"     каналы: телеграм {'вкл' if who.get('telegram_enabled') else 'ВЫКЛ'}, "
        f"почта {'вкл' if who.get('email_enabled') else 'ВЫКЛ'}"
    )
    if not who.get("is_active", True):
        typer.echo("     ! сотрудник помечен неработающим — рассылка его пропускает")
    if not linked:
        typer.echo("     Привязка: напишите боту /start и введите эту почту.")

    typer.echo("\n5. Чем кончились последние отправки")
    # Самое полезное место во всей проверке. Причина, по которой сообщение не
    # ушло, лежит именно здесь — у доставки, а не у уведомления: «Телеграм не
    # привязан», «тихие часы», отказ почтового сервера словами. Ни платформа,
    # ни журнал сервиса этого не покажут так коротко: платформа отказа не
    # видит вовсе, а в журнале причина утонет между строк рассылки.
    history = httpx.get(
        f"{base}/api/notifications",
        headers=head,
        params={"user_id": user_id, "limit": 5},
        timeout=5.0,
    )
    if history.status_code != 200:
        typer.echo(f"   ! историю посмотреть не вышло: {history.status_code}")
    else:
        rows = history.json()
        if not rows:
            typer.echo("   пусто: этому человеку платформа ещё ничего не ставила.")
            typer.echo("     Значит, дело не в рассылке — события до сервиса не доходят.")
        for row in rows:
            typer.echo(
                f"   · {row.get('created_at', '')[:16]} {row.get('event') or row.get('title')}"
            )
            for way in row.get("deliveries", []):
                trouble = f" — {way['error']}" if way.get("error") else ""
                typer.echo(f"     {way.get('channel')}: {way.get('status')}{trouble}")

    if not send:
        typer.echo("\nОтправить проверочное сообщение: повторите с --send")
        return

    typer.echo("\n6. Проверочное сообщение")
    sent = httpx.post(f"{base}/api/recipients/{user_id}/test", headers=head, timeout=10.0)
    if sent.status_code >= 400:
        typer.echo(f"   ✗ сервис отказал {sent.status_code}: {sent.text[:300]}")
        raise typer.Exit(code=1)
    typer.echo("   ✓ поставлено в очередь сервиса.")
    typer.echo("     Не пришло за минуту — смотрите журнал сервиса: make logs в notification.")
    typer.echo("     Там будет видно, отказал Телеграм или почтовый сервер.")


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
