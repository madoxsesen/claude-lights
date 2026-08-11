"""Install the KWin window rule, and explain the hotkey KDE will not let us bind.

KWin accepts layer-shell surfaces but never composites them (see widget.py), so
the widget is an ordinary window and everything about how it behaves comes from
a KWin rule matched on the Wayland app_id it sets (``claude-lights``): position,
keep-above, no border, no focus, and hidden from taskbar/pager/switcher. Without
the rule it is an unplaced, focus-stealing, taskbar-visible window. That half is
fully automatic here, and kwinrulesrc is merged rather than overwritten because
it may already hold the user's own rules.

The global hotkey is NOT automatable, verified on 2026-08-11:

* Writing a ``[services][<id>.desktop]`` entry plus a matching .desktop file,
  then running ``kbuildsycoca6 --noincremental`` and restarting
  plasma-kglobalaccel, never produces a registered component.
* Binding the same command by hand in System Settings does work, and makes KDE
  write its own .desktop and shortcut entry, after which the component appears
  in ``org.kde.KGlobalAccel.allComponents``.
* Calling ``org.kde.KGlobalAccel.setShortcut`` over D-Bus is accepted, returns
  an empty list, and registers nothing: the component must register itself.

So writing shortcut config would only leave dead entries in the user's KDE
configuration. This module prints instructions instead of pretending.
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path

from claude_lights import APP_ID

KWIN_RULES_PATH = Path.home() / ".config" / "kwinrulesrc"

# Verified working on 2026-08-11: forces position, keep-above, no border, and
# skip-{taskbar,pager,switcher}. acceptfocus=false and fsplevel=4 are what
# stop the widget stealing focus; every *rule key is 2 (Force) so KWin
# overrides whatever the user's own window settings would otherwise give it.
_RULE_KEYS: dict[str, str] = {
    "Description": f"{APP_ID} widget",
    "above": "true",
    "aboverule": "2",
    "acceptfocus": "false",
    "acceptfocusrule": "2",
    "fsplevel": "4",
    "fsplevelrule": "2",
    "noborder": "true",
    "noborderrule": "2",
    "position": "0,0",
    "positionrule": "2",
    "skippager": "true",
    "skippagerrule": "2",
    "skipswitcher": "true",
    "skipswitcherrule": "2",
    "skiptaskbar": "true",
    "skiptaskbarrule": "2",
    "wmclass": APP_ID,
    "wmclasscomplete": "false",
    "wmclassmatch": "1",
}

def _launcher_path() -> Path:
    return Path(__file__).resolve().parent.parent / "bin" / "claude-lights"


def _read_config(path: Path) -> configparser.ConfigParser:
    """Raises configparser.Error on a file that isn't valid INI. Callers must
    not swallow that: a kwinrulesrc we can't parse must never be treated as
    an empty one, or we'd overwrite whatever the user actually had in it."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    # KDE config keys are case-sensitive ("Description" vs "wmclass"); the
    # default optionxform would lowercase every key on write.
    parser.optionxform = str  # type: ignore[method-assign]
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def _atomic_write(path: Path, parser: configparser.ConfigParser) -> None:
    # Write to a temp file in the same directory and rename over the target,
    # so a crash mid-write cannot leave the user's live KDE config truncated.
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        parser.write(fh, space_around_delimiters=False)
    os.replace(tmp, path)


def merge_kwin_rule(parser: configparser.ConfigParser) -> str:
    """Add or update our rule section in `parser`, in place, preserving every
    other section and every other [General] key untouched. Returns the id
    (section name) our rule ended up under."""
    order: list[str] = []
    if parser.has_option("General", "rules"):
        order = [item for item in parser.get("General", "rules").split(",") if item]

    numeric_sections = [s for s in parser.sections() if s.isdigit()]
    for section in numeric_sections:
        if section not in order:
            # Heals a [General] whose rules= list fell out of sync with the
            # sections actually present, rather than silently dropping one.
            order.append(section)

    our_section = next(
        (s for s in numeric_sections if parser.get(s, "wmclass", fallback=None) == APP_ID),
        None,
    )
    if our_section is None:
        # rules= can reference more ids than have a physical section (a
        # user-editing artefact, or a [General] that drifted). The next id
        # must dodge those dangling references too, not just the sections
        # that actually exist, or it collides with one of them.
        existing_ids = {int(s) for s in numeric_sections} | {int(s) for s in order if s.isdigit()}
        next_id = max(existing_ids, default=0) + 1
        our_section = str(next_id)
        order.append(our_section)

    if parser.has_section(our_section):
        for key in list(parser[our_section]):
            parser.remove_option(our_section, key)
    else:
        parser.add_section(our_section)
    for key, value in _RULE_KEYS.items():
        parser.set(our_section, key, value)

    if not parser.has_section("General"):
        parser.add_section("General")
    parser.set("General", "count", str(len(order)))
    parser.set("General", "rules", ",".join(order))
    return our_section


def write_kwin_rule(path: Path = KWIN_RULES_PATH) -> tuple[bool, str]:
    """Merge our rule into kwinrulesrc (backing up whatever was there first)
    and ask the running KWin to reconfigure. Returns (applied, message).

    Refuses to write anything if the existing file can't be parsed: treating
    an unparseable file as an empty one would silently discard everything in
    it, which is worse than leaving the install half-done and saying so."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Backed up once, ever, per file: install is meant to be re-runnable (to
    # re-apply the rule after KDE rewrites kwinrulesrc, say), and a second
    # run's "before" is the first run's "after". Re-backing up on every call
    # would overwrite the one copy of the user's true pre-install content
    # with our own prior merge.
    backup = path.with_name(f"{path.name}.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)

    try:
        parser = _read_config(path)
    except configparser.Error as exc:
        return (
            False,
            f"{path} could not be parsed as INI ({exc}); left untouched, nothing was written "
            f"(a copy of it is at {backup} if you want to inspect it)",
        )

    merge_kwin_rule(parser)
    _atomic_write(path, parser)

    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if qdbus is None:
        return (
            False,
            f"wrote {path}, but qdbus6 was not found on PATH; run "
            "'qdbus6 org.kde.KWin /KWin reconfigure' yourself, or log out and back in",
        )
    try:
        # The reconfigure method lives at /KWin, not the bus root; calling
        # without the object path fails with "not a valid path name".
        subprocess.run([qdbus, "org.kde.KWin", "/KWin", "reconfigure"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        return (
            False,
            f"wrote {path}, but 'qdbus6 org.kde.KWin /KWin reconfigure' failed ({exc}); "
            "log out and back in for the rule to take effect",
        )
    return True, f"merged the window rule into {path} and told KWin to reconfigure"


def _print_hotkey_instructions(keys: str) -> None:
    print(
        f"\nThe {keys} hotkey has to be added by hand, once:\n"
        "  System Settings > Keyboard > Shortcuts > Add > Command\n"
        f"  Command:  {_launcher_path()} toggle\n"
        f"  Shortcut: {keys}\n"
        "\nThis is a KDE limitation, not an oversight. A shortcut only works once "
        "its component is registered with kglobalaccel, and that registration "
        "cannot be produced by writing config files: it is done by KDE itself "
        "when you bind the key. Writing the config anyway would just leave dead "
        "entries in your KDE configuration, so this installer does not."
    )


def install(keys: str = "Meta+C") -> int:
    """Install the KWin rule and print the manual hotkey steps.

    Returns 0 when the rule applied. The hotkey is not counted against success:
    it is inherently manual (see the module docstring), so failing the install
    over it would report a problem the user cannot fix."""
    launcher = _launcher_path()
    if not launcher.exists():
        print(f"launcher not found at {launcher}")
        return 1

    kwin_ok, kwin_msg = write_kwin_rule()
    print(f"KWin rule: {'ok' if kwin_ok else 'FAILED'}, {kwin_msg}")

    _print_hotkey_instructions(keys)

    if kwin_ok:
        return 0
    print("\nThe window rule did not apply. See the FAILED line above.")
    return 1
