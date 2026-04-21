#!/usr/bin/env bash
# install.sh — Vels Claude Light one-command installer for Ubuntu/Debian VPS.
# Safe to re-run: all steps are idempotent.

# shellcheck disable=SC2034  # forward-declared constants used by future installer steps

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
        # Prompt for password once so later steps don't prompt mid-run.
        $SUDO -v
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
        $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
    fi
}

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

prechecks_all() {
    step "🔍 Проверяю окружение"
    check_os
    ensure_sudo
    apt_install_missing curl git python3 python3-venv python3-pip
    log_ok "apt-пакеты (curl, git, python3, venv, pip)"
    check_claude_cli
}

# ---- main ----
main() {
    print_banner
    prechecks_all
    echo "TODO: онбординг"
}

# Run only when executed, not when sourced (for tests).
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
    main "$@"
fi
