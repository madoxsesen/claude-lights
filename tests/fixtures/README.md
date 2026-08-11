# Fixtures

Fixture session files for eyeballing `claude_lights/widget.py`.

**These fixtures pin a specific pid, and that pid WILL be dead by the time
you read this.** Every file reuses the pid of a live process so the
liveness check in `claude_lights/registry.py` passes without spawning real
Claude Code sessions -- but that means the moment the process that minted
them exits, `registry.scan()` sees zero live sessions and every fixture
here scans to nothing. There is no way to commit a fixture that stays live
forever. **Always regenerate before using these** -- don't assume a fresh
checkout works as-is.

Regenerate both sets against a fresh long-lived pid with:

```bash
cd ~/git/claude-lights
sleep 999999 &      # anything long-lived works; this is just the simplest
HELPER_PID=$!
disown

.venv/bin/python - <<PY
import json, pathlib

PID = $HELPER_PID

def stat_start(pid: int) -> str:
    raw = pathlib.Path(f"/proc/{pid}/stat").read_text()
    return raw[raw.rfind(")") + 2 :].split()[19]

start = stat_start(PID)

four = pathlib.Path("tests/fixtures/four")
for old in four.glob("*.json"):
    old.unlink()
for i, (name, status) in enumerate([
    ("atira-d0", "idle"), ("atira-d4", "busy"),
    ("frontend-7e", "shell"), ("infra-9a", "waiting"),
]):
    (four / f"{PID}{i}.json").write_text(json.dumps({
        "pid": PID, "cwd": "/home/msesen/git/atira",
        "startedAt": 1000 + i, "procStart": start,
        "name": name, "status": status, "tmux": None,
    }))

unverified = pathlib.Path("tests/fixtures/unverified")
for old in unverified.glob("*.json"):
    old.unlink()
(unverified / f"{PID}0.json").write_text(json.dumps({
    "pid": PID, "cwd": "/home/msesen/git/atira",
    "startedAt": 3000, "procStart": start,
    "name": "verified-idle", "status": "idle", "tmux": None,
}))
(unverified / f"{PID}1.json").write_text(json.dumps({
    "pid": PID, "cwd": "/home/msesen/git/atira",
    "startedAt": 3001,
    "name": "unverified-busy", "status": "busy", "tmux": None,
}))
print("regenerated four/ and unverified/ against pid", PID)
PY
```

Keep the `sleep 999999` (or whatever you used) running for as long as you
need the fixtures live; killing it makes them scan to zero again.

Because every fixture in a set shares one pid, drive these with the stateless
`registry.scan()` rather than `Registry.poll()` -- `poll()` keys by pid and
would collapse same-pid fixtures into a single dot.

- `four/` - one session per colour: idle (green), busy (yellow), shell
  (yellow), waiting (red, blinking). Names `atira-d0`, `atira-d4`,
  `frontend-7e`, `infra-9a` with ascending `startedAt` so the 2x2 layout order
  is deterministic. This is the canonical demo fixture.
- `unverified/` - two sessions: `verified-idle` has a correct `procStart` and
  renders green as `idle` normally would. `unverified-busy` has no
  `procStart` key at all, so `registry.scan()` cannot apply the PID-reuse
  guard and marks it `verified=False`; it must render grey (`Light.UNKNOWN`)
  rather than the yellow that its `busy` status would otherwise map to. This
  proves the grey override in `widget._light_for_session()`.
