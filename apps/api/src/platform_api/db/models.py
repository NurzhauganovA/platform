"""Таблицы каркаса платформы.

Здесь только общее: кто работает, в какой организации, с какими правами, что
загружено и какие задачи выполняются. Предметных таблиц — закупок, документов,
цен — тут нет и быть не должно: они живут в базах своих проектов.

Организация введена сразу, хотя пока она одна. Добавить её потом означает
пройтись по каждому запросу и каждому индексу в системе, где уже лежат чужие
коммерческие данные, и один пропущенный запрос показывает одному заказчику
закупки другого.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform_api.db.base import Base, Timestamps, UUIDPrimaryKey


class Role(StrEnum):
    """Кто что видит.

    Разделение уже существует в документах, которые проект выпускает: КП для
    заказчика собирается без себестоимости, задание закупщику — с ней. В вебе
    эта же граница проходит по правам, иначе она держится только на том, что
    человек не открыл соседнюю страницу.
    """

    ADMIN = "admin"
    """Настройки, ключи, реквизиты компаний, управление людьми."""

    ANALYST = "analyst"
    """Тендерщик: закупки, разбор, себестоимость, маржа, наши КП."""

    BUYER = "buyer"
    """Закупщик: задание, поставщики, целевая цена закупа и статусы.
    Нашей отпускной цены и маржи не видит — ему они для работы не нужны,
    а утечь могут вместе с ним."""

    MANAGER = "manager"
    """Менеджер поставки: ведёт лот от объявления до оплаты.

    Он же госзакупщик. Отдельно от тендерщика (`analyst`), потому что делают
    они разное: тендерщик считает, участвовать ли, менеджер отвечает за то,
    чтобы участие состоялось и договор закрылся.
    """

    TECHNOLOGIST = "technologist"
    """Технолог: подтверждает, что товар подходит под требования."""

    ASSEMBLER = "assembler"
    """Сборщик: подтверждает, что заказ соберут и отгрузят в срок."""

    HEAD = "head"
    """Руководитель. Решает, участвуем ли, когда цифры спорные."""

    COMMERCIAL = "commercial"
    """Коммерческий директор. Второй голос в том же решении."""

    LAWYER = "lawyer"
    """Юрист: замечания к спецификациям и жалобы.

    Отдельная роль, а не тендерщик с правом правки. Юрист приходит в
    замечание, когда заказчик отказал и разговор переходит на язык норм; всё
    остальное в платформе — цены и себестоимость — ему для этого не нужно и
    видеть их он не должен.
    """

    VIEWER = "viewer"
    """Только чтение отчётов."""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Organization(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")

    password_hash: Mapped[str] = mapped_column(Text)
    """Argon2id. Пароль в открытом виде не хранится и не логируется нигде."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    failed_logins: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    """Защита от подбора пароля. Без неё форма входа — открытый перебор по
    словарю, а за ней лежат коммерческие данные и ключи к платным моделям."""

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        from platform_api.db.base import utcnow

        return self.locked_until is not None and self.locked_until > utcnow()


class PasswordReset(Base, UUIDPrimaryKey, Timestamps):
    """Код для сброса пароля: короткий, одноразовый, с быстрым сроком.

    Хранится отпечатком, как и пароль. Утечка базы иначе означала бы, что
    любой действующий код читается глазами, а за ним — вход под чужой учётной
    записью со всеми ценами и ключами к платным моделям.

    Число попыток считается здесь, а не в памяти процесса: процессов бывает
    два, и счётчик в памяти обнуляется выкладкой — то есть тогда, когда его
    как раз и обходят.

    Куда код ушёл, записано (`channel`). Человек звонит и говорит «код не
    пришёл»: без этой отметки нельзя отличить «ушёл в Телеграм, а он его не
    открывал» от «почта не настроена и не ушёл никуда».
    """

    __tablename__ = "password_resets"
    __table_args__ = (Index("password_reset_user", "user_id", "used_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    code_hash: Mapped[str] = mapped_column(Text)
    """Отпечаток кода. Сам код живёт только в письме и в Телеграме."""

    channel: Mapped[str] = mapped_column(String(16), default="")
    """Куда ушёл: `telegram` или `email`. Пусто — не ушёл никуда."""

    expires_at: Mapped[datetime] = mapped_column()
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Membership(Base, UUIDPrimaryKey, Timestamps):
    """Человек в организации и его роль."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="user_organization"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=32))

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Session(Base, UUIDPrimaryKey, Timestamps):
    """Вход, живущий в httpOnly-куке.

    В куке лежит только идентификатор — сама сессия здесь, и поэтому её можно
    отозвать. Токен, который нельзя погасить со стороны сервера, означает, что
    уволившийся сотрудник ходит в систему до истечения срока.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """Хэш от значения из куки, а не само значение: утёкшая копия базы не
    должна давать вход."""

    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user_agent: Mapped[str] = mapped_column(String(512), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship()

    @property
    def is_valid(self) -> bool:
        from platform_api.db.base import utcnow

        return self.revoked_at is None and self.expires_at > utcnow()


class StoredFile(Base, UUIDPrimaryKey, Timestamps):
    """Загруженный файл.

    Ключ — sha256 содержимого, как и в кэше разбора: один и тот же документ в
    трёх закупках хранится один раз. В тендерных папках дубликаты не
    исключение, а норма — там же встречается один образец МЗ, разложенный по
    пяти папкам заказчиков.
    """

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256", name="organization_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(255), default="")
    original_name: Mapped[str] = mapped_column(String(512), default="")

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Job(Base, UUIDPrimaryKey, Timestamps):
    """Фоновая задача.

    Разбор идёт минутами и стоит денег, поэтому живёт в очереди, а не в
    обработчике запроса. Состояние хранится в базе, а не только в Redis:
    человек должен увидеть, чем закончился вчерашний прогон и сколько он
    стоил, даже если очередь с тех пор перезапускали.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    module: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
        index=True,
    )

    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    progress_done: Mapped[int] = mapped_column(default=0, server_default="0")
    progress_total: Mapped[int] = mapped_column(default=0, server_default="0")
    progress_note: Mapped[str] = mapped_column(String(512), default="")

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    """Во сколько обошёлся прогон. Хранится вместе с задачей: вопрос «сколько
    мы потратили на разбор» задаётся всегда и обычно задним числом."""


class AuditEntry(Base, UUIDPrimaryKey):
    """Кто что сделал.

    Пишется по действиям, меняющим деньги и доступ: вход, выдача роли, запуск
    платного разбора, выпуск КП. Не для отчётности — для ответа на вопрос
    «кто отправил заказчику это предложение», который однажды будет задан.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(index=True)


class WorkStage(StrEnum):
    """У кого сейчас лот, взятый в работу.

    Не «статус задачи», а именно «у кого на столе»: процесс идёт между двумя
    отделами, и главный вопрос по любому лоту — чьего хода ждут.
    """

    ANALYSIS = "analysis"
    """У отдела разбора: выбирает поставщиков, отмечает, что искать снабжению."""

    SUPPLY = "supply"
    """У снабжения: проверяет цены и ссылки, ищет то, чего не нашли, ставит
    сроки поставки."""

    RETURNED = "returned"
    """Снабжение вернуло разбору: цены подтверждены, можно готовить КП."""


class OptionSource(StrEnum):
    """Откуда взялся вариант закупки. По нему видно, чьё это суждение."""

    FOUND = "found"
    """Нашла модель при разборе — цена с площадки, требует проверки."""

    ASKED = "asked"
    """Разбор попросил снабжение найти: есть только название товара."""

    SUPPLY = "supply"
    """Добавило снабжение — то, что оно нашло само."""


class TenderWork(Base, UUIDPrimaryKey, Timestamps):
    """Лот, взятый в работу: сквозной процесс между отделами.

    Отдельно от лота, а не полем в нём. Лот — это связь позиций в отборе, её
    пересобирают и распускают; работа — событие с историей, и терять её вместе
    с изменением состава нельзя.

    Позиции переписываются в работу целиком, а не ссылкой. Отбор
    пересобирается при каждом разборе, названия у позиций меняются — а работа
    должна остаться той же, с теми же позициями, по которым её и взяли.
    """

    __tablename__ = "tender_works"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    code: Mapped[str] = mapped_column(String(32), index=True)
    """Код работы: «TN-00042» открытой позиции. По нему её и зовут."""

    title: Mapped[str] = mapped_column(String(512))
    customer: Mapped[str] = mapped_column(String(255), default="")

    stage: Mapped[WorkStage] = mapped_column(
        Enum(WorkStage, native_enum=False, length=16), default=WorkStage.ANALYSIS, index=True
    )

    analysis_note: Mapped[str] = mapped_column(Text, default="")
    """Что разбор просит у снабжения — словами, помимо самих позиций."""

    supply_note: Mapped[str] = mapped_column(Text, default="")
    """Что снабжение отвечает разбору."""

    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    """Когда лот ушёл другому отделу. По нему видно, сколько он лежит."""

    positions: Mapped[list[TenderWorkPosition]] = relationship(
        back_populates="work", cascade="all, delete-orphan", lazy="selectin"
    )


class TenderWorkPosition(Base, UUIDPrimaryKey, Timestamps):
    """Позиция в работе — то, что придётся поставить."""

    __tablename__ = "tender_work_positions"

    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_works.id", ondelete="CASCADE"), index=True
    )

    folder_path: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    code: Mapped[str] = mapped_column(String(32), default="")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    """Сумма закупки по позиции — то, с чем сравнивают себестоимость."""

    ordering: Mapped[int] = mapped_column(Integer, default=0)

    spec: Mapped[str] = mapped_column(Text, default="", server_default="")
    """Техническое задание позиции — то единственное, что видит снабжение.

    Лежит в самой работе, а не собирается на каждый показ. Черновик пишется
    при взятии в работу, дальше его правит разбор, и переданное снабжению
    задание не должно меняться от того, что папку разобрали заново.
    """

    spec_source: Mapped[str] = mapped_column(String(512), default="", server_default="")
    """Из какого документа собран черновик. Спорное требование нужно уметь
    проверить — разбору исходный документ по-прежнему открыт."""

    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    """Заметка снабжения по позиции: одна строка при выборе поставщика.

    Короткая намеренно. Комментарий на весь лот отвечает на «как прошло», а
    объяснять приходится позицию: почему взяли дороже, почему ждать месяц.
    Записанное в общий комментарий это теряется, а не записанное — забывается
    к следующему разговору с разбором.
    """

    options: Mapped[list[TenderWorkOption]] = relationship(
        back_populates="position", cascade="all, delete-orphan", lazy="selectin"
    )
    work: Mapped[TenderWork] = relationship(back_populates="positions")


class TenderWorkOption(Base, UUIDPrimaryKey, Timestamps):
    """Где купить эту позицию — один вариант.

    Отобранные разбором находки, его же заявки «найдите вот это» и то, что
    добавило снабжение, — всё это варианты. Различает их `source`: по нему
    видно, чьё это суждение и насколько ему верить.
    """

    __tablename__ = "tender_work_options"

    position_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_work_positions.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[OptionSource] = mapped_column(Enum(OptionSource, native_enum=False, length=16))

    name: Mapped[str] = mapped_column(String(512), default="")
    """Что именно покупаем. У заявки снабжению это единственное заполненное
    поле: остальное они и должны выяснить."""

    supplier: Mapped[str] = mapped_column(String(255), default="")
    marketplace: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(String(2048), default="")
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Через сколько дней товар у нас. Заполняет снабжение — до него этого
    никто не знает, а от срока зависит, беремся ли мы вообще."""

    note: Mapped[str] = mapped_column(Text, default="")

    chosen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    """Разбор подтвердил этот вариант.

    Снабжению это главный признак: подтверждённого поставщика проверяют, а не
    ищут заново. Без отметки оба отдела делают одну и ту же работу дважды.
    """

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    position: Mapped[TenderWorkPosition] = relationship(back_populates="options")


class DiscussionStage(StrEnum):
    """Где обсуждение в нашей работе.

    Это наш ход, а не портала: что портал ответил, живёт в `outcome`. Смешать
    их в одно поле — значит однажды не суметь ответить на вопрос «мы уже
    отправили или ещё пишем», когда заказчик молчит третий день.
    """

    DRAFTING = "drafting"
    """Замечание пишется: лот в очереди у модели или она уже работает."""

    MODERATION = "moderation"
    """Написано моделью, ждёт менеджера. Ни одно замечание не уходит наружу
    непрочитанным: его читает заказчик, и цена небрежности — отказ."""

    WITH_LAWYERS = "lawyers"
    """Менеджер проверил, передал юристам. Отправляют официально они."""

    SENT = "sent"
    """Юристы отправили через портал или eOtinish. Дальше ждём ответа."""

    NOT_NEEDED = "not_needed"
    """Обсуждать нечего: требования не мешают предложить наше оборудование.

    Отдельным состоянием, а не удалением: «мы это смотрели и решили не
    трогать» и «до этого лота руки не дошли» — разные ответы, и на второй
    приходится смотреть заново.
    """


class DiscussionOutcome(StrEnum):
    """Чем кончилось на стороне заказчика."""

    WAITING = "waiting"
    """Отправлено, ответа нет. Проверяется по расписанию."""

    ACCEPTED = "accepted"
    """Преграду убрали: заказчик изменил документацию."""

    REJECTED = "rejected"
    """Отклонили с обоснованием. Дальше либо закрываем, либо жалоба."""

    CLOSED = "closed"
    """Закрыли после отказа: спорить дальше не стоит."""

    COMPLAINT = "complaint"
    """Ушло юристам на жалобу."""


class DiscussionWriting(StrEnum):
    """Как идёт написание моделью. Видно в списке, пока идёт прогон."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class Discussion(Base, UUIDPrimaryKey, Timestamps):
    """Замечание к конкурсной документации закупки.

    Не переписка и не заметка. Это официальное обращение к заказчику: до
    участия мы проверяем документацию и техническую спецификацию и указываем
    на требования, которые необоснованно сужают круг участников и не дают
    предложить наше оборудование. По закону на предварительное обсуждение
    даётся два рабочих дня со дня размещения объявления — отсюда и срок, и
    спешка.

    Одно обсуждение на лот. Заводится по площадкам закупок и **не касается
    тендерного отбора**: туда закупки приходят папкой по почте, обсуждать их
    не с кем и незачем.

    Версия модели и версия менеджера хранятся рядом. Менеджер правит текст
    перед отправкой, и через месяц при разборе отказа нужно понимать, что
    именно ушло заказчику и чем оно отличалось от написанного моделью.
    """

    __tablename__ = "discussions"
    __table_args__ = (
        UniqueConstraint("module", "row_id", name="discussion_on_row"),
        Index("discussion_stage", "module", "stage"),
        Index("discussion_deadline", "deadline"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    module: Mapped[str] = mapped_column(String(32))
    row_id: Mapped[str] = mapped_column(String(128))
    """Устойчивое имя строки: то же, чем её опознаёт список и код «GZ000001»."""

    code: Mapped[str] = mapped_column(String(32), default="")
    """Код строки на момент заведения — им обсуждение и называют вслух."""

    # Снимок закупки на момент заведения. Копией, а не ссылкой в базу
    # площадки: список пересобирается при каждой выгрузке, а обсуждение должно
    # остаться тем же, по которому его завели.
    title: Mapped[str] = mapped_column(Text, default="")
    customer: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    enstru_code: Mapped[str] = mapped_column(String(32), default="", index=True)

    category: Mapped[str] = mapped_column(String(128), default="", index=True)
    """Категория товара. По ней делят работу между людьми: «компьютеры» и
    «серверы» у нас ведут разные менеджеры, и общий список из четырёхсот
    обсуждений каждому из них наполовину чужой."""

    deadline: Mapped[datetime | None] = mapped_column(nullable=True)
    """Срок окончания обсуждения с портала. По нему считается остаток времени
    и по нему же сортируется очередь менеджера: два рабочих дня проходят
    быстро, и пропущенный срок закрывает вопрос совсем."""

    stage: Mapped[DiscussionStage] = mapped_column(
        Enum(DiscussionStage, native_enum=False, length=16),
        default=DiscussionStage.DRAFTING,
        index=True,
    )
    outcome: Mapped[DiscussionOutcome] = mapped_column(
        Enum(DiscussionOutcome, native_enum=False, length=16),
        default=DiscussionOutcome.WAITING,
    )
    writing: Mapped[DiscussionWriting] = mapped_column(
        Enum(DiscussionWriting, native_enum=False, length=16),
        default=DiscussionWriting.QUEUED,
    )
    trouble: Mapped[str] = mapped_column(Text, default="")
    """Почему написать не удалось. Пустой текст без причины выглядит как
    недоделка платформы, а не как отказ модели."""

    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """Ответственный менеджер. Пусто — обсуждение ничьё, и это видно в списке:
    ничьё горящее обсуждение и есть то, что теряется."""

    ai_text: Mapped[str] = mapped_column(Text, default="")
    ai_model: Mapped[str] = mapped_column(String(64), default="")
    ai_written_at: Mapped[datetime | None] = mapped_column(nullable=True)
    """Что написала модель. Не переписывается правкой менеджера: сравнить
    отправленное с исходным нужно ровно тогда, когда пришёл отказ."""

    text: Mapped[str] = mapped_column(Text, default="")
    """Что уходит заказчику. Сначала копия текста модели, дальше — правка
    менеджера."""

    edited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    """Ответ заказчика как есть. По нему решают, закрывать или жаловаться."""


class DiscussionMessage(Base, UUIDPrimaryKey, Timestamps):
    """Сообщение обсуждения по строке рабочего списка.

    Обсуждение идёт до разбора и вместо переписки. Решение «берём или нет»
    редко принимает один человек: тендерщик видит цену, снабженец знает, что
    этого поставщика ждали три месяца, а руководитель помнит, чем кончилась
    прошлая закупка у этого заказчика. Сейчас это живёт в мессенджере, и через
    неделю никто не вспомнит, почему прошли мимо.

    Общее для всех разделов, а не только для госзакупок. Ключ тот же, что у
    кода строки: раздел плюс её устойчивое имя. Заводить своё обсуждение в
    каждом модуле значило бы четыре одинаковых таблицы и четыре набора правил
    о том, кто что может править.

    Строка живёт своей жизнью: отбор пересобирается, лоты перевыгружаются.
    Привязка к устойчивому имени строки, а не к записи в базе ядра, — иначе
    обсуждение исчезало бы при каждом обновлении.
    """

    __tablename__ = "discussion_messages"
    __table_args__ = (Index("discussion_module_row", "module", "row_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    module: Mapped[str] = mapped_column(String(32))
    row_id: Mapped[str] = mapped_column(String(128))
    """Устойчивое имя строки: номер закупки у госзакупок, имя строки у отбора."""

    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(nullable=True)
    """Когда сообщение правили. Показывается рядом с ним: молча изменённый
    текст в общей ветке — это спор о том, кто что сказал."""


class WorklistCode(Base, UUIDPrimaryKey, Timestamps):
    """Постоянный код строки рабочего списка: «TN-00042».

    Порядковый номер для этого не годится. Он считается по списку, а список
    пересобирается: появилась одна закупка — и всё, что ниже, сдвинулось на
    единицу. Сотрудник говорит «посмотри сорок вторую», а у собеседника это
    уже другая строка.

    Код выдаётся один раз и остаётся при позиции. Приставка своя у каждого
    раздела — впереди площадки Mitwork и госзакупки, и «сорок второй» без
    приставки будет в каждой из них.

    Ключ — то же, чем платформа опознаёт строку: папка, название и код ЕНС.
    Переименует заказчик позицию — код сменится, и это честно: это уже другая
    позиция, а не та же под новым именем.
    """

    __tablename__ = "worklist_codes"
    __table_args__ = (
        UniqueConstraint("module", "row_key", name="module_row"),
        UniqueConstraint("module", "number", name="module_number"),
    )

    module: Mapped[str] = mapped_column(String(32), index=True)
    row_key: Mapped[str] = mapped_column(String(64))
    number: Mapped[int] = mapped_column(Integer)


class TenderLot(Base, UUIDPrimaryKey, Timestamps):
    """Закупка, которую ведут целиком, а не позициями по отдельности.

    Решение человека, а не свойство данных. В заключении заказчика позиций
    бывает три. По одной из них заработок выглядит отличным, её берут в
    работу — и там выясняется, что поставить придётся все три, а на остальных
    двух убыток. В сумме сделка убыточна, и увидеть это надо до подачи.

    Из данных лот не вывести. Позиции одного заключения иногда разыгрываются
    порознь, а бывает и наоборот: заказчик разложил один лот по двум папкам, и
    ни один признак в документах об этом не говорит.
    """

    __tablename__ = "tender_lots"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    positions: Mapped[list[TenderLotPosition]] = relationship(
        back_populates="lot", cascade="all, delete-orphan", lazy="selectin"
    )


class TenderLotPosition(Base, UUIDPrimaryKey, Timestamps):
    """Позиция в составе лота.

    Хранится папкой и названием, а не идентификатором строки: тот считается
    от них же и меняется с каждым новым разбором, и после перезапуска ядра
    лот распался бы на пустые ссылки.

    Одна позиция — не больше чем в одном лоте организации: два лота с общей
    позицией дают два разных итога по одной и той же поставке, и какой из них
    правда, потом не выяснить.
    """

    __tablename__ = "tender_lot_positions"
    __table_args__ = (
        UniqueConstraint("organization_id", "folder_path", "title", name="organization_position"),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_lots.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    folder_path: Mapped[str] = mapped_column(String(1024))
    """Папка закупки — та же, что в базе ядра, абсолютным путём."""

    title: Mapped[str] = mapped_column(String(512))
    """Название позиции, как его дало ядро."""

    lot: Mapped[TenderLot] = relationship(back_populates="positions")


__all__ = [
    "AuditEntry",
    "Job",
    "JobStatus",
    "Membership",
    "OptionSource",
    "Organization",
    "Role",
    "Session",
    "StoredFile",
    "TenderLot",
    "TenderLotPosition",
    "TenderWork",
    "TenderWorkOption",
    "TenderWorkPosition",
    "User",
    "WorkStage",
    "WorklistCode",
]


class Department(StrEnum):
    """Отдел, у которого лежит задача.

    Не роль. Роль — про право видеть цифры, отдел — про то, чья очередь
    работать. Один человек бывает в двух ролях, но задача всегда адресована
    отделу: иначе уволившийся сотрудник уносит с собой очередь.
    """

    DISCUSSION = "discussion"
    """Обсуждение: замечания к спецификации до подачи."""

    ANALYSIS = "analysis"
    """Разбор: считаем себестоимость и решаем, участвовать ли."""

    SUPPLY = "supply"
    """Снабжение: ищет товар и подтверждает цены."""

    LEGAL = "legal"
    """Юристы: жалобы, судебные процессы, подпись под обращениями."""

    TECHNOLOGIST = "technologist"
    """Технолог: подходит ли товар под спецификацию заказчика."""

    ASSEMBLER = "assembler"
    """Сборщик: соберём и отгрузим в срок."""

    APPROVAL = "approval"
    """Согласование перед подачей."""

    SUBMISSION = "submission"
    """Подача и всё после неё: итоги, договор, исполнение."""


class LotStatus(StrEnum):
    """Где лот в сквозном процессе компании.

    Один статус на весь путь, а не по статусу на отдел. Отделов пять, и у
    каждого свой взгляд; общий вопрос при этом один — «что сейчас с этой
    закупкой», и отвечать на него сложением пяти состояний означает пять
    разных ответов на планёрке.

    Порядок объявления — порядок жизни. По нему строится и полоса хода в
    карточке, и сортировка списка: заведённый в понедельник лот, дошедший до
    договора, важнее вчерашнего, до которого не дошли руки.
    """

    NEW = "new"
    """Появился в выгрузке, никто не смотрел."""

    DISCUSSION = "discussion"
    """Пишем замечание к спецификации. До подачи, и срок здесь короче всего."""

    ANALYSIS = "analysis"
    """На разборе: считаем себестоимость и маржу."""

    APPROVAL = "approval"
    """На согласовании: отделы подтверждают, что берёмся."""

    READY = "ready"
    """Готов к участию. Осталось подать в срок."""

    AWAITING = "awaiting"
    """Подали, ждём протокол итогов."""

    WON = "won"
    LOST = "lost"

    CONTRACT = "contract"
    """Выиграли, подписываем договор."""

    FULFILLING = "fulfilling"
    """Исполняем: везём, отгружаем, подписываем акты."""

    AWAITING_PAYMENT = "awaiting_payment"
    DONE = "done"

    SKIPPED = "skipped"
    """Не участвуем — решение наше, с причиной."""

    CANCELLED = "cancelled"
    """Отменён заказчиком. Не наш выбор, и отличать его от `skipped` важно:
    по отменённым не считают, сколько закупок мы пропустили зря."""


class Participation(StrEnum):
    """Берём ли лот в работу вообще.

    Отдельно от статуса. Статус говорит, где лот идёт, а это — пускать ли его
    дальше выгрузки: под наши коды приходит вчетверо больше, чем мы способны
    разобрать, и первый отсев делают руками.
    """

    MAYBE = "maybe"
    """По умолчанию. Никто ещё не смотрел."""

    YES = "yes"
    NO = "no"
    """Не участвуем и скрываем из списка. С причиной: через месяц по тем же
    заказчикам решают заново, и «почему тогда прошли мимо» — рабочий вопрос."""


class TaskState(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class ApprovalKind(StrEnum):
    """Кто подтверждает участие. Пять подписей, и каждая про своё."""

    MANAGER = "manager"
    """Менеджер: сроки и условия участия."""

    SUPPLY = "supply"
    """Снабжение: товар есть и цена подтверждена."""

    LEGAL = "legal"
    """Юрист: требования выполнимы, преград нет."""

    TECHNOLOGIST = "technologist"
    """Технолог: товар подходит под спецификацию."""

    ASSEMBLER = "assembler"
    """Сборщик: соберём и отгрузим в срок."""


class ApprovalState(StrEnum):
    WAITING = "waiting"
    APPROVED = "approved"
    REJECTED = "rejected"


class LotCard(Base, UUIDPrimaryKey, Timestamps):
    """Лот в работе компании: одна карточка на всё, что с ним происходит.

    Ключ — площадка плюс устойчивое имя строки, тот же, что у кода и у
    обсуждения. Заводить карточку в каждом модуле значило бы четыре набора
    статусов и четыре места, где их надо согласовать; а сотрудник, который
    ведёт лот, ходит во все площадки сразу.

    Снимок закупки хранится копией, а не ссылкой в базу площадки: выгрузка
    пересобирает список каждый час, названия и суммы у заказчика меняются, а
    карточка должна остаться той, по которой её завели. Живые цифры смотрят в
    разборе, здесь — то, что было на момент решения.

    Карточка не заводится сама. Она появляется, когда лот берут в работу:
    иначе в списке лежали бы тысячи пустых карточек по всем выгруженным лотам,
    и «в работе» перестало бы что-либо значить.
    """

    __tablename__ = "lot_cards"
    __table_args__ = (
        UniqueConstraint("module", "row_id", name="card_on_row"),
        Index("card_status", "organization_id", "status"),
        Index("card_owner", "owner_id", "status"),
        Index("card_deadline", "deadline"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    module: Mapped[str] = mapped_column(String(32))
    """Площадка: `goszakup`, `skstore`, `omarket`, `tender`."""

    row_id: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(32), index=True)

    source_number: Mapped[str] = mapped_column(String(64), default="", index=True)
    """Номер закупки на площадке — «17552688-1».

    Отдельно от `row_id` и от кода. Ключ у нас номер лота: у объявления с
    четырьмя лотами номер закупки один на всех. Но вслух говорят именно его, и
    в замечании заказчику стоит он же; без него лот не найти ни в списке
    площадки, ни на портале.
    """

    title: Mapped[str] = mapped_column(Text, default="")
    customer: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    enstru_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    category: Mapped[str] = mapped_column(String(128), default="", index=True)
    """Категория товара. Своя, а не портальная: по ней делят работу между
    людьми, и «компьютеры» с «серверами» у нас ведут разные менеджеры."""

    deadline: Mapped[datetime | None] = mapped_column(nullable=True)
    """Окончание приёма заявок. По нему считается, успеваем ли, и по нему же
    сортируется всё, что показывают человеку."""

    status: Mapped[LotStatus] = mapped_column(
        Enum(LotStatus, native_enum=False, length=24), default=LotStatus.NEW, index=True
    )
    participation: Mapped[Participation] = mapped_column(
        Enum(Participation, native_enum=False, length=8), default=Participation.MAYBE
    )
    skip_reason: Mapped[str] = mapped_column(Text, default="")

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """Менеджер поставки: отвечает за лот целиком, от объявления до оплаты."""

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """У кого лот прямо сейчас. Меняется по ходу: обсуждение у юриста, разбор у
    тендерщика, поиск у снабжения. Менеджер при этом остаётся тот же."""

    note: Mapped[str] = mapped_column(Text, default="")

    won_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    """С какой ценой выиграли. Пусто, пока итогов нет."""

    winner: Mapped[str] = mapped_column(Text, default="")
    """Кто выиграл, если не мы. По победителям смотрят, с кем соревнуемся и по
    какой цене они берут."""

    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    tasks: Mapped[list[Task]] = relationship(
        back_populates="card", cascade="all, delete-orphan", lazy="selectin"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="card", cascade="all, delete-orphan", lazy="selectin"
    )


class Task(Base, UUIDPrimaryKey, Timestamps):
    """Задача по лоту.

    Одна таблица на все отделы. «Мои задачи» у юриста, «запросы на поиск
    товара» у снабжения и «передать обсуждение юристам» — это одно и то же с
    разных сторон, и разводить их по таблицам значит писать один и тот же
    список пять раз, а потом пять раз чинить в нём сортировку.

    Задача всегда о лоте. Задача без лота — это заметка, для неё есть
    обсуждение строки; а очередь, в которой половина записей ни к чему не
    привязана, перестаёт быть очередью работы.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index("task_assignee", "assignee_id", "state"),
        Index("task_department", "organization_id", "department", "state"),
        Index("task_due", "due_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lot_cards.id", ondelete="CASCADE"), index=True
    )

    department: Mapped[Department] = mapped_column(
        Enum(Department, native_enum=False, length=16), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")

    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """Пусто — задача отдела, а не человека. Такая висит в общей очереди, и
    берут её оттуда: ничья срочная задача и есть то, что теряется."""

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    state: Mapped[TaskState] = mapped_column(
        Enum(TaskState, native_enum=False, length=12), default=TaskState.OPEN, index=True
    )
    done_at: Mapped[datetime | None] = mapped_column(nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    """Чем кончилось. Закрытая задача без единого слова о результате через
    месяц неотличима от брошенной."""

    card: Mapped[LotCard] = relationship(back_populates="tasks")


class Approval(Base, UUIDPrimaryKey, Timestamps):
    """Подпись отдела под участием в закупке.

    Пять подписей, каждая про своё, и все нужны до подачи. Держим строками, а
    не пятью полями в карточке: у подписи есть автор, время и причина отказа,
    а поле их не вмещает — и «кто это одобрил» превращается в вопрос без
    ответа ровно тогда, когда закупка вышла в убыток.
    """

    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("card_id", "kind", name="approval_once"),)

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lot_cards.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ApprovalKind] = mapped_column(Enum(ApprovalKind, native_enum=False, length=16))
    state: Mapped[ApprovalState] = mapped_column(
        Enum(ApprovalState, native_enum=False, length=12), default=ApprovalState.WAITING
    )
    by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    card: Mapped[LotCard] = relationship(back_populates="approvals")


class LotEvent(Base, UUIDPrimaryKey, Timestamps):
    """Что с лотом делали и кто.

    Заводится ради вопроса «кому платить премию». Компания смотрит, кто
    закупку вытащил: кто разобрал, кто нашёл товар, кто вовремя подписал, кто
    ответил заказчику. Из карточки этого не видно — она показывает только
    итог, а по итогу премию делить нельзя: у лота, который вёл один человек, и
    у лота, который прошёл через пятерых, итог одинаковый.

    Отдельной таблицей, а не выводом из подписей и задач. Вывод не покажет
    переходы — а именно они и есть работа: перевёл в разбор, вернул на
    доработку, объявил готовым. И не отличит человека от прогона.

    Запись не редактируется и не удаляется. Лента, которую можно поправить,
    для расчёта премий не годится: спор о том, кто что сделал, решается ею, а
    не памятью участников.
    """

    __tablename__ = "lot_events"
    __table_args__ = (Index("lot_event_card_at", "card_id", "created_at"),)

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lot_cards.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[str] = mapped_column(String(32), default="")
    """Роль на момент действия, строкой.

    Именно на момент, а не сегодняшняя: снабженец, ставший руководителем,
    подписывал за снабжение — и в ленте должно остаться так."""

    by_machine: Mapped[bool] = mapped_column(default=False, server_default="false")
    """Сделано прогоном или моделью, а не человеком. Без этого признака премию
    в отчёте получит робот."""

    kind: Mapped[str] = mapped_column(String(32), index=True)
    """`took`, `moved`, `signed`, `rejected`, `decided`, `assigned`, `task`,
    `task_done`, `task_taken`, `result`, `file`, `remark`."""

    title: Mapped[str] = mapped_column(String(255), default="")
    """Что произошло, готовой строкой: «Перевёл в «На разборе»».

    Готовой, а не собираемой на показе: названия состояний и отделов меняются,
    а лента должна помнить, как это называлось тогда."""

    detail: Mapped[str] = mapped_column(Text, default="")
    """Подробность: причина отказа, комментарий исполнителя, куда назначен."""

    from_status: Mapped[str] = mapped_column(String(32), default="")
    to_status: Mapped[str] = mapped_column(String(32), default="")
    """Откуда и куда перевели. Отдельными полями, а не разбором `title`:
    по ним считается, сколько лот простоял на каждом этапе и у кого. Разбирать
    ради этого готовую строку значит сломаться на первой же правке слов."""


class LotFile(Base, UUIDPrimaryKey, Timestamps):
    """Файл, приложенный к лоту руками.

    Отдельно от документов заказчика: те лежат на портале и приходят выгрузкой.
    Здесь то, что добавили мы — переписка, счёт поставщика, снимок экрана
    спецификации, — и потерять его вместе с пересборкой списка нельзя.
    """

    __tablename__ = "lot_files"
    __table_args__ = (Index("lot_file_card", "card_id"),)

    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lot_cards.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")


class SpecSheet(Base, UUIDPrimaryKey, Timestamps):
    """Разбор технической спецификации таблицей: что покупают и с чем.

    Одна запись на лот, ключ тот же, что у карточки и у кода: площадка плюс
    устойчивое имя строки. Отдельно от карточки, потому что живёт своей
    жизнью: карточку заводят при взятии в работу, а таблицу собирают, когда
    доходят руки разобрать спецификацию, — и пересобирают заново, когда
    заказчик её переписал.

    Столбцы и строки лежат одним документом, а не таблицей ячеек. Сотрудник
    добавляет столбцы и строки по ходу работы — «блока питания в ТС нет, а
    поставить надо», — и в разложенном на ячейки виде каждая такая правка
    означала бы вставку с пересчётом порядка. Читается и пишется всё равно
    целиком: таблица небольшая, десятки строк.

    Первые три столбца заполняет модель по файлу спецификации; остальные —
    люди. Разница видна в самом столбце (`filled_by`): пересборка моделью
    затирает её работу, и трогать чужие столбцы она не должна.
    """

    __tablename__ = "spec_sheets"
    __table_args__ = (UniqueConstraint("module", "row_id", name="sheet_on_row"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )

    module: Mapped[str] = mapped_column(String(32))
    row_id: Mapped[str] = mapped_column(String(128))

    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    """Столбцы: ключ, заголовок, ширина, кем заполняется."""

    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    """Строки: ключ строки и значения по ключам столбцов."""

    source_name: Mapped[str] = mapped_column(String(512), default="")
    """Имя файла спецификации, по которому собрано. По нему видно, не устарела
    ли таблица: заказчик переписывает спецификацию, и файл меняется."""

    model: Mapped[str] = mapped_column(String(64), default="")
    """Какой моделью собрано. Тот же вопрос, что и к замечанию: разбор,
    сделанный запасной моделью, читают внимательнее."""

    trouble: Mapped[str] = mapped_column(Text, default="")
    """Почему не собралось. Пустая таблица без причины выглядит как поломка
    платформы, хотя дело обычно в том, что спецификации у лота нет вовсе."""

    built_at: Mapped[datetime | None] = mapped_column(nullable=True)
    """Когда модель разобрала спецификацию. Пусто — разбирали только руками."""

    built_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
