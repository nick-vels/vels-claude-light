# Vels Claude Light

Минимальный Telegram-мост к Claude Code CLI. Один приватный чат = одна сессия Claude.

## Команды

- `/new` (или `/clear`) — сбросить контекст, начать новую сессию Claude
- `/compact` — попросить Claude сжать свою историю
- `/stop` — прервать текущую генерацию
- `/status` — статус текущей сессии

Всё остальное отправляется в Claude как обычный prompt.

## Установка

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # затем отредактируйте .env
python -m src.main
```

## Переменные окружения

Смотрите `.env.example`. Обязательные: `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS`, `WORKING_DIR`.

## Production (systemd)

Юнит-файл лежит в `scripts/vels-claude-light.service`. Типичный путь деплоя: `/opt/vels-claude-light/`.
