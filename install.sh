#!/usr/bin/env bash
# install.sh — Vels Claude Light one-command installer for Ubuntu/Debian VPS.
# Safe to re-run: all steps are idempotent.

# shellcheck disable=SC2034,SC2088  # forward-declared constants; literal ~ in validators is intentional

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

# Assigned by ensure_sudo. Declared here so apt_install_missing can reference
# $SUDO even if shellcheck traces the call graph out-of-order.
SUDO=""

# ---- helpers ----
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

# ---- logging helpers ----
log_ok()   { printf '   %s✓%s %s\n' "$C_OK" "$C_RESET" "$*"; }
log_warn() { printf '   %s!%s %s\n' "$C_WARN" "$C_RESET" "$*"; }
log_err()  { printf '   %s✗%s %s\n' "$C_ERR" "$C_RESET" "$*" >&2; }
log_info() { printf '   %s\n' "$*"; }
step()     { printf '\n%s%s%s\n' "$C_BOLD" "$*" "$C_RESET"; }
die()      { log_err "$*"; exit 1; }

# ---- validators ----
# validate_token <token> -> prints "ok" on match, returns 1 otherwise
validate_token() {
    local t=${1:-}
    [[ -n "$t" ]] || return 1
    [[ "$t" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] || return 1
    printf "ok"
}

# parse_user_ids "1,2,3" -> prints normalized "1,2,3", returns 1 on invalid
# Strips whitespace around and inside each comma-separated id.
parse_user_ids() {
    local raw=${1:-}
    [[ -n "$raw" ]] || return 1
    local IFS=,
    local parts=()
    read -ra parts <<<"$raw"
    local out=()
    local p
    for p in "${parts[@]}"; do
        p="${p//[[:space:]]/}"
        [[ "$p" =~ ^[0-9]+$ ]] || return 1
        out+=("$p")
    done
    (IFS=,; printf "%s" "${out[*]}")
}

# expand_workspace_path "~/foo" -> "/home/<user>/foo"; "/abs" passthrough; returns 1 on relative
# Strips trailing slash (except for root "/") so paths have a single canonical form.
expand_workspace_path() {
    local raw=${1:-}
    [[ -n "$raw" ]] || return 1
    local result
    if [[ "$raw" == "~" ]]; then
        result="$HOME"
    elif [[ "$raw" == "~/"* ]]; then
        result="$HOME/${raw#"~/"}"
    elif [[ "$raw" == "/"* ]]; then
        result="$raw"
    else
        return 1
    fi
    [[ "$result" != "/" && "$result" == */ ]] && result="${result%/}"
    printf "%s" "$result"
}

# default_workspace: placeholder default for onboarding. Task 4 may override.
default_workspace() { printf "%s" "~/workspace"; }

# ---- telegram helpers ----
# getme_check <token>: on success prints bot username to stdout and returns 0;
# on failure logs an error to stderr and returns non-zero.
# Test hook: if VELS_GETME_MOCK is set, its value is printed verbatim (no HTTP).
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
    # Minimal JSON parse without jq.
    local ok username
    ok=$(printf "%s" "$response" | grep -o '"ok":true' || true)
    if [[ -z "$ok" ]]; then
        log_err "Telegram отказал: $response"
        return 1
    fi
    username=$(printf "%s" "$response" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
    [[ -n "$username" ]] || username="unknown"
    printf "%s" "$username"
}

check_os() {
    [[ "$(uname -s)" == "Linux" ]] || die "Скрипт работает только на Linux."
    command -v apt-get >/dev/null 2>&1 \
        || die "Нужен apt-get (Ubuntu/Debian). Поддержки других пакетных менеджеров нет."
}

ensure_sudo() {
    if [[ $EUID -eq 0 ]]; then
        # already root, sudo not needed
        SUDO=""
    else
        command -v sudo >/dev/null 2>&1 \
            || die "Скрипт требует sudo. Установите: apt-get install sudo, или запустите от root."
        SUDO="sudo"
        # Prompt once so later sudo calls don't re-prompt. sudo opens /dev/tty
        # itself; we only need to react if it fails (no TTY, wrong password).
        $SUDO -v || die "sudo не смог подтвердить права. Нужна интерактивная сессия."
    fi
}

# apt_install_missing pkg1 pkg2 ...
# Installs only packages that are absent; silent if everything is present.
apt_install_missing() {
    local missing=()
    for pkg in "$@"; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if ((${#missing[@]} > 0)); then
        log_info "ставлю через apt: ${missing[*]}"
        $SUDO apt-get update -qq
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
    fi
}

check_claude_cli() {
    if ! command -v claude >/dev/null 2>&1; then
        log_err "claude CLI не найден"
        cat >&2 <<'EOF'

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

prechecks_all() {
    step "🔍 Проверяю окружение"
    check_os
    ensure_sudo
    apt_install_missing curl git python3 python3-venv python3-pip
    log_ok "apt-пакеты (curl, git, python3, venv, pip)"
    check_claude_cli
}

# ---- service user ----
# resolve_service_user: decides which Linux user runs the service.
#   - sudo launched by regular user: SERVICE_USER = $SUDO_USER (no account creation).
#   - direct root (no SUDO_USER): SERVICE_USER = vels-bot (we'll create it).
#   - plain non-root: die (user must re-run under sudo).
# Sets globals: SERVICE_USER, SERVICE_HOME, SERVICE_NEEDS_CREATE.
# Test hook: VELS_EUID_OVERRIDE, if set, is used in place of $EUID.
resolve_service_user() {
    local euid="${VELS_EUID_OVERRIDE:-$EUID}"
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        SERVICE_USER="$SUDO_USER"
        SERVICE_HOME=$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6 || true)
        [[ -n "$SERVICE_HOME" ]] || SERVICE_HOME="/home/$SUDO_USER"
        SERVICE_NEEDS_CREATE=0
    elif (( euid == 0 )); then
        SERVICE_USER="$VELS_BOT_USER"
        SERVICE_HOME="$VELS_BOT_HOME"
        SERVICE_NEEDS_CREATE=1
    else
        die "Запустите через sudo (sudo ./install.sh)."
    fi
}

# create_service_user_if_needed: creates the vels-bot system user on the direct-root path.
# Idempotent: returns silently if the user already exists.
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

# If the service user is our managed vels-bot account, the default $HOME/workspace
# path (captured before we knew SERVICE_USER) won't be writable by vels-bot.
# Swap it for $SERVICE_HOME/workspace and warn if the user explicitly chose a
# path outside vels-bot's home tree.
reconcile_workspace_with_user() {
    (( SERVICE_NEEDS_CREATE == 1 )) || return 0
    if [[ "$CFG_WORKSPACE" == "$HOME/workspace" || "$CFG_WORKSPACE" == "$HOME/"* ]]; then
        local new="$SERVICE_HOME/workspace"
        log_warn "меняю workspace с $CFG_WORKSPACE на $new (владелец будет $SERVICE_USER)"
        CFG_WORKSPACE="$new"
    elif [[ "$CFG_WORKSPACE" != "$SERVICE_HOME"* ]]; then
        log_warn "workspace $CFG_WORKSPACE будет принадлежать $SERVICE_USER — другие пользователи туда не попадут"
    fi
}

# ---- onboarding ----
# Prompts user for token / ids / workspace. Sets globals:
#   CFG_TOKEN, CFG_IDS, CFG_WORKSPACE
prompt_onboarding() {
    step "⚙️  Настройка бота"

    # --- 1. token ---
    local token
    while :; do
        printf "\n1/3  Токен Telegram-бота\n"
        printf "     Получите у @BotFather командой /newbot.\n"
        printf "     Пример: 1234567890:AAF...XyZ\n\n"
        read -rp "     Токен: " token || die "Ввод прерван (EOF)."
        if ! validate_token "$token" >/dev/null 2>&1; then
            log_err "неверный формат токена"
            continue
        fi
        log_info "проверяю токен через getMe…"
        local username
        if ! username=$(getme_check "$token"); then
            continue  # getme_check already logged via log_err to stderr
        fi
        CFG_TOKEN="$token"
        CFG_BOT_USERNAME="$username"
        log_ok "бот: @${username}"
        break
    done

    # --- 2. ids ---
    local ids parsed
    while :; do
        printf "\n2/3  Ваш Telegram user ID\n"
        printf "     Узнайте у @userinfobot. Несколько — через запятую.\n\n"
        read -rp "     ID: " ids || die "Ввод прерван (EOF)."
        if parsed=$(parse_user_ids "$ids" 2>/dev/null); then
            CFG_IDS="$parsed"
            break
        fi
        log_err "ID должен быть числом (или несколько через запятую)"
    done

    # --- 3. workspace ---
    local default_ws ws expanded
    default_ws=$(default_workspace)
    while :; do
        printf "\n3/3  Рабочая директория Claude\n"
        printf "     Если её нет — создам. Enter = дефолт.\n\n"
        read -rp "     Путь [${default_ws}]: " ws || die "Ввод прерван (EOF)."
        ws="${ws:-$default_ws}"
        if expanded=$(expand_workspace_path "$ws" 2>/dev/null); then
            CFG_WORKSPACE="$expanded"
            break
        fi
        log_err "путь должен быть абсолютным (начинаться с / или ~/)"
    done
}

# ---- main ----
main() {
    print_banner
    prechecks_all
    prompt_onboarding
    resolve_service_user
    reconcile_workspace_with_user
    create_service_user_if_needed
    echo "TODO: установка кода"
    echo "service_user=$SERVICE_USER ws=$CFG_WORKSPACE bot=@${CFG_BOT_USERNAME:-unknown}"
}

# Run only when executed, not when sourced (for tests).
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
    main "$@"
fi
