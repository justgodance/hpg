# Учебное руководство разработчика: Архитектура и тонкости кода

Этот документ создан для подробного разбора сложных концепций, архитектурных решений и «подводных камней» Python, FastAPI и SQLAlchemy 2.0, которые мы применяем в проекте **Guild Quest Board**.

---

## Оглавление
1. [Асинхронность и Event Loop в Python](#1-асинхронность-и-event-loop-в-python)
2. [SQLAlchemy 2.0: Современный асинхронный ORM](#2-sqlalchemy-20-современный-асинхронный-orm)
   - [Mapped и mapped_column: строгая типизация](#21-mapped-и-mapped_column-строгая-типизация)
   - [Решение проблемы циклических импортов (TYPE_CHECKING)](#22-решение-проблемы-циклических-импортов-type_checking)
   - [Два Foreign Key на одну таблицу (AmbiguousForeignKeysError)](#23-два-foreign-key-на-одну-таблицу-ambiguousforeignkeyserror)
   - [Проблема N+1 и почему в async обязателен lazy="selectin"](#24-проблема-n1-и-почему-в-async-обязателен-lazyselectin)
   - [Частичные уникальные индексы (Partial Unique Indexes)](#25-частичные-уникальные-индексы-partial-unique-indexes)
3. [FastAPI: Dependency Injection и Lifespan](#3-fastapi-dependency-injection-и-lifespan)
   - [Асинхронный генератор сессий (get_db)](#31-асинхронный-генератор-сессий-get_db)
   - [Жизненный цикл приложения (@asynccontextmanager lifespan)](#32-жизненный-цикл-приложения-asynccontextmanager-lifespan)
4. [Pydantic v2: Тонкости валидации и сериализации](#4-pydantic-v2-тонкости-валидации-и-сериализации)
   - [computed_field: Динамические поля без нагрузки на БД](#41-computed_field-динамические-поля-без-нагрузки-на-бд)
   - [from_attributes=True (бывший orm_mode)](#42-from_attributestrue-бывший-orm_mode)
5. [Паттерны игровой логики](#5-паттерны-игровой-логики)
   - [Динамическая инфляция без фоновых воркеров (Celery/Cron)](#51-динамическая-инфляция-без-фоновых-воркеров-celerycron)
   - [Конвейер доски (Refill Board) и исключающие выборки](#52-конвейер-доски-refill-board-и-исключающие-выборки)
   - [Механика Андердога (Handicap-система)](#53-механика-андердога-handicap-система)
6. [Управление конфигурацией: The Twelve-Factor App и вынос данных](#6-управление-конфигурацией-the-twelve-factor-app-и-вынос-данных)
   - [Почему «магические числа» в коде — это антипаттерн](#61-почему-магические-числа-в-коде--это-антипаттерн)
   - [Единый источник правды: pydantic-settings и BaseSettings](#62-единый-источник-правды-pydantic-settings-и-basesettings)
   - [Отделение кода от контента (Data Separation: JSON файлы)](#63-отделение-кода-от-контента-data-separation-json-файлы)
   - [Надежные пути через pathlib.Path](#64-надежные-пути-через-pathlibpath)
7. [Взвешенный спавн (Drop Rates) и паттерн Mystery Box (Late Binding)](#7-взвешенный-спавн-drop-rates-и-паттерн-mystery-box-late-binding)
   - [Взвешенные вероятности через random.choices](#71-взвешенные-вероятности-через-randomchoices)
   - [Паттерн «Подарок Санты» и Nullable Foreign Key (Late Binding)](#72-паттерн-подарок-санты-и-nullable-foreign-key-late-binding)
8. [Архитектура двойного режима СУБД и Кросс-версионность Python](#8-архитектура-двойного-режима-субд-и-кросс-версионность-python)
   - [SQLite (aiosqlite) vs PostgreSQL (asyncpg) в одном коде](#81-sqlite-aiosqlite-vs-postgresql-asyncpg-в-одном-коде)
   - [Кросс-версионность Python: от 3.9 до 3.12 (typing, backport, PEP 563)](#82-кросс-версионность-python-от-39-до-312-typing-backport-pep-563)
9. [Серверная модель состояний «Скрытый контракт» и Двухэтапная фиксация (Two-Step Take)](#9-серверная-модель-состояний-скрытый-контракт-и-двухэтапная-фиксация-two-step-take)
   - [Геймдизайн и сокрытие информации на сервере](#91-геймдизайн-и-сокрытие-информации-на-сервере)
   - [Разделение состояния через @computed_field в Pydantic](#92-разделение-состояния-через-computed_field-в-pydantic)
   - [Двухэтапный контракт: Preview (рулетка) vs Confirm-Take (транзакция)](#93-двухэтапный-контракт-preview-рулетка-vs-confirm-take-транзакция)
10. [DevOps, Docker & Контейнеризация для Production](#10-devops-docker--контейнеризация-для-production)
    - [Многоэтапная сборка (Multi-stage Dockerfile) для Python](#101-многоэтапная-сборка-multi-stage-dockerfile-для-python)
    - [Безопасность: non-root пользователь и минимизация attack surface](#102-безопасность-non-root-пользователь-и-минимизация-attack-surface)
    - [Docker Compose: оркестрация сервисов и Healthcheck зависимостей](#103-docker-compose-оркестрация-сервисов-и-healthcheck-зависимостей)
11. [Эксплуатация серверов, Uvicorn/Gunicorn и тюнинг ядра Linux](#11-эксплуатация-серверов-uvicorngunicorn-и-тюнинг-ядра-linux)
    - [Производственная модель процессов: Gunicorn Master + Uvicorn Workers](#111-производственная-модель-процессов-gunicorn-master--uvicorn-workers)
    - [Расчет пула воркеров: формула (2 * CPU) + 1 и борьба с утечками памяти](#112-расчет-пула-воркеров-формула-2--cpu--1-и-борьба-с-утечками-памяти)
    - [Graceful Shutdown (SIGTERM/SIGINT) и жизненный цикл запросов](#113-graceful-shutdown-sigtermsigint-и-жизненный-цикл-запросов)
    - [Nginx Reverse Proxy: буферизация медленных клиентов и заголовки](#114-nginx-reverse-proxy-буферизация-медленных-клиентов-и-заголовки)
    - [Тюнинг ядра Linux: somaxconn, backlog, ulimit и TCP TIME_WAIT](#115-тюнинг-ядра-linux-somaxconn-backlog-ulimit-и-tcp-time_wait)
12. [Базы Данных в Production: Высоконадежные миграции Alembic и тюнинг PostgreSQL](#12-базы-данных-в-production-высоконадежные-миграции-alembic-и-тюнинг-postgresql)
    - [Zero-Downtime миграции и паттерн Expand and Contract](#121-zero-downtime-миграции-и-паттерн-expand-and-contract)
    - [Асинхронные миграции в Alembic](#122-асинхронные-миграции-в-alembic)
    - [Тюнинг Connection Pool: QueuePool, max_overflow, pool_recycle, pool_pre_ping](#123-тюнинг-connection-pool-queuepool-max_overflow-pool_recycle-pool_pre_ping)
    - [Пессимистические блокировки: SELECT FOR UPDATE SKIP LOCKED](#124-пессимистические-блокировки-select-for-update-skip-locked)
13. [Шпаргалка к Senior/Middle Собеседованию: 10 каверзных вопросов по Backend & DevOps](#13-шпаргалка-к-seniormiddle-собеседованию-10-каверзных-вопросов-по-backend--devops)
    - [Вопрос 1: Race Condition при взятии квеста (FOR UPDATE vs Partial Unique Index)](#вопрос-1-race-condition-при-взятии-квеста)
    - [Вопрос 2: Проблема N+1 в Async SQLAlchemy и скрытая ловушка selectinload](#вопрос-2-проблема-n1-в-async-sqlalchemy-и-скрытая-ловушка-selectinload)
    - [Вопрос 3: Client Disconnect в FastAPI и асинхронный генератор Depends(get_db)](#вопрос-3-client-disconnect-в-fastapi-и-асинхронный-генератор-dependsget_db)
    - [Вопрос 4: Как масштабировать FastAPI приложение на многоядерном сервере?](#вопрос-4-как-масштабировать-fastapi-приложение-на-многоядерном-сервере)
    - [Вопрос 5: Архитектура Twelve-Factor App и изоляция конфигурации](#вопрос-5-архитектура-twelve-factor-app-и-изоляция-конфигурации)
    - [Вопрос 6: Как реализовать Zero-Downtime миграцию при добавлении NOT NULL колонки в таблицу на 50 млн строк?](#вопрос-6-как-реализовать-zero-downtime-миграцию-при-добавлении-not-null-колонки)
    - [Вопрос 7: Что произойдет, если в async def эндпоинте вызвать time.sleep(10) или тяжелую CPU-функцию?](#вопрос-7-что-произойдет-если-в-async-def-эндпоинте-вызвать-timesleep10)
    - [Вопрос 8: Connection Pool Exhaustion — причины, диагностика и решение](#вопрос-8-connection-pool-exhaustion--причины-диагностика-и-решение)
    - [Вопрос 9: Зачем нужен Nginx перед Uvicorn, если Uvicorn сам является ASGI-сервером?](#вопрос-9-зачем-нужен-nginx-перед-uvicorn)
    - [Вопрос 10: Чем отличается graceful shutdown в Docker контейнерах и как его протестировать?](#вопрос-10-чем-отличается-graceful-shutdown-в-docker-контейнерах)
    - [Вопрос 11: Паттерн "Технический реролл" без штрафов](#вопрос-11-паттерн-технический-реролл-без-штрафов-как-проектировать-исключительную-бизнес-логику-в-соревновательных-системах)
    - [Вопрос 12: Валидация и агрегация пользовательских числовых метрик (Actual Playtime Tracking)](#вопрос-12-валидация-и-агрегация-пользовательских-числовых-метрик-actual-playtime-tracking)
    - [Вопрос 13: Мгновенная реактивность через HTMX Out-of-Band (OOB) Swaps и паттерн «Interactive Spin-on-Demand»](#вопрос-13-мгновенная-реактивность-через-htmx-out-of-band-oob-swaps-и-паттерн-interactive-spin-on-demand)

---



## 1. Асинхронность и Event Loop в Python

### Зачем здесь `async` и `await`?
В классическом синхронном Python (как в Flask или старом Django) каждый запрос блокирует поток ОС во время ожидания ответа от базы данных или сети.
FastAPI работает на базе **`asyncio`** и сервере **Uvicorn**:
- Пока база данных PostgreSQL выполняет сложный запрос (I/O-bound операция), поток не простаивает.
- Event Loop переключается на обслуживание запросов других игроков.
- Для этого драйвер БД должен быть строго асинхронным — поэтому мы используем **`asyncpg`**, а не синхронный `psycopg2`.

---

## 2. SQLAlchemy 2.0: Современный асинхронный ORM

До версии 2.0 в SQLAlchemy использовался синтаксис `Column(Integer, primary_key=True)`. Он плохо поддерживал статические анализаторы типов (mypy, PyCharm, VS Code Pylance). 

### 2.1 Mapped и mapped_column: строгая типизация
В SQLAlchemy 2.0 используется система типов Python (PEP 484):
```python
# app/models/user.py
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    free_drops: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
```
- `Mapped[int]` сообщает IDE и линтерам точный тип поля.
- `mapped_column(...)` задает свойства колонки в SQL (nullable, default, foreign key, index).

### 2.2 Решение проблемы циклических импортов (`TYPE_CHECKING`)
В сложных проектах модели часто ссылаются друг на друга: `User` знает о `Quest`, а `Quest` знает о `User`. Если просто написать `from app.models.quest import Quest` в файле `user.py`, Python упадет с ошибкой `ImportError: cannot import name ... (circular import)`.

**Как это решается на уровне Senior-разработки:**
```python
from typing import TYPE_CHECKING
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.quest import Quest  # Импортируется ТОЛЬКО анализаторами типов (IDE)

class User(Base):
    # В relationship передаем строковое имя класса "Quest" в кавычках.
    # Во время выполнения SQLAlchemy найдет модель в реестре Base.metadata
    quests: Mapped[list["Quest"]] = relationship(back_populates="user")
```
`TYPE_CHECKING` во время работы приложения равен `False`, поэтому циклический импорт физически не происходит.

### 2.3 Два Foreign Key на одну таблицу (`AmbiguousForeignKeysError`)
В модели `Quest` есть два внешних ключа, указывающих на таблицу `games`:
1. `game_id` — игра по умолчанию для квеста.
2. `current_rolled_game_id` — игра, выпавшая в рулетке.

Если просто написать `relationship("Game")`, SQLAlchemy выдаст ошибку: *«Не могу определить, по какому внешнему ключу связывать Quest и Game»*.

**Решение:** явно указать `foreign_keys`:
```python
# app/models/quest.py
game: Mapped["Game"] = relationship(
    foreign_keys=[game_id],
    back_populates="quests",
    lazy="selectin",
)
current_rolled_game: Mapped["Game | None"] = relationship(
    foreign_keys=[current_rolled_game_id],
    lazy="selectin",
)

# app/models/game.py
quests: Mapped[list["Quest"]] = relationship(
    foreign_keys="[Quest.game_id]",
    back_populates="game",
)
```

### 2.4 Проблема N+1 и почему в async обязателен `lazy="selectin"`
В классическом синхронном SQLAlchemy по умолчанию используется ленивая загрузка (`lazy="select"`). Когда вы обращаетесь к `quest.game.title`, ORM в этот момент «на лету» делает дополнительный `SELECT` в базу.

В **асинхронном режиме это запрещено**, так как обращение к атрибуту объекта `quest.game` в Python синхронно, а вызов I/O в базу требует `await`. Если вызвать ленивое поле в async, вы получите:
`sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`

**Решение:**
Мы используем `lazy="selectin"` на связях и `selectinload(Quest.game)` в запросах.
SQLAlchemy загружает родительские объекты и все связанные сущности за фиксированное число запросов через SQL `WHERE id IN (...)`, полностью защищая от падений и проблемы N+1.

### 2.5 Частичные уникальные индексы (Partial Unique Indexes)
Бизнес-правило: *«Игрок может иметь только один активный квест одновременно»*.

Обычно новички проверяют это только кодом в Python (`if active_quest: raise`). Но при двух параллельных кликах пользователя оба запроса могут пройти проверку до коммита (Race Condition).

**Senior-решение:** Гарантия на уровне СУБД с помощью частичного индекса PostgreSQL:
```python
# app/models/quest.py
__table_args__ = (
    Index(
        "uq_user_active_quest",
        "user_id",
        unique=True,
        postgresql_where=text("status = 'IN_PROGRESS' AND user_id IS NOT NULL"),
    ),
)
```
Этот индекс запрещает дубликат `user_id` **только для строк со статусом 'IN_PROGRESS'**. Завершенных (`COMPLETED`) квестов у пользователя могут быть сотни!

---

## 3. FastAPI: Dependency Injection и Lifespan

### 3.1 Асинхронный генератор сессий (`get_db`)
```python
# app/database.py
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
```
В роутерах мы пишем: `db: AsyncSession = Depends(get_db)`.
- FastAPI создает новую транзакционную сессию в момент прихода HTTP-запроса.
- `yield session` отдает сессию в эндпоинт.
- Блок `finally` гарантирует, что даже если внутри функции произойдет ошибка `HTTPException`, сессия будет корректно закрыта и соединение вернется в Connection Pool.

### 3.2 Жизненный цикл приложения (`lifespan`)
Старые методы `@app.on_event("startup")` и `on_event("shutdown")` объявлены устаревшими (deprecated).
Современный стандарт FastAPI — контекстный менеджер `lifespan`:
```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код ДО yield выполняется при старте сервера
    await init_db()
    async with async_session_maker() as session:
        await seed_games_if_empty(session)
        await seed_challenges_if_empty(session)
        await refill_board(session)
    yield
    # Код ПОСЛЕ yield выполняется при корректной остановке сервера
```

---

## 4. Pydantic v2: Тонкости валидации и сериализации

### 4.1 `@computed_field`: Динамические поля без нагрузки на БД
Мы внедрили механику инфляции: *«Квест получает +20% к награде за каждые 24 часа на доске»*.

Если бы мы каждую ночь пересчитывали очки и перезаписывали базу через Cron, мы бы создавали лишнюю нагрузку и риски сбоев.
Вместо этого мы храним `spawned_at` (момент появления) и вычисляем актуальные очки прямо во время сериализации в JSON с помощью `@computed_field`:

```python
# app/schemas/quest.py
class QuestResponse(BaseModel):
    ...
    spawned_at: datetime
    locked_reward: int | None = None

    @computed_field
    @property
    def current_reward(self) -> int:
        if self.locked_reward is not None:
            return self.locked_reward  # Если взят — отдаем зафиксированную сумму

        base = (self.current_rolled_game or self.game).reward_points
        now = datetime.now(timezone.utc)
        spawned = self.spawned_at.replace(tzinfo=timezone.utc) if not self.spawned_at.tzinfo else self.spawned_at
        full_days = max(0, int((now - spawned).total_seconds() // 86400))
        return round(base * (1.0 + 0.2 * full_days))
```
В базе данных хранится только неизменяемый timestamp, а клиент всегда видит актуальные очки!

### 4.2 `from_attributes=True`
В Pydantic v1 писали `class Config: orm_mode = True`. В Pydantic v2 это заменено на `model_config = ConfigDict(from_attributes=True)`. Это говорит Pydantic: *«Читай данные не только из словарей `data["title"]`, но и из атрибутов ORM-моделей `quest.game.title`»*.

---

## 5. Паттерны игровой логики

### 5.1 Динамическая инфляция и фиксация (Locking)
- Пока квест лежит на доске: `locked_reward == None`. При каждом запросе эндпоинта `GET /api/quests/` схема вычисляет текущую награду с учетом инфляции.
- В момент, когда игрок нажимает **«Взять квест»** (`POST /api/quests/{id}/take`), мы рассчитываем сумму на эту секунду и записываем её в `Quest.locked_reward`.
- Теперь награда «заморожена»: если игрок проходит игру 2 недели, инфляция больше не начисляется, а при сдаче (`complete_quest`) он получает ровно ту сумму, на которую подписался при старте.

### 5.2 Конвейер доски (`refill_board`)
Чтобы доска всегда была интересной:
1. Мы считаем доступные квесты: `SELECT count(id) FROM quests WHERE status = 'AVAILABLE'`.
2. Если их меньше 12, находим игры, которых сейчас нет на доске (ни в доступных, ни в прохождении):
```python
active_games_stmt = select(Quest.game_id).where(
    Quest.status.in_([QuestStatus.AVAILABLE, QuestStatus.IN_PROGRESS])
)
# Исключаем активные:
games_stmt = select(Game).where(Game.id.not_in(active_games_stmt)).order_by(func.random()).limit(needed)
```
3. Создаем новые квесты со свежим `spawned_at = now()`.

### 5.3 Механика Андердога (Handicap-система)
Чтобы избежать ситуации, когда лидер оторвался и другим игрокам не интересно играть:
- Мы динамически находим максимум очков: `SELECT max(total_score) FROM users`.
- Если `(max_score - user.total_score) > settings.UNDERDOG_SCORE_GAP`, игрок получает статус **Андердога**.
- Это дает два преимущества:
  1. Доступ к эксклюзивным выгодным контрактам (`is_underdog_only == True`).
  2. Автоматический бонус `+20%` к очкам при успешной сдаче любого квеста.

---

## 6. Управление конфигурацией: The Twelve-Factor App и вынос данных

### 6.1 Почему «магические числа» в коде — это антипаттерн
Ранее в коде встречались литералы: `12` (размер доски), `2000` (порог андердога), `2` (дропы), `0.2` (инфляция 20%), `24` (интервал часов).
Если организатор марафона захочет изменить размер доски с 12 до 16, разработчику пришлось бы искать число `12` по всем файлам проекта (в CRUD, схемах, роутерах, тестах), что неминуемо ведет к человеческим ошибкам и рассинхронизации.

### 6.2 Единый источник правды: `pydantic-settings` и `BaseSettings`
Мы вынесли все балансные числа в класс `Settings` в **`app/config.py`**:
```python
class Settings(BaseSettings):
    MAX_BOARD_SIZE: int = Field(default=12, description="Количество квестов на доске")
    DEFAULT_FREE_DROPS: int = Field(default=2)
    INFLATION_INTERVAL_HOURS: int = Field(default=24)
    INFLATION_RATE_PER_INTERVAL: float = Field(default=0.2)
    UNDERDOG_SCORE_GAP: int = Field(default=2000)
    ...
```
**Преимущества по стандарту Twelve-Factor App (III. Конфигурация):**
1. Любой параметр можно переопределить через переменные окружения ОС или файл `.env` без правки кода (например, указать в `.env` строку `MAX_BOARD_SIZE=16`).
2. Pydantic автоматически валидирует типы: если в переменную передать строку вместо числа, приложение не запустится с понятным сообщением об ошибке еще на старте.

### 6.3 Отделение кода от контента (Data Separation: JSON файлы)
Список игр и испытаний — это контент (данные), а не код приложения.
- Каталог игр вынесен в **`data/games.json`**.
- Модификаторы/челленджи вынесены в **`data/challenges.json`**.

При инициализации базы данных функции `seed_games_if_empty` и `seed_challenges_if_empty` читают эти файлы через `json.load`. Это позволяет геймдизайнеру или организатору марафона редактировать список доступных игр и условий в обычном JSON-редакторе, не трогая Python-код.

### 6.4 Надежные пути через `pathlib.Path`
Частая ошибка начинающих разработчиков — открытие файлов по относительному пути: `open("data/games.json")`.
Если запустить сервер из другой рабочей директории (например, из папки `tests/` или родительского каталога), Python выбросит `FileNotFoundError`.

**Senior-решение:** отталкиваться от абсолютного расположения файла `app/config.py`:
```python
from pathlib import Path

# Вычисляем корень проекта относительно текущего файла: app/config.py -> app -> hpg (корень)
BASE_DIR = Path(__file__).resolve().parent.parent

GAMES_DATA_PATH: Path = BASE_DIR / "data" / "games.json"
CHALLENGES_DATA_PATH: Path = BASE_DIR / "data" / "challenges.json"
```
Оператор `/` в объектах `Path` автоматически учитывает операционную систему (слэши в Linux и бэкслэши в Windows).

---

## 7. Взвешенный спавн (Drop Rates) и паттерн Mystery Box (Late Binding)

### 7.1 Взвешенные вероятности через `random.choices`
В геймдеве лут, дроп карточек и генерация квестов редко бывают равномерными (`1/N`).
В нашем марафоне категории имеют разные вероятности:
- `STEAM`: 40%
- `PRESET`: 25%
- `SERIES`: 15%
- `EMULATOR`: 10%
- `SANTA`: 7% (Специальный подарок-сюрприз)
- `GOTY`: 3% (Редкие блокбастеры)

В стандартной библиотеке Python для этого используется функция **`random.choices(population, weights=weights, k=count)`**:
```python
CATEGORIES = ["STEAM", "PRESET", "SERIES", "EMULATOR", "SANTA", "GOTY"]
WEIGHTS = [0.40, 0.25, 0.15, 0.10, 0.07, 0.03]

# Генерируем сразу N категорий для недостающих слотов доски
chosen = random.choices(CATEGORIES, weights=WEIGHTS, k=needed)
```
Python использует эффективный алгоритм с кумулятивной суммой весов (Cumulative Distribution Function), работающий за O(k).

### 7.2 Паттерн «Подарок Санты» и Nullable Foreign Key (Late Binding)
Обычно внешний ключ `game_id` в таблице квестов обязателен (`nullable=False`).
Однако для механики **«Подарок от всех» (Mystery Box)** мы применили паттерн **Late Binding (Позднее связывание)**:
1. Карточка спавнится на доске с `game_id = None`, `card_type = 'SANTA'` и `is_santa_box = True`.
2. Никто из участников не знает, какая игра внутри, пока не нажмет кнопку «Взять квест».
3. В момент взятия (`POST /api/quests/{id}/take`) сервер бросает жребий 50/50:
   - **True**: игра из категории `SANTA_TOP` (+10% бонус к очкам).
   - **False**: игра из категории `SANTA_COAL` (Уголек для терпеливых со штрафной сложностью, +50% бонус к очкам).
4. Сервер связывает `quest.game_id = chosen_game.id`, сбрасывает `is_santa_box = False` и блокирует финальную награду в `locked_reward`.

**Архитектурный вывод:** делая `game_id` nullable, мы превратили запись в реляционной БД в динамический контейнер-сюрприз без необходимости создавать отдельную избыточную таблицу `santa_boxes`.

---

## 8. Архитектура двойного режима СУБД и Кросс-версионность Python

### 8.1 SQLite (aiosqlite) vs PostgreSQL (asyncpg) в одном коде
В enterprise-архитектуре важно, чтобы приложение можно было запустить в один клик без поднятия тяжелой инфраструктуры:
- **В Docker / Production**: `DATABASE_URL=postgresql+asyncpg://...` (максимальная производительность, пулы соединений, отказоустойчивость).
- **Локально на машине разработчика**: `DATABASE_URL=sqlite+aiosqlite:///./hpg.db` (файл базы создается на лету, не требует установленного Docker Desktop или сервера PostgreSQL).

В `app/database.py` движок автоматически адаптирует параметры подключения:
```python
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
```

### 8.2 Кросс-версионность Python: от 3.9 до 3.12 (typing, backport, PEP 563)
Синтаксис объединения типов `int | None` (PEP 604) появился только в Python 3.10.
Чтобы проект одинаково стабильно работал и на локальной машине с Python 3.9, и в современном контейнере Python 3.12:
1. Во все модули добавлена строчка `from __future__ import annotations` (PEP 563 — отложенная оценка строковых аннотаций во время компиляции AST).
2. Подключен `eval-type-backport` для корректного разрешения Pydantic v2 на старых версиях рантайма.
3. В `Quest` модели использован `Mapped[Optional[int]]` для совместимости декларативного маппера SQLAlchemy 2.0.

---

## 9. Серверная модель состояний «Скрытый контракт» и Двухэтапная фиксация (Two-Step Take)

### 9.1 Геймдизайн и сокрытие информации на сервере
Если отдавать клиенту полные названия игр сразу на бирже, игроки будут заниматься черрипикингом (охотой за легкими тайтлами).
Поэтому в статусе `AVAILABLE` сервер раскрывает только жанр, платформу и диапазон времени (например, `10–20 ч`).

### 9.2 Разделение состояния через `@computed_field` в Pydantic
Вместо условной логики в шаблонах или контроллерах, модель схемы `QuestResponse` производит динамическую проекцию:
- `is_revealed`: `True` только при `status in (IN_PROGRESS, COMPLETED)`.
- `display_title`: На бирже отдает название категории/пресета, а в работе — настоящее имя `game.title`.
- `display_time`: На бирже отдает безопасный интервал `time_range`, а в работе — точные `hltb_hours`.

### 9.3 Двухэтапный контракт: Preview (рулетка) vs Confirm-Take (транзакция)
Чтобы игрок мог увидеть случайный выбор Колеса Судьбы, но квест **не принимался автоматически**:
1. **Эндпоинт `POST /quests/{id}/take` (Только Preview):**
   - Сервер выбирает кандидата игры и генерирует список из 15 элементов для анимации рулетки.
   - **Критически важно:** Статус квеста в БД **НЕ меняется** (остается `AVAILABLE`), `user_id` не назначается.
   - Пользователь видит результат вращения барабана и две явные кнопки: `[ Принять контракт ]` и `[ Отказаться ]`.
2. **Эндпоинт `POST /quests/{id}/confirm-take` (Явная фиксация):**
   - Вызывается **только** при осознанном клике игрока на кнопку согласия.
   - Атомарно переводит квест в `IN_PROGRESS`, фиксирует награду `locked_reward`, привязывает `user_id` и запускает конвейер `refill_board`.
3. **Отказ от контракта:**
   - Если игрок нажимает `[ Отказаться ]` или закрывает окно, квест остается доступным на доске для любого участника марафона.

---

## 10. DevOps, Docker & Контейнеризация для Production

### 10.1 Многоэтапная сборка (Multi-stage Dockerfile) для Python
В production-окружении недопустимо использовать раздутые образы (Fat Images), содержащие компиляторы `gcc`, `make` и заголовки `python-dev`.
Мы используем **Multi-stage build**:
```dockerfile
# ---------------- Stage 1: Builder ----------------
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     gcc     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---------------- Stage 2: Final Runtime ----------------
FROM python:3.12-slim AS runner

WORKDIR /app

# Создаем непривилегированного пользователя appuser (UID 10001)
RUN groupadd -g 10001 appgroup &&     useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Копируем установленные wheel-пакеты из builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

COPY --chown=appuser:appgroup . /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
**Преимущества:**
- Уменьшение размера образа с 800+ МБ до 120–150 МБ.
- Отсутствие компилятора в итоговом образе: злоумышленник не сможет скомпилировать эксплойт при взломе контейнера.
- Эффективный кэш слоев: пока не изменился `requirements.txt`, этап компиляции пропускается мгновенно.

### 10.2 Безопасность: non-root пользователь и минимизация attack surface
Запуск контейнеров под `root` — одна из главных уязвимостей в облачной инфраструктуре (Container Breakout).
В нашей конфигурации:
- Пользователь `appuser` лишен прав `sudo`.
- Все файлы приложения принадлежат группе `appgroup`.
- Docker runtime монтирует корневую файловую систему в режиме `read-only` (за исключением временной директории `/tmp`).

### 10.3 Docker Compose: оркестрация сервисов и Healthcheck зависимостей
```yaml
services:
  web:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:secret@db:5432/hpg_db
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      - POSTGRES_DB=hpg_db
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=secret
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d hpg_db"]
      interval: 5s
      timeout: 5s
      retries: 5
```
**Критическая деталь DevOps:** `condition: service_healthy`. Без этого флага контейнер `web` стартует одновременно с `db`, попытается выполнить `init_db()` до инициализации сокета PostgreSQL и аварийно завершится с ошибкой `ConnectionRefusedError`.

---

## 11. Эксплуатация серверов, Uvicorn/Gunicorn и тюнинг ядра Linux

### 11.1 Производственная модель процессов: Gunicorn Master + Uvicorn Workers
В локальной разработке Uvicorn запускается как одиночный процесс (`--reload`).
В Production один поток Python ограничен GIL и одним ядром процессора.
На многоядерном сервере (например, 8 vCPU) правильная архитектура:
**Gunicorn в роли Process Manager + UvicornWorker в роли асинхронных исполнителей**:
```bash
gunicorn app.main:app     --workers 9     --worker-class uvicorn.workers.UvicornWorker     --bind 0.0.0.0:8000     --max-requests 5000     --max-requests-jitter 500     --timeout 30     --graceful-timeout 30
```

### 11.2 Расчет пула воркеров: формула (2 * CPU) + 1 и борьба с утечками памяти
1. **Формула количества воркеров:**  
   $$	ext{Workers} = (2 	imes 	ext{CPU\_Cores}) + 1$$  
   На 4 ядрах запускается 9 воркеров. Это гарантирует, что даже если часть воркеров ожидает дискового I/O или сборщика мусора (GC), оставшиеся ядра процессора непрерывно загружены обработкой запросов.
2. **Борьба с фрагментацией памяти CPython:**  
   `--max-requests 5000` и `--max-requests-jitter 500`: каждый воркер мягко перезапускается после обработки примерно 5000 запросов. Это полностью предотвращает деградацию памяти из-за фрагментации кучи в долгоживущих Python-процессах.

### 11.3 Graceful Shutdown (SIGTERM/SIGINT) и жизненный цикл запросов
При деплое новой версии или перезапуске pod-а в Kubernetes оркестратор отправляет процессу сигнал `SIGTERM`:
1. Gunicorn перестает принимать новые TCP-соединения (`listen backlog`).
2. Работающим воркерам дается тайм-аут (`--graceful-timeout 30`) на завершение уже выполняющихся запросов и коммитов в БД.
3. В FastAPI срабатывает блок выхода контекстного менеджера `@asynccontextmanager lifespan`:
   ```python
   # app/main.py
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # startup
       yield
       # shutdown: закрываем пул соединений с базой
       await engine.dispose()
   ```
4. Если воркер не завершился за 30 секунд, Master-процесс отправляет жесткий сигнал `SIGKILL`.

### 11.4 Nginx Reverse Proxy: буферизация медленных клиентов и заголовки
**Почему нельзя выставлять Uvicorn напрямую в интернет без Nginx?**
1. **Slowloris / медленные клиенты:** Если клиент на 2G-смартфоне медленно отправляет тело POST-запроса по 1 байту в секунду, он держит открытый коннект Uvicorn. Nginx с включенной буферизацией (`proxy_buffering on`) полностью вычитывает запрос в свой буфер в памяти и передает в Uvicorn мгновенно.
2. **TLS/SSL Termination & HTTP/2:** Nginx берет на себя тяжелое RSA/ECC шифрование и мультиплексирование потоков HTTP/2, разгружая рантайм Python.
3. **Пул постоянных соединений (Upstream Keepalive):**
   ```nginx
   upstream uvicorn_backend {
       server 127.0.0.1:8000;
       keepalive 32;
   }

   server {
       listen 80;
       server_name board.guild.com;

       location / {
           proxy_pass http://uvicorn_backend;
           proxy_http_version 1.1;
           proxy_set_header Connection "";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

### 11.5 Тюнинг ядра Linux: somaxconn, backlog, ulimit и TCP TIME_WAIT
Под нагрузкой более 10 000 RPS настройки Linux по умолчанию начинают сбрасывать входящие пакеты:
1. **Лимит файловых дескрипторов (ulimit -n):**
   Каждый TCP-сокет в Linux — это файловый дескриптор. По умолчанию лимит равен 1024.
   В `/etc/security/limits.conf`:
   ```
   * soft nofile 65535
   * hard nofile 65535
   ```
2. **Очередь входящих соединений ядра (somaxconn):**
   ```bash
   sysctl -w net.core.somaxconn=4096
   sysctl -w net.ipv4.tcp_max_syn_backlog=4096
   ```
3. **Утилизация сокетов в состоянии TIME_WAIT:**
   При частых HTTP/1.0 запросах тысячи сокетов зависают на 60 секунд:
   ```bash
   sysctl -w net.ipv4.tcp_tw_reuse=1
   ```

---

## 12. Базы Данных в Production: Высоконадежные миграции Alembic и тюнинг PostgreSQL

### 12.1 Zero-Downtime миграции и паттерн Expand and Contract
При миллионной аудитории нельзя остановить сервис на техническое обслуживание для применения `ALTER TABLE`.
**Паттерн Expand and Contract (Параллельное сосуществование):**
1. **Фаза 1 (Expand):** Добавляем новую колонку как `NULLABLE` без блокировки таблицы.
2. **Фаза 2 (Dual Write):** Код приложения обновляется и пишет одновременно в старую и новую колонку.
3. **Фаза 3 (Backfill):** Фоновый воркер чанками по 1000 записей мигрирует исторические данные:  
   `UPDATE quests SET new_col = old_col WHERE id BETWEEN ...`.
4. **Фаза 4 (Contract):** Код переключается на чтение только из новой колонки, старая колонка безопасно удаляется.

### 12.2 Асинхронные миграции в Alembic
В классическом `alembic` используется синхронный `engine`. Для asyncpg в `alembic/env.py` мы конфигурируем запуск через `async_engine`:
```python
async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
```

### 12.3 Тюнинг Connection Pool: QueuePool, max_overflow, pool_recycle, pool_pre_ping
- **`pool_size = 10`**: Количество постоянно открытых соединений в пуле.
- **`max_overflow = 20`**: Сколько дополнительных соединений разрешено открыть при резком пике нагрузки (всплеске трафика).
- **`pool_pre_ping = True`**: Перед выдачей коннекта приложению SQLAlchemy выполняет `SELECT 1`. Если межсетевой экран (Firewall/NAT) сбросил неактивный сокет, коннект тихо пересоздается без ошибки 500 для пользователя.
- **`pool_recycle = 3600`**: Принудительное закрытие и пересоздание соединений каждый час для предотвращения утечек памяти на стороне сервера БД.

### 12.4 Пессимистические блокировки: SELECT FOR UPDATE SKIP LOCKED
Если мы проектируем очередь задач или биржу раздачи контрактов между множеством воркеров:
```python
stmt = (
    select(Quest)
    .where(Quest.status == QuestStatus.AVAILABLE)
    .limit(1)
    .with_for_update(skip_locked=True)
)
```
- `FOR UPDATE`: Блокирует строку от изменения другими транзакциями.
- `SKIP LOCKED`: Воркер **не ждет** освобождения заблокированных строк другими воркерами, а сразу берет следующую свободную запись! Это исключает лок-контеншн (lock contention) и дает горизонтальное линейное масштабирование.

---

## 13. Шпаргалка к Senior/Middle Собеседованию: 10 каверзных вопросов по Backend & DevOps

---

### Вопрос 1: Race Condition при взятии квеста
**Интервьюер:** *«Два игрока одновременно нажали кнопку "Взять квест" на один и тот же контракт. Как приложение защищено от дубликата?»*  
**Блестящий ответ:**
1. **Уровень СУБД (Частичный уникальный индекс):**
   ```python
   Index(
       "uq_user_active_quest",
       "user_id",
       unique=True,
       postgresql_where=text("status = 'IN_PROGRESS' AND user_id IS NOT NULL"),
   )
   ```
2. **Атомарный условный UPDATE (Optimistic Locking):**
   `update(Quest).where(Quest.id == qid, Quest.status == 'AVAILABLE').values(status='IN_PROGRESS', user_id=uid)`
   Если строка уже изменена конкурирующим запросом, `result.rowcount == 0` — бросаем `HTTPException(409)`.

---

### Вопрос 2: Проблема N+1 в Async SQLAlchemy и скрытая ловушка selectinload
**Интервьюер:** *«Почему в асинхронной SQLAlchemy нельзя просто вызвать quest.game.title? И что произойдет, если в lazy="selectin" передать выборку из 100 000 строк?»*  
**Блестящий ответ:**
1. В `asyncio` вызов атрибута в Python синхронен — в нем невозможно сделать неявный `await`. Без предварительной загрузки падает `MissingGreenlet`.
2. `selectinload` собирает все ключи и делает второй запрос `WHERE id IN (...)`.
3. **Ловушка:** В SQL есть лимит на число параметров (65535 в PostgreSQL). При 100 000 строк `selectinload` упадет с переполнением параметров или создаст гигантский пакет. Решение: пагинация, чанкирование через `yield_per(1000)` или использование `joinedload` (LEFT JOIN).

---

### Вопрос 3: Client Disconnect в FastAPI и асинхронный генератор Depends(get_db)
**Интервьюер:** *«Клиент закрыл вкладку через 50 мс, пока выполнялся тяжелый запрос к БД. Что произойдет с сессией?»*  
**Блестящий ответ:**
1. Uvicorn детектирует разрыв TCP-сокета и бросает в корутину эндпоинта `asyncio.CancelledError`.
2. В `get_db` блок `finally: await session.close()` выполнится обязательно. Сессия автоматически откатит незакоммиченную транзакцию и вернет физическое соединение обратно в Connection Pool.

---

### Вопрос 4: Как масштабировать FastAPI приложение на многоядерном сервере?
**Интервьюер:** *«Одиночный процесс Uvicorn упирается в 1 ядро процессора из-за GIL. Как задействовать все 16 ядер сервера?»*  
**Блестящий ответ:**
Запустить **Gunicorn с классом UvicornWorker**:
`gunicorn app.main:app -w 33 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000`.  
Master-процесс слушает порт и балансирует входящие сокеты между 33 изолированными процессами ОС, преодолевая ограничение GIL.

---

### Вопрос 5: Архитектура Twelve-Factor App и изоляция конфигурации
**Интервьюер:** *«Зачем вам pydantic-settings, если можно было просто объявить переменные в constants.py?»*  
**Блестящий ответ:**
1. **Фактор III Twelve-Factor App:** Конфигурация отделена от кода. Любой параметр (размер доски, порог очков) переопределяется через переменные окружения контейнера (`docker run -e MAX_BOARD_SIZE=16`) без пересборки Docker-образа.
2. Строгая валидация типов при старте (Fail-Fast): опечатка в конфигурации не допустит запуск невалидного инстанса.

---

### Вопрос 6: Как реализовать Zero-Downtime миграцию при добавлении NOT NULL колонки?
**Интервьюер:** *«В таблице на 50 млн строк нужно добавить колонку rating NOT NULL DEFAULT 0. Если выполнить ALTER TABLE напрямую, таблица заблокируется на минуты. Как сделать это без простоя?»*  
**Блестящий ответ:**
1. Добавить колонку без дефолта как `NULL`: `ALTER TABLE quests ADD COLUMN rating INT;` (в PostgreSQL >= 11 добавление колонки с константным дефолтом мгновенно обновляет каталог метаданных, но на старых версиях или сложных выражениях требует переписывания таблицы).
2. Заполнять данные пачками в фоне (`UPDATE quests SET rating = 0 WHERE id BETWEEN ...`).
3. Добавить ограничение `NOT NULL` с флагом `NOT VALID`: `ALTER TABLE quests ADD CONSTRAINT check_rating CHECK (rating IS NOT NULL) NOT VALID;` — это не блокирует запись.
4. Валидировать ограничение в фоне: `ALTER TABLE quests VALIDATE CONSTRAINT check_rating;`.

---

### Вопрос 7: Что произойдет, если в async def эндпоинте вызвать time.sleep(10)?
**Интервьюер:** *«Разработчик случайно написал time.sleep(10) внутри async def эндпоинта. Чем это грозит?»*  
**Блестящий ответ:**
`time.sleep()` блокирует системный поток ОС, в котором крутится Event Loop.
На протяжении 10 секунд **все запросы всех остальных пользователей** сервера будут заморожены.  
**Решение:**
- Если нужна пауза: `await asyncio.sleep(10)`.
- Если нужно выполнить тяжелый CPU-расчет или синхронную библиотеку: вынести в пул потоков через `await asyncio.to_thread(func)` или `loop.run_in_executor(process_pool, cpu_heavy_func)`.

---

### Вопрос 8: Connection Pool Exhaustion — причины, диагностика и решение
**Интервьюер:** *«В логах появилась ошибка TimeoutError: QueuePool limit of size 10 overflow 20 reached. Что делать?»*  
**Блестящий ответ:**
1. **Причины:** Зависшие транзакции, не закрытые сессии (утечка сессий мимо блока `try...finally`), или медленные запросы без индексов, забивающие все соединения.
2. **Диагностика:** Посмотреть активные запросы в PostgreSQL через `SELECT * FROM pg_stat_activity WHERE state = 'active'`.
3. **Решение:** Добавить `pool_timeout=30`, оптимизировать медленные SQL-запросы, настроить `statement_timeout = '5s'` в PostgreSQL, чтобы зависшие запросы прерывались базой автоматически.

---

### Вопрос 9: Зачем нужен Nginx перед Uvicorn?
**Интервьюер:** *«Uvicorn — быстрый ASGI сервер на базе uvloop. Зачем ставить перед ним Nginx?»*  
**Блестящий ответ:**
1. **Защита от медленных клиентов (Slowloris):** Nginx буферизует входящий трафик и отдает Uvicorn готовый пакет.
2. **Безопасность:** Ограничение частоты запросов (`limit_req_zone`), защита от DDoS.
3. **SSL/TLS и HTTP/2 termination:** Высокопроизводительное аппаратное шифрование в C-коде Nginx.
4. **Статика:** Nginx отдает файлы изображений и бандлы напрямую через системный вызов ядра Linux `sendfile(2)`, минуя рантайм Python.

---

### Вопрос 10: Чем отличается graceful shutdown в Docker контейнерах и как его протестировать?
**Интервьюер:** *«Что делает команда docker stop и почему иногда контейнер "висит" ровно 10 секунд перед остановкой?»*  
**Блестящий ответ:**
1. `docker stop` посылает процессу с `PID 1` сигнал `SIGTERM` и запускает таймер на 10 секунд (по умолчанию). Если процесс не завершился, посылается `SIGKILL`.
2. **Почему висит 10 секунд:** Если в Dockerfile команда запуска написана в shell-форме (`CMD uvicorn app.main:app`), то `PID 1` получает оболочка `/bin/sh`, которая по умолчанию **не транслирует сигналы** дочернему процессу Python! Uvicorn не получает `SIGTERM` и убивается по таймауту.
3. **Правильное решение:** Всегда использовать exec-форму JSON массива: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]`. В этом случае Python становится `PID 1` и корректно перехватывает сигнал.

---

### Вопрос 11: Паттерн "Технический реролл" без штрафов: как проектировать исключительную бизнес-логику в соревновательных системах?
**Интервьюер:** *«В турнирной системе есть механика платного реролла со штрафом к очкам. Как спроектировать бесплатный технический реролл (если игра вылетает/не запускается), исключив возможность читерства и дублирования кода?»*  
**Блестящий ответ:**
1. **Параметризация CRUD уровня:** Функция `reroll_quest(..., is_technical: bool = False, reason: Optional[str] = None)` объединяет общую логику (поиск кандидата из той же категории карточки, инфляционные расчеты, обновление связей) с разветвлением эффектов:
   - При `is_technical=False`: декрементируется `user.rerolls_left` и инкрементируется `quest.reroll_count` (накладывающий штраф -10%/реролл на финальную награду).
   - При `is_technical=True`: баланс `user.rerolls_left` не затрагивается, `quest.reroll_count` не увеличивается (награда не штрафуется), но инкрементируется аудит-поле `quest.technical_reroll_count` и сохраняется причина `quest.technical_reroll_reason`.
2. **Аудируемость и прозрачность:** Сохранение причины технического реролла (категория проблемы + комментарий игрока) позволяет судьям/администраторам отслеживать абуз и при необходимости проверять отчеты об ошибках.
3. **Бесшовный UX через HTMX:** Технический реролл возвращает тот же анимационный барабан рулетки (`roulette_modal.html` с бейджем `is_technical=True`), создавая ощущение честной и плавной замены.

---

### Вопрос 12: Валидация и агрегация пользовательских числовых метрик (Actual Playtime Tracking)
**Интервьюер:** *«Как правильно собирать и агрегировать фактически затраченное игроком время (actual_hours) при завершении квеста?»*  
**Блестящий ответ:**
1. **Валидация на входе (Defense in Depth):**
   - HTML5 / HTMX уровень: `<input type="number" step="0.1" min="0.1" max="9999" required>` гарантирует ввод положительного десятичного числа и блокирует пустую отправку в браузере.
   - Pydantic / FastAPI уровень: `actual_hours: Optional[float] = Form(None)` валидирует тип данных на бэкенде.
   - CRUD уровень: проверка `float(actual_hours) > 0` и округление до 1 знака (`round(val, 1)`) для консистентного хранения в SQLite/Postgres.
2. **Отказоустойчивость модальных окон:** Модальное окно завершения квеста (`completion_modal.html`) инкапсулирует `<form>`, где выбор исхода челленджа («Выполнен» / «Провален» / «Обычное завершение») отправляется как значение нажатой кнопки (`name="challenge_status"`), автоматически включая поле `actual_hours` в единый POST-запрос.
3. **Агрегация статистики:** В профиле игрока вычисляется `total_actual_hours = round(sum(q.actual_hours for q in raw_history if q.actual_hours is not None), 1)` и выводится на отдельную плитку турнирных показателей наряду с винрейтом и очками.

---

### Вопрос 13: Мгновенная реактивность через HTMX Out-of-Band (OOB) Swaps и паттерн «Interactive Spin-on-Demand»
**Интервьюер:** *«Когда пользователь берет квест и открывает колесо рулетки, как обновить активные квесты на доске и счетчики в шапке без SPA-фреймворка (React/Vue/Redux) и без ожидания перезагрузки страницы?»*  
**Блестящий ответ:**
1. **Механика HTMX Out-of-Band Swaps (`hx-swap-oob`):**
   - Кнопка на карточке квеста отправляет запрос с конкретной целью: `hx-post="/quests/{id}/take"` с `hx-target="#roulette-modal-container"`.
   - В синхронном REST-ответе FastAPI возвращает составной фрагмент HTML:
     - Основной блок: `<div id="roulette-modal">...</div>` (попадает в `hx-target`).
     - OOB-блок доски: `<div id="main-board" hx-swap-oob="outerHTML">...</div>` (HTMX находит элемент `#main-board` на странице и мгновенно заменяет его актуальным состоянием из базы, где взятый квест уже находится в колонке «В Процессе»).
     - OOB-блок ресурсов: `<div id="user-stats-bar" hx-swap-oob="outerHTML">...</div>` (обновляет бейдж количества активных слотов `1/1`).
   - Итог: ни одного вебсокета, ни строчки JS-стейт-менеджера — страница консистентна и мгновенно реактивна.
2. **Геймификация и браузерные ограничения (Spin on Demand vs Auto-spin):**
   - Автоматическое вращение рулетки сразу при открытии модального окна лишает игрока ощущения контроля (player agency) и эффекта ожидания (anticipation).
   - Более того, современные браузеры (Chrome, Firefox, Safari) блокируют звук `AudioContext` (щелчки барабана), если он инициирован без прямого пользовательского жеста (User Gesture Autoplay Policy).
   - Реализация: колесо инициализируется в статичном положении (`drawWheel(0)`), а в центре размещается пульсирующая интерактивная кнопка «КРУТИТЬ». Клик игрока:
     1) Резюмирует аудиоконтекст (`audioCtx.resume()`), гарантируя чистый звук вращения;
     2) Запускает requestAnimationFrame-анимацию с кубическим замедлением (cubic easing);
     3) Превращает кнопку в «СТОП» для возможности ускоренного пропуска.

---

### Вопрос 14: Оптимизация задержек при открытии игровых интерфейсов (Zero-blocking Event Loop) и отказоустойчивое разрешение CDN-ассетов (Resilient Asset Preloading & Procedural Fallbacks)
**Интервьюер:** *«При открытии модального окна рулетки сервер отвечал с задержкой в 3.5 секунды, а в секторах колеса не отображались картинки части игр (404 на CDN). Как локализовать и устранить узкие места в асинхронном стеке FastAPI и на клиенте?»*  
**Блестящий ответ:**

1. **Диагностика и устранение синхронного блокирующего I/O (Zero-blocking Event Loop):**
   - **Корень проблемы:** Вспомогательная функция разрешения ссылок `resolve_single_image_url()` использовала синхронную библиотеку `requests.get(f"https://store.steampowered.com/api/appdetails?appids={appid}", timeout=2.5)` прямо в контексте обработки HTTP-запроса `take_quest_endpoint`. При обращении к некэшированным `appid >= 3000000` или при сетевом троттлинге Steam вызов блокировал весь главный поток asyncio (Event Loop) на 2.5–3.5 секунды.
   - **Решение:** Полное устранение синхронных сетевых вызовов в потоке веб-запроса. Переход на чистую алгоритмическую нормализацию ссылок в памяти и мгновенный возврат ответа:
     ```python
     def normalize_steam_image_url(url: Optional[str], appid: Optional[int] = None) -> Optional[str]:
         if not url:
             return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg" if appid else None
         if re.search(r'/[0-9a-f]{32,45}/header\.jpg', url):
             return url.replace('/header.jpg', '/capsule_231x87.jpg')
         return url
     ```
   - **Результат:** Время генерации модального окна сократилось с 3540 мс до 40–90 мс (ускорение более чем в 35 раз!).

2. **Специфика CDN Steam и каскадная нормализация (CDN Hash Mismatch):**
   - **Анатомия ошибки 404:** Steam Store CDN генерирует уникальные SHA1-хэши отдельно для каждого типа ассета. Скрейпер сохранял хэш от `capsule_231x87.jpg`, после чего наивная замена строки на `header.jpg` приводила к запросу несуществующего пути `{hash}/header.jpg` (HTTP 404). При этом исходный файл `{hash}/capsule_231x87.jpg` доступен с кодом 200 OK.
   - **Миграция БД:** Единовременная пакетная нормализация более 3000 записей в SQLite (`parser/data/games.db` и `hpg.db`) восстановила доступность сотен обложек.
   - **Приоритезация запросов в SQLite:** В SQL-выборку добавлен предикат упорядочивания:
     ```sql
     ORDER BY (CASE WHEN image_url LIKE '%shared.fastly%' OR image_url LIKE '%/capsule_%' THEN 0 ELSE 1 END), RANDOM()
     ```
     что гарантирует первоочередной выбор тайтлов со 100% валидными CDN-обложками без потери случайности.

3. **Клиентская отказоустойчивость: Двунаправленный fallback и процедурные холсты:**
   - **Двунаправленный перебор CDN:** На клиенте функция `getCandidateUrls` строит цепочку попыток: `url` -> замена `header.jpg` на `capsule_231x87.jpg` -> обратная замена `capsule` на `header` -> прямые пути `shared.akamai` и `cdn.akamai`.
   - **Процедурная генерация при сбое сети (In-Memory Canvas):** Если игра удалена из Steam или клиент находится оффлайн, функция `createProceduralCover` генерирует стилизованную ведьмачью карточку с золотым тиснением, рунами и названием жанра на оффскрин-холсте `460x215` через `toDataURL()`. Ни один сектор колеса никогда не остается пустым или сломанным.
   - **Информативный прелоадер:** Центральная кнопка колеса и статусная строка показывают точный прогресс предзагрузки (`[X/15]`), превращаясь в пульсирующую кнопку «🎲 КРУТИТЬ» по готовности или по безопасному таймауту (2.0 с).


