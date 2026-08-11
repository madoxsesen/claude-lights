# Fixtures

Fixture session files for eyeballing `claude_lights/widget.py`.

Every file reuses the pid of a live process so the liveness check in
`claude_lights/registry.py` passes without spawning real Claude Code sessions.
Regenerate them with the snippet in Task 5 of the implementation plan if the
pid goes stale (i.e. the process that owned it has exited).

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
