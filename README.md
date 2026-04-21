# Vels Claude Light

Минимальный Telegram-мост к Claude Code CLI. Один приватный чат = одна сессия Claude.

## Быстрая установка на VPS

На свежем Ubuntu 22.04+/Debian 12+:

1. Установите и авторизуйте Claude Code CLI (это делается один раз руками, требует Anthropic-аккаунта):

   ```bash
   npm install -g @anthropic-ai/claude-code
   claude   # выполните логин по инструкции
   ```

2. Запустите установщик бота — одна команда:

   ```bash
   curl -sSL https://raw.githubusercontent.com/<owner>/vels-claude-light/main/install.sh | bash
   ```

   Скрипт спросит:
   - **Токен Telegram-бота** (получить у [@BotFather](https://t.me/BotFather): `/newbot`)
   - **Ваш Telegram user ID** (узнать у [@userinfobot](https://t.me/userinfobot): `/start`)
   - **Рабочую директорию** (папка, в которой Claude будет работать)

   И поднимет бот как systemd-сервис, который сам перезапускается при любых сбоях.

3. Откройте Telegram и напишите боту — он должен ответить.

### Удаление

```bash
sudo /opt/vels-claude-light/uninstall.sh
```

Скрипт спросит, удалять ли рабочую папку и сервисного пользователя.

## Команды бота

- `/new` (или `/clear`) — сбросить контекст, начать новую сессию Claude
- `/compact` — попросить Claude сжать свою историю
- `/stop` — прервать текущую генерацию
- `/status` — статус текущей сессии

Всё остальное (текст, картинки, файлы) отправляется в Claude как prompt.

## Разработка (локально)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # и отредактируйте
python -m src.main
```

Переменные окружения — см. `.env.example`.

## Структура

- `src/bot.py` — aiogram-диспетчер, команды, очередь
- `src/bridge.py` — subprocess-обёртка над `claude -p`
- `src/streaming.py` — `sendMessageDraft`-стриминг с таймером
- `src/uploads.py` — сохранение картинок и файлов из Telegram
- `src/storage.py` — JSON-хранилище session_id
- `scripts/vels-claude-light.service` — systemd unit (шаблон)
- `install.sh` / `uninstall.sh` — установщик
