# Podcast Tool

Run ./podcast insert-speech, ./podcast subtitle-only, or ./podcast translate-audio.
This package contains compiled application modules only. No Python runtime,
third-party libraries, tools, or models are bundled.

Each config/<Feature>/config.ini selects the external environment through
RuntimeConfig.env_folder, resolved relative to this package root.
The launcher uses env_folder/.venv/bin/python and that environment's libraries,
components and model stores. System python3 is used only to read bootstrap
configuration. A compatible Python version, architecture, and prepared runtime
environment are required. Missing dependencies are not installed automatically.

Place source audio in input/audio or edit configuration. Output defaults to output/.
Append --self-check to verify runtime imports and tools without processing audio.
Moving the application is supported; update env_folder if its relative location
changes. Original application source is not shipped. Compilation does not prevent
reverse engineering. Manage dependencies independently with migration.
