"""Install the KWin window rule and the KDE global shortcut.

Wayland forbids an application from grabbing its own global hotkey, and KWin
accepts layer-shell surfaces but never composites them (see widget.py), so
both halves of "make the widget behave" live outside the app entirely, in
KDE's own config files:

1. A KWin window rule, matched on the Wayland app_id the widget sets
   (``claude-lights``), forces the window's position, keep-above, border and
   taskbar/pager/switcher visibility. Without it the widget is an unplaced,
   focus-stealing, taskbar-visible ordinary window.
2. A KDE global shortcut (Plasma 6 dropped khotkeys) bound to a .desktop
   file that runs ``claude-lights toggle``.

kwinrulesrc may already hold the user's own rules, so it is merged, never
overwritten. kglobalshortcutsrc is written through kwriteconfig6, the only
sanctioned writer, because Plasma owns that file and overwrites hand edits.
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path

KWIN_RULES_PATH = Path.home() / ".config" / "kwinrulesrc"
APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"

DESKTOP_ID = "claude-lights-toggle.desktop"
FRIENDLY_NAME = "Toggle Claude Lights"
APP_ID = "claude-lights"

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

_DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name={name}
Exec={exec_path} toggle
NoDisplay=true
Terminal=false
X-KDE-GlobalAccel-CommandShortcut=true
"""


def _launcher_path() -> Path:
    return Path(__file__).resolve().parent.parent / "bin" / "claude-lights"


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    # KDE config keys are case-sensitive ("Description" vs "wmclass"); the
    # default optionxform would lowercase every key on write.
    parser.optionxform = str  # type: ignore[method-assign]
    if path.exists():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error:
            # A file we can't parse must not block install. Start fresh on
            # top of the backup write_kwin_rule() already took.
            pass
    return parser


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
        next_id = max((int(s) for s in numeric_sections), default=0) + 1
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
    and ask the running KWin to reconfigure. Returns (applied, message)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)

    parser = _read_config(path)
    merge_kwin_rule(parser)
    with path.open("w", encoding="utf-8") as fh:
        parser.write(fh, space_around_delimiters=False)

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


def write_desktop_file(launcher: Path, directory: Path = APPLICATIONS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    desktop_file = directory / DESKTOP_ID
    desktop_file.write_text(_DESKTOP_TEMPLATE.format(name=FRIENDLY_NAME, exec_path=launcher))
    return desktop_file


def write_global_shortcut(keys: str) -> tuple[bool, str]:
    """Register `keys` against our .desktop file in kglobalshortcutsrc via
    kwriteconfig6. Returns (applied, message); never hot-reloads kglobalaccel,
    since kglobalaccel6 is not on PATH on this machine."""
    kwriteconfig = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if kwriteconfig is None:
        return False, "kwriteconfig6 not found; nothing was written to kglobalshortcutsrc"

    for key, value in (
        ("_k_friendly_name", FRIENDLY_NAME),
        ("_launch", f"{keys},none,{FRIENDLY_NAME}"),
    ):
        try:
            subprocess.run(
                [
                    kwriteconfig,
                    "--file",
                    "kglobalshortcutsrc",
                    "--group",
                    DESKTOP_ID,
                    "--key",
                    key,
                    value,
                ],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            return False, f"kwriteconfig6 failed writing kglobalshortcutsrc ({exc})"
    return True, f"registered {keys} in kglobalshortcutsrc via kwriteconfig6"


def _print_manual_fallback(keys: str) -> None:
    print(
        "\nkglobalaccel6 is not on PATH here, so this installer cannot hot-reload the "
        "shortcut, and KDE sometimes only picks up a new one after the next login.\n"
        f"If {keys} does not toggle the widget, bind it by hand:\n"
        "  System Settings > Keyboard > Shortcuts > Add > Command\n"
        f"  Command: {_launcher_path()} toggle\n"
        f"  Shortcut: {keys}"
    )


def install(keys: str = "Meta+C") -> int:
    launcher = _launcher_path()
    if not launcher.exists():
        print(f"launcher not found at {launcher}")
        return 1

    kwin_ok, kwin_msg = write_kwin_rule()
    print(f"KWin rule: {'ok' if kwin_ok else 'FAILED'}, {kwin_msg}")

    desktop_file = write_desktop_file(launcher)
    print(f"wrote {desktop_file}")

    shortcut_ok, shortcut_msg = write_global_shortcut(keys)
    print(f"Global shortcut: {'ok' if shortcut_ok else 'FAILED'}, {shortcut_msg}")

    _print_manual_fallback(keys)

    if kwin_ok and shortcut_ok:
        return 0
    print("\nInstall did not fully apply. See the FAILED line(s) above.")
    return 1
