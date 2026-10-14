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
8. [Server-Driven UI (Jinja2 + HTMX) и локальный запуск без Docker](#8-server-driven-ui-jinja2--htmx-и-локальный-запуск-без-docker)
   - [Почему HTMX вместо React/Vue (Server-Driven UI)](#81-почему-htmx-вместо-reactvue-server-driven-ui)
   - [Анатомия HTMX-свопов (hx-target и hx-swap)](#82-анатомия-htmx-свопов-hx-target-и-hx-swap)
   - [Двойной режим БД: SQLite (aiosqlite) для локального запуска и PostgreSQL для Docker](#83-двойной-режим-бд-sqlite-aiosqlite-для-локального-запуска-и-postgresql-для-docker)
   - [Кросс-версионность Python: от 3.9 до 3.12 (typing и backport)](#84-кросс-версионность-python-от-39-до-312-typing-и-backport)
9. [Механика «Скрытый контракт» (Condition-Based Contracts) и Out-Of-Band HTMX](#9-механика-скрытый-контракт-condition-based-contracts-и-out-of-band-htmx)
   - [Геймдизайн: зачем скрывать название игры на бирже?](#91-геймдизайн-зачем-скрывать-название-игры-на-бирже)
   - [Разделение состояния через @computed_field в Pydantic](#92-разделение-состояния-через-computed_field-в-pydantic)
   - [Мгновенная синхронизация колонок через hx-swap-oob (Out-of-Band)](#93-мгновенная-синхронизация-колонок-через-hx-swap-oob-out-of-band)

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

8. [Server-Driven UI (Jinja2 + HTMX) и локальный запуск без Docker](#8-server-driven-ui-jinja2--htmx-и-локальный-запуск-без-docker)
   - [Почему HTMX вместо React/Vue (Server-Driven UI)](#81-почему-htmx-вместо-reactvue-server-driven-ui)
   - [Анатомия HTMX-свопов (hx-target и hx-swap)](#82-анатомия-htmx-свопов-hx-target-и-hx-swap)
   - [Двойной режим БД: SQLite (aiosqlite) для локального запуска и PostgreSQL для Docker](#83-двойной-режим-бд-sqlite-aiosqlite-для-локального-запуска-и-postgresql-для-docker)
   - [Кросс-версионность Python: от 3.9 до 3.12 (typing и backport)](#84-кросс-версионность-python-от-39-до-312-typing-и-backport)

---

## 8. Server-Driven UI (Jinja2 + HTMX) и локальный запуск без Docker

### 8.1 Почему HTMX вместо React/Vue (Server-Driven UI)?
В классическом SPA (Single Page Application) вы вынуждены:
1. Писать код на двух языках (Python на бэкенде, TypeScript/JavaScript на фронтенде).
2. Дублировать модели данных и логику валидации.
3. Собирать тяжелый bundle через Vite/Webpack и настраивать CORS.

**HTMX возвращает нас к веб-стандартам (HTML-over-the-wire):**
- Сервер возвращает не сырой JSON, а готовые кусочки HTML (Jinja2 partials).
- Браузер просто заменяет целевой элемент в DOM (`hx-target` + `hx-swap`).
- Никакого клиентского JavaScript-фреймворка, мгновенный рендеринг и нулевой runtime overhead.

### 8.2 Анатомия HTMX-свопов
1. **Взятие контракта (`hx-post="/quests/{id}/take"`):**
   - Цель: `hx-target="#board-container"`, метод `hx-swap="innerHTML"`.
   - Бэкенд распаковывает подарок (если это был Санта-бокс), конвейер пополняет доску новой игрой до 12, а сервер возвращает актуальный список карточек.
2. **Дроп контракта (`hx-post="/quests/{id}/drop"`):**
   - Цель: `hx-target="closest .quest-card"`, метод `hx-swap="outerHTML"`.
   - Сервер возвращает статус `200 OK` с пустым телом, и карточка бесшовно исчезает из колонки «В работе».
3. **Реролл рулетки (`hx-post="/quests/{id}/reroll"`):**
   - Цель: `hx-target="closest .quest-card"`, метод `hx-swap="outerHTML"`.
   - Сервер выбирает новую игру из пула, пересчитывает штраф (-10%) и возвращает только обновленный HTML одной конкретной карточки.

### 8.3 Двойной режим БД: SQLite (aiosqlite) для локального запуска и PostgreSQL для Docker
В enterprise-архитектуре важно, чтобы приложение можно было запустить в один клик без поднятия тяжелой инфраструктуры:
- **В Docker / Production**: `DATABASE_URL=postgresql+asyncpg://...` (максимальная производительность, пулы соединений, отказоустойчивость).
- **Локально на машине разработчика**: `DATABASE_URL=sqlite+aiosqlite:///./hpg.db` (файл базы создается на лету, не требует установленного Docker Desktop или сервера PostgreSQL).
В `app/database.py` движок автоматически адаптирует параметры:
```python
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
```

### 8.4 Кросс-версионность Python: от 3.9 до 3.12
Синтаксис объединения типов `int | None` (PEP 604) появился только в Python 3.10.
Чтобы проект одинаково стабильно работал и на локальной машине с Python 3.9, и в современном контейнере Python 3.12:
1. Во все модули добавлена строчка `from __future__ import annotations` (PEP 563 — отложенная оценка строковых аннотаций во время компиляции AST).
2. Подключен `eval-type-backport` для корректного разрешения Pydantic v2 на старых версиях рантайма.
3. В `Quest` модели использован `Mapped[Optional[int]]` для совместимости декларативного маппера SQLAlchemy 2.0.

---

## 9. Механика «Скрытый контракт» (Condition-Based Contracts) и Out-Of-Band HTMX

### 9.1 Геймдизайн: зачем скрывать название игры на бирже?
Если показывать конкретные названия игр (например, «Hollow Knight» или «Portal 2») прямо на бирже:
- Игроки начинают охотиться только за знакомыми играми («черрипикинг»).
- Менее популярные игры «зависают» на доске, снижая динамику марафона.

**Решение через «Скрытые контракты»:**
1. **На бирже (AVAILABLE)** видна не игра, а условия:
   - **STEAM**: Часовой диапазон (например, `10–20 ч`), жанр (`Action Roguelite`, `Метроидвания`).
   - **PRESET**: Название пресета (`Пресет: Метроидвании и 2D`, `Пресет: Инди-эстетика`).
   - **SERIES**: Франшиза (`Франшиза Soulsborne`, `Трилогия BioShock`).
   - **EMULATOR**: Платформа (`Эмулятор: PlayStation 1 (Ретро)`, `Эмулятор: Nintendo 64`).
   - **GOTY**: Шедевр года с крупным банком очков и большим хронометражем (`35+ ч`).
   - **SANTA**: Таинственный подарок (50/50 Топ или Уголёк).
2. **Раскрытие (Unveil)**: игра раскрывается только в момент нажатия «Взять контракт» и перемещается в правую колонку «В работе».

### 9.2 Разделение состояния через `@computed_field` в Pydantic
Вместо написания сложной логики в Jinja2-шаблонах, модель ответа [QuestResponse](file:///c:/Users/Xiaomi/hpg/app/schemas/quest.py) вычисляет всё на стороне Python:
- `is_revealed`: `True`, только если квест в статусе `IN_PROGRESS` или `COMPLETED`.
- `display_title`: На бирже отдает название пресета/серии/типа, а при взятии — настоящее название `game.title`.
- `display_time`: На бирже отдает безопасный интервал `time_range` (`5–10 ч`, `10–20 ч`), а в работе — точное время `hltb_hours`.

### 9.3 Мгновенная синхронизация колонок через `hx-swap-oob` (Out-of-Band)
При взятии контракта нужно обновить:
1. Левую колонку `#board-container` (удалить взятую карточку и добавить свежую с конвейера).
2. Правую колонку `#active-quests-container` (отобразить взятую карточку с уже раскрытой игрой).

В традиционных фреймворках для этого нужен WebSocket, Redux или два отдельных AJAX-запроса.
В HTMX это решается одной строчкой в ответе сервера:
```python
# Возвращаем новую сетку биржи + OOB-блок для правого контейнера
return HTMLResponse(content=board_cards_html + f'<div id="active-quests-container" hx-swap-oob="innerHTML">{active_cards_html}</div>')
```
HTMX парсит ответ, обновляет основную цель `#board-container`, а затем автоматически находит в DOM элемент `#active-quests-container` и бесшовно обновляет его содержимое!

---

*Приложение полностью готово к соревнованию гильдии в режиме таинственных контрактов!*




