# improve: the supervised improvement loop's tmux-ctl entry (spec 2026-11-16 §5). Protected (docs/superpowers/improve/protected.txt).
improve_main() {
  local root=$1; shift
  exec python3 -I "$root/board/improve.py" "$@"
}
