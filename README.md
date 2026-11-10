# twigt

Task trees on the command line. Each task has a title, a body, tags and a
status; whole branches move up, down, in, out or into another tree.

```text
1 Nextcloud follow-ups [ops] · 10 Nov        🔲 open
├─ 2 monitoring: uptime + cert expiry [ops]  ✅ done
├─ 3 ufw cleanup on ubuntu1 ≡                ▶ in progress
│  ├─ 6 check port 80 from outside           🔲 open
│  └─ 4 drop the dead 8443 rule              🔲 open
└─ 5 card: secure 11000/8080                 ⏸ you: which host first
```

`≡` marks a task with a body. Numbers never change and are never reused,
so "see 4" stays true wherever 4 moves.

## Install

```sh
uv tool install git+https://github.com/mamueluth/twigt
```

Python 3.11+, Linux or macOS, no dependencies.

## Use

```sh
twigt new "Nextcloud follow-ups" -t ops   # a new tree, in focus
twigt add "ufw cleanup" -m "Docker writes iptables itself."
twigt add "drop the dead 8443 rule" -u 2  # under 2 instead of the focus
twigt start 2
twigt done 2 -n "rules gone"              # with the open tasks below it
twigt                                     # show
```

| Command | Does |
| --- | --- |
| `show [N]` | the context's trees and a line per other open tree; with N, that task in full. `-b` bodies, `--open`, `--tag T`, `--all`, `--closed` |
| `new TITLE`, `add [TITLE …]` | a tree, focused; tasks under the focus or `-u N`. `-m BODY` (`-` reads stdin), `-t TAG`, or an outline on stdin |
| `edit N` | title and body in `$EDITOR`, the first line the title; or `--title`, `-m BODY` |
| `start`, `done`, `drop`, `reopen`, `wait`, `you` `N … [-n NOTE]` | the status; `done` and `drop` close the open tasks below too |
| `up`, `down`, `in`, `out` `N` | past a sibling; under the task above; next to the parent |
| `mv N -u M`, `mv N --root` | under any task in any tree; a tree of its own |
| `tag`, `untag` `N TAG …` | tags |
| `delete N …`, `restore N` | take a branch out; put it back where it was |
| `focus N`, `attach N` | where `add` puts tasks; make N's tree one of the context's |

Statuses: `open` 🔲, `active` ▶ in progress, `you` ⏸ (waits on you),
`waiting` ⏳ (on something else), `done` ✅, `dropped` ❌. An outline is one
task per line, nested by indentation, `title | status: note`:

```text
ufw cleanup | active
  drop the dead 8443 rule
card: secure 11000/8080 | you: which host first
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
