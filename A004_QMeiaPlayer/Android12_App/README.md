# RingPlayer for Android 12

A native Java Android Studio project. Open **this folder (`Android12_App`)** in Android Studio, not the desktop Python project.

## Build and run

1. Open `Android12_App` in Android Studio Ladybug or newer.
2. Use **JDK 17** for Gradle (Settings → Build Tools → Gradle → Gradle JDK).
3. Let Android Studio sync and install **Android SDK Platform 35** and the requested build tools.
4. Select an Android 12 / API 31 or 32 device or emulator and click Run.

The project uses Android Gradle Plugin 8.7.3 and the included Gradle 8.9 wrapper. It intentionally targets API 32 for the requested Android 12 application; this is a local/sideload build, not a current Google Play submission configuration. Minimum supported API is 31 (Android 12). No Python or desktop libraries are used by the app.

Command line (with JDK 17 and `ANDROID_HOME` configured):

```bash
./gradlew assembleDebug lintDebug
```

Windows:

```bat
gradlew.bat assembleDebug lintDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`.

If Android Studio reports `prepareKotlinBuildScriptModel` missing in `:app`,
open the root `Android12_App` folder (the one containing `settings.gradle`),
not its `app` subfolder, then select **Sync Project with Gradle Files**.
The app module forwards this IDE tooling task to the root task for compatibility.
If configuring the SDK manually, put `local.properties` in `Android12_App/`
with `sdk.dir` pointing to your Android SDK installation.

## First launch and folder access

Tap **OPEN → Choose folder** and select your music folder, including any albums below it.
The app loads the music immediately and automatically finds or creates `classify`
beside that folder, in its parent directory. Enable **OPEN → All files access** to allow access to the parent. No second folder selection is required. For example, selecting
`SD card/Music/Unsorted` uses `SD card/Music/classify` for genre folders. The scanner excludes
`classify` and `tmp_trash` so moved tracks are not loaded again. If creating `classify`
fails, music still loads and the app reports the problem; classification retries
creation when used. The sibling destination is recalculated on restart. Existing files in an older
classification folder are left in place; they are not automatically moved.

Android's system folder picker grants persistent access. Android 12 prevents
selecting certain protected folders and storage roots. Use ordinary music subfolders.
To request optional broad storage permission, tap **OPEN → All files access**,
enable **Allow access to manage all files** for RingPlayer, and return to the app.
The app displays the permission status when you return. Folder selection is still
required; this permission does not remove system folder-picker restrictions.

Cancellation leaves the existing library unchanged. If access is revoked, use OPEN again. Prefer local device storage or an SD card: document-provider support for moving, deleting and writing varies. A provider that cannot move natively uses copy-then-delete; a failed source deletion cleans up the new copy and reports an error.

## Behavior

- Auto-scan and prepare paused after selecting a folder; remember folders, current track, mode, volume and the random queue in SQLite.
- **Classify:** move the original immediately, while playback continues from a private disk cache to the end. A paused track stays paused. Already-classified tracks cannot be classified or deleted again from the current session.
- **SEQ / RANDOM:** exclusive red selection; loop sequentially or shuffle each round with no within-round repeats. Avoid the same track across round boundaries when possible. Previous in random mode follows actual navigation history.
- **VOL− / VOL+:** adjust the app's volume by 10 percentage points. Android's hardware volume still controls overall media output.
- **DEL:** move current unclassified track to the source folder's `tmp_trash` without confirmation, then advance.
- **DEL PRE:** delete the last actually played track, without interrupting the current one. Classified or unavailable previous tracks produce a brief message.
- **RESTORE:** restore most recent deletion to its original parent folder, without interrupting playback. Up to ten records per source folder survive restarts. The oldest retained file is permanently removed before admitting an eleventh deletion. Names are numbered on collision. If an original parent folder has been deleted externally, restoration reports an error and keeps the trash record.
- **SHOW / HIDE:** show or collapse the genre section; playback, logs and the bottom action bar remain accessible. Smaller displays scroll the main content.
- Long press the name, folder or log to view its full text. All application messages are English; Android system dialogs follow the device language.
- Playback continues in the background with notification and lock-screen media controls; audio focus pauses or ducks playback, and headphone disconnection pauses it.

Scanning excludes hidden files, `tmp_trash` and `classify`. MP3, WAV, OGG, Opus, FLAC, AAC and M4A playback depends on Android's codecs; WMA commonly has no platform decoder and is skipped. Unplayable files are not deleted. File loading uses a single private cache file, released on track change; disk space for the current track is required. After a process crash, stale playback caches are removed on next service startup.

The track counter refers to the remaining source list. A just-classified track may display `0 / N` while it finishes playing. Scanning and file operations run off the UI thread. Large files or slow/cloud providers can take time; the app displays a loading/busy state.

## Source layout

- `MainActivity.java`: native adaptive layout, folder picker and controls.
- `PlayerService.java`: playback service, media session, history and operations.
- `Documents.java`: Android Storage Access Framework scanning and file operations.
- `Store.java`: SQLite settings and retained-deletion records.
- `Track.java`: persisted track metadata.
- `design/`: approved visual concepts and their rendering script (not needed at runtime).

## Device acceptance checks

Use a disposable music folder for initial testing:

1. Pick the music folder, confirm Opus/MP3 files appear and remain paused until PLAY is tapped.
2. Classify during playback and while paused; verify the file moves and playback position does not reset.
3. Test sequence/random, lock-screen controls, headphone unplug, background playback, and phone-call/audio-focus interruption. Confirm wired, USB, and Bluetooth headphone removal pauses playback, including during track loading. A fresh launch starts paused; returning to the app while its playback service is running preserves the current playing or paused state.
4. Delete current and previous tracks; restore; test same-name collisions and the eleven-deletion boundary.
5. Close and reopen the app; confirm state and retained files survive.
6. Test your SD card/document provider, permission revocation, unavailable files and low-storage behavior.

A successful build does not replace device checks for audio and document-provider behavior.
