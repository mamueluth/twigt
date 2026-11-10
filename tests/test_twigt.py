"""What twigt's users rely on, through the command line: an outline becomes
a tree with its own id, numbered from 1, its marks in one column; a task is
always its tree and number; moves within a tree keep the numbers, and a
branch that leaves its tree is renumbered; closing takes the open tasks
below along; a deleted branch comes back where it was; contexts keep their
own trees and focus; a task's body shows on demand."""

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
TREE_ID = r"(?:[bdfghjklmnprstvz][aeiou]){2,}"


class Twigt:
    def __init__(self, monkeypatch, capsys):
        self.monkeypatch, self.capsys = monkeypatch, capsys

    def __call__(self, *args, stdin="", ctx="default"):
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        main(["--ctx", ctx, *args])
        return self.capsys.readouterr().out

    def refused(self, *args, **options):
        """The reason a command was refused."""
        with pytest.raises(SystemExit) as stop:
            self(*args, **options)
        return f"{stop.value.code} {self.capsys.readouterr().err}"


@pytest.fixture
def twigt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TWIGT_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("TWIGT_CTX", raising=False)
    return Twigt(monkeypatch, capsys)


def shape(output):
    """The first tree in the output as (depth, tree id or number) pairs;
    message lines have no mark."""
    first = next(block for block in output.strip().split("\n\n") if re.search(MARKS, block.splitlines()[0]))
    pairs = []
    for line in first.splitlines():
        match = re.search(r"([a-z]+|\d+) ", line)
        pairs.append((match.start() // 3, int(match[1]) if match[1].isdigit() else match[1]))
    return pairs


def tree_id(output):
    return shape(output)[0][1]


def test_each_tree_has_its_own_id_and_numbers_from_1(twigt):
    lines = twigt("new", "Nextcloud follow-ups", "-t", "ops", stdin=OUTLINE).splitlines()
    assert re.fullmatch(TREE_ID + r" Nextcloud follow-ups \[ops\] · \d+ \w+ +🔲 open", lines[0])
    assert re.fullmatch(r"├─ 1 monitoring: uptime \+ cert expiry +✅ done", lines[1])
    assert re.fullmatch(r"├─ 2 ufw cleanup +🔲 open", lines[2])
    assert re.fullmatch(r"│  └─ 3 drop the dead 8443 rule +🔲 open", lines[3])
    assert re.fullmatch(r"└─ 4 card: secure 11000/8080 +⏸ you: which host first", lines[4])
    assert len({re.search(MARKS, line).start() for line in lines}) == 1
    first = tree_id(lines[0])
    output = twigt("new", "other", stdin="x\n")
    second = tree_id(output)
    assert second != first
    assert shape(output) == [(0, second), (1, 1)]
    twigt("start", f"{first}:2")
    assert re.search(r"2 ufw cleanup +▶ in progress", twigt("show", first))
    assert "kemi:5" in twigt.refused("start", "2")  # a task is always its tree and number


def test_moves_keep_numbers_within_a_tree_and_renumber_a_branch_that_leaves(twigt):
    a = tree_id(twigt("new", "a", stdin=OUTLINE))
    assert shape(twigt("up", f"{a}:4")) == [(0, a), (1, 1), (1, 4), (1, 2), (2, 3)]
    assert shape(twigt("down", f"{a}:4")) == [(0, a), (1, 1), (1, 2), (2, 3), (1, 4)]
    assert shape(twigt("in", f"{a}:4")) == [(0, a), (1, 1), (1, 2), (2, 3), (2, 4)]

    output = twigt("out", f"{a}:2")  # out of a tree's top level: a tree of its own, numbered from 1
    b = tree_id(output)
    assert f"Renumbered: {a}:2 → {b}, {a}:3 → {b}:1, {a}:4 → {b}:2." in output
    assert shape(output) == [(0, b), (1, 1), (1, 2)]
    assert shape(twigt("show", "--all")) == [(0, a), (1, 1)]

    output = twigt("mv", b, "-u", f"{a}:1")  # a whole tree into another: that tree's next numbers
    assert f"Renumbered: {b} → {a}:5, {b}:1 → {a}:6, {b}:2 → {a}:7." in output
    assert shape(output) == [(0, a), (1, 1), (2, 5), (3, 6), (3, 7)]
    assert f"no tree {b}" in twigt.refused("show", b)

    output = twigt("mv", f"{a}:5", "--root")
    c = tree_id(output)
    assert shape(output) == [(0, c), (1, 1), (1, 2)]
    assert "a branch can't go under itself" in twigt.refused("mv", a, "-u", f"{a}:1")
    assert shape(twigt("show", "--all")) == [(0, a), (1, 1)]  # a refused move changes nothing


def test_closing_takes_the_open_tasks_below_along_and_a_closed_tree_leaves_the_view(twigt):
    a = tree_id(twigt("new", "a", stdin=OUTLINE))
    output = twigt("done", f"{a}:2", "-n", "rules gone")
    assert f"Closed along with them: {a}:3." in output
    assert re.search(r"2 ufw cleanup +✅ done: rules gone\n.*3 drop the dead 8443 rule +✅ done\n", output)
    twigt("drop", a)
    assert "No open trees" in twigt("show")
    assert "❌ dropped" in twigt("show", "--closed")
    assert "🔲 open" in twigt("reopen", a)


def test_a_deleted_branch_comes_back_where_it_was(twigt):
    output = twigt("new", "a", stdin=OUTLINE)
    a, before = tree_id(output), shape(output)
    output = twigt("delete", f"{a}:2")
    assert f"Deleted {a}:2 with its 1 sub-task" in output
    assert shape(output) == [(0, a), (1, 1), (1, 4)]
    assert f"`twigt restore {a}:2`" in twigt.refused("show", f"{a}:3")
    assert f"restore that" in twigt.refused("restore", f"{a}:3")
    assert shape(twigt("restore", f"{a}:2")) == before
    assert shape(twigt("add", "new one")) == before + [(1, 5)]  # numbers are never given out twice

    twigt("delete", f"{a}:3")
    twigt("delete", f"{a}:2")
    output = twigt("restore", f"{a}:3")  # its parent is gone: a tree of its own
    assert "is a tree of its own now" in output
    assert shape(output) == [(0, tree_id(output))]


def test_renumber_closes_the_gaps_and_a_restore_takes_free_numbers(twigt):
    a = tree_id(twigt("new", "a", stdin="one\ntwo\nthree\nfour\nfive\nsix\n"))
    twigt("focus", f"{a}:6")
    assert shape(twigt("delete", f"{a}:2", f"{a}:5")) == [(0, a), (1, 1), (1, 3), (1, 4), (1, 6)]
    output = twigt("renumber", a)
    assert f"Renumbered: {a}:3 → {a}:2, {a}:4 → {a}:3, {a}:6 → {a}:4." in output
    assert re.search(r"├─ 2 three .*\n├─ 3 four .*\n└─ 4 six ", output)
    assert shape(twigt("add", "x"))[-2:] == [(1, 4), (2, 5)]  # the focus went along with six, now 4
    output = twigt("restore", f"{a}:2")  # its number is taken now: the tree's next one
    assert f"Renumbered: {a}:2 → {a}:6." in output
    assert re.search(r"├─ 6 two ", output)
    assert "Numbered 1, 2, 3 … already." not in twigt("renumber", a)
    assert "Numbered 1, 2, 3 … already." in twigt("renumber", a)
    assert f"renumber takes a tree: {a}" in twigt.refused("renumber", f"{a}:1")


def test_contexts_keep_their_own_trees_and_focus_and_follow_a_renumbering(twigt):
    a = tree_id(twigt("new", "a", stdin=OUTLINE, ctx="chat-a"))
    assert re.search(rf"Other open trees:\n{a} a · \d+ \w+ · 3 open", twigt("show", ctx="chat-b"))
    assert "nothing in focus" in twigt.refused("add", "x", ctx="chat-b")
    twigt("focus", f"{a}:2", ctx="chat-b")
    output = twigt("add", "x", "y", ctx="chat-b")
    assert f"Added {a}:5, {a}:6 under {a}:2." in output
    assert shape(output)[2:6] == [(1, 2), (2, 3), (2, 5), (2, 6)]
    assert shape(twigt("show", ctx="chat-b"))[0] == (0, a)
    assert "Other open trees" not in twigt("show", ctx="chat-b")
    assert shape(twigt("add", "z", ctx="chat-a"))[-1] == (1, 7)  # chat-a's focus is still the tree

    b = tree_id(twigt("mv", f"{a}:2", "--root", ctx="chat-a"))
    assert f"Added {b}:4 under {b}." in twigt("add", "w", ctx="chat-b")  # chat-b's focus went along


def test_a_body_shows_on_demand_and_edits_in_the_editor(twigt, tmp_path, monkeypatch):
    a = tree_id(twigt("new", "a"))
    twigt("add", "ufw cleanup", "-m", "Docker writes iptables itself.\nKeep 4022.", "-t", "ops")
    assert re.search(r"└─ 1 ufw cleanup \[ops\] ≡ +🔲 open", twigt("show"))
    expected = f"{a}:1 ufw cleanup [ops]  🔲 open\nin {a} a\n\nDocker writes iptables itself.\nKeep 4022."
    assert twigt("show", f"{a}:1").startswith(expected)
    assert "\n      Docker writes iptables itself.\n      Keep 4022." in twigt("show", "-b")

    editor = tmp_path / "editor.py"
    editor.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('UFW cleanup\\n\\nAll rules gone.\\n')\n")
    monkeypatch.setenv("EDITOR", f"{sys.executable} {editor}")
    monkeypatch.delenv("VISUAL", raising=False)
    assert twigt("edit", f"{a}:1").startswith(f"{a}:1 UFW cleanup [ops]  🔲 open\nin {a} a\n\nAll rules gone.")
    assert twigt("edit", f"{a}:1", "-m", "-", stdin="From stdin.\n").endswith("\n\nFrom stdin.\n")
