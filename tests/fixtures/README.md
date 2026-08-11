# Fixtures

There are no fixture files here any more. There used to be pid-bound JSON
files (`four/`, `unverified/`), but every one of them pinned a specific
live pid to pass `registry.py`'s liveness check, and every one of them went
stale the moment that pid's process exited -- which happened repeatedly,
including to the long-lived helper process kept alive specifically to stop
it happening. A fixture that only stays valid while a stray background
process keeps running is not a fixture worth committing.

## For eyeballing the widget: `widget.DemoRegistry`

`claude_lights.widget.DemoRegistry` returns four hand-built `Session`
objects directly -- no files, no pids, nothing that can go stale:

```python
from gi.repository import Gtk
from claude_lights import widget

widget.LightsWindow(widget.DemoRegistry())
Gtk.main()
```

One session per colour (idle/green, busy/yellow, waiting/red-blinking) plus
an unverified one (`verified=False`, so it renders the `Light.UNKNOWN` grey
override regardless of its `busy` status). Task 6 wires this up behind a
`--demo` flag.

## For exercising the real file-scanning path: point `--fake` at your own directory

If you specifically need to test `registry.scan()` / `Registry.poll()`
against real files (as opposed to the widget's drawing, which `DemoRegistry`
already covers), build a throwaway directory yourself. Every session file
needs a `pid` that is genuinely alive when you read it, because
`registry.py` checks `/proc/<pid>/stat` and rejects anything else:

```bash
.venv/bin/python - <<'PY'
import json, os, pathlib

pid = os.getpid()  # only live for as long as this python process is
raw = pathlib.Path(f"/proc/{pid}/stat").read_text()
start = raw[raw.rfind(")") + 2:].split()[19]

d = pathlib.Path("/tmp/claude-lights-manual-fixture")
d.mkdir(parents=True, exist_ok=True)
(d / f"{pid}0.json").write_text(json.dumps({
    "pid": pid, "cwd": "/home/msesen/git/atira", "startedAt": 1000,
    "procStart": start, "name": "atira-d0", "status": "idle", "tmux": None,
}))
print("wrote", d)
PY
```

Whatever pid you use, the fixture is only live for as long as that process
is. Don't commit the result -- regenerate it fresh whenever you need it.
