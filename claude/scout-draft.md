# Trend scout: draft one spec

You are in a git worktree of agent-board. One finding from this week's scout pass is given below as
JSON: what a new Claude Code or Anthropic capability would enable here, with its source and evidence.
Write one design spec for it. A person will approve, reject or ask for a revision; nothing you write
is built before that.

Before you write, read the code the finding touches (Read, Grep, Glob) and two or three recent specs
under `docs/superpowers/specs/` for this repo's form and level of detail.

Write exactly one file, at the path given below under "Write the spec to". Create or change no other
file. Its form:

    # <Title> — design

    Proposed by: scout · Source: <url> (<published date>)

    ## Problem
    ## Decisions
    ## Design
    ## Error handling
    ## Testing
    ## Out of scope

- The title says what agent-board gains, in plain words.
- The `Proposed by` line is given below; copy it as it is.
- **Problem:** what agent-board cannot do, or does worse, today. Name the code that shows it.
- **Decisions:** every choice the design rests on, one bullet each, each ending with
  *(proposed, not approved)*. The user has decided nothing yet, so mark every one.
- **Design:** what changes, file by file, with the values a plan would need (names, formats, limits).
- **Error handling**, **Testing**, **Out of scope:** as in the specs you read.

Rules for file names, checked by code after you finish (a spec that breaks one is dropped):
- Cite only files you have read in this worktree. Put an existing file's repo-relative path in
  backticks, such as `board/server.py`.
- Never put in backticks a file that does not exist in this worktree: a file the design would
  create, a state file, a file in the home directory. Write those in plain text or *italics*.
- Take quotes and claims about the new capability only from the finding's evidence.

When the file is written, answer with one line: its path.
