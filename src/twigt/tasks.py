"""The task forest and every change to it.

A tree is a task without a parent. Every task has a number that never
changes and is never reused, so moving a branch keeps references to it
("see 43") valid. Deleted branches are kept, with where they were, until
restored. Contexts (a shell, a chat) each keep their trees and a focus:
the task `add` puts new tasks under."""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple, TypedDict

STATUSES = ("open", "active", "you", "waiting", "done", "dropped")
CLOSED = frozenset({"done", "dropped"})
FORMAT = 1


class Problem(Exception):
    """A request that can't be done; the message says why."""


class Task(TypedDict):
    id: int
    title: str
    body: str
    status: str
    note: str
    tags: list[str]
    created: str
    updated: str
    tasks: list[Task]


class Deleted(TypedDict):
    task: Task
    parent: int | None  # None: it was a tree
    index: int
    deleted: str


class Context(TypedDict):
    trees: list[int]  # the tasks it attached; shown as the trees they're in, latest first
    focus: int | None


class Data(TypedDict):
    format: int
    next: int
    trees: list[Task]
    deleted: list[Deleted]
    contexts: dict[str, Context]


class Spec(NamedTuple):
    """A task to be made, from a title or an outline line."""

    title: str
    status: str = "open"
    note: str = ""
    tasks: tuple[Spec, ...] = ()


class Place(NamedTuple):
    siblings: list[Task]
    index: int
    parent: Task | None
    ancestors: list[Task]  # the tree first, the parent last

    @property
    def task(self) -> Task:
        return self.siblings[self.index]


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def empty() -> Data:
    return {"format": FORMAT, "next": 1, "trees": [], "deleted": [], "contexts": {}}


def walk(tasks: Iterable[Task]) -> Iterator[Task]:
    for task in tasks:
        yield task
        yield from walk(task["tasks"])


def is_open(task: Task) -> bool:
    return task["status"] not in CLOSED


def locate(data: Data, number: int) -> Place:
    def search(siblings: list[Task], parent: Task | None, ancestors: list[Task]) -> Place | None:
        for index, task in enumerate(siblings):
            if task["id"] == number:
                return Place(siblings, index, parent, ancestors)
            found = search(task["tasks"], task, ancestors + [task])
            if found:
                return found
        return None

    place = search(data["trees"], None, [])
    if place is None:
        for entry in data["deleted"]:
            if any(task["id"] == number for task in walk([entry["task"]])):
                raise Problem(f"{number} is deleted: `twigt restore {entry['task']['id']}` brings it back")
        raise Problem(f"no task {number}")
    return place


def get(data: Data, number: int) -> Task:
    return locate(data, number).task


def tree_of(data: Data, number: int) -> Task:
    place = locate(data, number)
    return place.ancestors[0] if place.ancestors else place.task


TAG = re.compile(r"^[^\s\[\],]+$")


def check_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise Problem("a task needs a title")
    return title


def check_tag(tag: str) -> str:
    if not TAG.match(tag):
        raise Problem(f"{tag!r} can't be a tag: no spaces, commas or brackets")
    return tag


def make(data: Data, spec: Spec, body: str = "", tags: Iterable[str] = ()) -> Task:
    """A new task and its sub-tasks, numbered on from the last number given out."""
    stamp = now()
    task: Task = {
        "id": data["next"],
        "title": check_title(spec.title),
        "body": body.strip("\n"),
        "status": spec.status,
        "note": spec.note,
        "tags": list(dict.fromkeys(check_tag(tag) for tag in tags)),
        "created": stamp,
        "updated": stamp,
        "tasks": [],
    }
    data["next"] += 1
    task["tasks"] = [make(data, child) for child in spec.tasks]
    return task


OUTLINE_STATUS = re.compile(r"\s+\|\s+(" + "|".join(STATUSES) + r")(?::\s*(.*))?$")


def parse_outline(lines: Iterable[str]) -> list[Spec]:
    """Indented lines -> specs: deeper indentation nests, "- " or "* " is
    dropped, and "title | status: note" sets the status."""
    entries: list[tuple[int, Spec]] = []  # (indent, the line's spec without its sub-tasks)
    for line in lines:
        if not line.strip():
            continue
        title = line.strip()
        if title.startswith(("- ", "* ")):
            title = title[2:]
        status, note = "open", ""
        match = OUTLINE_STATUS.search(title)
        if match:
            title, status, note = title[: match.start()], match[1], (match[2] or "").strip()
        entries.append((len(line) - len(line.lstrip()), Spec(check_title(title), status, note)))

    def nest(start: int, parent_indent: int) -> tuple[list[Spec], int]:
        """The specs from start on that are deeper than parent_indent, and where they end."""
        specs, index = [], start
        while index < len(entries) and entries[index][0] > parent_indent:
            indent, spec = entries[index]
            children, index = nest(index + 1, indent)
            specs.append(spec._replace(tasks=tuple(children)))
        return specs, index

    return nest(0, -1)[0]


def touch(task: Task) -> None:
    task["updated"] = now()


def set_status(data: Data, numbers: Iterable[int], status: str, note: str) -> list[int]:
    """Set the named tasks' status and note. Closing (done, dropped) also
    closes their open sub-tasks, without a note. Returns every task changed."""
    changed = []
    for number in numbers:
        named = get(data, number)
        targets = [named]
        if status in CLOSED:
            targets += [task for task in walk(named["tasks"]) if is_open(task)]
        for task in targets:
            task["status"], task["note"] = status, note if task is named else ""
            touch(task)
            changed.append(task["id"])
    return changed


def edit(data: Data, number: int, title: str | None, body: str | None) -> Task:
    task = get(data, number)
    if title is not None:
        task["title"] = check_title(title)
    if body is not None:
        task["body"] = body.strip("\n")
    touch(task)
    return task


def tag(data: Data, number: int, tags: Iterable[str]) -> Task:
    task = get(data, number)
    for name in tags:
        if check_tag(name) not in task["tags"]:
            task["tags"].append(name)
    touch(task)
    return task


def untag(data: Data, number: int, tags: Iterable[str]) -> Task:
    task = get(data, number)
    for name in tags:
        if name not in task["tags"]:
            raise Problem(f"{number} has no tag {name!r}")
        task["tags"].remove(name)
    touch(task)
    return task


# Moves. A task always moves with its whole branch.


def move_up(data: Data, number: int) -> None:
    place = locate(data, number)
    if place.index == 0:
        raise Problem(f"{number} is first already")
    siblings, index = place.siblings, place.index
    siblings[index - 1], siblings[index] = siblings[index], siblings[index - 1]


def move_down(data: Data, number: int) -> None:
    place = locate(data, number)
    if place.index == len(place.siblings) - 1:
        raise Problem(f"{number} is last already")
    siblings, index = place.siblings, place.index
    siblings[index + 1], siblings[index] = siblings[index], siblings[index + 1]


def indent(data: Data, number: int) -> None:
    """Under the task above it, as its last sub-task."""
    place = locate(data, number)
    if place.index == 0:
        raise Problem(f"{number} has no task above it to go under")
    task = place.siblings.pop(place.index)
    place.siblings[place.index - 1]["tasks"].append(task)


def outdent(data: Data, number: int) -> bool:
    """Next to its parent, right after it. Returns whether it became a tree."""
    place = locate(data, number)
    if place.parent is None:
        raise Problem(f"{number} is a tree already")
    parent = locate(data, place.parent["id"])
    parent.siblings.insert(parent.index + 1, place.siblings.pop(place.index))
    return parent.parent is None


def move_under(data: Data, number: int, target: int) -> None:
    """Under target, as its last sub-task; target may be in another tree."""
    place = locate(data, number)
    if any(task["id"] == target for task in walk([place.task])):
        raise Problem(f"{target} is in {number}'s branch: a branch can't go under itself")
    destination = get(data, target)
    destination["tasks"].append(place.siblings.pop(place.index))


def make_tree(data: Data, number: int) -> None:
    place = locate(data, number)
    if place.parent is None:
        raise Problem(f"{number} is a tree already")
    data["trees"].append(place.siblings.pop(place.index))


def delete(data: Data, number: int) -> Deleted:
    place = locate(data, number)
    entry: Deleted = {
        "task": place.siblings.pop(place.index),
        "parent": place.parent["id"] if place.parent else None,
        "index": place.index,
        "deleted": now(),
    }
    data["deleted"].append(entry)
    return entry


def restore(data: Data, number: int) -> tuple[Task, bool]:
    """Back where it was. Returns the task and whether its parent was gone,
    which makes it a tree of its own."""
    entry = next((entry for entry in reversed(data["deleted"]) if entry["task"]["id"] == number), None)
    if entry is None:
        for other in data["deleted"]:
            if any(task["id"] == number for task in walk([other["task"]])):
                raise Problem(f"{number} was deleted with {other['task']['id']}: restore {other['task']['id']}")
        raise Problem(f"{number} isn't deleted")
    data["deleted"].remove(entry)
    parent = None
    if entry["parent"] is not None:
        try:
            parent = get(data, entry["parent"])
        except Problem:
            parent = None
    siblings = parent["tasks"] if parent else data["trees"]
    index = entry["index"] if parent or entry["parent"] is None else len(siblings)
    siblings.insert(min(index, len(siblings)), entry["task"])
    return entry["task"], entry["parent"] is not None and parent is None


# Contexts.


def context(data: Data, name: str) -> Context:
    return data["contexts"].setdefault(name, {"trees": [], "focus": None})


def attach(data: Data, name: str, number: int) -> None:
    """Make the tree number is in one of the context's trees, its latest."""
    trees = context(data, name)["trees"]
    if number in trees:
        trees.remove(number)
    trees.insert(0, get(data, number)["id"])


def focus(data: Data, name: str, number: int) -> None:
    attach(data, name, number)
    context(data, name)["focus"] = number


def focused(data: Data, name: str) -> Task:
    number = data["contexts"].get(name, {}).get("focus")
    if number is None:
        raise Problem('nothing in focus: start a tree with `twigt new "title"`, pick a task with `twigt focus N`, or add with -u N')
    try:
        return get(data, number)
    except Problem as problem:
        raise Problem(f"the focus is gone ({problem}); pick a task with `twigt focus N`, or add with -u N") from None


def trees_of(data: Data, name: str) -> list[Task]:
    """The trees the context's tasks are in now, latest first; a task that
    moved into another tree brings that tree, a deleted one nothing."""
    trees: dict[int, Task] = {}
    for number in data["contexts"].get(name, {}).get("trees", []):
        try:
            tree = tree_of(data, number)
        except Problem:
            continue
        trees.setdefault(tree["id"], tree)
    return list(trees.values())
