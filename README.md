# 🤖 Telegram Video Downloader Bot

Бесплатный Telegram-бот для скачивания видео с **YouTube, TikTok, Instagram и VK**.
Построен на **aiogram 3.x + FastAPI + Uvicorn + yt-dlp + ffmpeg**.

Бот показывает **рекламное сообщение перед скачиванием** (текст и ссылка
настраиваются в `.env`), благодаря чему вы можете зарабатывать на рекламе.

---

## ✨ Возможности

- `/start` — приветствие с кнопками «Как пользоваться» и «Поддержать автора».
- Отправка ссылки → проверка доступности через yt-dlp.
- Определение максимального качества и размера видео.
- **Рекламное сообщение** (`AD_TEXT`) с кнопкой «Перейти к рекламодателю» (`AD_LINK`).
- Кнопка **«📥 Скачать видео»** запускает фоновую загрузку (`asyncio.subprocess`).
- Сообщение «Идёт загрузка…» и прогресс в процентах.
- Отправка файлом (≤ 50 МБ), либо ссылкой на transfer.sh (≤ 2 ГБ),
  либо сообщение о размере для файлов больше лимитов.
- **Реклама показывается один раз за сессию/интервал** через SQLite
  (настраивается `AD_COOLDOWN_HOURS`).
- Логирование всех скачиваний в SQLite + админ-команда `/stats`.
- FSM-форма обратной связи `/feedback`.
- Healthcheck и webhook для деплоя на Railway 24/7.

---

## 📁 Структура проекта

```
.
├── config.py        # Загрузка .env (BOT_TOKEN, AD_TEXT, AD_LINK, MAX_FILE_SIZE и др.)
├── database.py      # SQLite: пользователи, реклама, логи скачиваний, FSM
├── downloader.py    # Асинхронный yt-dlp (asyncio.subprocess) + transfer.sh
├── keyboards.py     # Inline-клавиатуры
├── handlers.py      # Команды, ссылки, callback-кнопки, FSM
├── main.py          # Точка входа: FastAPI + webhook/long-polling + healthcheck
├── requirements.txt
├── Dockerfile
├── .env.example     # Шаблон переменных окружения
└── README.md
```

---

## 🚀 Локальный запуск (Long Polling — просто и бесплатно)

1. Установите Python 3.10+ и **ffmpeg** (в Windows — `winget install ffmpeg`).
2. Клонируйте проект и создайте виртуальное окружение:
   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Linux/macOS
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Создайте файл `.env` из шаблона:
   ```bash
   cp .env.example .env
   ```
   Впишите свой `BOT_TOKEN` (получить у [@BotFather](https://t.me/BotFather)).
5. Запустите:
   ```bash
   python main.py
   ```
6. Отправьте боту ссылку и проверьте работу.

> Для локального запуска используйте режим long-polling
> (`USE_LONG_POLLING=true`, `USE_WEBHOOK=false`) — внешний URL не нужен.

---

## 🐳 Запуск через Docker

```bash
docker build -t video-downloader-bot .
docker run --env-file .env -p 8000:8000 video-downloader-bot
```

Healthcheck: `GET /health` → `{"status":"ok"}`.

---

## 🚄 Деплой на Railway 24/7

Railway позволяет держать бота онлайн круглосуточно бесплатно (startup-план).

### Вариант 1 — Long Polling (проще всего, без домена)

1. Залейте код в GitHub-репозиторий.
2. В [Railway.app](https://railway.app) нажмите **New Project → Deploy from GitHub repo**.
3. Railway сам найдёт `Dockerfile` и поднимет контейнер.
4. В настройках сервиса (Variables) укажите переменные:
   - `BOT_TOKEN=...`
   - `AD_TEXT=...`, `AD_LINK=...`
   - `USE_LONG_POLLING=true`, `USE_WEBHOOK=false`
   - `ADMIN_IDS=...` (ваш Telegram ID)
5. Railway сам прокидывает `PORT` → приложение слушает `0.0.0.0:8000`.
6. Приложение перезапускается автоматически при каждом деплое — бот работает 24/7.

### Вариант 2 — Webhook (надёжнее, нужен публичный URL)

1. Создайте в Railway сервис и получите публичный домен
   (**Settings → Networking → Generate Domain**), например `https://mybot.up.railway.app`.
2. В переменных укажите:
   - `USE_WEBHOOK=true`
   - `USE_LONG_POLLING=false`
   - `PUBLIC_URL=https://mybot.up.railway.app`
   - `WEBHOOK_SECRET=случайная-строка` (защита эндпоинта)
3. При старте бот сам вызовет `setWebhook` на `PUBLIC_URL + /webhook`.

---

## 📋 Настройка рекламы (главная фича)

В `.env`:

| Переменная | Описание |
|---|---|
| `AD_TEXT` | Текст рекламного сообщения перед скачиванием |
| `AD_LINK` | Ссылка на рекламодателя (кнопка «Перейти к рекламодателю») |
| `AD_BUTTON_LABEL` | Текст кнопки перехода к рекламодателю |
| `AD_COOLDOWN_HOURS` | Как часто показывать рекламу одному пользователю, в часах. `0` = каждый раз |

**Как это работает:** пользователь отправляет ссылку → бот проверяет видео →
если нужно, показывает рекламу → отдельной кнопкой предлагает «📥 Скачать видео».
Реклама показывается не чаще, чем раз в `AD_COOLDOWN_HOURS` часов (лог в SQLite).

---

## 🛠 Возможные проблемы и решения

- **`yt-dlp: not found`** — установите yt-dlp через `pip install yt-dlp` или в Docker
  (он уже включён в `requirements.txt`).
- **`ffmpeg: not found`** — установите ffmpeg (в Docker он уже стоит из apt).
- **Видео недоступно / private** — бот корректно сообщит об ошибке.
- **Instagram требует логин** — для некоторых приватных постов может потребоваться
  cookies. В базовой версии работает только для публичного контента.
- **Файл больше 2 ГБ** — бот сообщит размер и предложит скачать через сторонние сервисы.

---

## 📊 Статистика

- Команда `/stats` (доступна только `ADMIN_IDS`) показывает: пользователей,
  скачиваний (всего/за день), успехов, ошибок и показов рекламы.
- Все данные хранятся в SQLite (`bot.db`).

---

## ⚠️ Дисклеймер

Используйте бота в соответствии с правилами платформ и законодательством.
Скачивание контента может нарушать условия использования некоторых сервисов.