# Парсер игр из Steam и HowLongToBeat (HLTB)

Автономное модульное приложение для парсинга каталога игр Steam и сбора времени прохождения основной сюжетной линии из HowLongToBeat.

---

## 🎯 Возможности

- **Полный сбор необходимых данных**:
  - **Из Steam**: Название игры (`title`), ссылка на обложку (`image_url`), процент положительных отзывов (`review_percentage`), дата выхода (`release_date`), разработчик (`developer`), метки/теги продукта (`tags`), прямая ссылка на страницу игры (`steam_url`).
  - **Из HowLongToBeat**: Ссылка на страницу игры (`hltb_url`), количество часов на прохождение сюжета (`hltb_main_story_hours`).
- **Фильтрация по дате**: Парсятся только игры, которые **уже вышли до сегодняшнего дня** (игры в статусе «Coming soon», «TBA» или с будущими датами релиза отсекаются автоматически).
- **Инкрементальный режим (допарсинг новинок)**:
  - При повторном запуске парсер проверяет свежие релизы сверху вниз (`Released_DESC`).
  - Пропускает игры, которые уже есть в базе данных.
  - Автоматически завершает работу, когда доходит до ранее спарсенного слоя базы.
  - **Вам не нужно заново парсить десятки тысяч игр ради нескольких новинок!**
- **Надёжное хранилище SQLite + экспорт в большой файл**:
  - Все данные сохраняются на лету в транзакционную базу данных SQLite (`parser/data/games.db`).
  - Если процесс прервётся (Ctrl+C или сбой сети), ни одна игра не потеряется.
  - Автоматический экспорт в три удобных формата в папку `parser/output/`:
    1. **`steam_hltb_games.jsonl`** (JSON Lines — **рекомендуемый формат для больших данных**, читается построчно без расхода оперативной памяти);
    2. **`steam_hltb_games.json`** (Стандартный JSON-массив);
    3. **`steam_hltb_games.csv`** (Таблица для Excel / Google Sheets).

---

## 📁 Структура папки `parser`

```text
parser/
├── data/
│   └── games.db                # База данных SQLite с индексами
├── output/
│   ├── steam_hltb_games.jsonl  # Итоговый большой файл (JSON Lines)
│   ├── steam_hltb_games.json   # Итоговый файл JSON
│   └── steam_hltb_games.csv    # Итоговый файл CSV
├── config.py                   # Конфигурация, URL-адреса, задержки и лимиты
├── db.py                       # Работа с базой данных SQLite (upsert, очереди, выборка)
├── steam.py                    # Клиент Steam (поиск, даты, теги, разработчики, отзывы)
├── hltb.py                     # Клиент HowLongToBeat (авторизация токенов, нечеткий поиск)
├── exporter.py                 # Экспорт данных в JSONL, JSON, CSV
├── main.py                     # Главный CLI-интерфейс
├── requirements.txt            # Зависимости
└── README.md                   # Документация
```

---

## 🚀 Установка и запуск

Парсер использует виртуальное окружение проекта:

```bash
# Установка зависимостей (если требуется)
pip install -r parser/requirements.txt
```

### 1. Инкрементальный запуск (по умолчанию)
Парсит новинки, вышедшие с момента прошлого запуска, и обновляет файлы экспорта:

```bash
python parser/main.py
# или явно:
python parser/main.py --mode incremental
```

Ограничить количество новых игр (например, спарсить первые 50 новинок):
```bash
python parser/main.py --mode incremental --limit 50
```

### 2. Сбор каталога (Full Mode)
Парсит игры каталога Steam (с возможностью сортировки):

# Спарсить 100 популярных игр с наивысшими оценками
python parser/main.py --mode full --limit 100 --sort Reviews_DESC

# Продолжить сбор каталога с определенного смещения (например, после 4000 игр):
python parser/main.py --mode full --start-offset 4050

# Быстрый сбор каталога без запросов к HLTB (HLTB можно догрузить позже)
python parser/main.py --mode full --start-offset 4050 --skip-hltb
```

### 3. Догрузка данных HowLongToBeat
Если часть игр была спарсена с флагом `--skip-hltb` или в HLTB появились новые данные:

```bash
python parser/main.py --mode hltb
```

### 4. Повторный экспорт базы в файлы
Сгенерировать обновлённые `.jsonl`, `.json` и `.csv` из базы данных SQLite:

```bash
python parser/main.py --mode export
```

### 5. Просмотр статистики
Посмотреть количество игр в базе, процент с отзывами и среднее время прохождения:

```bash
python parser/main.py --mode stats
```

---

## 📋 Пример записи в файле экспорта

```json
{
  "title": "The WereCleaner",
  "image_url": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2795000/header.jpg",
  "review_percentage": 99.0,
  "release_date": "2024-05-07",
  "developer": "Howlin' Hugs",
  "tags": [
    "Stealth",
    "Casual",
    "Cartoony",
    "Dark Humor",
    "Cute",
    "Strategy",
    "Arcade",
    "Singleplayer",
    "Tactical",
    "Retro",
    "Action-Adventure"
  ],
  "steam_url": "https://store.steampowered.com/app/2795000/",
  "hltb_url": "https://howlongtobeat.com/game/150023",
  "hltb_main_story_hours": 0.7,
  "steam_appid": 2795000,
  "review_count": 8526,
  "review_desc": "Overwhelmingly Positive"
}
```

---

## 🛡️ Надёжность и защита от блокировок
- Парсер соблюдает вежливые задержки между запросами к Steam и HowLongToBeat (`config.py`).
- Поддерживается автоматическое обновление токенов сессии HLTB при устаревании (HTTP 403) и экспоненциальная задержка при лимитах (HTTP 429).
- Прерывание по `Ctrl+C` корректно фиксирует текущие данные в базе и завершает работу без повреждения файлов.
