"""CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_lights import ipc


def _run_widget(session_dir: Path | None = None, demo: bool = False) -> int:
    # Imported lazily so `toggle` and `install` never need GTK.
    from claude_lights import widget

    return widget.run(session_dir, demo=demo)


def _install() -> int:
    from claude_lights import shortcut

    return shortcut.install()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-lights")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["toggle", "install"],
        help="omit to run the widget",
    )
    parser.add_argument(
        "--fake",
        metavar="DIR",
        help="read session files from DIR instead of ~/.claude/sessions",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="show four synthetic sessions, one per colour, for a visual check",
    )
    args = parser.parse_args(argv)

    if args.command == "toggle":
        if ipc.send_toggle():
            return 0
        print("claude-lights is not running", file=sys.stderr)
        return 1

    if args.command == "install":
        return _install()

    return _run_widget(Path(args.fake) if args.fake else None, demo=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
