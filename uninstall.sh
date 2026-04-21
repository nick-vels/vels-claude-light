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
    read -r ans || ans=""
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
        read -r ans || ans=""
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

printf '\n%s✅  Vels Claude Light удалён%s\n\n' "$C_OK" "$C_RESET"
