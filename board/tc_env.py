"""tc_env: the board's view of tools/lib/tc-env.zsh, the single definition of the state dir,
the shell-command list, the waiting-prompt regex and the worker model/effort choices.
Parsed, not copied: edit the .zsh file only. Test: tests/test_tc_env.py."""
import os
import re
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "tools" / "lib" / "tc-env.zsh"
_TEXT = LIB.read_text(encoding="utf-8")


def _quoted(name):
    return re.search(rf"^{name}='(.*)'\s*$", _TEXT, re.M).group(1)


def _array(name):
    return tuple(re.search(rf"^{name}=\((.*)\)\s*$", _TEXT, re.M).group(1).split())


SHELLS = frozenset(_quoted("TC_SHELLS").strip("()").split("|"))
PROMPT_PATTERN = _quoted("TC_PROMPT_RE")
MODELS = _array("TC_MODELS")
EFFORTS = _array("TC_EFFORTS")
DEFAULT_MODEL = re.search(r"^TC_DEFAULT_MODEL=(\S+)", _TEXT, re.M).group(1)
DEFAULT_EFFORT = re.search(r"^TC_DEFAULT_EFFORT=(\S+)", _TEXT, re.M).group(1)


def state_dir():
    """Same rule as tc_state_dir in tc-env.zsh: $TC_STATE, else ${TMPDIR:-/tmp}/tmux-ctl-<uid>."""
    return Path(os.environ.get("TC_STATE") or f"{(os.environ.get('TMPDIR') or '/tmp').rstrip('/')}/tmux-ctl-{os.getuid()}")
