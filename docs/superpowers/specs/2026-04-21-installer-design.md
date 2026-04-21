# Vels Claude Light — installer design

Status: approved (brainstorm), pending implementation plan.
Date: 2026-04-21.

## Goal

Позволить не-техническому практиканту развернуть бот на своём Linux-VPS
за одну команду и три ответа в терминале. Никакого обновления,
рестарта руками, сложных настроек.

## Scope

- **In**: Linux-only установка (Ubuntu/Debian 22.04+, Debian 12+).
- **Out**: macOS, Windows, автообновление, Docker, мультиинстанс на одном хосте.
- **Prereq**: на VPS уже установлен и авторизован `claude` CLI (Claude Code).
  Его bootstrap — не в зоне ответственности установщика.

## Distribution

Публичный GitHub-репозиторий. Имя — по усмотрению автора, без требования
приватности: в коде нет секретов, токены уходят в `.env` на VPS.
`<owner>` в ссылках ниже — плейсхолдер, заменяется на реальный GitHub
username/organization при первой публикации.

Две эквивалентные точки входа:

```bash
# A. Однострочник
curl -sSL https://raw.githubusercontent.com/<owner>/vels-claude-light/main/install.sh | bash

# B. Классический git clone
git clone https://github.com/<owner>/vels-claude-light.git
cd vels-claude-light
./install.sh
```

Скрипт идентичный, просто в варианте A он сам делает клон в `/opt/`
после получения sudo-пароля.

## UX установщика

### Этап 1 — баннер и предчек

```
██╗   ██╗███████╗██╗     ███████╗
██║   ██║██╔════╝██║     ██╔════╝
██║   ██║█████╗  ██║     ███████╗
╚██╗ ██╔╝██╔══╝  ██║     ╚════██║
 ╚████╔╝ ███████╗███████╗███████║
  ╚═══╝  ╚══════╝╚══════╝╚══════╝

       Vels Claude Light · installer
──────────────────────────────────────

🔍 Проверяю окружение
   ✓ Python 3.12                  (есть)
   ✓ python3-venv, python3-pip    (есть)
   ✗ git                          → ставлю через apt…
   ✗ claude CLI                   → установите сами:
                                     npm install -g @anthropic-ai/claude-code
                                     claude       (залогиньтесь)
```

- Недостающие apt-пакеты (`git`, `python3-venv`, `python3-pip`) ставятся
  автоматически через `sudo apt-get install -y`.
- `claude` CLI установщик **не ставит**: требует от пользователя
  поставить самостоятельно и прекращает работу с подсказкой.
- Всё остальное (Node.js, Anthropic-аутентификация) — вне скоупа.

### Этап 2 — онбординг (`.env`)

Три вопроса, один за другим, с валидацией:

```
⚙️  Настройка бота
──────────────────────────────────────

1/3  Токен Telegram-бота
     Получите у @BotFather командой /newbot.
     Выглядит примерно так: 1234567890:AAF...XyZ

     Токен:  ▌

2/3  Ваш Telegram user ID
     Узнайте у @userinfobot (отправьте ему /start).
     Если нужно пустить несколько людей — через запятую.

     ID:  ▌

3/3  Рабочая директория Claude
     Папка, с которой Claude будет работать (cwd).
     Если её нет — скрипт создаст. Enter = дефолт.

     Путь [~/workspace]:  ▌
```

Валидация:

| Поле | Правило |
|---|---|
| `TELEGRAM_BOT_TOKEN` | regex `^\d+:[A-Za-z0-9_-]{30,}$` + `getMe`-проверка |
| `ALLOWED_USER_IDS` | все части — положительные целые |
| `WORKING_DIR` | раскрыть `~`, путь абсолютный, создать если нет, проверить `-w` |

Если `.env` уже есть — показать текущие значения звёздочками (token
полностью маскируется, ID частично), предложить «оставить / переввести»
по каждому полю отдельно.

### Этап 3 — установка под капотом

Идемпотентно (можно запускать повторно):

1. `sudo` один раз в начале.
2. `apt-get install -y` недостающих пакетов.
3. Определить «кто будет владельцем сервиса» (см. ниже).
4. `git clone` или `git pull` в `/opt/vels-claude-light/`.
5. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
6. Записать `.env` (`chmod 600`, владелец — service user).
7. Создать `WORKING_DIR`, если не существует, права — service user.
8. Сгенерировать `/etc/systemd/system/vels-claude-light.service` из шаблона
   с подставленным `User=`.
9. `systemctl daemon-reload && systemctl enable --now vels-claude-light`.
10. Через 3 секунды — `systemctl is-active` + `journalctl -u … -n 10`.
11. Показать итоговый экран.

### Этап 4 — выбор service user

| Кто запустил install.sh | Что делаем |
|---|---|
| Обычный user через `sudo` (т.е. `$SUDO_USER` установлен) | `User=$SUDO_USER` в unit'е, ничего не создаём |
| Обычный user без `sudo` | Выходим с ошибкой «Запустите через sudo» |
| Прямой root (SSH как `root@host`) | Создаём системного пользователя `vels-bot` (`useradd --system --create-home --home-dir /var/lib/vels-bot --shell /usr/sbin/nologin --comment 'vels-claude-light service account' vels-bot`), `chown -R vels-bot:vels-bot` над `/opt/vels-claude-light` и `WORKING_DIR`, `User=vels-bot` в unit'е. Дефолт `WORKING_DIR` в этом случае — `/var/lib/vels-bot/workspace` (а не `~/workspace`), чтобы путь точно был во владении сервиса. Если пользователь указал путь вне `/var/lib/vels-bot/` — предупреждение «этой папкой смогут пользоваться только из-под `vels-bot`», но установка продолжается. |

**Почему не root**: Claude Code работает в режиме `bypassPermissions` —
он не просит подтверждения на `bash`/`Edit`/`Write`. Если процесс
запущен от root, любая ошибка/галлюцинация может стереть систему. Под
обычным пользователем Linux сам ограничит ущерб его собственными файлами.

### Этап 5 — итоговый экран (успех)

```
──────────────────────────────────────
✅  Установка завершена

   Сервис:        vels-claude-light  (active, running)
   Пользователь:  vels
   Папка:         /opt/vels-claude-light
   Claude cwd:    /home/vels/workspace
   Бот:           @<username из getMe>

📋  Последние логи:
     <10 строк из journalctl>

🛠   Полезные команды:
     sudo systemctl status vels-claude-light   — статус
     sudo journalctl -u vels-claude-light -f   — живые логи
     sudo systemctl restart vels-claude-light  — перезапуск
     sudo systemctl stop vels-claude-light     — остановить
     /opt/vels-claude-light/uninstall.sh       — удалить целиком

Откройте Telegram и напишите боту — он должен ответить.
```

### Этап 5b — итоговый экран (провал)

Если `systemctl is-active` возвращает что-то кроме `active`:

```
──────────────────────────────────────
❌  Сервис не поднялся

Последние 30 строк логов:
<journalctl -u vels-claude-light -n 30>

Полные логи:   sudo journalctl -u vels-claude-light -n 100
Перезапуск:    sudo systemctl restart vels-claude-light
```

Возврат `exit 1`, чтобы CI / скрипты поверх установщика могли это ловить.

## `uninstall.sh`

Лежит в `/opt/vels-claude-light/uninstall.sh`, запускается через sudo.

```
🗑   Удаляю Vels Claude Light

   ✓ systemctl stop vels-claude-light
   ✓ systemctl disable vels-claude-light
   ✓ rm /etc/systemd/system/vels-claude-light.service
   ✓ systemctl daemon-reload

Рабочая папка (/home/vels/workspace) — удалить? [y/N]: _
Пользователь vels-bot был создан установщиком — удалить? [Y/n]: _

   ✓ rm -rf /opt/vels-claude-light
```

- `WORKING_DIR` по умолчанию **не** удаляется (данные практиканта).
- `vels-bot` удаляется только если был создан нами (распознаём по GECOS-метке
  `vels-claude-light service account`).

## Systemd unit (финальный)

```ini
[Unit]
Description=Vels Claude Light — Telegram bridge to Claude Code
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=/opt/vels-claude-light
EnvironmentFile=/opt/vels-claude-light/.env
ExecStart=/opt/vels-claude-light/.venv/bin/python -m src.main
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vels-claude-light

[Install]
WantedBy=multi-user.target
```

`${SERVICE_USER}` подставляется установщиком (`$SUDO_USER` или `vels-bot`).

**Что даёт практически:**

- Процесс упал (сеть, OOM, баг) → systemd поднимет через 5 сек.
- Цикл-падений (ошибка на старте) → после 10 рестартов за минуту systemd
  останавливает попытки и переводит сервис в `failed`, чтобы не жечь CPU.
  Через минуту можно вручную `systemctl restart`.
- aiogram сам поддерживает long-polling reconnect при сетевых глюках —
  отдельной логики ретраев в Python не нужно.

## Ошибки и идемпотентность

- Все шаги установщика можно запускать **повторно**: `.venv` переиспользуется,
  `git clone` превращается в `git pull`, `.env` не переспрашивает поля
  молча, unit перезаписывается только при изменении.
- Установщик падает с понятной ошибкой на:
  - отсутствующем `claude` CLI;
  - не-Linux-ОС (`uname` ≠ `Linux`);
  - не-поддерживаемом дистрибутиве (нет `apt-get` — проверка `which apt-get`);
  - не-прошедшем токене Telegram (`getMe` вернул 401);
  - содержимом `/opt/vels-claude-light/`, которое не похоже на нашу предыдущую
    установку (нет `.env` или `scripts/vels-claude-light.service` — значит
    папку создал кто-то другой, не трогаем).
- Всё, что делается через `apt-get` и `systemctl`, не молчит: показывается
  то, что происходит, чтобы практикант видел прогресс.
- При нажатии Ctrl+C на этапе онбординга (до того как мы начали менять систему)
  установщик выходит без побочных эффектов. После старта системных изменений
  (apt, /opt, systemd) обработчик `trap` выводит «установка прервана, запустите
  повторно, чтобы завершить» — и оставляет частичное состояние, которое
  повторный запуск приведёт к валидному (идемпотентность).
- `curl` нужен для `getMe`-проверки и скачивания `install.sh`; если его нет —
  ставим через `apt-get install -y curl` на первом шаге.

## Файловая раскладка (итог)

```
/opt/vels-claude-light/
├── .env                              (600, service user)
├── .venv/
├── src/
│   ├── bot.py
│   ├── bridge.py
│   ├── formatter.py
│   ├── main.py
│   ├── storage.py
│   ├── streaming.py
│   └── uploads.py
├── scripts/vels-claude-light.service (шаблон)
├── requirements.txt
├── install.sh
├── uninstall.sh
└── README.md

/etc/systemd/system/vels-claude-light.service  (инстанцированный)
~/<workspace>/                                 (cwd Claude)
```

## Документация в README

Секция «Быстрая установка» сверху, до «Установка» (dev-варианта):

```markdown
## Быстрая установка на VPS

На свежем Ubuntu/Debian-сервере (залогиньтесь не под root):

    curl -sSL https://raw.githubusercontent.com/<owner>/vels-claude-light/main/install.sh | bash

Скрипт спросит токен, Telegram ID и папку для работы — и поднимет бот
как systemd-сервис. Предварительно нужно установить и залогиниться
в Claude Code CLI:

    npm install -g @anthropic-ai/claude-code
    claude   # первый раз — залогиньтесь по инструкции

## Удаление

    sudo /opt/vels-claude-light/uninstall.sh
```

Остальной README сохранить как есть (dev-инструкция через venv, переменные
окружения, команды бота).
