# twigt

Task trees on the command line. Each task has a title, a body, tags and a
status; whole branches move up, down, in, out or into another tree.

```text
kemi Nextcloud follow-ups [ops] · 10 Nov     🔲 open
├─ 1 monitoring: uptime + cert expiry [ops]  ✅ done
├─ 2 ufw cleanup on ubuntu1 ≡                ▶ in progress
│  ├─ 2.1 drop the dead 8443 rule            🔲 open
│  └─ 2.2 check port 80 from outside         🔲 open
└─ 3 card: secure 11000/8080                 ⏳ you: which host first
```

`kemi` is the tree's id, a word made from a hash of its title and the time
it was started. Its tasks are numbered as an outline, and a task is always
its tree and number: `kemi:2.1`. `≡` marks a task with a body.

## Install

```sh
uv tool install git+https://github.com/mamueluth/twigt
```

Python 3.11+, Linux or macOS, no dependencies.

## Use

```sh
twigt new "Nextcloud follow-ups" -t ops   # a new tree, in focus; prints its id, say kemi
twigt add "ufw cleanup" -m "Docker writes iptables itself."
twigt add "drop the dead 8443 rule" -u kemi:1
twigt start kemi:1
twigt done kemi:1 -n "rules gone"         # with the open tasks below it
twigt                                     # show
```

| Command | Does |
| --- | --- |
| `show [TASK]` | the context's trees and a line per other open tree; with TASK, that task in full. `-b` bodies, `--open`, `--tag T`, `--all`, `--closed` |
| `new TITLE`, `add [TITLE …]` | a tree, focused; tasks under the focus or `-u TASK`. `-m BODY` (`-` reads stdin), `-t TAG`, or an outline on stdin |
| `edit TASK` | title and body in `$EDITOR`, the first line the title; or `--title`, `-m BODY` |
| `start`, `done`, `drop`, `reopen`, `wait` `TASK … [-n NOTE]` | the status; `done` and `drop` close the open tasks below too |
| `up`, `down` `TASK` | swap place and number with the sibling before or after |
| `in`, `out` `TASK` | to the end of the task above; to the end of its parent's level, or from a tree's top level a tree of its own |
| `mv TASK -u TASK`, `mv TASK --root` | to the end of any task in any tree; a tree of its own |
| `renumber TREE` | every level 1, 2, 3 …, closing the gaps |
| `tag`, `untag` `TASK TAG …` | tags |
| `delete TASK …`, `restore TASK` | take a branch out; put it back where it was |
| `focus TASK`, `attach TASK` | where `add` puts tasks; make TASK's tree one of the context's |

TASK is `kemi:2.1`, or `kemi` for the tree itself. Siblings always stand in
number order: a new or moved task goes last with the highest number + 1, and
a moved branch takes its sub-tasks along under its new number (`2.1` moved
under 3 is `3.1`, its `2.1.1` now `3.1.1`; as a tree of its own, `2.1.1`
becomes `1`). Deleting leaves a gap; a restored branch takes its old number
if it's still free, else goes last. Whatever changes numbers says so.

Statuses: `open` 🔲, `active` ▶ in progress, `waiting` ⏳ (the note says on
what or whom), `done` ✅, `dropped` ❌. An outline is one task per line,
nested by indentation, `title | status: note`:

```text
ufw cleanup | active
  drop the dead 8443 rule
card: secure 11000/8080 | waiting: you: which host first
```

## Data

One JSON file, `twigt.json`, in `$TWIGT_DATA`, else
`$XDG_DATA_HOME/twigt` (`~/.local/share/twigt`). Every change is locked and
written in one step, so several shells can work on it at once. A context
(`$TWIGT_CTX` or `--ctx`, default `default`) has its own trees and focus:
give each shell or agent session its own.

## Development

`uv run pytest` runs the tests; `uv tool install --editable .` installs the
working copy.
