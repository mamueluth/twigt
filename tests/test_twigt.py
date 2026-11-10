"""What twigt's users rely on, through the command line: an outline becomes
a numbered tree with its marks in one column; a task keeps its number
wherever its branch moves; closing takes the open tasks below along; a
deleted branch comes back where it was; contexts keep their own trees and
focus; a task's body shows on demand."""

import io
import re
import sys

import pytest

from twigt.cli import main

OUTLINE = """\
monitoring: uptime + cert expiry | done
ufw cleanup
  drop the dead 8443 rule
card: secure 11000/8080 | you: which host first
"""


MARKS = "[🔲▶⏸⏳✅❌]"


@pytest.fixture
def twigt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TWIGT_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("TWIGT_CTX", raising=False)

    def run(*args, stdin="", ctx="default"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        main(["--ctx", ctx, *args])
        return capsys.readouterr().out

    return run


def refused(run, *args, **options):
    with pytest.raises(SystemExit) as stop:
        run(*args, **options)
    return str(stop.value.code)


def shape(output):
    """The first tree in the output as (depth, number) pairs; message lines have no mark."""
    first = next(block for block in output.strip().split("\n\n") if re.search(MARKS, block.splitlines()[0]))
    return [(match.start() // 3, int(match[1])) for match in map(re.compile(r"(\d+) ").search, first.splitlines())]


def test_an_outline_becomes_a_numbered_tree_with_its_marks_in_one_column(twigt):
    lines = twigt("new", "Nextcloud follow-ups", "-t", "ops", stdin=OUTLINE).splitlines()
    assert re.fullmatch(r"1 Nextcloud follow-ups \[ops\] · \d+ \w+ +🔲 open", lines[0])
    assert re.fullmatch(r"├─ 2 monitoring: uptime \+ cert expiry +✅ done", lines[1])
    assert re.fullmatch(r"├─ 3 ufw cleanup +🔲 open", lines[2])
    assert re.fullmatch(r"│  └─ 4 drop the dead 8443 rule +🔲 open", lines[3])
    assert re.fullmatch(r"└─ 5 card: secure 11000/8080 +⏸ you: which host first", lines[4])
    assert len({re.search(MARKS, line).start() for line in lines}) == 1
    twigt("start", "3")
    assert re.search(r"3 ufw cleanup +▶ in progress", twigt("show"))


def test_a_task_keeps_its_number_wherever_its_branch_moves(twigt):
    twigt("new", "a", stdin=OUTLINE)
    assert shape(twigt("up", "5")) == [(0, 1), (1, 2), (1, 5), (1, 3), (2, 4)]
    assert shape(twigt("down", "5")) == [(0, 1), (1, 2), (1, 3), (2, 4), (1, 5)]
    assert shape(twigt("in", "5")) == [(0, 1), (1, 2), (1, 3), (2, 4), (2, 5)]
    assert shape(twigt("out", "3")) == [(0, 3), (1, 4), (1, 5)]  # out of a tree's top level: a tree of its own
    assert shape(twigt("show", "--all")) == [(0, 1), (1, 2)]
    assert shape(twigt("mv", "3", "-u", "2")) == [(0, 1), (1, 2), (2, 3), (3, 4), (3, 5)]
    assert shape(twigt("mv", "4", "--root")) == [(0, 4)]
    assert "a branch can't go under itself" in refused(twigt, "mv", "1", "-u", "5")
    assert shape(twigt("show", "--all")) == [(0, 1), (1, 2), (2, 3), (3, 5)]  # a refused move changes nothing


def test_closing_takes_the_open_tasks_below_along_and_a_closed_tree_leaves_the_view(twigt):
    twigt("new", "a", stdin=OUTLINE)
    output = twigt("done", "3", "-n", "rules gone")
    assert "Closed along with them: 4." in output
    assert re.search(r"3 ufw cleanup +✅ done: rules gone\n.*4 drop the dead 8443 rule +✅ done\n", output)
    twigt("drop", "1")
    assert "No open trees" in twigt("show")
    assert "❌ dropped" in twigt("show", "--closed")
    assert "🔲 open" in twigt("reopen", "1")


def test_a_deleted_branch_comes_back_where_it_was(twigt):
    before = shape(twigt("new", "a", stdin=OUTLINE))
    output = twigt("delete", "3")
    assert "Deleted 3 with its 1 sub-task" in output
    assert shape(output) == [(0, 1), (1, 2), (1, 5)]
    assert "`twigt restore 3`" in refused(twigt, "show", "4")
    assert "restore 3" in refused(twigt, "restore", "4")
    assert shape(twigt("restore", "3")) == before
    assert shape(twigt("add", "new one")) == before + [(1, 6)]  # numbers are never given out twice


def test_contexts_keep_their_own_trees_and_focus(twigt):
    twigt("new", "a", stdin=OUTLINE, ctx="chat-a")
    assert re.search(r"Other open trees:\n1 a · \d+ \w+ · 3 open", twigt("show", ctx="chat-b"))
    assert "nothing in focus" in refused(twigt, "add", "x", ctx="chat-b")
    twigt("focus", "3", ctx="chat-b")
    assert shape(twigt("add", "x", "y", ctx="chat-b"))[2:6] == [(1, 3), (2, 4), (2, 6), (2, 7)]
    assert shape(twigt("show", ctx="chat-b"))[0] == (0, 1)
    assert "Other open trees" not in twigt("show", ctx="chat-b")
    assert shape(twigt("add", "z", ctx="chat-a"))[-1] == (1, 8)  # chat-a's focus is still 1


def test_a_body_shows_on_demand_and_edits_in_the_editor(twigt, tmp_path, monkeypatch):
    twigt("new", "a")
    twigt("add", "ufw cleanup", "-m", "Docker writes iptables itself.\nKeep 4022.", "-t", "ops")
    assert re.search(r"└─ 2 ufw cleanup \[ops\] ≡ +🔲 open", twigt("show"))
    assert twigt("show", "2").startswith("2 ufw cleanup [ops]  🔲 open\nin 1 a\n\nDocker writes iptables itself.\nKeep 4022.")
    assert "\n      Docker writes iptables itself.\n      Keep 4022." in twigt("show", "-b")

    editor = tmp_path / "editor.py"
    editor.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('UFW cleanup\\n\\nAll rules gone.\\n')\n")
    monkeypatch.setenv("EDITOR", f"{sys.executable} {editor}")
    monkeypatch.delenv("VISUAL", raising=False)
    assert twigt("edit", "2").startswith("2 UFW cleanup [ops]  🔲 open\nin 1 a\n\nAll rules gone.")
    assert twigt("edit", "2", "-m", "-", stdin="From stdin.\n").endswith("\n\nFrom stdin.\n")
