# claude-lights

A traffic light per running Claude Code session, pinned to the top-left
corner of a KDE Plasma Wayland desktop.

## Colours

| Colour | Meaning | Registry status |
|---|---|---|
| Green | Idle, free to hand it work | `idle` |
| Yellow | Busy: thinking or running a command | `busy`, `shell` |
| Red, blinking | Waiting on you, act now | `waiting` |
| Grey | Unrecognised status | anything else |

A session also renders grey, regardless of its status, if its registry file
has no `procStart` field. `procStart` is what lets the widget tell a live
process apart from a different process that happens to have reused the same
pid; without it that check cannot be done, so the session is shown but
flagged rather than trusted.

## How it works

Sessions are discovered by polling `~/.claude/sessions/*.json`, the session
registry Claude Code already maintains for its own use. There are no hooks,
and nothing is added to `settings.json`. Reads are defensive throughout: an
unreadable or malformed file degrades that one dot to grey or drops it,
rather than crashing the widget. The registry format is Claude Code's
internal detail, not a public contract.

KWin advertises the Wayland layer-shell protocol but does not actually
composite layer-shell surfaces, so the widget is an ordinary undecorated
GTK window. All of its placement, keep-above behaviour and taskbar/pager/
switcher suppression come from a KWin window rule matched on the window's
`app_id` (`claude-lights`), not from anything the window itself can request
on Wayland. `claude-lights install` writes that rule; see Usage below.

## Requirements

Ubuntu with KDE Plasma on Wayland, system Python 3.12+, and PyGObject:

```bash
sudo apt install python3-gi-cairo
```

A successful `import cairo` in Python proves nothing here: the package
that matters is the GObject-Introspection to cairo bridge, not the cairo
module itself, and the two can be out of sync. The check that actually
tells you whether drawing will work is:

```bash
python3 -c "import gi; gi.require_foreign('cairo')"
```

If that raises, the widget will start but every draw call will fail. This
distinction cost real debugging time, hence calling it out here.

## Usage

```bash
bin/claude-lights                    # run in the foreground
bin/claude-lights --demo             # four synthetic sessions, one per colour
bin/claude-lights --fake DIR         # read session files from DIR instead of
                                      # ~/.claude/sessions; see
                                      # tests/fixtures/README.md for how to
                                      # build one
bin/claude-lights toggle             # show or hide an already-running widget
bin/claude-lights install            # install the KWin rule and the Meta+C
                                      # global shortcut
```

`install` does two independent things and reports on each separately:

- Merges a window rule into `~/.config/kwinrulesrc` (backing up whatever was
  there first) and asks the running KWin to reconfigure. This does not
  require logging out.
- Writes a `.desktop` file and registers `Meta+C` against it in
  `kglobalshortcutsrc` via `kwriteconfig6`, the only writer Plasma will not
  silently overwrite. It cannot hot-reload the shortcut on this machine
  (`kglobalaccel6` is not on PATH), so the binding may not be live until the
  next login. `install` prints a manual fallback (System Settings >
  Keyboard > Shortcuts > Add > Command) for that case.

## Start at login

```bash
cp packaging/claude-lights.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-lights.service
```

## Tests

```bash
uv venv --system-site-packages .venv
uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -v
```

`--system-site-packages` is required so the venv can see the system
PyGObject bindings installed by `python3-gi-cairo`; they are not on PyPI.

## Known limits

- Layer-shell is unusable on this KWin, so the widget's placement, stacking
  and taskbar visibility all depend on the KWin rule installed by
  `claude-lights install`. Without that rule the window shows up unplaced,
  focus-stealing and visible in the taskbar.
- `set_keep_above` and the rule's `above=true` are advisory, not absolute: a
  genuinely fullscreen window still covers the widget.
- The session registry format is internal to Claude Code and may change
  without notice. Reads are defensive against that, so a change should
  degrade the widget to fewer or grey dots rather than crash it, but this
  is not a guarantee Claude Code makes.
- Single display only.
