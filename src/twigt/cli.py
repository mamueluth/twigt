"""The twigt command: one function per subcommand. Every change prints the
tree it changed, so the result is always in view."""

from __future__ import annotations

import argparse
import io
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from twigt import render, tasks
from twigt.store import Store, default_folder
from twigt.tasks import Data, Moved, Problem, Ref, Spec, Task, show_ref

STATUS_VERBS = {
    "start": "active",
    "done": "done",
    "drop": "dropped",
    "reopen": "open",
    "wait": "waiting",
}

EPILOG = """\
A task is its tree's id and its outline number, kemi:6.2.1; a tree alone
is kemi. An outline (on stdin for new and add) is one task per line,
nested by indentation; "title | status: note" sets a status: open,
active (in progress), waiting, done, dropped."""


def ref(text: str) -> Ref:
    try:
        return tasks.parse_ref(text)
    except Problem as problem:
        raise argparse.ArgumentTypeError(str(problem)) from None


def body_from(value: str | None) -> str | None:
    """-m BODY, or -m - for the body on stdin."""
    return sys.stdin.read() if value == "-" else value


def outline_from_stdin() -> list[Spec]:
    if sys.stdin.isatty():
        return []
    return tasks.parse_outline(sys.stdin.read().splitlines())


def in_editor(title: str, body: str) -> tuple[str, str]:
    """Title and body in $VISUAL or $EDITOR, as a git commit message: the
    first line is the title, the rest the body."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "TASK.md"
        path.write_text(f"{title}\n\n{body}\n", encoding="utf-8")
        try:
            subprocess.run([*shlex.split(editor), str(path)], check=True)
        except FileNotFoundError:
            raise Problem(f"no editor {editor!r}: set $EDITOR") from None
        except subprocess.CalledProcessError:
            raise Problem("the editor failed: nothing changed") from None
        lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].strip():
        raise Problem("the first line, the title, is empty: nothing changed")
    return lines[0], "\n".join(lines[1:]).strip("\n")


def trees(data: Data, refs: list[Ref]) -> str:
    """The trees these tasks are in, each once."""
    roots: dict[str, Task] = {}
    for each in refs:
        root = tasks.locate(data, each).tree
        roots.setdefault(root["id"], root)
    return "\n\n".join(render.tree(root) for root in roots.values())


def renumbered(moved: Moved, what: str = "Renumbered") -> str:
    """old → new for each task whose number changed; its sub-tasks follow it."""
    if not moved:
        return ""
    return f"{what}: " + ", ".join(f"{show_ref(old)} → {show_ref(new)}" for old, new in moved) + ".\n\n"


def cmd_show(store: Store, args: argparse.Namespace) -> str:
    data = store.read()
    shown = render.matcher(args.open, args.tag)
    if args.ref is not None:
        return render.detail(tasks.locate(data, args.ref), shown, args.bodies)
    if args.all:
        roots = [root for root in data["trees"] if (args.closed or tasks.is_open(root)) and shown(root)]
        return "\n\n".join(render.tree(root, shown, args.bodies) for root in roots) or "No open trees."
    mine = [root for root in tasks.trees_of(data, args.ctx) if shown(root)]
    return render.overview(data, mine, args.ctx, shown, args.bodies, args.closed)


def cmd_new(store: Store, args: argparse.Namespace) -> str:
    body = body_from(args.body)
    children = [] if args.body == "-" else outline_from_stdin()
    with store.change() as data:
        tree = tasks.new_tree(data, Spec(args.title, tasks=tuple(children)), body or "", args.tag)
        tasks.focus(data, args.ctx, (tree["id"], ()))
        return render.tree(tree)


def cmd_add(store: Store, args: argparse.Namespace) -> str:
    body = body_from(args.body)
    if args.titles:
        if body is not None and len(args.titles) > 1:
            raise Problem("-m goes with one title")
        specs = [Spec(title) for title in args.titles]
    else:
        if body is not None:
            raise Problem("-m goes with a title, not an outline")
        specs = outline_from_stdin()
        if not specs:
            raise Problem("nothing to add: give a title, or an outline on stdin")
    with store.change() as data:
        parent = tasks.locate(data, args.under) if args.under is not None else tasks.focused(data, args.ctx)
        added = ", ".join(map(show_ref, tasks.add(data, parent, specs, body or "", args.tag)))
        return f"Added {added} under {show_ref(parent.ref)}.\n\n" + render.tree(parent.tree)


def cmd_edit(store: Store, args: argparse.Namespace) -> str:
    title, body = args.title, body_from(args.body)
    if title is None and body is None:
        # Outside the lock: another change may go through while the editor is open.
        current = tasks.get(store.read(), args.ref)
        title, body = in_editor(current["title"], current["body"])
        if (title, body) == (current["title"], current["body"]):
            return "Nothing changed."
    with store.change() as data:
        tasks.edit(data, args.ref, title, body)
        return render.detail(tasks.locate(data, args.ref))


def cmd_status(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        changed = tasks.set_status(data, args.refs, STATUS_VERBS[args.command], args.note or "")
        along = [show_ref(each) for each in changed if each not in args.refs]
        head = f'Closed along with them: {", ".join(along)}.\n\n' if along else ""
        return head + trees(data, args.refs)


def cmd_move(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        before = tasks.locate(data, args.ref).tree
        if args.command in ("up", "down"):
            moved = tasks.swap(data, args.ref, -1 if args.command == "up" else 1)
        elif args.command == "in":
            moved = tasks.indent(data, args.ref)
        elif args.command == "out":
            moved = tasks.outdent(data, args.ref)
        elif args.root:
            moved = tasks.make_tree(data, args.ref)
        else:
            moved = tasks.move_under(data, args.ref, args.under)
        now = moved[0][1]
        after = tasks.locate(data, now).tree
        if not now[1] and after is not before:
            tasks.attach(data, args.ctx, now)  # a new tree: the context's
        shown = [after]
        if after is not before and any(root is before for root in data["trees"]):
            shown.append(before)  # out of one tree into another: both changed
        return renumbered(moved, "Moved") + "\n\n".join(render.tree(root) for root in shown)


def cmd_tag(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        (tasks.tag if args.command == "tag" else tasks.untag)(data, args.ref, args.tags)
        return trees(data, [args.ref])


def cmd_delete(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        lines, left = [], []
        for each in args.refs:
            entry = tasks.delete(data, each)
            below = sum(1 for _ in tasks.walk(entry["task"]["tasks"]))
            with_them = f" with its {below} sub-task{'s' if below > 1 else ''}" if below else ""
            lines.append(f"Deleted {show_ref(each)}{with_them}; `twigt restore {show_ref(each)}` brings it back.")
            if not tasks.is_tree(entry["task"]) and tasks.find_tree(data, entry["tree"]):
                left.append((entry["tree"], ()))
        return "\n".join(lines) + ("\n\n" + trees(data, left) if left else "")


def cmd_restore(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        task, moved = tasks.restore(data, args.ref)
        now = moved[0][1] if moved else args.ref
        head = ""
        if not now[1] and args.ref[1]:
            tasks.attach(data, args.ctx, now)
            head = f"{show_ref(args.ref)} was under a task that is gone: it is a tree of its own now.\n"
        return head + renumbered(moved) + trees(data, [now])


def cmd_renumber(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        moved = tasks.renumber(data, args.ref)
        return (renumbered(moved) or "Numbered 1, 2, 3 … already.\n\n") + trees(data, [args.ref])


def cmd_focus(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        tasks.focus(data, args.ctx, args.ref)
        task = tasks.get(data, args.ref)
        return f'Focus: {show_ref(args.ref)} {task["title"]}; `twigt add` puts new tasks under it.\n\n' + trees(data, [args.ref])


def cmd_attach(store: Store, args: argparse.Namespace) -> str:
    with store.change() as data:
        tasks.attach(data, args.ctx, args.ref)
        return trees(data, [args.ref])


COMMANDS: dict[str, Callable[[Store, argparse.Namespace], str]] = {
    "show": cmd_show,
    "new": cmd_new,
    "add": cmd_add,
    "edit": cmd_edit,
    **{verb: cmd_status for verb in STATUS_VERBS},
    **{move: cmd_move for move in ("up", "down", "in", "out", "mv")},
    "tag": cmd_tag,
    "untag": cmd_tag,
    "delete": cmd_delete,
    "restore": cmd_restore,
    "renumber": cmd_renumber,
    "focus": cmd_focus,
    "attach": cmd_attach,
}


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(
        prog="twigt",
        description="Task trees on the command line. No command: show.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    main.add_argument("--data", type=Path, help="the data folder (default: $TWIGT_DATA, else ~/.local/share/twigt)")
    main.add_argument(
        "--ctx",
        default=os.environ.get("TWIGT_CTX") or "default",
        help="the context, which has its own trees and focus (default: $TWIGT_CTX, else 'default')",
    )
    commands = main.add_subparsers(dest="command", metavar="COMMAND")

    def command(name: str, text: str) -> argparse.ArgumentParser:
        return commands.add_parser(name, help=text, description=text[0].upper() + text[1:] + ".")

    def one(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("ref", type=ref, metavar="TASK", help="kemi:6.2, or a tree: kemi")

    def several(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("refs", nargs="+", type=ref, metavar="TASK", help="kemi:6.2, or a tree: kemi")

    show = command("show", "the context's trees and a line per other tree; with TASK, that task in full")
    show.add_argument("ref", nargs="?", type=ref, metavar="TASK", help="kemi:6.2, or a tree: kemi")
    show.add_argument("--all", action="store_true", help="every tree in full")
    show.add_argument("--closed", action="store_true", help="closed trees too")
    show.add_argument("--open", action="store_true", help="only open tasks, and the tasks above them")
    show.add_argument("--tag", help="only tasks with this tag, and the tasks above them")
    show.add_argument("-b", "--bodies", action="store_true", help="the bodies too")

    new = command("new", "start a tree and focus it; sub-tasks as an outline on stdin")
    new.add_argument("title")
    add = command("add", "add tasks under the focus or -u TASK; several titles, or an outline on stdin")
    add.add_argument("titles", nargs="*", metavar="TITLE")
    add.add_argument("-u", "--under", type=ref, metavar="TASK")
    for creating in (new, add):
        creating.add_argument("-m", "--body", help="the body; - reads it from stdin")
        creating.add_argument("-t", "--tag", action="append", default=[], help="a tag; repeat for more")

    edit = command("edit", "change the title or body; neither given: both in $EDITOR")
    one(edit)
    edit.add_argument("--title")
    edit.add_argument("-m", "--body", help="the body; - reads it from stdin")

    for verb, text in (
        ("start", "mark in progress"),
        ("done", "mark done, with the open tasks below"),
        ("drop", "mark dropped (won't be done), with the open tasks below"),
        ("reopen", "mark open again"),
        ("wait", "mark waiting; the note says on what or whom"),
    ):
        status = command(verb, text)
        several(status)
        status.add_argument("-n", "--note", help="what came of it, or what it waits for")

    for move, text in (
        ("up", "swap place and number with the task before it"),
        ("down", "swap place and number with the task after it"),
        ("in", "move to the end of the task above it"),
        ("out", "move to the end of its parent's level; from a tree's top level, a tree of its own"),
    ):
        one(command(move, text))
    mv = command("mv", "move to the end of any task, in any tree, or make it a tree of its own")
    one(mv)
    where = mv.add_mutually_exclusive_group(required=True)
    where.add_argument("-u", "--under", type=ref, metavar="TASK")
    where.add_argument("--root", action="store_true", help="a tree of its own")

    for name, text in (("tag", "add tags"), ("untag", "remove tags")):
        tagging = command(name, text)
        one(tagging)
        tagging.add_argument("tags", nargs="+", metavar="TAG")

    several(command("delete", "take tasks out, with everything below; restore brings them back"))
    one(command("restore", "put a deleted task back where it was"))
    one(command("renumber", "number every level of a tree 1, 2, 3 …, closing the gaps"))
    one(command("focus", "make TASK the one add puts new tasks under"))
    one(command("attach", "make TASK's tree one of the context's trees"))
    return main


def main(argv: list[str] | None = None) -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    args = parser().parse_args(argv)
    if args.command is None:
        args = parser().parse_args([*argv, "show"])
    try:
        print(COMMANDS[args.command](Store(args.data or default_folder()), args))
        sys.stdout.flush()
    except Problem as problem:
        sys.exit(f"twigt: {problem}")
    except BrokenPipeError:  # the reader stopped early, as `twigt | head` does
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
