#!/usr/bin/env bash
# install.sh — Vels Claude Light one-command installer for Ubuntu/Debian VPS.
# Safe to re-run: all steps are idempotent.

set -euo pipefail

# ---- constants ----
# shellcheck disable=SC2034  # all constants below are used by future installer steps
readonly INSTALL_DIR="/opt/vels-claude-light"
# shellcheck disable=SC2034
readonly UNIT_PATH="/etc/systemd/system/vels-claude-light.service"
# shellcheck disable=SC2034
readonly SERVICE_NAME="vels-claude-light"
# shellcheck disable=SC2034
readonly REPO_URL_DEFAULT="https://github.com/<owner>/vels-claude-light.git"
readonly VELS_BOT_USER="vels-bot"
# shellcheck disable=SC2034
readonly VELS_BOT_HOME="/var/lib/${VELS_BOT_USER}"
# shellcheck disable=SC2034
readonly VELS_BOT_GECOS="vels-claude-light service account"

# ---- colors ----
# shellcheck disable=SC2034
readonly C_RESET=$'\033[0m'
# shellcheck disable=SC2034
readonly C_BOLD=$'\033[1m'
# shellcheck disable=SC2034
readonly C_OK=$'\033[0;32m'      # green
# shellcheck disable=SC2034
readonly C_WARN=$'\033[0;33m'    # yellow
# shellcheck disable=SC2034
readonly C_ERR=$'\033[0;31m'     # red
# shellcheck disable=SC2034
readonly C_DIM=$'\033[2m'

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

# ---- main ----
main() {
    print_banner
    echo "TODO: остальные этапы"
}

# Run only when executed, not when sourced (for tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
