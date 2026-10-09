import platform


def current_platform_label() -> str:
    system = platform.system().lower()
    if "windows" in system:
        return "Windows"
    if "linux" in system:
        return "Ubuntu/Linux"
    return platform.system() or "Unknown"
