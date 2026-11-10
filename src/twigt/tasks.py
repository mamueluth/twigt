"""The task trees and every change to them.

Each tree has an id of its own, a pronounceable word made from a hash of
its title and the time it was made (`kemi`). Its tasks are numbered as an
outline: 6, its sub-tasks 6.1 and 6.2, theirs 6.2.1. A task is always its
tree and number: `kemi:6.2.1`.

A task stores only its number among its siblings, so a branch that moves
takes its sub-tasks' numbers along under its new one. Siblings always
stand in number order: new and moved tasks go last with the highest
number + 1, up and down swap two siblings with their numbers, deleting
leaves a gap, and `renumber` closes the gaps.

Behind the numbers, every task has a key that never changes. Where a
deleted branch was and a context's trees and focus hold keys, so they stay
true through every move and renumbering."""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple, TypedDict

STATUSES = ("open", "active", "waiting", "done", "dropped")
CLOSED = frozenset({"done", "dropped"})
FORMAT = 1


class Problem(Exception):
    """A request that can't be done; the message says why."""


class Task(TypedDict):
    key: int  # never changes, never shown
    id: int | str  # a task's number among its siblings; a tree's id
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
    tree: str  # the tree it was in (a deleted tree: its own id)
    path: list[int]  # its number there, for `restore kemi:6.2`; [] for a tree
    parent: int | None  # the parent's key; None: it was a tree
    deleted: str


class Context(TypedDict):
    trees: list[int]  # keys of tasks; shown as the trees they're in now, latest first
    focus: int | None  # a key


class Data(TypedDict):
    format: int
    key: int  # the key the next task gets
    trees: list[Task]
    deleted: list[Deleted]
    contexts: dict[str, Context]
    used: list[str]  # every tree id ever given out


class Spec(NamedTuple):
    """A task to be made, from a title or an outline line."""

    title: str
    status: str = "open"
    note: str = ""
    tasks: tuple[Spec, ...] = ()


Path = tuple[int, ...]
Ref = tuple[str, Path]  # (tree, number path); an empty path: the tree itself
Moved = list[tuple[Ref, Ref]]  # old ref -> new ref of the tasks a change renumbered


class Place(NamedTuple):
    siblings: list[Task]
    index: int
    parent: Task | None  # None: the task is a tree
    ancestors: list[Task]  # the tree first, the parent last
    tree: Task

    @property
    def task(self) -> Task:
        return self.siblings[self.index]

    @property
    def path(self) -> Path:
        if self.parent is None:
            return ()
        return tuple(above["id"] for above in self.ancestors[1:]) + (self.task["id"],)

    @property
    def ref(self) -> Ref:
        return (self.tree["id"], self.path)


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def empty() -> Data:
    return {"format": FORMAT, "key": 1, "trees": [], "deleted": [], "contexts": {}, "used": []}


def walk(tasks: Iterable[Task]) -> Iterator[Task]:
    for task in tasks:
        yield task
        yield from walk(task["tasks"])


def is_open(task: Task) -> bool:
    return task["status"] not in CLOSED


def is_tree(task: Task) -> bool:
    return isinstance(task["id"], str)


REF = re.compile(r"([a-z]+)(?::(\d+(?:\.\d+)*)?)?")


def parse_ref(text: str) -> Ref:
    match = REF.fullmatch(text.strip().lower())
    if not match:
        raise Problem(f"{text!r} isn't a task or tree: write kemi:6.2 for a task, kemi for a tree")
    return match[1], tuple(int(part) for part in match[2].split(".")) if match[2] else ()


def show_ref(ref: Ref) -> str:
    tree, path = ref
    return f"{tree}:{'.'.join(map(str, path))}" if path else tree


CONSONANTS = "bdfghjklmnprstvz"
VOWELS = "aeiou"


def fresh_id(data: Data, title: str) -> str:
    """Syllables from a hash of the title and the time: two, or more where
    the shorter ones are taken. An id is never given out twice."""
    digest = hashlib.sha256(f"{title}\n{now()}".encode()).digest()
    syllables = [CONSONANTS[byte >> 4] + VOWELS[byte % 5] for byte in digest]
    for length in range(2, len(syllables) + 1):
        candidate = "".join(syllables[:length])
        if candidate not in data["used"]:
            data["used"].append(candidate)
            return candidate
    raise Problem("no free tree id")  # 32 syllables all taken: can't happen


def find_tree(data: Data, tree_id: str) -> Task | None:
    return next((tree for tree in data["trees"] if tree["id"] == tree_id), None)


def by_key(data: Data, key: int) -> Place | None:
    for index, tree in enumerate(data["trees"]):
        if tree["key"] == key:
            return Place(data["trees"], index, None, [], tree)

    def inside(siblings: list[Task], parent: Task, ancestors: list[Task]) -> Place | None:
        for index, task in enumerate(siblings):
            if task["key"] == key:
                return Place(siblings, index, parent, ancestors, ancestors[0])
            found = inside(task["tasks"], task, ancestors + [task])
            if found:
                return found
        return None

    for tree in data["trees"]:
        found = inside(tree["tasks"], tree, [tree])
        if found:
            return found
    return None


def ref_of(data: Data, task: Task) -> Ref:
    place = by_key(data, task["key"])
    assert place is not None, "a task that is in a tree"
    return place.ref


def locate(data: Data, ref: Ref) -> Place:
    tree_id, path = ref
    tree = find_tree(data, tree_id)
    place = None
    if tree is not None and not path:
        place = Place(data["trees"], data["trees"].index(tree), None, [], tree)
    elif tree is not None:
        parent, ancestors = tree, [tree]
        for depth, number in enumerate(path):
            index = next((i for i, task in enumerate(parent["tasks"]) if task["id"] == number), None)
            if index is None:
                break
            if depth == len(path) - 1:
                place = Place(parent["tasks"], index, parent, ancestors, tree)
            else:
                parent = parent["tasks"][index]
                ancestors = ancestors + [parent]
    if place is None:
        found = deleted_entry(data, ref)
        if found:
            raise Problem(f"{show_ref(ref)} is deleted: `twigt restore {show_ref(entry_ref(found[0]))}` brings it back")
        raise Problem(f"no tree {tree_id}" if tree is None else f"no task {show_ref(ref)}")
    return place


def get(data: Data, ref: Ref) -> Task:
    return locate(data, ref).task


def entry_ref(entry: Deleted) -> Ref:
    return (entry["tree"], tuple(entry["path"]))


def deleted_entry(data: Data, ref: Ref) -> tuple[Deleted, bool] | None:
    """The deleted branch ref is in, and whether ref is that branch's top."""
    tree_id, path = ref
    for entry in data["deleted"]:
        top = entry_ref(entry)
        if top[0] != tree_id or path[: len(top[1])] != top[1]:
            continue
        if path == top[1]:
            return entry, True
        inner = path[len(top[1]) :]
        siblings = entry["task"]["tasks"]
        for number in inner:
            task = next((sub for sub in siblings if sub["id"] == number), None)
            if task is None:
                break
            siblings = task["tasks"]
        else:
            return entry, False
    return None


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


def next_number(siblings: list[Task]) -> int:
    return max((int(task["id"]) for task in siblings), default=0) + 1


def make(data: Data, spec: Spec, body: str = "", tags: Iterable[str] = (), number: int | str = 1) -> Task:
    """A new task, and its sub-tasks numbered 1, 2, 3 …"""
    stamp = now()
    task: Task = {
        "key": data["key"],
        "id": number,
        "title": check_title(spec.title),
        "body": body.strip("\n"),
        "status": spec.status,
        "note": spec.note,
        "tags": list(dict.fromkeys(check_tag(tag) for tag in tags)),
        "created": stamp,
        "updated": stamp,
        "tasks": [],
    }
    data["key"] += 1
    task["tasks"] = [make(data, child, number=index) for index, child in enumerate(spec.tasks, 1)]
    return task


def new_tree(data: Data, spec: Spec, body: str = "", tags: Iterable[str] = ()) -> Task:
    tree = make(data, spec, body, tags, number=fresh_id(data, spec.title))
    data["trees"].append(tree)
    return tree


def add(data: Data, under: Place, specs: Iterable[Spec], body: str = "", tags: Iterable[str] = ()) -> list[Ref]:
    """New tasks last under under.task, numbered on from the highest there."""
    siblings = under.task["tasks"]
    refs = []
    for spec in specs:
        siblings.append(make(data, spec, body, tags, number=next_number(siblings)))
        refs.append((under.tree["id"], under.path + (siblings[-1]["id"],)))
    return refs


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


def set_status(data: Data, refs: Iterable[Ref], status: str, note: str) -> list[Ref]:
    """Set the named tasks' status and note. Closing (done, dropped) also
    closes their open sub-tasks, without a note. Returns every task changed."""
    changed = []
    for ref in refs:
        named = get(data, ref)
        targets = [named]
        if status in CLOSED:
            targets += [task for task in walk(named["tasks"]) if is_open(task)]
        for task in targets:
            task["status"], task["note"] = status, note if task is named else ""
            touch(task)
            changed.append(ref_of(data, task))
    return changed


def edit(data: Data, ref: Ref, title: str | None, body: str | None) -> Task:
    task = get(data, ref)
    if title is not None:
        task["title"] = check_title(title)
    if body is not None:
        task["body"] = body.strip("\n")
    touch(task)
    return task


def tag(data: Data, ref: Ref, tags: Iterable[str]) -> Task:
    task = get(data, ref)
    for name in tags:
        if check_tag(name) not in task["tags"]:
            task["tags"].append(name)
    touch(task)
    return task


def untag(data: Data, ref: Ref, tags: Iterable[str]) -> Task:
    task = get(data, ref)
    for name in tags:
        if name not in task["tags"]:
            raise Problem(f"{show_ref(ref)} has no tag {name!r}")
        task["tags"].remove(name)
    touch(task)
    return task


# Moves. A task always moves with its whole branch, and lands last.


def in_tree(place: Place, ref: Ref, what: str) -> None:
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree: {what} moves tasks within a tree")


def swap(data: Data, ref: Ref, step: int) -> Moved:
    """Up (step -1) or down (+1): trade places and numbers with the neighbour."""
    place = locate(data, ref)
    in_tree(place, ref, "up" if step < 0 else "down")
    other = place.index + step
    if not 0 <= other < len(place.siblings):
        raise Problem(f"{show_ref(ref)} is {'first' if step < 0 else 'last'} already")
    siblings, index = place.siblings, place.index
    a, b = siblings[index], siblings[other]
    old_a, old_b = place.ref, ref_of(data, b)
    a["id"], b["id"] = b["id"], a["id"]
    siblings[index], siblings[other] = b, a
    return [(old_a, ref_of(data, a)), (old_b, ref_of(data, b))]


def land(data: Data, task: Task, siblings: list[Task], old: Ref) -> Moved:
    task["id"] = next_number(siblings)
    siblings.append(task)
    return [(old, ref_of(data, task))]


def indent(data: Data, ref: Ref) -> Moved:
    """Last under the task above it."""
    place = locate(data, ref)
    in_tree(place, ref, "in")
    if place.index == 0:
        raise Problem(f"{show_ref(ref)} has no task above it to go under")
    above = place.siblings[place.index - 1]
    return land(data, place.siblings.pop(place.index), above["tasks"], ref)


def outdent(data: Data, ref: Ref) -> Moved:
    """Last among its parent's siblings; from a tree's top level, a tree of its own."""
    place = locate(data, ref)
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree already")
    if place.parent is place.tree:
        return make_tree(data, ref)
    parent = by_key(data, place.parent["key"])
    return land(data, place.siblings.pop(place.index), parent.siblings, ref)


def move_under(data: Data, ref: Ref, target: Ref) -> Moved:
    """Last under target, in any tree; a tree moved becomes a task there."""
    place = locate(data, ref)
    destination = locate(data, target)
    if any(task is destination.task for task in walk([place.task])):
        raise Problem(f"{show_ref(target)} is in {show_ref(ref)}'s branch: a branch can't go under itself")
    return land(data, place.siblings.pop(place.index), destination.task["tasks"], ref)


def as_tree(data: Data, task: Task, old: Ref) -> Moved:
    """task becomes a tree of its own; its sub-tasks keep their numbers."""
    task["id"] = fresh_id(data, task["title"])
    data["trees"].append(task)
    return [(old, (task["id"], ()))]


def make_tree(data: Data, ref: Ref) -> Moved:
    place = locate(data, ref)
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree already")
    return as_tree(data, place.siblings.pop(place.index), ref)


def renumber(data: Data, ref: Ref) -> Moved:
    """Every level of the tree numbered 1, 2, 3 … in the order shown.
    Returns the tasks whose own number changed; their sub-tasks follow."""
    place = locate(data, ref)
    if place.parent is not None:
        raise Problem(f"renumber takes a tree: {place.tree['id']}, not {show_ref(ref)}")
    tree_id, moved = place.tree["id"], []

    def level(siblings: list[Task], old_path: Path, new_path: Path) -> None:
        for number, task in enumerate(siblings, 1):
            old, new = old_path + (task["id"],), new_path + (number,)
            if task["id"] != number:
                moved.append(((tree_id, old), (tree_id, new)))
                task["id"] = number
            level(task["tasks"], old, new)

    level(place.tree["tasks"], (), ())
    return moved


def delete(data: Data, ref: Ref) -> Deleted:
    place = locate(data, ref)
    path = list(place.path)  # before the task leaves its place
    entry: Deleted = {
        "task": place.siblings.pop(place.index),
        "tree": place.tree["id"],
        "path": path,
        "parent": None if place.parent is None else place.parent["key"],
        "deleted": now(),
    }
    data["deleted"].append(entry)
    return entry


def restore(data: Data, ref: Ref) -> tuple[Task, Moved]:
    """Back under the task it was under, wherever that is now: at its old
    number where that is free, else last. With that task gone, a tree of
    its own. Returns where it went, if not where it was."""
    found = deleted_entry(data, ref)
    if found is None:
        raise Problem(f"{show_ref(ref)} isn't deleted")
    entry, top = found
    if not top:
        raise Problem(f"{show_ref(ref)} was deleted with {show_ref(entry_ref(entry))}: restore that")
    data["deleted"].remove(entry)
    task = entry["task"]
    if is_tree(task):
        data["trees"].append(task)
        return task, []
    parent = by_key(data, entry["parent"])
    if parent is None:
        return task, as_tree(data, task, ref)
    siblings = parent.task["tasks"]
    if any(sibling["id"] == task["id"] for sibling in siblings):
        return task, land(data, task, siblings, ref)
    siblings.insert(sum(sibling["id"] < task["id"] for sibling in siblings), task)
    new = ref_of(data, task)
    return task, [] if new == ref else [(ref, new)]


# Contexts.


def context(data: Data, name: str) -> Context:
    return data["contexts"].setdefault(name, {"trees": [], "focus": None})


def attach(data: Data, name: str, ref: Ref) -> None:
    """Make ref's tree one of the context's trees, its latest."""
    key = locate(data, ref).tree["key"]
    trees = context(data, name)["trees"]
    if key in trees:
        trees.remove(key)
    trees.insert(0, key)


def focus(data: Data, name: str, ref: Ref) -> None:
    attach(data, name, ref)
    context(data, name)["focus"] = get(data, ref)["key"]


def focused(data: Data, name: str) -> Place:
    key = data["contexts"].get(name, {}).get("focus")
    place = None if key is None else by_key(data, key)
    if place is None:
        gone = "" if key is None else "the task in focus is deleted; "
        raise Problem(f'{gone}nothing in focus: start a tree with `twigt new "title"`, pick a task with `twigt focus kemi:6`, or add with -u')
    return place


def trees_of(data: Data, name: str) -> list[Task]:
    """The trees the context's tasks are in now, latest first: a tree moved
    into another brings that one, a deleted one nothing."""
    trees: dict[str, Task] = {}
    for key in data["contexts"].get(name, {}).get("trees", []):
        place = by_key(data, key)
        if place is not None:
            trees.setdefault(place.tree["id"], place.tree)
    return list(trees.values())
