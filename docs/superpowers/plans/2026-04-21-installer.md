# Vels Claude Light — installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Один `install.sh` + `uninstall.sh`, которые ставят бот как systemd-сервис на Ubuntu/Debian VPS за одну команду и три ответа в терминале.

**Architecture:** Single-file bash-скрипт со strict-mode (`set -euo pipefail`) и main-guard паттерном (`if [[ "${BASH_SOURCE[0]}" == "${0}" ]]`), который позволяет `source`-ить его в тестах без запуска основного потока. Чистые функции (валидаторы, резолвинг пользователя) вынесены в отдельные функции и покрыты bash-unit-тестами. Side-effect функции (`apt`, `useradd`, `systemctl`) тестируются вручную на свежем VPS.

**Tech Stack:** bash 4+, GNU coreutils, apt, systemd, curl, git, python3-venv, shellcheck (lint).

---

## Testing approach for bash

Unit-тесты пишем только для функций без side effects: `validate_token`, `parse_user_ids`, `expand_workspace_path`, `resolve_service_user` (с замоканными `$SUDO_USER` / `$EUID`). Тесты лежат в `tests/installer_test.sh`, запускаются командой `bash tests/installer_test.sh`. Используем простые `assert_eq` / `assert_fail` функции — без зависимостей на bats или внешние фреймворки.

Функции с реальными системными вызовами (`apt_install`, `create_service_user`, `install_systemd_unit`, `start_service`) не покрываем unit-тестами — вместо этого в конце плана есть задача «end-to-end проверка на чистом Debian 12 через OrbStack/Lima».

---

## File Structure

**Новые файлы:**

```
install.sh                 ← основной установщик (~350 строк)
uninstall.sh               ← деинсталлятор (~80 строк)
tests/installer_test.sh    ← bash-unit-тесты для валидаторов и резолверов
```

**Модифицируемые:**

```
scripts/vels-claude-light.service   ← превращается в шаблон с ${SERVICE_USER}
README.md                           ← добавляется секция «Быстрая установка на VPS»
```

**Не трогаем:**

Весь код бота (`src/`), тесты бота (`tests/test_*.py`), storage.

---

## Task 1: Скелет install.sh + main-guard

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Написать скелет с strict mode и main-guard**

```bash
#!/usr/bin/env bash
# install.sh — Vels Claude Light one-command installer for Ubuntu/Debian VPS.
# Safe to re-run: all steps are idempotent.

set -euo pipefail

# ---- constants ----
readonly INSTALL_DIR="/opt/vels-claude-light"
readonly UNIT_PATH="/etc/systemd/system/vels-claude-light.service"
readonly SERVICE_NAME="vels-claude-light"
readonly REPO_URL_DEFAULT="https://github.com/<owner>/vels-claude-light.git"
readonly VELS_BOT_USER="vels-bot"
readonly VELS_BOT_HOME="/var/lib/${VELS_BOT_USER}"
readonly VELS_BOT_GECOS="vels-claude-light service account"

# ---- colors ----
readonly C_RESET=$'\033[0m'
readonly C_BOLD=$'\033[1m'
readonly C_OK=$'\033[0;32m'      # green
readonly C_WARN=$'\033[0;33m'    # yellow
readonly C_ERR=$'\033[0;31m'     # red
readonly C_DIM=$'\033[2m'

# ---- main ----
main() {
    print_banner
    echo "TODO: остальные этапы"
}

# Run only when executed, not when sourced (for tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
```

- [ ] **Step 2: Добавить print_banner()**

```bash
print_banner() {
    cat <<'EOF'

██╗   ██╗███████╗██╗     ███████╗
██║   ██║██╔════╝██║     ██╔════╝
██║   ██║█████╗  ██║     ███████╗
╚██╗ ██╔╝██╔══╝  ██║     ╚════██║
 ╚████╔╝ ███████╗███████╗███████║
  ╚═══╝  ╚══════╝╚══════╝╚══════╝

       Vels Claude Light · installer
──────────────────────────────────────
EOF
}
```

- [ ] **Step 3: Сделать исполняемым и запустить для проверки**

```bash
chmod +x install.sh
./install.sh
```

Expected: напечатается баннер + строка "TODO: остальные этапы", exit 0.

- [ ] **Step 4: Установить shellcheck и прогнать**

```bash
# На dev-машине:
brew install shellcheck      # macOS
# или: sudo apt-get install -y shellcheck    # linux

shellcheck install.sh
```

Expected: no issues.

- [ ] **Step 5: Commit**

```bash
git add install.sh
git commit -m "feat(installer): skeleton with banner and main-guard"
```

---

## Task 2: Prechecks и автоустановка apt-пакетов

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Добавить функции логирования**

В install.sh, после `print_banner`:

```bash
log_ok()   { printf "   ${C_OK}✓${C_RESET} %s\n" "$*"; }
log_warn() { printf "   ${C_WARN}!${C_RESET} %s\n" "$*"; }
log_err()  { printf "   ${C_ERR}✗${C_RESET} %s\n" "$*" >&2; }
log_info() { printf "   %s\n" "$*"; }
step()     { printf "\n${C_BOLD}%s${C_RESET}\n" "$*"; }
die()      { log_err "$*"; exit 1; }
```

- [ ] **Step 2: Добавить функцию check_os**

```bash
check_os() {
    [[ "$(uname -s)" == "Linux" ]] || die "Скрипт работает только на Linux."
    command -v apt-get >/dev/null 2>&1 \
        || die "Нужен apt-get (Ubuntu/Debian). Поддержки других пакетных менеджеров нет."
}
```

- [ ] **Step 3: Добавить функцию ensure_sudo**

```bash
ensure_sudo() {
    if [[ $EUID -eq 0 ]]; then
        # уже root, sudo не нужен
        SUDO=""
    else
        command -v sudo >/dev/null 2>&1 \
            || die "Скрипт требует sudo. Установите: apt-get install sudo, или запустите от root."
        SUDO="sudo"
        # Спросить пароль один раз, чтобы дальше не прерывать.
        $SUDO -v
    fi
}
```

- [ ] **Step 4: Добавить функцию apt_install_missing**

```bash
# apt_install_missing pkg1 pkg2 ...
# Ставит только отсутствующее; если всё уже есть — молча выходит.
apt_install_missing() {
    local missing=()
    for pkg in "$@"; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if ((${#missing[@]} > 0)); then
        log_info "ставлю через apt: ${missing[*]}"
        $SUDO apt-get update -qq
        $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
    fi
}
```

- [ ] **Step 5: Добавить функцию check_claude_cli**

```bash
check_claude_cli() {
    if ! command -v claude >/dev/null 2>&1; then
        log_err "claude CLI не найден"
        cat <<'EOF'

   Vels Claude Light — это мост к Claude Code CLI, его нужно
   установить отдельно:

       npm install -g @anthropic-ai/claude-code
       claude      # первый раз — залогиньтесь

   После этого перезапустите установщик.
EOF
        exit 1
    fi
    local ver
    ver=$(claude --version 2>/dev/null | head -n1 || echo "unknown")
    log_ok "claude CLI ($ver)"
}
```

- [ ] **Step 6: Добавить prechecks_all и вызвать из main**

```bash
prechecks_all() {
    step "🔍 Проверяю окружение"
    check_os
    ensure_sudo
    apt_install_missing curl git python3 python3-venv python3-pip
    log_ok "apt-пакеты (curl, git, python3, venv, pip)"
    check_claude_cli
}

main() {
    print_banner
    prechecks_all
    echo "TODO: онбординг"
}
```

- [ ] **Step 7: shellcheck + прогон**

```bash
shellcheck install.sh
./install.sh   # на macOS даст "только на Linux", это ожидаемо
```

- [ ] **Step 8: Commit**

```bash
git add install.sh
git commit -m "feat(installer): OS/sudo/apt/claude prechecks with auto-apt-install"
```

---

## Task 3: Валидаторы (TDD) + онбординг .env

**Files:**
- Modify: `install.sh`
- Create: `tests/installer_test.sh`

- [ ] **Step 1: Написать падающие тесты валидаторов**

Создать `tests/installer_test.sh`:

```bash
#!/usr/bin/env bash
# Unit tests for pure functions in install.sh (no side effects).
set -uo pipefail

# shellcheck source=../install.sh
source "$(dirname "$0")/../install.sh"  # main-guard прячет main()

FAIL=0
assert_eq() {
    local got=$1 want=$2 name=$3
    if [[ "$got" == "$want" ]]; then
        printf "  ✓ %s\n" "$name"
    else
        printf "  ✗ %s\n    got:  %s\n    want: %s\n" "$name" "$got" "$want" >&2
        FAIL=1
    fi
}
assert_fail() {
    local name=$1; shift
    if "$@" 2>/dev/null; then
        printf "  ✗ %s (expected failure, got success)\n" "$name" >&2
        FAIL=1
    else
        printf "  ✓ %s\n" "$name"
    fi
}

echo "== validate_token =="
assert_eq "$(validate_token '1234567890:AAFabcdefghijklmnopqrstuvwxyz12345')" "ok" "valid token"
assert_fail "empty token"       validate_token ""
assert_fail "no colon"          validate_token "1234567890AAF"
assert_fail "short secret"      validate_token "1234567890:abc"
assert_fail "non-digit prefix"  validate_token "abc:AAFabcdefghijklmnopqrstuvwxyz12345"

echo "== parse_user_ids =="
assert_eq "$(parse_user_ids '123456')" "123456" "single id"
assert_eq "$(parse_user_ids '123,456,789')" "123,456,789" "three ids"
assert_eq "$(parse_user_ids '123 , 456')" "123,456" "whitespace around comma"
assert_fail "non-numeric"  parse_user_ids "abc"
assert_fail "mixed"        parse_user_ids "123,abc"
assert_fail "empty"        parse_user_ids ""

echo "== expand_workspace_path =="
assert_eq "$(HOME=/home/vels expand_workspace_path '~/workspace')" "/home/vels/workspace" "tilde expansion"
assert_eq "$(expand_workspace_path '/abs/path')" "/abs/path" "absolute passthrough"
assert_fail "relative"  expand_workspace_path "rel/path"

exit $FAIL
```

- [ ] **Step 2: Запустить тесты — должны упасть (функций ещё нет)**

```bash
chmod +x tests/installer_test.sh
bash tests/installer_test.sh
```

Expected: ошибки «command not found: validate_token» и т.п.

- [ ] **Step 3: Реализовать валидаторы в install.sh**

```bash
# validate_token <token> -> "ok" | error (returns 1)
validate_token() {
    local t=${1:-}
    [[ -n "$t" ]] || return 1
    [[ "$t" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] || return 1
    printf "ok"
}

# parse_user_ids "1,2,3" -> "1,2,3" | error (returns 1)
# Normalizes whitespace around commas.
parse_user_ids() {
    local raw=${1:-}
    [[ -n "$raw" ]] || return 1
    local IFS=,
    read -ra parts <<<"$raw"
    local out=()
    for p in "${parts[@]}"; do
        p="${p//[[:space:]]/}"
        [[ "$p" =~ ^[0-9]+$ ]] || return 1
        out+=("$p")
    done
    (IFS=,; printf "%s" "${out[*]}")
}

# expand_workspace_path "~/foo" -> "/home/user/foo" | error for relative
expand_workspace_path() {
    local raw=${1:-}
    [[ -n "$raw" ]] || return 1
    if [[ "$raw" == "~" ]]; then
        printf "%s" "$HOME"
    elif [[ "$raw" == "~/"* ]]; then
        printf "%s/%s" "$HOME" "${raw#"~/"}"
    elif [[ "$raw" == "/"* ]]; then
        printf "%s" "$raw"
    else
        return 1
    fi
}
```

- [ ] **Step 4: Запустить тесты — должны пройти**

```bash
bash tests/installer_test.sh
```

Expected: все строки с `✓`, exit 0.

- [ ] **Step 5: Добавить функцию prompt_onboarding**

```bash
# Prompts user for token / ids / workspace, fills vars by reference.
# Globals set: CFG_TOKEN, CFG_IDS, CFG_WORKSPACE
prompt_onboarding() {
    step "⚙️  Настройка бота"

    # --- 1. token ---
    while :; do
        printf "\n1/3  Токен Telegram-бота\n"
        printf "     Получите у @BotFather командой /newbot.\n"
        printf "     Пример: 1234567890:AAF...XyZ\n\n"
        read -rp "     Токен: " token
        if validate_token "$token" >/dev/null 2>&1; then
            CFG_TOKEN="$token"
            break
        fi
        log_err "неверный формат токена"
    done

    # --- 2. ids ---
    while :; do
        printf "\n2/3  Ваш Telegram user ID\n"
        printf "     Узнайте у @userinfobot. Несколько — через запятую.\n\n"
        read -rp "     ID: " ids
        if parsed=$(parse_user_ids "$ids" 2>/dev/null); then
            CFG_IDS="$parsed"
            break
        fi
        log_err "ID должен быть числом (или несколько через запятую)"
    done

    # --- 3. workspace ---
    local default_ws
    default_ws=$(default_workspace)
    while :; do
        printf "\n3/3  Рабочая директория Claude\n"
        printf "     Если её нет — создам. Enter = дефолт.\n\n"
        read -rp "     Путь [${default_ws}]: " ws
        ws="${ws:-$default_ws}"
        if expanded=$(expand_workspace_path "$ws" 2>/dev/null); then
            CFG_WORKSPACE="$expanded"
            break
        fi
        log_err "путь должен быть абсолютным (начинаться с / или ~/)"
    done
}

# default_workspace: where user's workspace lives by default.
# Resolved later by service-user logic; here just a placeholder.
default_workspace() { printf "~/workspace"; }
```

- [ ] **Step 6: Добавить вызов в main**

```bash
main() {
    print_banner
    prechecks_all
    prompt_onboarding
    echo "TODO: установка"
    echo "token=${CFG_TOKEN:0:10}..., ids=$CFG_IDS, ws=$CFG_WORKSPACE"
}
```

- [ ] **Step 7: shellcheck + прогон тестов**

```bash
shellcheck install.sh tests/installer_test.sh
bash tests/installer_test.sh
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add install.sh tests/installer_test.sh
git commit -m "feat(installer): token/id/path validators + onboarding prompts

Includes unit tests for pure validators (validate_token, parse_user_ids,
expand_workspace_path)."
```

---

## Task 4: getMe-проверка токена и резолвинг service user

**Files:**
- Modify: `install.sh`
- Modify: `tests/installer_test.sh`

- [ ] **Step 1: Добавить функцию getme_check (с опциональным мокированием для тестов)**

```bash
# getme_check <token> -> prints bot username | exits 1
# Usable mock: if VELS_GETME_MOCK is set, echoes it instead of curling.
getme_check() {
    local token=$1
    if [[ -n "${VELS_GETME_MOCK:-}" ]]; then
        printf "%s" "$VELS_GETME_MOCK"
        return 0
    fi
    local response
    response=$(curl -fsS --max-time 10 "https://api.telegram.org/bot${token}/getMe") || {
        log_err "не удалось достучаться до api.telegram.org (сеть? файрвол?)"
        return 1
    }
    # cheap JSON parse without jq
    local ok username
    ok=$(printf "%s" "$response" | grep -o '"ok":true' || true)
    [[ -n "$ok" ]] || { log_err "Telegram вернул: $response"; return 1; }
    username=$(printf "%s" "$response" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
    [[ -n "$username" ]] || username="unknown"
    printf "%s" "$username"
}
```

- [ ] **Step 2: Добавить тест с моком**

В `tests/installer_test.sh` добавить:

```bash
echo "== getme_check (mocked) =="
assert_eq "$(VELS_GETME_MOCK='my_bot' getme_check 'tok')" "my_bot" "mock returns username"
```

Запустить тест:

```bash
bash tests/installer_test.sh
```

Expected: pass.

- [ ] **Step 3: Встроить getme_check в prompt_onboarding**

После успешной regex-валидации токена:

```bash
if validate_token "$token" >/dev/null 2>&1; then
    log_info "проверяю токен через getMe…"
    if username=$(getme_check "$token" 2>&1); then
        CFG_TOKEN="$token"
        CFG_BOT_USERNAME="$username"
        log_ok "бот: @${username}"
        break
    fi
    # getme_check уже напечатал ошибку
fi
```

- [ ] **Step 4: Добавить функцию resolve_service_user**

```bash
# Fills SERVICE_USER, SERVICE_HOME, SERVICE_NEEDS_CREATE.
resolve_service_user() {
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        SERVICE_USER="$SUDO_USER"
        SERVICE_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
        SERVICE_NEEDS_CREATE=0
    elif [[ $EUID -eq 0 ]]; then
        SERVICE_USER="$VELS_BOT_USER"
        SERVICE_HOME="$VELS_BOT_HOME"
        SERVICE_NEEDS_CREATE=1
    else
        die "Запустите через sudo (sudo ./install.sh)."
    fi
}
```

- [ ] **Step 5: Тесты для resolve_service_user (с моком EUID)**

В `tests/installer_test.sh`:

```bash
echo "== resolve_service_user =="
# sudo-case
SUDO_USER=vels EUID=1000 resolve_service_user 2>/dev/null
assert_eq "$SERVICE_USER" "vels" "SUDO_USER path"
# root-without-sudo-case
unset SUDO_USER; EUID=0 resolve_service_user 2>/dev/null
assert_eq "$SERVICE_USER" "vels-bot" "direct root path"
```

Prereq: `VELS_BOT_USER` из install.sh уже в окружении после source (да, т.к. `readonly`).

- [ ] **Step 6: Добавить функцию create_service_user_if_needed**

```bash
create_service_user_if_needed() {
    (( SERVICE_NEEDS_CREATE == 1 )) || return 0
    if id -u "$SERVICE_USER" >/dev/null 2>&1; then
        log_ok "пользователь $SERVICE_USER уже существует"
        return 0
    fi
    log_info "создаю системного пользователя $SERVICE_USER"
    $SUDO useradd --system --create-home \
        --home-dir "$SERVICE_HOME" \
        --shell /usr/sbin/nologin \
        --comment "$VELS_BOT_GECOS" \
        "$SERVICE_USER"
    log_ok "пользователь $SERVICE_USER создан"
}
```

- [ ] **Step 7: Добавить корректировку CFG_WORKSPACE в root-случае**

Вставить сразу после `resolve_service_user`:

```bash
# Если мы создаём vels-bot, дефолтный ~/workspace превращается в
# /var/lib/vels-bot/workspace (иначе vels-bot не сможет туда писать).
reconcile_workspace_with_user() {
    if (( SERVICE_NEEDS_CREATE == 1 )); then
        # Подменяем, только если пользователь оставил дефолт или ~/…
        if [[ "$CFG_WORKSPACE" == "$HOME/workspace" || "$CFG_WORKSPACE" == "$HOME/"* ]]; then
            local new="$SERVICE_HOME/workspace"
            log_warn "меняю workspace с $CFG_WORKSPACE на $new (владелец будет $SERVICE_USER)"
            CFG_WORKSPACE="$new"
        elif [[ "$CFG_WORKSPACE" != "$SERVICE_HOME"* ]]; then
            log_warn "workspace $CFG_WORKSPACE будет принадлежать $SERVICE_USER — другие пользователи туда не попадут"
        fi
    fi
}
```

- [ ] **Step 8: Обновить main**

```bash
main() {
    print_banner
    prechecks_all
    prompt_onboarding
    resolve_service_user
    reconcile_workspace_with_user
    create_service_user_if_needed
    echo "TODO: установка кода"
}
```

- [ ] **Step 9: shellcheck + тесты**

```bash
shellcheck install.sh tests/installer_test.sh
bash tests/installer_test.sh
```

- [ ] **Step 10: Commit**

```bash
git add install.sh tests/installer_test.sh
git commit -m "feat(installer): getMe validation + service user resolution"
```

---

## Task 5: Установка кода + venv + .env + workspace

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Добавить функцию install_code**

```bash
install_code() {
    step "📦 Устанавливаю код в $INSTALL_DIR"
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "обновляю существующую копию (git pull)…"
        $SUDO git -C "$INSTALL_DIR" pull --ff-only --quiet
    elif [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        # Папка есть и не пустая, но не git-репа — признак foreign content
        die "$INSTALL_DIR не пустая и не является нашей копией. Уберите её вручную или запустите uninstall.sh."
    else
        log_info "клонирую репозиторий…"
        $SUDO mkdir -p "$(dirname "$INSTALL_DIR")"
        $SUDO git clone --quiet "$REPO_URL_DEFAULT" "$INSTALL_DIR"
    fi
    $SUDO chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
    log_ok "код на месте"
}
```

- [ ] **Step 2: Добавить функцию install_python_env**

```bash
install_python_env() {
    step "🐍 Python-окружение"
    if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
        $SUDO -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/.venv"
        log_ok "venv создан"
    else
        log_ok "venv уже есть"
    fi
    log_info "pip install -r requirements.txt…"
    $SUDO -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
    $SUDO -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
    log_ok "зависимости установлены"
}
```

- [ ] **Step 3: Добавить функцию write_env**

```bash
write_env() {
    step "📝 .env"
    local env_file="$INSTALL_DIR/.env"
    $SUDO tee "$env_file" >/dev/null <<EOF
TELEGRAM_BOT_TOKEN=$CFG_TOKEN
ALLOWED_USER_IDS=$CFG_IDS
WORKING_DIR=$CFG_WORKSPACE
PERMISSION_MODE=bypassPermissions
CLAUDE_BINARY=auto
CLAUDE_TIMEOUT_MINUTES=30
SESSIONS_FILE=data/sessions.json
MAX_MESSAGE_LENGTH=4096
CODE_AS_FILE_THRESHOLD=500
EOF
    $SUDO chown "$SERVICE_USER":"$SERVICE_USER" "$env_file"
    $SUDO chmod 600 "$env_file"
    log_ok ".env записан (chmod 600, owner=$SERVICE_USER)"
}
```

- [ ] **Step 4: Добавить функцию ensure_workspace**

```bash
ensure_workspace() {
    step "📂 Рабочая директория"
    if [[ ! -d "$CFG_WORKSPACE" ]]; then
        $SUDO mkdir -p "$CFG_WORKSPACE"
        log_ok "создана: $CFG_WORKSPACE"
    else
        log_ok "уже есть: $CFG_WORKSPACE"
    fi
    $SUDO chown "$SERVICE_USER":"$SERVICE_USER" "$CFG_WORKSPACE"
}
```

- [ ] **Step 5: Обновить main**

```bash
main() {
    print_banner
    prechecks_all
    prompt_onboarding
    resolve_service_user
    reconcile_workspace_with_user
    create_service_user_if_needed
    install_code
    install_python_env
    write_env
    ensure_workspace
    echo "TODO: systemd"
}
```

- [ ] **Step 6: shellcheck**

```bash
shellcheck install.sh
```

- [ ] **Step 7: Commit**

```bash
git add install.sh
git commit -m "feat(installer): code/venv/env/workspace install steps"
```

---

## Task 6: Шаблон systemd unit + установка + health check

**Files:**
- Modify: `scripts/vels-claude-light.service`
- Modify: `install.sh`

- [ ] **Step 1: Превратить .service в шаблон**

Содержимое `scripts/vels-claude-light.service`:

```ini
[Unit]
Description=Vels Claude Light — Telegram bridge to Claude Code
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__SERVICE_USER__
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

Placeholder `__SERVICE_USER__` заменит установщик.

- [ ] **Step 2: Добавить функцию install_systemd_unit в install.sh**

```bash
install_systemd_unit() {
    step "⚙️  systemd unit"
    local template="$INSTALL_DIR/scripts/vels-claude-light.service"
    [[ -f "$template" ]] || die "шаблон $template не найден — проверьте репозиторий"
    # Рендерим через sed с безопасным разделителем.
    $SUDO sed "s|__SERVICE_USER__|$SERVICE_USER|g" "$template" \
        | $SUDO tee "$UNIT_PATH" >/dev/null
    log_ok "$UNIT_PATH записан (User=$SERVICE_USER)"
    $SUDO systemctl daemon-reload
}
```

- [ ] **Step 3: Добавить функцию start_service + health check**

```bash
start_service() {
    step "🚀 Запускаю сервис"
    $SUDO systemctl enable --quiet "$SERVICE_NAME"
    $SUDO systemctl restart "$SERVICE_NAME"
    log_info "ожидаю 3 секунды, чтобы сервис успел стартовать…"
    sleep 3
    if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
        log_ok "сервис в статусе active"
        return 0
    fi
    return 1
}
```

- [ ] **Step 4: Добавить функции print_success / print_failure**

```bash
print_success() {
    cat <<EOF

──────────────────────────────────────
${C_OK}✅  Установка завершена${C_RESET}

   Сервис:        $SERVICE_NAME  (active, running)
   Пользователь:  $SERVICE_USER
   Папка:         $INSTALL_DIR
   Claude cwd:    $CFG_WORKSPACE
   Бот:           @${CFG_BOT_USERNAME:-unknown}

📋  Последние логи:
EOF
    $SUDO journalctl -u "$SERVICE_NAME" -n 10 --no-pager | sed 's/^/     /'
    cat <<EOF

🛠   Полезные команды:
     sudo systemctl status $SERVICE_NAME   — статус
     sudo journalctl -u $SERVICE_NAME -f   — живые логи
     sudo systemctl restart $SERVICE_NAME  — перезапуск
     sudo systemctl stop $SERVICE_NAME     — остановить
     $INSTALL_DIR/uninstall.sh         — удалить целиком

Откройте Telegram и напишите боту — он должен ответить.
EOF
}

print_failure() {
    cat <<EOF

──────────────────────────────────────
${C_ERR}❌  Сервис не поднялся${C_RESET}

Последние 30 строк логов:
EOF
    $SUDO journalctl -u "$SERVICE_NAME" -n 30 --no-pager | sed 's/^/     /'
    cat <<EOF

Полные логи:   sudo journalctl -u $SERVICE_NAME -n 100
Перезапуск:    sudo systemctl restart $SERVICE_NAME
EOF
    exit 1
}
```

- [ ] **Step 5: Обновить main до финала**

```bash
main() {
    print_banner
    prechecks_all
    prompt_onboarding
    resolve_service_user
    reconcile_workspace_with_user
    create_service_user_if_needed
    install_code
    install_python_env
    write_env
    ensure_workspace
    install_systemd_unit
    if start_service; then
        print_success
    else
        print_failure
    fi
}
```

- [ ] **Step 6: shellcheck**

```bash
shellcheck install.sh
```

- [ ] **Step 7: Commit**

```bash
git add install.sh scripts/vels-claude-light.service
git commit -m "feat(installer): systemd unit templating and health-check"
```

---

## Task 7: Uninstall-скрипт

**Files:**
- Create: `uninstall.sh`

- [ ] **Step 1: Написать uninstall.sh**

```bash
#!/usr/bin/env bash
# uninstall.sh — снимает vels-claude-light с VPS.
set -euo pipefail

readonly INSTALL_DIR="/opt/vels-claude-light"
readonly UNIT_PATH="/etc/systemd/system/vels-claude-light.service"
readonly SERVICE_NAME="vels-claude-light"
readonly VELS_BOT_USER="vels-bot"
readonly VELS_BOT_GECOS="vels-claude-light service account"

C_RESET=$'\033[0m'; C_OK=$'\033[0;32m'; C_ERR=$'\033[0;31m'; C_WARN=$'\033[0;33m'
log_ok()   { printf "   ${C_OK}✓${C_RESET} %s\n" "$*"; }
log_warn() { printf "   ${C_WARN}!${C_RESET} %s\n" "$*"; }
die()      { printf "   ${C_ERR}✗${C_RESET} %s\n" "$*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || die "Запустите через sudo."
    exec sudo "$0" "$@"
fi

printf "\n🗑   Удаляю Vels Claude Light\n\n"

# --- Сохраняем параметры до удаления файлов ---
workspace=""
if [[ -f "$INSTALL_DIR/.env" ]]; then
    workspace=$(grep -E '^WORKING_DIR=' "$INSTALL_DIR/.env" | head -n1 | cut -d= -f2- || true)
fi

# --- Сервис ---
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    log_ok "systemctl stop $SERVICE_NAME"
    systemctl disable --quiet "$SERVICE_NAME" 2>/dev/null || true
    log_ok "systemctl disable $SERVICE_NAME"
fi
if [[ -f "$UNIT_PATH" ]]; then
    rm -f "$UNIT_PATH"
    log_ok "rm $UNIT_PATH"
    systemctl daemon-reload
    log_ok "systemctl daemon-reload"
fi

# --- Workspace (опционально) ---
if [[ -n "$workspace" && -d "$workspace" ]]; then
    printf "\nРабочая папка %s — удалить? [y/N]: " "$workspace"
    read -r ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        rm -rf "$workspace"
        log_ok "rm -rf $workspace"
    else
        log_warn "оставляю $workspace"
    fi
fi

# --- vels-bot user (только если создавали мы) ---
if id -u "$VELS_BOT_USER" >/dev/null 2>&1; then
    gecos=$(getent passwd "$VELS_BOT_USER" | cut -d: -f5)
    if [[ "$gecos" == "$VELS_BOT_GECOS" ]]; then
        printf "\nПользователь %s был создан установщиком — удалить? [Y/n]: " "$VELS_BOT_USER"
        read -r ans
        if [[ -z "$ans" || "$ans" =~ ^[Yy]$ ]]; then
            userdel -r "$VELS_BOT_USER" 2>/dev/null || userdel "$VELS_BOT_USER"
            log_ok "userdel $VELS_BOT_USER"
        else
            log_warn "оставляю пользователя $VELS_BOT_USER"
        fi
    fi
fi

# --- Каталог кода ---
if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    log_ok "rm -rf $INSTALL_DIR"
fi

printf "\n${C_OK}✅  Vels Claude Light удалён${C_RESET}\n\n"
```

- [ ] **Step 2: shellcheck**

```bash
shellcheck uninstall.sh
```

- [ ] **Step 3: Сделать исполняемым и закоммитить**

```bash
chmod +x uninstall.sh
git add uninstall.sh
git commit -m "feat(uninstall): complete removal script with workspace/user prompts"
```

---

## Task 8: README — секция «Быстрая установка»

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Заменить содержимое README**

```markdown
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
```

- [ ] **Step 2: Проверить, что все упомянутые файлы существуют**

```bash
ls src/bot.py src/bridge.py src/streaming.py src/uploads.py src/storage.py \
   scripts/vels-claude-light.service install.sh uninstall.sh
```

Expected: все есть.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: quick-install section and updated structure overview"
```

---

## Task 9: End-to-end проверка на чистом Debian 12

**Files:** (никакие файлы не меняются, задача — тестирование)

- [ ] **Step 1: Развернуть одноразовый контейнер**

Вариант A (OrbStack на Mac):

```bash
orb create debian bot-install-test
orb -m bot-install-test bash
```

Вариант B (Docker):

```bash
docker run --rm -it --name bot-install-test \
  debian:12 bash
```

Внутри:

```bash
apt-get update && apt-get install -y curl sudo nodejs npm
npm install -g @anthropic-ai/claude-code
# тут нельзя авторизовать claude без API-ключа или интерактивного OAuth —
# подставим фейковый ответ для проверки именно установщика:
cat >/usr/local/bin/claude <<'SH'
#!/usr/bin/env bash
case "$1" in
  --version) echo "claude 2.1.116" ;;
  *) echo "mock claude" ;;
esac
SH
chmod +x /usr/local/bin/claude
```

- [ ] **Step 2: Создать тестового юзера и войти под ним**

```bash
useradd -m -s /bin/bash -G sudo testuser
passwd -d testuser
su - testuser
```

- [ ] **Step 3: Запустить установщик**

```bash
curl -sSL https://raw.githubusercontent.com/<owner>/vels-claude-light/main/install.sh | bash
```

Если репо ещё не опубликовано — локально:

```bash
cd /tmp && git clone /path/to/vels-claude-light   # через том в контейнер
cd vels-claude-light && ./install.sh
```

В промптах ввести тестовый токен (его можно получить у @BotFather в отдельном тестовом боте), свой ID, Enter для workspace.

- [ ] **Step 4: Проверить результат**

```bash
sudo systemctl status vels-claude-light
sudo journalctl -u vels-claude-light -n 30
```

Expected: `active (running)`, в логах — `bot ready: @…`, `Start polling`.

Послать боту `/start` — должен ответить.

- [ ] **Step 5: Проверить uninstall**

```bash
sudo /opt/vels-claude-light/uninstall.sh
```

Ответить Y/N на вопросы. После:

```bash
systemctl list-unit-files | grep vels || echo "unit gone OK"
ls /opt/vels-claude-light 2>&1 || echo "dir gone OK"
```

- [ ] **Step 6: Повторить от прямого root**

В новом контейнере войти как root, запустить `./install.sh`. Проверить, что создался `vels-bot`:

```bash
id vels-bot
systemctl show vels-claude-light --property=User
# должно быть User=vels-bot
```

Uninstall должен предложить удалить `vels-bot` и удалить.

- [ ] **Step 7: Зафиксировать итог**

Если всё ок — ничего не коммитим (задача — проверка). Если по ходу всплыли баги — правим install.sh/uninstall.sh, снова прогоняем Task 3 (валидаторы) и возвращаемся сюда.

---

## Self-Review (автор)

**Spec coverage** — прошёл секции спеки:

| Секция спеки | Покрыто в таске |
|---|---|
| Баннер + prechecks | Task 1, 2 |
| Онбординг (3 вопроса + валидация) | Task 3 |
| getMe-проверка | Task 4 |
| Service user (SUDO_USER / vels-bot) | Task 4 |
| Установка кода + venv + .env + workspace | Task 5 |
| Systemd unit + start + health-check | Task 6 |
| Финальный экран (success/failure) | Task 6 |
| uninstall.sh | Task 7 |
| Идемпотентность + foreign content guard | Task 5 (`install_code`) |
| Systemd Restart/Burst | Task 6 (шаблон unit'а) |
| README quick-install | Task 8 |
| E2E-проверка на свежем VPS | Task 9 |

Всё закрыто.

**Placeholder scan** — проверено: ни одного TBD/TODO (кроме `<owner>` в шаблонах, это осознанный плейсхолдер из спеки), все шаги с кодом содержат полный код, все команды — с ожидаемым результатом.

**Type consistency** — имена переменных и функций стабильны: `SERVICE_USER` используется одинаково в install.sh/uninstall.sh/шаблоне unit'а. Имена env-полей совпадают с тем, что читает `src/main.py`. Функции валидаторов называются одинаково в основном коде и тестах.

**Ambiguity** — `<owner>` в `REPO_URL_DEFAULT` и README — один плейсхолдер, заменяется на реальный GitHub-username при публикации репозитория. Больше неясностей нет.
