"""claude-lights: a traffic light per running Claude Code session."""

# The Wayland app_id the widget sets, and the wmclass the KWin rule matches on.
# These must be the same string: the rule is the only thing giving the widget
# its position, keep-above, focus suppression and taskbar hiding, and a mismatch
# fails silently, leaving an unplaced focus-stealing window with no error.
APP_ID = "claude-lights"
