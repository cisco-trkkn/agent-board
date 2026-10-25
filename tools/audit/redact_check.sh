#!/usr/bin/env bash
# usage: redact_check.sh FILE... — fails on secret-shaped strings
set -u
pat='AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20}|sk-ant-[A-Za-z0-9_-]{10,}|xox[abprs]-[A-Za-z0-9-]{10,}|"private_key"[[:space:]]*:|AIza[0-9A-Za-z_-]{35}|(password|passwd|secret)[[:space:]]*[:=][[:space:]]*[^[:space:]<]{6,}|"(password|passwd|secret|token|api_?key)"[[:space:]]*:[[:space:]]*"[^"]{6,}"|api[_-]?key[[:space:]]*[:=][[:space:]]*[^[:space:]<"]{6,}|Bearer[[:space:]]+[A-Za-z0-9._~+/-]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
[ "$#" -gt 0 ] || { echo "redact: no files given"; exit 2; }
grep -nEiH -- "$pat" "$@"; rc=$?
if [ "$rc" -eq 0 ]; then exit 1; fi
if [ "$rc" -ge 2 ]; then echo "redact: error (grep exit $rc)"; exit 2; fi
echo "redact: clean ($# files)"
