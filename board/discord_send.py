#!/usr/bin/env python3
"""discord_send.py <project> <thread_key|-> <delete 0|1> <text> <abs file>...: write one post op."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_feed, tc_env

def main(argv):
    project, thread, delete, text, files = argv[0], argv[1], argv[2] == "1", argv[3], argv[4:]
    op = {"op": "post", "text": text, "tier": "progress", "mention_user": False, "files": files}
    if thread != "-": op["thread_key"] = thread
    if delete: op["delete_files"] = True
    discord_feed.outbox_write(tc_env.discord_dir(project), op)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
