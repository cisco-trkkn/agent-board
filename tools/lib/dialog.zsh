# dialog.zsh — sourced by tmux-ctl for `tmux-ctl dialog <win> show` (spec 2026-11-19-remote-discord-only §1).
# Reads the Claude Code dialog showing in a window's main pane, or in a pane given by id (%<digits>, anywhere on the server),
# from the pane text alone, and prints it as one JSON object. Read-only: no key is ever sent here.
# Built from approve.zsh (its screen read, its option-run rule, its ambiguity rules); approve.zsh itself is unchanged.
# Uses tmux-ctl's t, use_win, exists, target, die.
#
# Kinds are recognised only from real captured screens (tools/tests/fixtures/approve/*.txt, tools/tests/fixtures/dialogs/*.txt):
#   permission  "Do you want…"/"Would you like…", the run 1. 2. …, then only the `Esc to cancel` footer (approve.zsh's rule)
#   question    AskUserQuestion (footer `Enter to select · … · Esc to cancel`), and the plan-approval dialog
#               (`… Would you like to proceed?`, footer `ctrl+g to edit in …`)
#   trust       the folder-trust screen (`Accessing workspace:`, footer `Enter to confirm · Esc to cancel`); its rows have no numbers
#   resume      the `claude --resume` picker (`Resume session`, footer `… Enter to resume · Esc to close`); its rows have no numbers
#   unknown     any other numbered run with the cursor on one of its rows (the generic parse), and a permission prompt whose
#               preview could fake its own frame (approve's X:ambiguous). Every row of an unknown dialog is permanent: true.
# `login` is in the kind list of the spec but was never captured, so it has no branch: such a screen reads as unknown.

# The one list of permanent-row substrings, `|`-separated, matched case-insensitively against a label (`’` counts as `'`).
_DLG_PERMANENT="don't ask again|always allow|switch to auto mode|accept edits|use auto mode"

# _dlg_screen <pane>: the whole visible pane, one row per line: control characters and trailing blanks dropped, empty rows dropped.
# Bytes only (LC_ALL=C): the same output in any locale.
_dlg_screen() { t capture-pane -p -J -t "$1" 2>/dev/null | LC_ALL=C tr -d '\000-\011\013-\037\177' | LC_ALL=C sed -e 's/ *$//' | LC_ALL=C grep -a -v '^$' }

# _dlg_parse: stdin = the screen. Prints nothing when no dialog shows. Otherwise, in this order:
#   K:<kind>   Q:<question>   M:<0|1> (multi-select)   W:<0|1> (a free-text row is present)
#   O:<n>:<0|1>:<label>   one per option; the flag is `permanent`
#   L:<line>              one per line of the dialog: the rows after its top rule up to, not including, the key-hint footer
#                         (a teammate status divider `──── @name ─` or a task list after the footer is not part of it);
#                         a prompt taller than the pane starts at the first screen row and ends with its `↑ N more lines`
#                         row; the auto-mode countdown time is written M:SS
# Byte-literal dividers and cursor (no {n}, no multibyte class, no length() of a row): the same result in any locale.
_dlg_parse() {
  awk -v permlist="$_DLG_PERMANENT" '
    function isdiv(x)  { return index(x, "──────────") == 1 }
    function isrule(x) { return index(x, "╌╌╌╌╌╌╌╌╌╌") == 1 }
    function ltrim(x)  { sub(/^[ \t]+/, "", x); return x }
    function hascur(x) { return x ~ /^[ \t]*❯/ }
    function nocur(x)  { if (x ~ /^[ \t]*❯/) sub(/❯/, " ", x); return x }   # the cursor as one blank: the columns stay
    function indent(x) { x = nocur(x); match(x, /^[ \t]*/); return RLENGTH }
    function optnum(x,   t) {   # the number of an option row, else 0
      t = x; sub(/^[ \t]*(❯)?[ \t]*/, "", t)
      if (t ~ /^[0-9]+\.[ \t]+/) { sub(/\..*/, "", t); return t + 0 }
      return 0
    }
    function optlabel(x,   t) { t = x; sub(/^[ \t]*(❯)?[ \t]*[0-9]+\.[ \t]+/, "", t); return t }
    function join(a, b,   i, r) { r = ""; for (i = a; i <= b; i++) r = r (r == "" ? "" : " ") ltrim(l[i]); return r }
    # qjoin: join for a question drawn as wrapped rows behind a "│ " gutter (a long AskUserQuestion text): the gutter is dropped
    function qjoin(a, b,   i, r, x) { r = ""; for (i = a; i <= b; i++) { x = ltrim(l[i]); sub(/^│[ \t]*/, "", x); if (x != "") r = r (r == "" ? "" : " ") x }; return r }
    function reset() { no = 0; multi = 0; other = 0 }
    function addopt(n, label,   t, k) {
      if (label ~ /^\[( |✔)\] /) { multi = 1; sub(/^\[( |✔)\] /, "", label) }   # a multi-select checkbox
      if (label ~ /^Type something\.?$/ || label == "Tell Claude what to change") other = 1   # the free-text rows of the captured screens
      t = tolower(label); gsub(/’/, "\047", t)
      no++; on[no] = n; ol[no] = label; op[no] = 0
      for (k = 1; k <= np; k++) if (perm[k] != "" && index(t, perm[k])) op[no] = 1
    }
    # emit: the tagged block of rows a..b; all = 1 flags every row permanent (an unknown dialog)
    function emit(kind, qt, a, b, all,   i, x) {
      print "K:" kind; if (PAMB) print "A:ambiguous"; print "Q:" qt; print "M:" (multi ? 1 : 0); print "W:" (other ? 1 : 0)
      for (i = 1; i <= no; i++) print "O:" on[i] ":" ((all || op[i]) ? 1 : 0) ":" ol[i]
      for (i = a; i <= b; i++) {
        x = l[i]
        # auto mode draws "block this request in M:SS" and it ticks every second: only the time of that exact warning row is masked
        if (x ~ /^ *⚠ Claude Code will automatically block this request in [0-9][0-9]*:[0-9][0-9], to avoid holding up an unattended session$/)
          sub(/request in [0-9][0-9]*:[0-9][0-9],/, "request in M:SS,", x)
        print "L:" x
      }
      return 1
    }

    # permission: approve.zsh _ap_prompt. The options are only the contiguous run 1. 2. … right after the last
    # "Do you want…"/"Would you like…" line, so option-shaped text inside the command preview is never one.
    # A long option label wraps onto a row indented to the label column (approve/lead-tasklist-more-lines.txt, option 2).
    function labcol(x,   t) { t = nocur(x); match(t, /^[ \t]*[0-9]+\.[ \t]+/); return RLENGTH }
    # runend(i): the last row of the run 1. 2. … that starts at row i, the wrapped rows of its labels included
    function runend(i,   j, n, lc) {
      j = i; n = 1; lc = -1
      while (j <= N2) {
        if (optnum(l[j]) == n) { lc = labcol(l[j]); j++; n++ }
        else if (n > 1 && !optnum(l[j]) && !hascur(l[j]) && indent(l[j]) == lc) j++
        else break
      }
      return j - 1
    }
    # addrun(a, b): the options of the rows a..b of such a run; a wrapped row joins its label with one blank
    function addrun(a, b,   i, cn, cur) {
      cn = 0
      for (i = a; i <= b; i++) {
        if (optnum(l[i])) { if (cn) addopt(cn, cur); cn = optnum(l[i]); cur = optlabel(l[i]) }
        else cur = cur " " ltrim(l[i])
      }
      if (cn) addopt(cn, cur)
    }
    function permission(   i, q, e, s, a, ft, mr, nr, r1, r2, amb) {
      reset(); q = 0; e = 0
      for (i = 1; i < N2; i++) {
        if (l[i] !~ /(Do you want|Would you like)/ || optnum(l[i+1]) != 1) continue
        q = i; e = runend(i + 1)
      }
      if (!q) return 0
      # only these may follow the options: one `↑ N more lines` row (the prompt is taller than the pane: its top is off
      # screen) and the footer. A teammate status divider or a task list (dropped in END) counts only after a footer.
      ft = 0; mr = 0
      for (i = e + 1; i <= N2; i++) {
        if (!ft && !mr && l[i] ~ /^[ \t]*↑ [0-9]+ more lines$/) { mr = i; continue }
        if (l[i] ~ /^[ \t]*Esc to cancel/) { ft = 1; continue }
        return 0
      }
      if ((TDIV || TLIST) && !ft) return 0
      if (mr) {
        # taller than the pane: every row above the question belongs to the prompt, so `lines` start at the first screen row.
        # Ambiguous when a row there is not indented (a solid divider would be a frame top that cannot be on screen), or
        # more than two ╌ rules show.
        a = 1; nr = 0; amb = 0
        for (i = 1; i < q; i++) { if (isrule(l[i])) nr++; else if (l[i] ~ /^[^ \t]/) amb = 1 }
        if (nr > 2) amb = 1
      } else {
        s = q
        for (i = q; i >= 1; i--) if (isdiv(l[i])) { s = i; break }
        # ambiguous when the preview could fake its own frame: a solid divider or ╌ rule at column 1 above the chosen divider,
        # not exactly two ╌ rules between the divider and the question, or a non-indented row between the two rules
        r1 = 0; r2 = 0; nr = 0
        for (i = s + 1; i < q; i++) if (isrule(l[i])) { nr++; if (!r1) r1 = i; else if (!r2) r2 = i }
        amb = (nr != 2)
        for (i = r1 + 1; r1 && r2 && i < r2; i++) if (l[i] ~ /^[^ \t]/) amb = 1
        for (i = 1; i < s; i++) if (isdiv(l[i]) || isrule(l[i])) amb = 1
        a = (s < q ? s + 1 : q)
      }
      addrun(q + 1, e)
      PAMB = amb
      return emit(amb ? "unknown" : "permission", ltrim(l[q]), a, (mr ? mr : e), amb)
    }

    # question: AskUserQuestion (dialogs/question-*.txt). From the bottom: the footer, the last numbered row (Chat about this),
    # a rule, then up to the top rule of the dialog: an optional chip / tab bar row, the question, and the rows 1. 2. … at
    # column 3 with their description rows (and the unnumbered Submit row of a multi-select) between them.
    function question(   i, n, k, d2, s, o1, c, qt) {
      reset()
      if (N2 < 6 || l[N2] !~ /^[ \t]*Enter to select · / || l[N2] !~ / · Esc to cancel$/) return 0
      k = optnum(l[N2-1]); d2 = N2 - 2
      if (k < 2 || indent(l[N2-1]) != 2 || !isdiv(l[d2])) return 0
      s = 0; for (i = d2 - 1; i >= 1; i--) if (isdiv(l[i])) { s = i; break }
      if (!s) return 0
      o1 = 0; for (i = s + 1; i < d2; i++) if (optnum(l[i]) == 1 && indent(l[i]) == 2) { o1 = i; break }
      if (!o1) return 0
      c = s + 1; if (l[c] ~ /(☐|☒|✔)/) c++
      qt = qjoin(c, o1 - 1); if (qt == "") return 0
      n = 1
      for (i = o1; i < d2; i++) if (optnum(l[i]) == n && indent(l[i]) == 2) { addopt(n, optlabel(l[i])); n++ }
      if (k != n) return 0
      addopt(k, optlabel(l[N2-1]))
      return emit("question", qt, s + 1, N2 - 1, 0)
    }

    # plan approval (dialogs/plan.txt), kind question: "… Would you like to proceed?" under an indented rule, the run, at most
    # the one sub-row of the feedback option, then the `ctrl+g to edit in …` footer. The plan box above (from "Ready to code?")
    # belongs to `lines` when it is on screen.
    function plan(   i, j, n, q, e, qs, s) {
      reset(); q = 0; e = 0
      for (i = 1; i < N2; i++) {
        if (l[i] !~ /Would you like to proceed\?$/ || optnum(l[i+1]) != 1) continue
        j = i + 1; n = 1
        while (j <= N2 && optnum(l[j]) == n) { j++; n++ }
        q = i; e = j - 1
      }
      if (!q || l[N2] !~ /^[ \t]*ctrl\+g to edit in /) return 0
      if (!(e == N2 - 1 || (e == N2 - 2 && ltrim(l[N2-1]) == "shift+tab to approve with this feedback"))) return 0
      qs = 0; for (i = q - 1; i >= 1 && i >= q - 3; i--) if (isdiv(ltrim(l[i]))) { qs = i; break }
      if (!qs) return 0
      s = qs; for (i = qs - 1; i >= 1; i--) if (isdiv(ltrim(l[i])) && ltrim(l[i+1]) == "Ready to code?") { s = i; break }
      for (i = q + 1; i <= e; i++) addopt(optnum(l[i]), optlabel(l[i]))
      return emit("question", join(qs + 1, q), s + 1, N2 - 1, 0)
    }

    # trust (dialogs/trust.txt): the rows right above the footer, at one indent, exactly one of them under the cursor; they
    # carry no numbers on screen and are numbered 1, 2, … in screen order. The question is the first sentence of the check.
    function trust(   i, s, qi, qt, ind, b, nc) {
      reset()
      if (N2 < 5 || l[N2] !~ /^[ \t]*Enter to confirm · Esc to cancel$/) return 0
      s = 0; for (i = N2 - 1; i >= 1; i--) if (isdiv(l[i]) && l[i+1] ~ /^[ \t]*Accessing workspace:$/) { s = i; break }
      if (!s) return 0
      qi = 0; for (i = s + 1; i < N2; i++) if (l[i] ~ /^[ \t]*Quick safety check: /) { qi = i; break }
      if (!qi) return 0
      qt = ltrim(l[qi]); sub(/\?.*$/, "?", qt)
      ind = indent(l[N2-1]); b = N2 - 1
      while (b - 1 > qi && indent(l[b-1]) == ind) b--
      nc = 0; for (i = b; i < N2; i++) if (hascur(l[i])) nc++
      if (N2 - b < 2 || nc != 1) return 0
      for (i = b; i < N2; i++) addopt(i - b + 1, ltrim(nocur(l[i])))
      return emit("trust", qt, s + 1, N2 - 1, 0)
    }

    # resume (dialogs/resume.txt): a session is a title row followed by its `<age> · <branch> · <size>` row; the titles
    # carry no numbers on screen and are numbered 1, 2, … in screen order.
    function ismeta(x) { return x ~ /^[ \t]+[^ \t].* · .* · [0-9.]+[KMGT]?B$/ }
    function resume(   i, s, n) {
      reset()
      if (N2 < 5 || l[N2] !~ /Enter to resume/ || l[N2] !~ /Esc to close$/) return 0
      s = 0; for (i = N2 - 1; i >= 1; i--) if (isdiv(l[i]) && l[i+1] ~ /^[ \t]*Resume session/) { s = i; break }
      if (!s) return 0
      n = 0
      for (i = s + 3; i < N2; i++) if (ismeta(l[i]) && !ismeta(l[i-1])) addopt(++n, ltrim(nocur(l[i-1])))
      if (!n) return 0
      return emit("resume", ltrim(l[s+1]), s + 1, N2 - 1, 0)
    }

    # generic (a screen of no captured kind): the last contiguous run 1. 2. … of at least two rows with the cursor on exactly
    # one of them, a text row right above it (the question; a rule there means typed text in the input box), and no ❯ row
    # after it (the input box of a screen whose list is only text). Every row is permanent: nothing is guessed about it.
    function generic(   i, j, n, o1, e, nc, qt, s, b) {
      reset(); o1 = 0
      for (i = 1; i <= N2; i++) if (optnum(l[i]) == 1) o1 = i
      if (o1 < 2) return 0
      j = o1; n = 1
      while (j <= N2 && optnum(l[j]) == n) { j++; n++ }
      e = j - 1
      if (e - o1 < 1) return 0
      nc = 0; for (i = o1; i <= e; i++) if (hascur(l[i])) nc++
      if (nc != 1) return 0
      for (i = e + 1; i <= N2; i++) if (hascur(l[i])) return 0
      qt = ltrim(l[o1-1])
      if (index(qt, "─") == 1 || index(qt, "╌") == 1 || index(qt, "❯") == 1 || index(qt, "│") == 1 || index(qt, "╰") == 1) return 0
      s = 0; for (i = o1 - 2; i >= 1; i--) if (isdiv(ltrim(l[i]))) { s = i; break }
      for (i = o1; i <= e; i++) addopt(optnum(l[i]), optlabel(l[i]))
      # `lines` end before the key-hint footer when one shows (a row under it, a status line or a timer, is not the dialog);
      # without one they run to the last row
      b = N2; for (i = e + 1; i <= N2; i++) if (l[i] ~ /(Esc to |Enter to )/) { b = i - 1; break }
      return emit("unknown", qt, (s ? s + 1 : o1 - 1), b, 1)
    }
    # tasklist(): when the last rows of the screen are a task list (a `N/M tasks done` row, then only rows indented by two
    # or more), the row before it; else N2. A session with tasks draws the list under the dialog footer
    # (approve/lead-tasklist-more-lines.txt); above an input box it is not the last rows and stays.
    function tasklist(   i, h) {
      h = 0; for (i = N2; i >= 1; i--) if (l[i] ~ /^ +[0-9]+\/[0-9]+ tasks done/) { h = i; break }
      if (!h) return N2
      for (i = h + 1; i <= N2; i++) if (l[i] !~ /^  +[^ \t]/ || hascur(l[i]) || isdiv(ltrim(l[i]))) return N2
      return h - 1
    }

    BEGIN { np = split(permlist, perm, "|"); for (k = 1; k <= np; k++) perm[k] = tolower(perm[k]) }
    { l[NR] = $0 }
    END {
      N = NR; N2 = N; TDIV = 0; TLIST = 0; PAMB = 0
      if (N2 >= 1 && isdiv(l[N2]) && l[N2] ~ / @[A-Za-z0-9_.-]+ ─$/) { N2--; TDIV = 1 }   # a teammate status divider as the last row
      i = tasklist(); if (i < N2) { N2 = i; TLIST = 1 }                                   # a task list as the last rows
      if (permission() || question() || plan() || trust() || resume()) exit
      generic()
    }'
}

# _dlg_json: stdin = a _dlg_parse block. Prints it as one JSON object on one line (UTF-8 passed through as it is).
_dlg_json() {
  awk '
    function js(s,   o, p) {   # a JSON string: only \ and " need escaping (_dlg_screen drops the control characters)
      o = ""
      while ((p = match(s, /[\\"]/)) > 0) { o = o substr(s, 1, p - 1) "\\" substr(s, p, 1); s = substr(s, p + 1) }
      return "\"" o s "\""
    }
    {
      tag = substr($0, 1, 2); v = substr($0, 3)
      if (tag == "K:") kind = v
      else if (tag == "Q:") q = v
      else if (tag == "M:") multi = (v == "1")
      else if (tag == "W:") other = (v == "1")
      else if (tag == "O:") {
        n = v; sub(/:.*/, "", n); v = substr(v, length(n) + 2)
        opts = opts (opts == "" ? "" : ",") "{\"n\":" (n + 0) ",\"label\":" js(substr(v, 3)) ",\"permanent\":" (substr(v, 1, 1) == "1" ? "true" : "false") "}"
      }
      else if (tag == "L:") lines = lines (lines == "" ? "" : ",") js(v)
    }
    END {
      if (kind == "") exit 1
      print "{\"kind\":" js(kind) ",\"question\":" js(q) ",\"options\":[" opts "],\"multi\":" (multi ? "true" : "false") ",\"other\":" (other ? "true" : "false") ",\"lines\":[" lines "]}"
    }'
}

# _dlg_pane <win>: sets REPLY to the pane to read: <win> itself when it is a pane id (anywhere on the server), else the
# main pane of the window <win> of this session. Dies (exit 2) when there is no such pane or window.
_dlg_pane() {
  if [[ "$1" == %<-> ]]; then
    [[ "$(t display -p -t "$1" '#{pane_id}' 2>/dev/null)" == "$1" ]] || die "no pane '$1' on this tmux server"
    REPLY="$1"
  else
    use_win "$1"; exists "$1"
    REPLY="$(target "$1")"
  fi
}

# _dlg_approve_view: stdin = a _dlg_parse block. For `tmux-ctl approve`: prints nothing when the block is not a permission prompt;
# `X:ambiguous` alone when the prompt could fake its own frame (the parse's A: tag); else `T:<first row of the dialog, trimmed>`
# (the tool title), `P:<line>` for each line --expect must equal, in order, and `O:<n>:<label>` for each option. The P: lines are
# the command of a Bash prompt (between its two ╌ rules); any other prompt: the rows below the title down to the first ╌ rule
# (the file path only). Never the Bash description, the question or the option rows.
_dlg_approve_view() {
  awk '
    function trim(x) { sub(/^[ \t]+/, "", x); sub(/[ \t]+$/, "", x); return x }
    function isrule(x) { return index(x, "╌╌╌╌╌╌╌╌╌╌") == 1 }
    { tag = substr($0, 1, 2); v = substr($0, 3)
      if (tag == "K:") kind = v
      else if (tag == "A:") amb = 1
      else if (tag == "O:") { n = v; sub(/:.*/, "", n); v = substr(v, length(n) + 2); sub(/^[01]:/, "", v); o[++no] = n ":" v }
      else if (tag == "L:") l[++nl] = v }
    END {
      if (amb) { print "X:ambiguous"; exit }
      if (kind != "permission") exit
      r1 = 0; r2 = 0
      for (i = 1; i <= nl; i++) if (isrule(l[i])) { if (!r1) r1 = i; else if (!r2) r2 = i }
      print "T:" trim(l[1])
      if (r1 && r2) {
        if (l[1] !~ /^[ \t]*Bash command/) { for (i = 2; i < r1; i++) if (trim(l[i]) != "") print "P:" trim(l[i]) }
        else for (i = r1 + 1; i < r2; i++) if (trim(l[i]) != "") print "P:" trim(l[i])
      }
      for (i = 1; i <= no; i++) print "O:" o[i]
    }'
}

# _dlg_read <pane>: sets BLOCK to the parsed screen (empty when no dialog shows) and LINES to its `lines` joined by newlines.
_dlg_read() {
  BLOCK="$(_dlg_screen "$1" | _dlg_parse)"
  LINES_="$(print -r -- "$BLOCK" | grep -a '^L:' | sed -e 's/^L://')"
}

# _dlg_nav <pane> <delta>: Down x delta, or Up x -delta.
_dlg_nav() { local i; for (( i = 0; i < $2; i++ )); do t send-keys -t "$1" Down; done; for (( i = 0; i < -($2); i++ )); do t send-keys -t "$1" Up; done }

# _dlg_press_keys <pane> <kind> <multi> <ncheck> <cur> <plan> <opts…>: sends the keys of tools/tests/fixtures/dialogs/README.md `## Key probes`.
#   multi: opts = the rows to toggle (already the difference between the checked rows and the wanted set), ncheck = its checkbox
#   rows, cur = the cursor position of the read (row n for a checkbox row, ncheck+1 on `Submit`, ncheck+2 on `Chat about this`).
#   trust|resume|login: opts = the option wanted, cur = the option under the cursor. Else: a digit (plan: then Enter).
_dlg_press_keys() {
  local pane="$1" kind="$2" multi="$3" ncheck="$4" cur="$5" plan="$6" n; shift 6
  if [[ "$multi" == 1 ]]; then
    for n in "$@"; do t send-keys -t "$pane" -l -- "$n"; done          # a digit only toggles; the cursor stays
    _dlg_nav "$pane" $(( ncheck + 1 - cur ))                           # onto `Submit`
    t send-keys -t "$pane" Enter                                       # the review screen is a new dialog: never pressed here
    return
  fi
  n="$1"
  case "$kind" in
    trust|resume|login)   # rows without digits: from the cursor row of the read to row n, then Enter
      _dlg_nav "$pane" $(( n - cur )); t send-keys -t "$pane" Enter ;;
    *)
      t send-keys -t "$pane" -l -- "$n"
      [[ "$plan" == 1 ]] && t send-keys -t "$pane" Enter ;;
  esac
}

# dialog_press <win> <args…>: see the usage line. Reads the dialog twice (byte-identical `lines` both times and equal to
# --expect), checks copy mode after each read, then sends the keys; the label of each option comes from that same read.
_dlg_press() {
  local win="$1" pane expect="" have_expect=0 text="" have_text=0 opts=() u="usage: tmux-ctl dialog <win> press --expect <lines> (--option <n>... | --text <text>)"
  local first kind multi other ncheck cur ol i line labels n found other_n PLAN tog
  shift
  while (( $# )); do
    case "$1" in
      --expect) (( $# >= 2 )) || die "$u"; expect="$2"; have_expect=1; shift 2 ;;
      --option) (( $# >= 2 )) || die "$u"; [[ "$2" == <-> && "$2" != 0* ]] || die "--option needs a number ($u)"; opts+=("$2"); shift 2 ;;
      --text)   (( $# >= 2 )) || die "$u"; text="$2"; have_text=1; shift 2 ;;
      *) die "$u" ;;
    esac
  done
  (( have_expect )) || die "--expect <lines> is required: the dialog's lines from show, newline-joined ($u)"
  if (( ${#opts} > 0 && have_text )) || (( ${#opts} == 0 && ! have_text )); then die "give --option <n> (repeat it on a multi-select) or --text <text>, not both and not neither ($u)"; fi
  [[ "$have_text" == 1 && -z "$text" ]] && die "--text needs a non-empty text ($u)"
  _dlg_pane "$win"; pane="$REPLY"
  _dlg_read "$pane"
  [[ -n "$BLOCK" ]] || { print -u2 "dialog: none in $win"; return 1 }
  first="$BLOCK"
  [[ "$LINES_" == "$expect" ]] || { print -u2 "dialog: the dialog in $win changed"; return 1 }
  # what the keys depend on, all from this read
  kind="$(print -r -- "$first" | sed -n 's/^K://p')"
  multi="$(print -r -- "$first" | sed -n 's/^M://p')"
  other="$(print -r -- "$first" | sed -n 's/^W://p')"
  ol=("${(@f)$(print -r -- "$first" | sed -n 's/^O://p')}")   # n:perm:label
  ncheck=$(( ${#ol} - 1 ))
  # the cursor of the read: a multi-select counts checkbox rows 1..ncheck, `Submit` ncheck+1, `Chat about this` ncheck+2;
  # trust, resume and login rows have no numbers, so the cursor row is the option whose label is on the `❯` row
  typeset -A chk; cur=0
  for line in "${(@f)LINES_}"; do
    if [[ "$multi" == 1 ]]; then
      if [[ "$line" =~ '^[[:space:]]*(❯[[:space:]]+)?([0-9]+)\.[[:space:]]+\[(✔| )\] ' ]]; then
        [[ "${match[3]}" == "✔" ]] && chk[${match[2]}]=1
      fi
      if [[ "$line" =~ '^[[:space:]]*❯[[:space:]]+([0-9]+)\.' ]]; then (( match[1] > ncheck )) && cur=$(( ncheck + 2 )) || cur="${match[1]}"
      elif [[ "$line" =~ '^[[:space:]]*❯[[:space:]]+Submit$' ]]; then cur=$(( ncheck + 1 ))
      fi
    elif (( cur == 0 )) && [[ "$kind" == (trust|resume|login) && "$line" =~ '^[[:space:]]*❯[[:space:]]+(.*)$' ]]; then
      for n in "${ol[@]}"; do [[ "${n#*:*:}" == "${match[1]}" ]] && { cur="${n%%:*}"; break }; done
    fi
  done
  if (( cur == 0 )) && [[ "$multi" == 1 || "$kind" == (trust|resume|login) ]] && (( ! have_text || multi == 1 )); then
    print -u2 "dialog: $win: no cursor in the dialog"; return 1
  fi
  # the plan-approval dialog is the one whose free-text row is "Tell Claude what to change": a digit only moves its cursor, so Enter follows
  PLAN=0; [[ "$first" == *$'\n'"O:"<->":"[01]":Tell Claude what to change"* ]] && PLAN=1
  # option / text validation (usage errors, nothing sent): numbers of the dialog's options only
  labels=""
  if (( have_text )); then
    [[ "$other" == 1 ]] || die "this dialog has no free-text row (other: false); --text does not apply"
    other_n=0
    for line in "${ol[@]}"; do
      n="${line%%:*}"; i="${line#*:*:}"
      [[ "$i" == "Type something"(.|) || "$i" == "Tell Claude what to change" ]] && { other_n="$n"; break }
    done
    (( other_n )) || die "no free-text row found"
    labels="$text"
  else
    [[ "$multi" == 1 ]] && opts=(${(onu)opts})   # the --option set is the final set of checked rows: duplicates collapse
    if (( ${#opts} > 1 )) && [[ "$multi" != 1 ]]; then die "--option repeated: only a multi-select takes several"; fi
    for n in "${opts[@]}"; do
      found=0
      for line in "${ol[@]}"; do
        [[ "${line%%:*}" == "$n" ]] && { found=1; labels="${labels:+$labels, }${line#*:*:}"; break }
      done
      (( found )) || die "no option $n in this dialog"
    done
    # a multi-select's Chat-about-this row is not a checkbox
    if [[ "$multi" == 1 ]]; then for n in "${opts[@]}"; do (( n <= ncheck )) || die "option $n is not a checkbox of this multi-select"; done; fi
  fi
  [[ -n "$TC_DIALOG_BEFORE_SEND" ]] && eval "$TC_DIALOG_BEFORE_SEND" >/dev/null 2>&1
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "dialog: $win is in copy mode"; return 1 }
  _dlg_read "$pane"
  [[ "$BLOCK" == "$first" && "$LINES_" == "$expect" ]] || { print -u2 "dialog: the dialog in $win changed"; return 1 }
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "dialog: $win is in copy mode"; return 1 }
  if (( have_text )); then
    if [[ "$multi" == 1 ]]; then
      _dlg_nav "$pane" $(( other_n - cur ))
      t send-keys -t "$pane" -l -- "$text"
      _dlg_nav "$pane" $(( ncheck + 1 - other_n ))   # Other row onto Submit
      t send-keys -t "$pane" Enter
    else
      t send-keys -t "$pane" -l -- "$other_n"; t send-keys -t "$pane" -l -- "$text"; t send-keys -t "$pane" Enter
    fi
  else
    if [[ "$multi" == 1 ]]; then   # toggle only the rows whose checked state differs from the wanted set
      tog=(); for (( i = 1; i <= ncheck; i++ )); do (( ${+chk[$i]} == (${opts[(Ie)$i]} > 0) )) || tog+=("$i"); done
      _dlg_press_keys "$pane" "$kind" "$multi" "$ncheck" "$cur" "$PLAN" "${tog[@]}"
    else
      _dlg_press_keys "$pane" "$kind" "$multi" "$ncheck" "$cur" "$PLAN" "${opts[@]}"
    fi
  fi
  print -r -- "dialog: $win: chose \"$labels\""
}

dialog_cmd() {
  local win="$1" act="$2" pane block u="usage: tmux-ctl dialog <win> show|press"
  [[ -n "$win" ]] || die "$u"
  if [[ "$act" == press ]]; then shift 2; _dlg_press "$win" "$@"; return $?; fi
  shift 2 2>/dev/null
  [[ "$act" == show && $# -eq 0 ]] || die "$u"
  _dlg_pane "$win"; pane="$REPLY"
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "dialog: $win is in copy mode"; return 1 }
  block="$(_dlg_screen "$pane" | _dlg_parse)"
  [[ -n "$block" ]] || { print -u2 "dialog: none in $win"; return 1 }
  print -r -- "$block" | _dlg_json
}
