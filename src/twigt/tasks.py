"""The task trees and every change to them.

Each tree has an id of its own, a pronounceable word made from a hash of
its title and the time it was made (`kemi`), and numbers its tasks from 1.
A task is always its tree and number: `kemi:5`. Moving a branch within its
tree keeps the numbers; a branch that becomes a tree of its own is
numbered from 1 again, one moved into another tree gets that tree's next
numbers, and `renumber` closes the gaps deleting leaves.

Behind the numbers, every task has a key that never changes. Where a
deleted branch was and a context's trees and focus hold keys, so they stay
true through every move and renumbering."""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Callable, Iterable, Iterator
from typing import NamedTuple, NotRequired, TypedDict

STATUSES = ("open", "active", "you", "waiting", "done", "dropped")
CLOSED = frozenset({"done", "dropped"})
FORMAT = 1


class Problem(Exception):
    """A request that can't be done; the message says why."""


class Task(TypedDict):
    key: int  # never changes, never shown
    id: int | str  # a task's number in its tree; a tree's id
    next: NotRequired[int]  # trees only: the number the next task gets
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
    tree: str  # the tree it was in (a deleted tree: its own id), for `restore kemi:5`
    parent: int | None  # the parent's key; None: it was a tree
    index: int
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


Ref = tuple[str, int | None]  # (tree, number); no number: the tree itself
Mapping = dict[Ref, Ref]  # old ref -> new ref, for the tasks a change renumbered


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
    def ref(self) -> Ref:
        return (self.tree["id"], None if self.parent is None else self.task["id"])


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


REF = re.compile(r"([a-z]+)(?::(\d+)?)?")


def parse_ref(text: str) -> Ref:
    match = REF.fullmatch(text.strip().lower())
    if not match:
        raise Problem(f"{text!r} isn't a task or tree: write kemi:5 for a task, kemi for a tree")
    return match[1], int(match[2]) if match[2] else None


def show_ref(ref: Ref) -> str:
    tree, number = ref
    return tree if number is None else f"{tree}:{number}"


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


def search(trees: list[Task], wanted: Callable[[Task], bool]) -> Place | None:
    """The place of the first task wanted(task) is true for, trees first."""
    for index, tree in enumerate(trees):
        if wanted(tree):
            return Place(trees, index, None, [], tree)

    def inside(siblings: list[Task], parent: Task, ancestors: list[Task]) -> Place | None:
        for index, task in enumerate(siblings):
            if wanted(task):
                return Place(siblings, index, parent, ancestors, ancestors[0])
            found = inside(task["tasks"], task, ancestors + [task])
            if found:
                return found
        return None

    for tree in trees:
        found = inside(tree["tasks"], tree, [tree])
        if found:
            return found
    return None


def by_key(data: Data, key: int) -> Place | None:
    return search(data["trees"], lambda task: task["key"] == key)


def locate(data: Data, ref: Ref) -> Place:
    tree_id, number = ref
    tree = find_tree(data, tree_id)
    place = None
    if tree is not None and number is None:
        place = Place(data["trees"], data["trees"].index(tree), None, [], tree)
    elif tree is not None:
        place = search([tree], lambda task: task["id"] == number)
    if place is None:
        found = deleted_entry(data, ref)
        if found:
            raise Problem(f"{show_ref(ref)} is deleted: `twigt restore {show_ref(entry_ref(found[0]))}` brings it back")
        raise Problem(f"no tree {tree_id}" if tree is None else f"no task {show_ref(ref)}")
    return place


def get(data: Data, ref: Ref) -> Task:
    return locate(data, ref).task


def entry_ref(entry: Deleted) -> Ref:
    task = entry["task"]
    return (task["id"], None) if is_tree(task) else (entry["tree"], task["id"])


def deleted_entry(data: Data, ref: Ref) -> tuple[Deleted, bool] | None:
    """The deleted branch ref is in, and whether ref is that branch's top."""
    tree_id, number = ref
    for entry in data["deleted"]:
        if entry_ref(entry)[0] != tree_id:
            continue
        if entry_ref(entry) == ref:
            return entry, True
        if number is not None and any(sub["id"] == number for sub in walk(entry["task"]["tasks"])):
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


def blank(data: Data, spec: Spec, body: str, tags: Iterable[str]) -> Task:
    stamp = now()
    task: Task = {
        "key": data["key"],
        "id": 0,
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
    return task


def make(data: Data, tree: Task, spec: Spec, body: str = "", tags: Iterable[str] = ()) -> Task:
    """A new task and its sub-tasks, numbered on in tree."""
    task = blank(data, spec, body, tags)
    task["id"] = tree["next"]
    tree["next"] += 1
    task["tasks"] = [make(data, tree, child) for child in spec.tasks]
    return task


def new_tree(data: Data, spec: Spec, body: str = "", tags: Iterable[str] = ()) -> Task:
    tree = blank(data, spec, body, tags)
    tree["id"] = fresh_id(data, spec.title)
    tree["next"] = 1
    tree["tasks"] = [make(data, tree, child) for child in spec.tasks]
    data["trees"].append(tree)
    return tree


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
        place = locate(data, ref)
        named = place.task
        targets = [named]
        if status in CLOSED:
            targets += [task for task in walk(named["tasks"]) if is_open(task)]
        for task in targets:
            task["status"], task["note"] = status, note if task is named else ""
            touch(task)
            changed.append(place.ref if task is named else (place.tree["id"], task["id"]))
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


# Numbering.


def into_tree(task: Task, tree: Task, old_tree: str, mapping: Mapping) -> None:
    """task and its branch get tree's next numbers; a tree becomes a task."""
    old = (old_tree, None if is_tree(task) else task["id"])
    task.pop("next", None)
    task["id"] = tree["next"]
    tree["next"] += 1
    mapping[old] = (tree["id"], task["id"])
    for sub in task["tasks"]:
        into_tree(sub, tree, old_tree, mapping)


def as_tree(data: Data, task: Task, old_tree: str) -> Mapping:
    """task becomes a tree of its own, its branch numbered from 1."""
    old: Ref = (old_tree, task["id"])
    task["id"] = fresh_id(data, task["title"])
    task["next"] = 1
    mapping: Mapping = {old: (task["id"], None)}
    for sub in task["tasks"]:
        into_tree(sub, task, old_tree, mapping)
    data["trees"].append(task)
    return mapping


def renumber(data: Data, ref: Ref) -> Mapping:
    """The tree's tasks numbered 1, 2, 3 … top to bottom, as shown."""
    place = locate(data, ref)
    if place.parent is not None:
        raise Problem(f"renumber takes a tree: {place.tree['id']}, not {show_ref(ref)}")
    tree = place.tree
    tree["next"] = 1
    mapping: Mapping = {}
    for task in walk(tree["tasks"]):
        old = task["id"]
        task["id"] = tree["next"]
        tree["next"] += 1
        if old != task["id"]:
            mapping[(tree["id"], old)] = (tree["id"], task["id"])
    return mapping


# Moves. A task always moves with its whole branch.


def movable(place: Place, ref: Ref, what: str) -> None:
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree: {what} moves tasks within a tree")


def move_up(data: Data, ref: Ref) -> None:
    place = locate(data, ref)
    movable(place, ref, "up")
    if place.index == 0:
        raise Problem(f"{show_ref(ref)} is first already")
    siblings, index = place.siblings, place.index
    siblings[index - 1], siblings[index] = siblings[index], siblings[index - 1]


def move_down(data: Data, ref: Ref) -> None:
    place = locate(data, ref)
    movable(place, ref, "down")
    if place.index == len(place.siblings) - 1:
        raise Problem(f"{show_ref(ref)} is last already")
    siblings, index = place.siblings, place.index
    siblings[index + 1], siblings[index] = siblings[index], siblings[index + 1]


def indent(data: Data, ref: Ref) -> None:
    """Under the task above it, as its last sub-task."""
    place = locate(data, ref)
    movable(place, ref, "in")
    if place.index == 0:
        raise Problem(f"{show_ref(ref)} has no task above it to go under")
    task = place.siblings.pop(place.index)
    place.siblings[place.index - 1]["tasks"].append(task)


def outdent(data: Data, ref: Ref) -> Mapping:
    """Next to its parent, right after it; from a tree's top level, a tree
    of its own. Returns the renumbering, if any."""
    place = locate(data, ref)
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree already")
    if place.parent is place.tree:
        return make_tree(data, ref)
    parent = by_key(data, place.parent["key"])
    parent.siblings.insert(parent.index + 1, place.siblings.pop(place.index))
    return {}


def move_under(data: Data, ref: Ref, target: Ref) -> Mapping:
    """Under target, as its last sub-task. Within the tree the numbers stay;
    into another tree the branch gets that tree's next numbers."""
    place = locate(data, ref)
    destination = locate(data, target)
    if any(task is destination.task for task in walk([place.task])):
        raise Problem(f"{show_ref(target)} is in {show_ref(ref)}'s branch: a branch can't go under itself")
    task = place.siblings.pop(place.index)
    destination.task["tasks"].append(task)
    mapping: Mapping = {}
    if destination.tree is not place.tree:
        into_tree(task, destination.tree, place.tree["id"], mapping)
    return mapping


def make_tree(data: Data, ref: Ref) -> Mapping:
    place = locate(data, ref)
    if place.parent is None:
        raise Problem(f"{show_ref(ref)} is a tree already")
    return as_tree(data, place.siblings.pop(place.index), place.tree["id"])


def delete(data: Data, ref: Ref) -> Deleted:
    place = locate(data, ref)
    task = place.siblings.pop(place.index)
    parent = None if place.parent is None else place.parent["key"]
    entry: Deleted = {"task": task, "tree": place.tree["id"], "parent": parent, "index": place.index, "deleted": now()}
    data["deleted"].append(entry)
    return entry


def restore(data: Data, ref: Ref) -> tuple[Task, Mapping]:
    """Back under the task it was under, wherever that is now, with its
    numbers where they're free in that tree, else that tree's next ones.
    With that task gone, a tree of its own."""
    found = deleted_entry(data, ref)
    if found is None:
        raise Problem(f"{show_ref(ref)} isn't deleted")
    entry, top = found
    if not top:
        raise Problem(f"{show_ref(ref)} was deleted with {show_ref(entry_ref(entry))}: restore that")
    data["deleted"].remove(entry)
    task = entry["task"]
    if is_tree(task):
        data["trees"].insert(min(entry["index"], len(data["trees"])), task)
        return task, {}
    parent = by_key(data, entry["parent"])
    if parent is None:
        return task, as_tree(data, task, entry["tree"])
    tree, mapping = parent.tree, {}
    numbers = {sub["id"] for sub in walk([task])}
    taken = {other["id"] for other in walk(tree["tasks"])}
    parent.task["tasks"].insert(min(entry["index"], len(parent.task["tasks"])), task)
    if tree["id"] != entry["tree"] or taken & numbers:
        into_tree(task, tree, entry["tree"], mapping)
    else:
        tree["next"] = max(tree["next"], max(numbers) + 1)
    return task, mapping


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
        raise Problem(f'{gone}nothing in focus: start a tree with `twigt new "title"`, pick a task with `twigt focus kemi:5`, or add with -u')
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
