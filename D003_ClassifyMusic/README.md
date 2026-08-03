# Music File List Generator

`music_file_list_gui.py` is an English PyQt5 interface for the two existing generator scripts. It does not modify `extract_musicfiles.py` or `recurse_musicfiles.py`; it calls their existing functions.

## Run

On Windows, double-click `run_classify_music.bat`. It requires a standard CPython 3.8+
installation with `venv` and `pip`. During installation, select **Add Python to PATH**
and **Python Launcher**. The Microsoft Store `python.exe` app-execution alias is not a
Python installation and cannot create this application's virtual environment.

On Linux, run:

```bash
chmod +x run_classify_music.sh
./run_classify_music.sh
```

On Windows, the virtual environment is stored in `%LOCALAPPDATA%\ClassifyMusic\windows_venv`, so its creation does not require write access to the application folder. On Linux, it is stored under `EnvSetup/linux_venv`. PyQt5 installs automatically the first time it is needed.

## Output

Choose a source folder and an output folder in the window, then select either or both formats. The output folder defaults to the folder containing this application:

- `File names only (extract)` creates `<source-folder>_extract_<YYYY-MM-DD>.txt`.
- `Relative file paths from the selected folder (recurse)` creates `<source-folder>_recurse_<YYYY-MM-DD>.txt`.

The path entries start at the selected source folder, matching the supplied recurse example. Output files are saved in this `ClassifyMusic` directory. Running the same format for the same folder again on the same date replaces that format's previous file, matching the original scripts' daily-output convention.
