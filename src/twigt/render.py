"""Trees as box-drawn text: one line per task with its outline number,
title and tags, the status marks lined up in one column; ≡ marks a task
with a body."""

from __future__ import annotations

import datetime
from collections.abc import Callable

from twigt.tasks import Data, Path, Place, Task, is_open, show_ref, walk

MARKS = {
    "open": "🔲 open",
    "active": "▶ in progress",
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


def number(path: Path) -> str:
    return ".".join(map(str, path))


def label(task: Task, name: str, body_mark: bool = True) -> str:
    """name (the tree id or the outline number), title, tags, body mark."""
    tags = f' [{", ".join(task["tags"])}]' if task["tags"] else ""
    return f'{name} {task["title"]}{tags}{" ≡" if task["body"] and body_mark else ""}'


def matcher(open_only: bool = False, tag: str | None = None) -> Filter:
    """Which tasks to show: those matching, and every task above one."""

    def matches(task: Task) -> bool:
        return (not open_only or is_open(task)) and (tag is None or tag in task["tags"])

    return lambda task: any(matches(sub) for sub in walk([task]))


Row = tuple[str, str | None]  # (left, mark); a body line has no mark


def branch_rows(tasks: list[Task], prefix: Path, indent: str, shown: Filter, bodies: bool) -> list[Row]:
    rows: list[Row] = []
    visible = [task for task in tasks if shown(task)]
    for index, task in enumerate(visible):
        last = index == len(visible) - 1
        path = prefix + (task["id"],)
        rows.append((f'{indent}{"└─" if last else "├─"} {label(task, number(path))}', mark(task)))
        inner = indent + ("   " if last else "│  ")
        if bodies:
            rows += body_rows(task, inner, shown)
        rows += branch_rows(task["tasks"], path, inner, shown, bodies)
    return rows


def body_rows(task: Task, inner: str, shown: Filter) -> list[Row]:
    rail = "│  " if any(shown(sub) for sub in task["tasks"]) else "   "
    return [((inner + rail + line).rstrip(), None) for line in task["body"].splitlines()]


def lay_out(rows: list[Row]) -> list[str]:
    width = min(STATUS_COLUMN, max((len(left) for left, right in rows if right is not None), default=0))
    return [left if right is None else f"{left.ljust(width)}  {right}" for left, right in rows]


def tree(root: Task, shown: Filter | None = None, bodies: bool = False) -> str:
    """A whole tree: the root's line carries its id and the day it was started."""
    shown = shown or matcher()
    rows: list[Row] = [(f'{label(root, str(root["id"]))} · {day(root["created"])}', mark(root))]
    if bodies:
        rows += body_rows(root, "", shown)
    rows += branch_rows(root["tasks"], (), "", shown, bodies)
    return "\n".join(lay_out(rows))


def detail(place: Place, shown: Filter | None = None, bodies: bool = False) -> str:
    """One task in full: its line with its tree, where it is, its body, then its branch."""
    shown = shown or matcher()
    task = place.task
    parts = ["\n".join(lay_out([(label(task, show_ref(place.ref), body_mark=False), mark(task))]))]
    if place.ancestors:
        tree, *above = place.ancestors
        names = [f'{tree["id"]} {tree["title"]}']
        names += [f'{number(place.path[: depth + 1])} {task_above["title"]}' for depth, task_above in enumerate(above)]
        parts[0] += "\nin " + " › ".join(names)
    if task["body"]:
        parts.append(task["body"])
    children = branch_rows(task["tasks"], place.path, "", shown, bodies)
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
