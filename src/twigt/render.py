"""Trees as box-drawn text: one line per task with its number, title and
tags, the status marks lined up in one column; ≡ marks a task with a body."""

from __future__ import annotations

import datetime
from collections.abc import Callable

from twigt.tasks import Data, Place, Task, is_open, show_ref, walk

MARKS = {
    "open": "🔲 open",
    "active": "▶ in progress",
    "you": "⏸ you",
    "waiting": "⏳ waiting",
    "done": "✅ done",
    "dropped": "❌ dropped",
}
STATUS_COLUMN = 60  # where the marks line up; a longer line pushes only its own mark right

Filter = Callable[[Task], bool]


def mark(task: Task) -> str:
    status, note = task["status"], task["note"]
    if not note:
        return MARKS[status]
    if status == "waiting":
        return "⏳ " + note
    return f"{MARKS[status]}: {note}"


def day(stamp: str) -> str:
    moment = datetime.datetime.fromisoformat(stamp)
    year = "" if moment.year == datetime.date.today().year else f" {moment.year}"
    return f"{moment.day} {moment:%b}{year}"


def label(task: Task, body_mark: bool = True) -> str:
    tags = f' [{", ".join(task["tags"])}]' if task["tags"] else ""
    return f'{task["id"]} {task["title"]}{tags}{" ≡" if task["body"] and body_mark else ""}'


def matcher(open_only: bool = False, tag: str | None = None) -> Filter:
    """Which tasks to show: those matching, and every task above one."""

    def matches(task: Task) -> bool:
        return (not open_only or is_open(task)) and (tag is None or tag in task["tags"])

    return lambda task: any(matches(sub) for sub in walk([task]))


Row = tuple[str, str | None]  # (left, mark); a body line has no mark


def branch_rows(tasks: list[Task], indent: str, shown: Filter, bodies: bool) -> list[Row]:
    rows: list[Row] = []
    visible = [task for task in tasks if shown(task)]
    for index, task in enumerate(visible):
        last = index == len(visible) - 1
        rows.append((f'{indent}{"└─" if last else "├─"} {label(task)}', mark(task)))
        inner = indent + ("   " if last else "│  ")
        if bodies:
            rows += body_rows(task, inner, shown)
        rows += branch_rows(task["tasks"], inner, shown, bodies)
    return rows


def body_rows(task: Task, inner: str, shown: Filter) -> list[Row]:
    rail = "│  " if any(shown(sub) for sub in task["tasks"]) else "   "
    return [((inner + rail + line).rstrip(), None) for line in task["body"].splitlines()]


def lay_out(rows: list[Row]) -> list[str]:
    width = min(STATUS_COLUMN, max((len(left) for left, right in rows if right is not None), default=0))
    return [left if right is None else f"{left.ljust(width)}  {right}" for left, right in rows]


def tree(root: Task, shown: Filter | None = None, bodies: bool = False) -> str:
    """A whole tree: the root's line carries the day it was started."""
    shown = shown or matcher()
    rows: list[Row] = [(f'{label(root)} · {day(root["created"])}', mark(root))]
    if bodies:
        rows += body_rows(root, "", shown)
    rows += branch_rows(root["tasks"], "", shown, bodies)
    return "\n".join(lay_out(rows))


def detail(place: Place, shown: Filter | None = None, bodies: bool = False) -> str:
    """One task in full: its line with its tree, where it is, its body, then its branch."""
    shown = shown or matcher()
    task = place.task
    head = show_ref(place.ref) + label(task, body_mark=False).removeprefix(str(task["id"]))
    parts = ["\n".join(lay_out([(head, mark(task))]))]
    if place.ancestors:
        parts[0] += "\nin " + " › ".join(f'{above["id"]} {above["title"]}' for above in place.ancestors)
    if task["body"]:
        parts.append(task["body"])
    children = branch_rows(task["tasks"], "", shown, bodies)
    if children:
        parts.append("\n".join(lay_out(children)))
    return "\n\n".join(parts)


def summary(root: Task) -> str:
    count = sum(is_open(task) for task in walk(root["tasks"]))
    return f'{root["id"]} {root["title"]} · {day(root["created"])} · {count} open'


def overview(data: Data, mine: list[Task], context: str, shown: Filter, bodies: bool, closed: bool) -> str:
    """The context's trees in full, then one line per other open tree."""
    wanted = [root for root in mine if closed or is_open(root)]
    parts = [tree(root, shown, bodies) for root in wanted] or [f"No open trees in context {context!r}."]
    own = {root["id"] for root in mine}
    others = [root for root in data["trees"] if root["id"] not in own and is_open(root)]
    if others:
        parts.append("Other open trees:\n" + "\n".join(summary(root) for root in others))
    return "\n\n".join(parts)
