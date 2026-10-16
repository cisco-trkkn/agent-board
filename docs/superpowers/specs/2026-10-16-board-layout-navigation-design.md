# Agent Board: layout, navigation and folder picker

Date: 2026-10-16. The ideas inbox (group B) covers four ideas: the top navigation is hard to use; the agent worktrees panel is too narrow to show its remove button; the worktrees panel can't be used while a terminal is open; projects in dot-folders can't be opened.

Code: `~/.local/share/tmux-dash` (`index.html`, `server.py`, new `dirs.py`). These files are not under git: back up each one as `F.bak-YYYYMMDD` before editing it.

## Goals

- **Risky actions apart:** Close project is no longer next to Open project.
- **Moving between sections:** you can jump between the board's sections without scrolling around.
- **Worktrees always usable:** the worktrees list works at any width, and while a terminal or document is open.
- **Opening dot-folders:** a project folder can be picked by autocomplete or by browsing, and folders whose names start with `.` can be found that way.

Non-goals:
- splitting the board into separate views or routes (the single page stays);
- agent controls (group A);
- editing ideas (group D);
- the usage dashboard (group C).

## 1. Layout and navigation

### Header

- The project tabs stay as they are.
- On the right: the live indicator, `+ New agent`, and a `⋯` menu button.
- The `⋯` menu holds `Open project…`, then a divider, then `Close project…`, shown in the danger colour. Both open their existing dialogs, and Close keeps its confirmation.
- The menu closes on Escape, on an outside click, or once an item is chosen. It works from the keyboard: Enter or Space opens it, and the arrow keys move between items.

### Jump-to row

- A slim sticky row under the header: `Agents · Windows · Worktrees · Activity`.
- Clicking an entry scrolls the main column to that section (smooth scroll, offset for the sticky header).
- The highlighted entry follows the section in view, tracked by an `IntersectionObserver` on the section titles.
- The Artifacts sidebar stays on the left, unchanged.

### Drawer (terminal and documents)

- The terminal (`#term`) and the document viewer (`#doc`) no longer cover the main column. They open in one shared drawer on the right of the layout.
- The main column shrinks while the drawer is open, but still scrolls and stays fully interactive.
- Only one of the two shows at a time. Opening one replaces the other, so the slot is shared.
- **Resizing:** drag the drawer's left edge. The width is clamped between 320px and 70% of the viewport, and stored in `localStorage` (`dash.drawerWidth`). The default is 45%.
- Every `localStorage` access is wrapped in try/catch.
- ✕ closes the drawer. `Pop out ↗` keeps its current behaviour.
- **Narrow windows:** below 900px wide, the drawer stacks under the page at 60vh, as it does today, because a side split doesn't fit.

### Worktrees list

- Each row is a flex layout. The name and branch take the flexible space and truncate with an ellipsis, with `title` holding the full text.
- The status badges and the Remove button never shrink, and stay visible.
- Below about 520px of column width, the details wrap under the name.

## 2. Folder picker in the Open project dialog

### Autocomplete

- As you type in `#project-path`, the board lists the subfolders of the parent folder you've typed so far that start with the last path segment.
- At most 20 suggestions, including folders whose names start with `.`.
- **Keys:** the arrow keys move through the suggestions. Tab completes the selected one, adding a trailing `/`. Enter submits the dialog. Escape closes the list.
- `~` and `~/…` are expanded on the server.
- **Request timing:** requests are debounced by 150ms. A response that arrives after a newer request was sent is ignored.

### Browse button

- A `Browse…` button next to the input switches the dialog into a folder browser. It starts at the folder typed in the input if that exists, otherwise at `~`.
- **Top of the browser:**
  - a clickable breadcrumb of the current path;
  - an `↑ Up` button;
  - a `Show hidden` checkbox: off by default, remembered in `localStorage` (`dash.showHidden`).
- **The list:**
  - **Recent:** up to 10 recent projects (section 3) above the folder list.
  - **Folders:** only folders, sorted by name, with a `git` badge on folders that contain `.git`.
  - Clicking a folder goes into it.
- **Using a folder:** `Open this folder` fills the input with the current path and returns to the input view. `Back` returns without changing the input.

### Endpoint

`GET /api/dirs?path=<p>&prefix=<s>&hidden=<0|1>` returns:

```json
{"path": "/abs/resolved", "parent": "/abs" , "dirs": [{"name": ".claude", "git": false, "hidden": true}], "truncated": false}
```

- **Access:** it needs the board token, like every other `/api/*` route.
- **`path`:**
  - `~` is expanded, then the path is resolved with `os.path.realpath`.
  - An empty `path` means `~`.
  - `parent` is `null` at `/`.
- **What is listed:**
  - Only directories are listed, after symlinks are resolved. File names are never returned.
  - `prefix` keeps only the names that start with it, case-sensitively. It is used by autocomplete, which sends `hidden=1`.
  - `hidden=0` leaves out names that start with `.`.
- **Limits:** results are sorted by name and capped at 500 entries, with `truncated: true` when the cap is hit. Autocomplete keeps only the first 20.
- **Errors:**
  - a path that doesn't exist or isn't a directory returns 400 `{"error": "not a folder: <p>"}`;
  - a `PermissionError` returns 403 `{"error": "can't read <p>: permission denied"}`.
- **Scope:** it is not limited to `$HOME`. Projects may live elsewhere, and the board is bound to localhost and token-gated.

## 3. Recent projects, errors and testing

### Recent projects

- After a successful `dev` action, `server.py` records the path in `recent-projects.json` in the board's state folder, through `dirs.record_recent(path)`.
- **Format:** a JSON list of absolute paths, newest first, with no duplicates (an existing entry moves to the front), capped at 10.
- **Writing:** the file is written atomically: a temp file, then `os.replace`.
- **Reading:** `GET /api/dirs/recent` returns the stored list merged with the paths of the sessions open now. Open sessions come first, then the stored list, with duplicates removed. Paths that no longer exist are dropped.

### Errors

- **Autocomplete:** a failure gives an empty suggestion list, with no toast.
- **Browser:** a failed listing shows the error text inline in the dialog and keeps the previous folder.
- **Opening the project:** the existing `not a folder` toast stays.

### Testing

**Unit tests:** `tests/test_dirs.py`, using a temp tree, cover:
- directories only;
- hidden names flagged and filtered;
- the `git` badge;
- symlinked directories followed;
- a symlink to a file left out;
- `prefix` filtering;
- the 500 cap and `truncated`;
- `~` expansion;
- `parent` at `/`;
- `PermissionError` → 403 (a directory with mode 000, skipped when running as root);
- recent projects: dedupe and move-to-front, the cap of 10, the atomic write, missing paths dropped, and open sessions merged in first.

**Route tests:** `/api/dirs` without the token → 404 (the existing guard); with the token → 200, with the expected JSON.

**Live browser check:** using the Chrome tools on the live board, with real accumulated state, not a fresh scratch project. Confirm each of these:
- the `⋯` menu opens and closes, and Close is separated from Open;
- the Jump-to row scrolls to each section and highlights the right one;
- with the terminal drawer open, the worktrees Remove button is visible and clickable, and dragging the edge resizes the drawer and keeps the new width after a reload;
- typing `~/.cl` suggests `.claude`;
- Browse with `Show hidden` on lists `.claude`, and `Open this folder` fills the input;
- the Recent list shows `~/master-gcp-repo`.

### Files

- `~/.local/share/tmux-dash/index.html`: the header menu, Jump-to row, drawer, worktrees row layout and Open-project dialog.
- `~/.local/share/tmux-dash/server.py`: the `/api/dirs` and `/api/dirs/recent` routes, and recording recent projects in the `dev` action.
- `~/.local/share/tmux-dash/dirs.py` (new): `list_dirs(path, prefix, hidden)`, `record_recent(path)` and `recent(open_paths)`.
- `~/.local/share/tmux-dash/tests/test_dirs.py` (new).
