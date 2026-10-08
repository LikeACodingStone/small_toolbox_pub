# Android 12 UI proposal

These are design mockups, not an implemented Android application.

## Layout

- Full view: source folder, current track and times, transport, volume, SHOW/HIDE, SEQ/RANDOM, ten genre buttons, latest log, DEL/DEL PRE/RESTORE.
- Compact view: hides genre controls while retaining playback, deletion, restore and the latest log. It does not resize the Android application window.
- Blue actions and pale blue genre buttons carry over the desktop palette. Red indicates the selected playback mode. Delete controls use a pale red treatment.
- All labels and application messages are English.
- The overview illustrates the complete content at a logical width of 412. On shorter phones the middle content scrolls; the bottom delete/restore bar stays above system navigation. Implement touch targets of at least 48 dp, including any visually smaller buttons.
- Time, duration and count remain display labels. The progress line is a non-interactive visual indicator in this proposal. Track title, folder path and latest log are read-only text.
- Long titles tighten letter spacing, then reduce font size within readable limits. Folder paths omit leading components. Full text can be viewed on long press.

## Behaviors to preserve

Genre buttons move the original immediately while the playback stream continues. Pause state is retained. Playback advances only at track end or on explicit navigation. Keep sequential/random playback, random-round persistence, volume steps, previous-track deletion, ten-item LIFO restore, collision-safe file names and folder memory.

## Android implementation constraints to resolve

Use the system folder picker and persist its URI permission. Android 12 scoped storage does not automatically grant access to a selected folder's siblings: for `A/../classify`, request access to the parent folder (containing both `A` and `classify`) or let the user choose a separate classification destination. Keep deletion in an app-managed `tmp_trash` within the granted tree to support restore without a separate system confirmation per track where the document provider permits it. Cross-provider moves may require copy-then-delete.

Use a foreground media playback service with a media notification for background and lock-screen playback. Preserve audio focus and headset behavior. A private playback cache avoids holding the source file while moving it. System permission screens and provider restrictions cannot be removed by UI design.

## Files

- `android12-ui-overview.png`: full and compact screens side by side.
- `android12-full.png`, `android12-compact.png`: high-resolution individual screens.
- `draw_mockups.py`: deterministic Pillow rendering source; no app code.
