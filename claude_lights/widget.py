"""The widget window. Every GTK call in the project lives here."""

from __future__ import annotations

import logging
import math
import signal
from pathlib import Path
from typing import NamedTuple

import cairo
import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

# The Wayland app_id the KWin rule matches on. Must be set before any window is
# realized, which is why LightsWindow.__init__ calls _ensure_app_id() first.
_APP_ID = "claude-lights"


def _ensure_app_id() -> None:
    if GLib.get_prgname() != _APP_ID:
        GLib.set_prgname(_APP_ID)
        GLib.set_application_name(_APP_ID)


from claude_lights import ipc  # noqa: E402
from claude_lights.grid import layout  # noqa: E402
from claude_lights.registry import DEFAULT_SESSION_DIR, Registry, Session  # noqa: E402
from claude_lights.state import Light, blinks, light_for, rgb  # noqa: E402

log = logging.getLogger("claude-lights")


def _light_for_session(session: Session) -> Light:
    """Grey when the PID-reuse guard could not be applied, so an unverified
    session stays visible but is obviously distinct from a healthy one."""
    return light_for(session.status) if session.verified else Light.UNKNOWN


POLL_MS = 2000
BLINK_MS = 600

DOT_RADIUS = 13
LABEL_SIZE = 9.0
PAD = 6
GAP_X = 10
GAP_Y = 10
LABEL_GAP = 4
MAX_LABEL_W = 72

_LABEL = (0.85, 0.85, 0.88)
_OUTLINE = (0.0, 0.0, 0.0, 0.85)
_BLINK_DIM = 0.28


class _Layout(NamedTuple):
    """One cell size for the whole grid, derived from what will actually be
    drawn. _resize() and _draw() both call _measure() to get this, rather
    than each computing their own numbers, so they cannot disagree about
    where a dot ends up versus how big the window is."""

    cols: int
    rows: int
    cell_w: float
    cell_h: float
    ascent: float
    entries: list[tuple[str, float]]  # (fitted label, label width) per session


class LightsWindow(Gtk.Window):
    def __init__(
        self,
        registry: Registry,
        poll_ms: int = POLL_MS,
        blink_ms: int = BLINK_MS,
    ) -> None:
        _ensure_app_id()
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._registry = registry
        self._sessions: list[Session] = []
        self._toggled_on = True
        self._blink_on = True
        self._logged_poll_error = False
        self._logged_render_error = False
        self._logged_blink_error = False
        self._logged_toggle_error = False
        self._logged_draw_error = False
        self._logged_map_error = False

        # A throwaway 1x1 surface purely for text measurement, so _resize()
        # can size the window before there is any real draw context to
        # measure with. Same font calls as _draw() uses, so the numbers match.
        self._measure_ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self.add(self._area)

        # KWin accepts layer-shell surfaces but never composites them, so this
        # is an ordinary window. Placement, keep-above and taskbar suppression
        # come from the KWin rule that matches _APP_ID.
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)  # honoured under X11; on Wayland the rule enforces it
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # Never steal focus from the terminal underneath.
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        # Click-through: an empty input-shape region means the compositor
        # never routes pointer input to this window at all, so a click lands
        # on whatever is underneath instead of just uselessly focusing us.
        self.connect("map-event", self._on_map)

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self._on_toggle)
        GLib.timeout_add(poll_ms, self._on_poll)
        GLib.timeout_add(blink_ms, self._on_blink)
        self._on_poll()

    def _on_toggle(self) -> bool:
        # Never let an exception here kill the GLib source: a dead SIGUSR1
        # handler leaves the toggle permanently unresponsive with no signal
        # to the user that anything went wrong.
        try:
            self._toggled_on = not self._toggled_on
            self._apply_visibility()
        except Exception:
            if not self._logged_toggle_error:
                log.exception("toggle handling failed")
                self._logged_toggle_error = True
        else:
            self._logged_toggle_error = False
        return GLib.SOURCE_CONTINUE

    def _on_map(self, _widget, _event) -> bool:
        # Re-applied on every map, not just once: the toggle hides and shows
        # this same window repeatedly, and Wayland can recreate the surface
        # on remap rather than reuse it, which would silently drop the
        # input-shape region set at construction time.
        try:
            gdk_window = self.get_window()
            if gdk_window is not None:
                gdk_window.input_shape_combine_region(cairo.Region(), 0, 0)
        except Exception:
            if not self._logged_map_error:
                log.exception("failed to make the window click-through")
                self._logged_map_error = True
        else:
            self._logged_map_error = False
        return False

    def _on_poll(self) -> bool:
        # A timer callback must never raise, or the timer stops and the widget
        # silently freezes on stale colours.
        try:
            self._sessions = self._registry.poll()
        except Exception:
            if not self._logged_poll_error:
                log.exception("session poll failed; keeping last known state")
                self._logged_poll_error = True
            return GLib.SOURCE_CONTINUE
        self._logged_poll_error = False

        try:
            self._resize()
            self._apply_visibility()
            self._area.queue_draw()
        except Exception:
            if not self._logged_render_error:
                log.exception("applying polled sessions failed; keeping last known state")
                self._logged_render_error = True
        else:
            self._logged_render_error = False
        return GLib.SOURCE_CONTINUE

    def _on_blink(self) -> bool:
        # No `return` inside this try: an early return would skip the
        # sibling `else` below and leave _logged_blink_error stuck once set,
        # since "nothing is waiting" is the common case.
        try:
            if any(blinks(_light_for_session(s)) for s in self._sessions):
                self._blink_on = not self._blink_on
                self._area.queue_draw()
        except Exception:
            if not self._logged_blink_error:
                log.exception("blink tick failed")
                self._logged_blink_error = True
        else:
            self._logged_blink_error = False
        return GLib.SOURCE_CONTINUE

    def _measure(self) -> _Layout:
        cols, rows = layout(len(self._sessions))
        if cols == 0:
            return _Layout(0, 0, 0.0, 0.0, 0.0, [])

        ctx = self._measure_ctx
        ctx.select_font_face("Sans")
        ctx.set_font_size(LABEL_SIZE)

        entries: list[tuple[str, float]] = []
        cell_w = float(2 * DOT_RADIUS)
        for session in self._sessions:
            label = self._fit(ctx, session.name, MAX_LABEL_W)
            width = ctx.text_extents(label).width
            entries.append((label, width))
            cell_w = max(cell_w, width)

        ascent, _descent, line_height, _max_x_adv, _max_y_adv = ctx.font_extents()
        cell_h = 2 * DOT_RADIUS + LABEL_GAP + line_height
        return _Layout(cols, rows, cell_w, cell_h, ascent, entries)

    def _resize(self) -> None:
        # set_size_request() on the child, not self.resize() on the window:
        # an explicit resize() pins a size that survives future shrinks even
        # after the child's natural size drops, which is why the window
        # used to never shrink back down once it had shown four sessions.
        grid = self._measure()
        if grid.cols == 0:
            self._area.set_size_request(-1, -1)
            return
        width = 2 * PAD + grid.cols * grid.cell_w + (grid.cols - 1) * GAP_X
        height = 2 * PAD + grid.rows * grid.cell_h + (grid.rows - 1) * GAP_Y
        self._area.set_size_request(math.ceil(width), math.ceil(height))

    def _apply_visibility(self) -> None:
        if self._toggled_on and self._sessions:
            self.show_all()
        else:
            self.hide()

    def _on_draw(self, _area: Gtk.DrawingArea, ctx) -> bool:
        # GTK does not stop the process on an exception from a signal handler,
        # but it does print a traceback and can leave the frame half-painted.
        # A draw crash is exactly the "invisible and no clue why" failure mode
        # this file exists to prevent, so it gets the same guard as the timers.
        # No `return` inside the try: that would skip the sibling `else` and
        # leave _logged_draw_error stuck true after the first failure.
        try:
            result = self._draw(ctx)
        except Exception:
            if not self._logged_draw_error:
                log.exception("draw failed")
                self._logged_draw_error = True
            return False
        else:
            self._logged_draw_error = False
            return result

    def _draw(self, ctx) -> bool:
        # Uses the exact same _measure() as _resize(): if the two ever
        # computed cell sizes independently, a dot could land outside the
        # backdrop the moment the two calculations drifted apart.
        grid = self._measure()
        if grid.cols == 0:
            return False

        # No backdrop: the surface is fully transparent, so only the dots and
        # labels are painted. Dots stay plain solid fills; the label gets a
        # cheap dark outline so it is not actively invisible on a light
        # background, without trying to guarantee contrast in every case.
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

        ctx.select_font_face("Sans")
        ctx.set_font_size(LABEL_SIZE)

        for index, session in enumerate(self._sessions):
            col, row = index % grid.cols, index // grid.cols
            label, label_w = grid.entries[index]
            cx = PAD + col * (grid.cell_w + GAP_X) + grid.cell_w / 2
            cy = PAD + row * (grid.cell_h + GAP_Y) + DOT_RADIUS

            light = _light_for_session(session)
            alpha = _BLINK_DIM if (blinks(light) and not self._blink_on) else 1.0
            ctx.set_source_rgba(*rgb(light), alpha)
            ctx.arc(cx, cy, DOT_RADIUS, 0, 6.283185307179586)
            ctx.fill()

            label_x = cx - label_w / 2
            label_y = cy + DOT_RADIUS + LABEL_GAP + grid.ascent
            ctx.move_to(label_x, label_y)
            ctx.text_path(label)
            ctx.set_source_rgba(*_OUTLINE)
            ctx.set_line_width(2.5)
            ctx.stroke_preserve()
            ctx.set_source_rgb(*_LABEL)
            ctx.fill()

        return False

    @staticmethod
    def _fit(ctx, name: str, budget: float) -> str:
        if ctx.text_extents(name).width <= budget:
            return name
        trimmed = name
        while trimmed and ctx.text_extents(trimmed + "…").width > budget:
            trimmed = trimmed[:-1]
        return trimmed + "…" if trimmed else ""


class DemoRegistry:
    """Synthetic sessions for visual checks. Bypasses the registry entirely, so
    it cannot go stale the way pid-bound fixture files do -- there is no pid
    and no file for a process exit to invalidate."""

    def poll(self) -> list[Session]:
        return [
            Session(pid=1, name="atira-d0", cwd="", status="idle", started_at=0, tmux=None, verified=True),
            Session(pid=2, name="atira-d4", cwd="", status="busy", started_at=1, tmux=None, verified=True),
            Session(pid=3, name="infra-9a", cwd="", status="waiting", started_at=2, tmux=None, verified=True),
            Session(pid=4, name="ghost-7e", cwd="", status="busy", started_at=3, tmux=None, verified=False),
        ]


def run(session_dir: Path | None = None, demo: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        gi.require_foreign("cairo")
    except Exception:
        log.error(
            "missing the cairo foreign-struct bridge, so nothing can be painted. "
            "Install it with: sudo apt install python3-gi-cairo"
        )
        return 1
    ipc.write_pidfile()
    registry = DemoRegistry() if demo else Registry(session_dir or DEFAULT_SESSION_DIR)
    LightsWindow(registry)
    Gtk.main()
    return 0
