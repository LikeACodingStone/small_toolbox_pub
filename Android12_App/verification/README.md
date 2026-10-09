# Verification

Environment: Android 12 / API 31 x86_64 emulator, local external-storage document provider, generated Opus audio. No personal music was used.

Build checks:

- `./gradlew --no-daemon assembleDebug lintDebug` succeeds with JDK 17.
- Android lint reports no issues. The expired Play Store target check is explicitly disabled because this build targets Android 12 for sideloading.

Emulator checks completed:

- App installation and startup.
- System folder picker with persistent source and destination access.
- Opus scanning, automatic playback and duration display.
- Classification during playback: file moves, playback position continues without restart.
- Classification while paused: paused state retained.
- DEL PRE refuses to delete an already classified track.
- Current-track deletion and restoration to the original source folder.
- Eleven consecutive deletions retain exactly ten files; all ten restore successfully after force-stopping and restarting the app.
- Relaunch remembers folders and resumes the last available track from the beginning.
- SHOW/HIDE and scrolling genre controls on a 1080 x 1920 device.

Real-device acceptance remains necessary for audible output, SD card/cloud providers, calls, headset disconnection, and manufacturer-specific background restrictions. The emulator was run without host audio output.
