"""The GTK3 layer-shell window. Every GTK call in the project lives here."""

from __future__ import annotations

import logging
import signal
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import GLib, Gtk, GtkLayerShell  # noqa: E402

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
MARGIN = 8

CELL_W = 64
CELL_H = 58
DOT_RADIUS = 13
LABEL_SIZE = 9.0
PAD = 6

_BG = (0.09, 0.09, 0.11, 0.82)
_LABEL = (0.85, 0.85, 0.88)
_BLINK_DIM = 0.28


class LightsWindow(Gtk.Window):
    def __init__(
        self,
        registry: Registry,
        poll_ms: int = POLL_MS,
        blink_ms: int = BLINK_MS,
    ) -> None:
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

        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self.add(self._area)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "claude-lights")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, MARGIN)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, MARGIN)
        # Never steal keyboard focus from the terminal underneath.
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

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

    def _resize(self) -> None:
        cols, rows = layout(len(self._sessions))
        if cols == 0:
            return
        self.resize(cols * CELL_W + PAD * 2, rows * CELL_H + PAD * 2)

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
        cols, _rows = layout(len(self._sessions))
        if cols == 0:
            return False

        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.set_source_rgba(*_BG)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

        ctx.select_font_face("Sans")
        ctx.set_font_size(LABEL_SIZE)

        for index, session in enumerate(self._sessions):
            col, row = index % cols, index // cols
            cx = PAD + col * CELL_W + CELL_W / 2
            cy = PAD + row * CELL_H + DOT_RADIUS + 2

            light = _light_for_session(session)
            alpha = _BLINK_DIM if (blinks(light) and not self._blink_on) else 1.0
            ctx.set_source_rgba(*rgb(light), alpha)
            ctx.arc(cx, cy, DOT_RADIUS, 0, 6.283185307179586)
            ctx.fill()

            label = self._fit(ctx, session.name)
            width = ctx.text_extents(label).width
            ctx.set_source_rgb(*_LABEL)
            ctx.move_to(cx - width / 2, cy + DOT_RADIUS + 14)
            ctx.show_text(label)

        return False

    @staticmethod
    def _fit(ctx, name: str) -> str:
        budget = CELL_W - 4
        if ctx.text_extents(name).width <= budget:
            return name
        trimmed = name
        while trimmed and ctx.text_extents(trimmed + "…").width > budget:
            trimmed = trimmed[:-1]
        return trimmed + "…" if trimmed else ""


def run(session_dir: Path | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not GtkLayerShell.is_supported():
        log.error(
            "compositor does not support zwlr_layer_shell_v1. "
            "Install gir1.2-gtklayershell-0.1 and run under a Wayland session."
        )
        return 1
    ipc.write_pidfile()
    LightsWindow(Registry(session_dir or DEFAULT_SESSION_DIR))
    Gtk.main()
    return 0
