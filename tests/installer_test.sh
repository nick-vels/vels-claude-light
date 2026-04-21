#!/usr/bin/env bash
# Unit tests for pure functions in install.sh (no side effects).
set -uo pipefail

# shellcheck source=../install.sh
# shellcheck disable=SC1091
source "$(dirname "$0")/../install.sh"  # main-guard prevents main() from running

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
# shellcheck disable=SC2088  # literal tilde is exactly what we're asking the expander to handle
assert_eq "$(HOME=/home/vels expand_workspace_path '~/workspace')" "/home/vels/workspace" "tilde expansion"
assert_eq "$(expand_workspace_path '/abs/path')" "/abs/path" "absolute passthrough"
assert_fail "relative"  expand_workspace_path "rel/path"
# shellcheck disable=SC2088
assert_eq "$(HOME=/home/vels expand_workspace_path '~/')" "/home/vels" "tilde+slash becomes bare HOME"
assert_eq "$(expand_workspace_path '/abs/path/')" "/abs/path" "trailing slash stripped on absolute"
assert_eq "$(expand_workspace_path '/')" "/" "root slash preserved"

exit $FAIL
