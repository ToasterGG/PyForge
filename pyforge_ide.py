#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyForge IDE
===========

A complete, single-file, VS Code-styled desktop IDE written with PyQt6.

Highlights
----------
* Fully dockable / floatable / tabbable panel layout (QDockWidget).
* Project explorer (QFileSystemModel + QTreeView) with full right-click file ops.
* Universal tabbed viewer: code editor with line numbers + highlighting,
  image preview tabs, and a graceful binary-file notice with a raw-text escape hatch.
* Real interactive terminal (PowerShell on Windows, bash elsewhere) driven by QProcess,
  running real scripts through the configured Python interpreter (so input() works).
* Live PyPI library search + package manager (install / uninstall through real pip).
* Optional multi-provider AI assistant (Ollama / OpenAI / Anthropic) with Ask mode and
  Direct-Edit mode, plus one-click "Undo AI Edit".
* v3 "pro" tooling: command palette, auto-completion (+ optional jedi), snippets, code folding,
  live problem checking (+ optional pyflakes), Problems/TODO panels, black/ruff formatting,
  Git source control with gutter change marks and diffs, pytest test explorer, pdb debugging,
  interpreter / virtual-environment management.
* Settings persisted to ``~/.pyforge/config.json``, window layout persisted with QSettings.

Dependencies:  PyQt6, requests
Build:         pyinstaller --onefile --windowed --name PyForgeIDE pyforge_ide.py
"""

from __future__ import annotations

import ast
import builtins
import difflib
import importlib
import json
import keyword
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover - requests is an install requirement, but never hard-crash
    requests = None

from PyQt6.QtCore import (
    QCoreApplication,
    QDir,
    QEvent,
    QModelIndex,
    QPointF,
    QRectF,
    QStringListModel,
    QProcess,
    QProcessEnvironment,
    QRegularExpression,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QPen,
    QPolygonF,
    QTextBlockUserData,
    QFileSystemModel,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QToolButton,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------------------
# Constants & configuration
# --------------------------------------------------------------------------------------

APP_NAME = "PyForge IDE"
APP_VERSION = "3.0.0"
ORG_NAME = "PyForge"

CONFIG_DIR = Path.home() / ".pyforge"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict = {
    "python_path": "",
    "ai_provider": "ollama",
    "api_key": "",
    "model_name": "qwen2.5-coder",
    "ollama_url": "http://localhost:11434/v1",
    "last_project": "",
    "terminal_shell": "",
    "font_size": 11,
    "wrap_lines": False,
    "recent_projects": [],
    "recent_files": [],
    "show_hidden_files": False,
    "run_overrides": {},
    "build_presets": {},
    "last_build_preset": "",
    "live_preview": True,
    "terminal_font_size": 10,
    "show_whitespace": False,
    "scroll_past_end": False,
    "auto_save": False,
    "completion": True,
    "auto_close": True,
    "live_lint": True,
    "format_on_save": False,
    "jedi": True,
}

TEXT_EXTENSIONS = {
    ".py", ".pyw", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss",
    ".json", ".md", ".markdown", ".txt", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".log", ".bat", ".cmd", ".sh", ".ps1", ".sql", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".lua", ".r",
    ".gitignore", ".env", ".dockerfile", ".svg", ".qss", ".gradle", ".vue", ".svelte",
}

SPECIAL_TEXT_NAMES = {
    "dockerfile", "makefile", "license", "readme", "changelog", "requirements.txt",
    "pipfile", "procfile", ".gitignore", ".gitattributes", ".editorconfig", ".env",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff"}

MEDIA_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".mp4", ".webm", ".mkv", ".mov", ".avi"}

# How "Run" behaves for each file type. "" means "just launch it with the OS handler".
RUN_TARGETS = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "node", ".mjs": "node", ".cjs": "node",
    ".html": "browser", ".htm": "browser",
    ".sh": "shell", ".bash": "shell",
    ".ps1": "powershell", ".bat": "cmd", ".cmd": "cmd",
    ".php": "php", ".rb": "ruby", ".pl": "perl", ".lua": "lua",
    ".exe": "native", ".bat": "cmd",
}

# Files that get a live preview / rendered viewer instead of (or beside) an editor.
PREVIEW_KINDS = {".md": "markdown", ".markdown": "markdown", ".html": "web", ".htm": "web"}

LANGUAGE_NAMES = {
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".json": "JSON", ".md": "Markdown", ".markdown": "Markdown", ".txt": "Plain Text",
    ".csv": "CSV", ".tsv": "TSV", ".xml": "XML", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "Config", ".conf": "Config", ".log": "Log",
    ".bat": "Batch", ".cmd": "Batch", ".sh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
}

SHELL_DONE_MARKER = "__PYFORGE_JOB_DONE__"

PROJECT_STATE_FILENAME = ".pyforge_project.json"

# Default panel arrangement, serialised with QMainWindow.saveState():
#   Explorer (left) | editor | Outline + AI Assistant (tabbed, right)
#   Terminal + Packages + Build (tabbed, bottom, full width)
# Restoring a byte blob is the only reliable way to build tabbed dock groups -
# assembling them call-by-call makes Qt allocate duplicate dock tab bars.
DEFAULT_LAYOUT_B64 = (
    "AAAA/wAAAAD9AAAAAwAAAAAAAAE2AAAC6PwCAAAAAfsAAAAaAGQAbwBjAGsAXwBlAHgAcABsAG8AcgBlAHIBAAAA"
    "AAAAAugAAABWAP///wAAAAEAAAF8AAAC6PwCAAAAAfwAAAAAAAAC6AAAAHABAAAZ+gAAAAECAAAAAvsAAAAYAGQA"
    "bwBjAGsAXwBvAHUAdABsAGkAbgBlAQAAAAD/////AAAAVgD////7AAAADgBkAG8AYwBrAF8AYQBpAQAAAAD/////"
    "AAAAVgD///8AAAADAAAGpAAAAQT8AQAAAAH8AAAAAAAABqQAAAB7AP////oAAAAAAQAAAAP7AAAAGgBkAG8AYwBr"
    "AF8AdABlAHIAbQBpAG4AYQBsAQAAAAD/////AAAARgD////7AAAAGgBkAG8AYwBrAF8AcABhAGMAawBhAGcAZQBz"
    "AQAAAAD/////AAAARgD////7AAAAFABkAG8AYwBrAF8AYgB1AGkAbABkAQAAAAD/////AAAARgD///8AAAPmAAAC"
    "6AAAAAEAAAACAAAACAAAAAj8AAAAAA=="
)

MAX_TEXT_BYTES = 12 * 1024 * 1024  # 12 MB safety limit for the text editor

PYPI_INDEX_URL = "https://pypi.org/simple/"
PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"
USER_AGENT = "PyForgeIDE/" + APP_VERSION

# --------------------------------------------------------------------------------------
# Theme (VS Code "Dark Modern" inspired)
# --------------------------------------------------------------------------------------

COLOR = {
    "bg": "#1e1e1e",
    "bg_alt": "#252526",
    "bg_deep": "#181818",
    "panel": "#1f1f1f",
    "border": "#2b2b2b",
    "border_light": "#3c3c3c",
    "text": "#cccccc",
    "text_dim": "#8b8b8b",
    "accent": "#007acc",
    "accent_hover": "#1b8ad4",
    "hover": "#2a2d2e",
    "selection": "#264f78",
    "green": "#4ec9b0",
    "red": "#f14c4c",
    "yellow": "#dcdcaa",
}

THEME_QSS = """
* { outline: none; }

QWidget {
    background-color: #1e1e1e;
    color: #cccccc;
    font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
}

QMainWindow, QDialog { background-color: #1e1e1e; }

QToolTip {
    background-color: #252526;
    color: #cccccc;
    border: 1px solid #454545;
    padding: 4px 6px;
}

/* ---------------- menus ---------------- */
QMenuBar {
    background-color: #181818;
    border-bottom: 1px solid #2b2b2b;
    padding: 2px;
}
QMenuBar::item { padding: 5px 10px; background: transparent; border-radius: 3px; }
QMenuBar::item:selected { background-color: #2a2d2e; }
QMenu {
    background-color: #252526;
    border: 1px solid #454545;
    padding: 4px;
}
QMenu::item { padding: 6px 28px 6px 26px; border-radius: 3px; }
QMenu::item:selected { background-color: #094771; color: #ffffff; }
QMenu::item:disabled { color: #656565; }
QMenu::separator { height: 1px; background: #454545; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 6px; }

/* ---------------- docks ---------------- */
QDockWidget {
    color: #cccccc;
}
QDockWidget::title {
    background-color: #252526;
    padding: 6px 8px;
    border-bottom: 1px solid #2b2b2b;
    text-align: left;
    font-weight: 600;
}
QDockWidget > QWidget { background-color: #1e1e1e; }

QMainWindow::separator {
    background-color: #2b2b2b;
    width: 3px;
    height: 3px;
}
QMainWindow::separator:hover { background-color: #007acc; }

/* ---------------- tabs ---------------- */
QTabWidget::pane { border: none; background-color: #1e1e1e; }
QTabBar { background-color: #181818; qproperty-drawBase: 0; }
QTabBar::tab {
    background-color: #181818;
    color: #9d9d9d;
    padding: 7px 12px;
    border-right: 1px solid #252526;
    min-width: 60px;
}
QTabBar::tab:selected { background-color: #1e1e1e; color: #ffffff; border-top: 1px solid #007acc; }
QTabBar::tab:hover:!selected { background-color: #1f1f1f; color: #d4d4d4; }

/* ---------------- inputs ---------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox {
    background-color: #2a2a2a;
    color: #cccccc;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #007acc; }
QLineEdit:disabled, QComboBox:disabled { color: #6b6b6b; background-color: #252526; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #252526;
    border: 1px solid #454545;
    selection-background-color: #094771;
    outline: 0;
}

/* ---------------- buttons ---------------- */
QPushButton {
    background-color: #3a3d41;
    color: #e0e0e0;
    border: 1px solid #4a4d51;
    border-radius: 3px;
    padding: 5px 12px;
    min-height: 18px;
}
QPushButton:hover { background-color: #45494e; border-color: #5a5d61; }
QPushButton:pressed { background-color: #2f3236; }
QPushButton:disabled { background-color: #2b2b2b; color: #6b6b6b; border-color: #333333; }
QPushButton#primary {
    background-color: #0e639c;
    border: 1px solid #1177bb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primary:hover { background-color: #1177bb; }
QPushButton#primary:disabled { background-color: #2b3a45; border-color: #2b3a45; color: #7f8c93; }

QToolButton {
    background-color: transparent;
    border: none;
    border-radius: 3px;
    padding: 3px;
    color: #cccccc;
}
QToolButton:hover { background-color: #3a3d41; }
QToolButton:pressed { background-color: #094771; }

/* ---------------- trees / tables ---------------- */
QTreeView, QListWidget, QTableWidget {
    background-color: #252526;
    alternate-background-color: #232324;
    border: none;
    color: #cccccc;
    selection-background-color: #094771;
    selection-color: #ffffff;
}
QTreeView::item, QListWidget::item { padding: 3px 2px; border: none; }
QTreeView::item:hover, QListWidget::item:hover { background-color: #2a2d2e; }
QTreeView::item:selected, QListWidget::item:selected { background-color: #094771; }
QHeaderView::section {
    background-color: #252526;
    color: #9d9d9d;
    border: none;
    border-bottom: 1px solid #3c3c3c;
    padding: 5px 6px;
}
QTableWidget { gridline-color: #2b2b2b; }
QTableWidget::item { padding: 3px; }

/* ---------------- scrollbars ---------------- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar::handle:vertical {
    background: #424242; min-height: 24px; border-radius: 6px; margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #4f4f4f; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:horizontal {
    background: #424242; min-width: 24px; border-radius: 6px; margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #4f4f4f; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---------------- misc ---------------- */
QStatusBar { background-color: #181818; border-top: 1px solid #2b2b2b; color: #9d9d9d; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #9d9d9d; padding: 0 6px; }
QSplitter::handle { background-color: #2b2b2b; }
QSplitter::handle:hover { background-color: #007acc; }
QGroupBox {
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #cccccc; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #6b6b6b;
    border-radius: 2px;
    background: #2a2a2a;
}
QCheckBox::indicator:checked { background: #007acc; border-color: #007acc; }
QLabel#hint { color: #8b8b8b; }
QLabel#sectionTitle {
    color: #8b8b8b;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QFrame#card { background-color: #252526; border: 1px solid #2b2b2b; border-radius: 4px; }
QProgressBar {
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    background: #252526;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk { background-color: #007acc; }
"""

# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def human_size(num_bytes: int) -> str:
    """Return a human readable byte size."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def is_windows() -> bool:
    return platform.system() == "Windows"


def monospace_family() -> str:
    """Pick the nicest available monospace font."""
    candidates = [
        "Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono", "Fira Code",
        "Source Code Pro", "Hack", "Menlo", "Monaco", "DejaVu Sans Mono",
        "Liberation Mono", "Ubuntu Mono", "Courier New", "monospace",
    ]
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def monospace_font(size: int = 11, bold: bool = False) -> QFont:
    font = QFont(monospace_family(), size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setBold(bold)
    return font


def ui_font(size: int = 9, bold: bool = False) -> QFont:
    font = QApplication.font()
    font.setPointSize(size)
    font.setBold(bold)
    return font


def detect_python_interpreter() -> str:
    """Best-effort discovery of a usable system Python interpreter."""
    candidates = []
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    if is_windows():
        for name in ("python.exe", "python3.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        # The Python launcher knows about every installed CPython.
        try:
            proc = subprocess.run(
                ["py", "-c", "import sys; print(sys.executable)"],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                candidates.insert(0, proc.stdout.strip())
        except Exception:
            pass
    else:
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return "python" if is_windows() else "python3"


def default_shell() -> str:
    """Return the platform shell that the embedded terminal should drive."""
    if is_windows():
        for shell in ("powershell.exe", "pwsh.exe", "cmd.exe"):
            found = shutil.which(shell)
            if found:
                return found
        return "cmd.exe"
    env_shell = os.environ.get("SHELL", "")
    if env_shell and Path(env_shell).exists():
        return env_shell
    for shell in ("/bin/bash", "/usr/bin/bash", "/bin/zsh", "/bin/sh"):
        if Path(shell).exists():
            return shell
    return "/bin/sh"


POWERSHELL_NAMES = {"powershell.exe", "pwsh.exe", "powershell", "pwsh"}
CMD_NAMES = {"cmd.exe", "cmd"}


def shell_executable_name(shell_path: str | None) -> str:
    """Basename of a shell path, tolerant of both separators on any OS."""
    raw = str(shell_path or "")
    return re.split(r"[\\/]", raw)[-1].strip().lower()


def shell_kind(shell_path: str | None = None) -> str:
    """Classify a shell executable as 'powershell', 'cmd' or 'posix'."""
    name = shell_executable_name(shell_path or default_shell())
    if name in POWERSHELL_NAMES:
        return "powershell"
    if name in CMD_NAMES:
        return "cmd"
    return "posix"


def is_powershell(shell_path: str | None = None) -> bool:
    return shell_kind(shell_path) == "powershell"


def shell_quote(text: str, shell_path: str | None = None) -> str:
    """Quote a single argument for the shell that will receive the command."""
    value = str(text)
    if is_windows():
        if shell_kind(shell_path) == "powershell":
            # Inside PowerShell double quotes, backtick escapes the quote char.
            value = value.replace("`", "``").replace('"', '`"')
        else:
            value = value.replace('"', '""')
        return '"' + value + '"'
    return "'" + value.replace("'", "'\\''") + "'"


def command_prefix(shell_path: str | None = None) -> str:
    r"""Return the call operator needed when a command starts with a quoted path.

    PowerShell: a command may not begin with a quoted string, so the call operator
    ``&`` is required — ``& "C:\Python\python.exe" "script.py"``. Without it
    PowerShell raises ``UnexpectedToken``. POSIX shells and cmd.exe use no prefix
    (in cmd.exe a leading ``&`` is itself a syntax error).
    """
    return "& " if is_powershell(shell_path) else ""


def build_command(executable: str, arguments: str = "",
                  shell_path: str | None = None) -> str:
    """Compose a runnable command line for the target shell.

    The executable is always quoted (interpreter paths routinely contain spaces),
    which is exactly the case that needs the ``&`` call operator on PowerShell.
    """
    parts = [command_prefix(shell_path) + shell_quote(executable, shell_path)]
    if arguments:
        parts.append(arguments)
    return " ".join(parts)


def looks_like_text(path: Path, sample_size: int = 8192) -> bool:
    """Heuristic binary detection: NUL bytes or a failed UTF-8 decode means binary."""
    try:
        with path.open("rb") as handle:
            chunk = handle.read(sample_size)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A decode error in the *middle* of a multi-byte sequence at the sample
        # boundary is fine; anything earlier means this is probably binary.
        if exc.start < max(0, len(chunk) - 8):
            return False
    return True


def read_text_file(path: Path) -> tuple[str, str]:
    """Read a text file with a few sensible encodings. Returns (text, encoding)."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding if encoding != "utf-8-sig" else "utf-8"
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacements)"


SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", ".tox",
    ".next", ".nuxt", "target", "coverage", ".gradle", ".cache",
}


def iter_project_files(root: Path, limit: int = 20000):
    """Yield file paths under `root`, pruning dependency/build folders."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") and name not in (".gitignore", ".env"):
                continue
            yield Path(dirpath) / name
            count += 1
            if count >= limit:
                return


def remember(entries: list, value: str, limit: int = 12) -> list:
    """Insert `value` at the front of a most-recently-used list, de-duplicated."""
    value = str(value)
    cleaned = [entry for entry in entries if entry and entry != value]
    cleaned.insert(0, value)
    return cleaned[:limit]


def safe_resolve(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except Exception:
        return Path(path)


def language_for_path(path: Path | str | None) -> str:
    if not path:
        return "Plain Text"
    p = Path(path)
    name = p.name.lower()
    if name in SPECIAL_TEXT_NAMES:
        return "Plain Text"
    return LANGUAGE_NAMES.get(p.suffix.lower(), "Plain Text")


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_probably_text_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return False
    if suffix in TEXT_EXTENSIONS:
        return True
    return path.name.lower() in SPECIAL_TEXT_NAMES


class AppConfig:
    """JSON-backed application settings stored in the user's home directory."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data = dict(DEFAULT_CONFIG)
        self.load()

    # ------------------------------------------------------------------ load / save
    def load(self) -> None:
        with self._lock:
            try:
                if CONFIG_FILE.exists():
                    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for key, value in raw.items():
                            self._data[key] = value
            except Exception:
                # A corrupt config must never stop the IDE from starting.
                pass
            if not self._data.get("python_path"):
                self._data["python_path"] = detect_python_interpreter()
            if not self._data.get("terminal_shell"):
                self._data["terminal_shell"] = default_shell()

    def save(self) -> bool:
        with self._lock:
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(
                    json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8"
                )
                return True
            except Exception:
                return False

    # ------------------------------------------------------------------ access
    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value

    def update(self, values: dict) -> None:
        with self._lock:
            self._data.update(values)

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._data)


# --------------------------------------------------------------------------------------
# Syntax highlighting
# --------------------------------------------------------------------------------------


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


class PythonHighlighter(QSyntaxHighlighter):
    """VS Code flavoured Python highlighting."""

    KEYWORDS = [
        "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class",
        "continue", "def", "del", "elif", "else", "except", "finally", "for", "from",
        "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass",
        "raise", "return", "try", "while", "with", "yield", "match", "case",
    ]
    BUILTINS = [
        "abs", "all", "any", "bool", "bytes", "callable", "chr", "classmethod", "dict",
        "dir", "divmod", "enumerate", "eval", "exec", "filter", "float", "format",
        "frozenset", "getattr", "globals", "hasattr", "hash", "help", "hex", "id", "input",
        "int", "isinstance", "issubclass", "iter", "len", "list", "locals", "map", "max",
        "min", "next", "object", "oct", "open", "ord", "print", "property", "range", "repr",
        "reversed", "round", "set", "setattr", "slice", "sorted", "staticmethod", "str",
        "sum", "super", "tuple", "type", "vars", "zip", "self", "cls", "__init__", "len",
    ]

    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._build_rules()
        self.tri_single = (QRegularExpression(r"'''"), 1, _fmt("#6a9955", italic=True))
        self.tri_double = (QRegularExpression(r'"""'), 2, _fmt("#6a9955", italic=True))

    def _build_rules(self) -> None:
        kw = _fmt("#569cd6", bold=True)
        builtin = _fmt("#4ec9b0")
        string = _fmt("#ce9178")
        number = _fmt("#b5cea8")
        comment = _fmt("#6a9955", italic=True)
        func = _fmt("#dcdcaa")
        decorator = _fmt("#c586c0")
        constant = _fmt("#4fc1ff")

        self.rules.append((QRegularExpression(r"\b(" + "|".join(self.KEYWORDS) + r")\b"), kw))
        self.rules.append((QRegularExpression(r"\b(" + "|".join(self.BUILTINS) + r")\b"), builtin))
        self.rules.append((QRegularExpression(r"\b[A-Z][A-Za-z0-9_]+\b"), constant))
        self.rules.append((QRegularExpression(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)"), func))
        self.rules.append((QRegularExpression(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"), func))
        self.rules.append((QRegularExpression(r"\b[0-9]+\.?[0-9]*([eE][-+]?[0-9]+)?\b"), number))
        self.rules.append((QRegularExpression(r"\b0[xX][0-9a-fA-F]+\b"), number))
        self.rules.append((QRegularExpression(r"'[^'\\\n]*(\\.[^'\\\n]*)*'"), string))
        self.rules.append((QRegularExpression(r'"[^"\\\n]*(\\.[^"\\\n]*)*"'), string))
        self.rules.append((QRegularExpression(r"@[A-Za-z_][A-Za-z0-9_.]*"), decorator))
        self.rules.append((QRegularExpression(r"#[^\n]*"), comment))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt naming)
        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                group = 1 if match.lastCapturedIndex() >= 1 else 0
                self.setFormat(match.capturedStart(group), match.capturedLength(group), fmt)

        self._highlight_multiline(text, self.tri_single[0], self.tri_single[1],
                                  _fmt("#6a9955", italic=True))
        self._highlight_multiline(text, self.tri_double[0], self.tri_double[1],
                                  _fmt("#6a9955", italic=True))

    def _highlight_multiline(self, text, delimiter, state, fmt) -> None:
        start = 0
        if self.previousBlockState() == state:
            start = -1
        while start >= 0:
            match = delimiter.match(text, start)
            if not match.hasMatch():
                break
            begin = match.capturedStart()
            end_match = delimiter.match(text, begin + match.capturedLength())
            if end_match.hasMatch():
                length = end_match.capturedEnd() - begin
                self.setFormat(begin, length, fmt)
                start = end_match.capturedEnd()
            else:
                self.setFormat(begin, len(text) - begin, fmt)
                self.setCurrentBlockState(state)
                return


class GenericHighlighter(QSyntaxHighlighter):
    """Clean general-purpose highlighting: strings, numbers, comments, brackets, keys."""

    def __init__(self, document, language: str = "Plain Text") -> None:
        super().__init__(document)
        self.language = language
        lower = language.lower()
        self.string = _fmt("#ce9178")
        self.number = _fmt("#b5cea8")
        self.bracket = _fmt("#ffd700")
        self.key = _fmt("#9cdcfe")
        self.tag = _fmt("#569cd6")
        self.escape = _fmt("#d7ba7d")
        self.hash_comments = lower not in ("markdown", "toml", "yaml", "ini", "config")
        self.is_markdown = lower == "markdown"
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._build_rules()
        self.comment_start = (QRegularExpression(r"/\*"), 1, _fmt("#6a9955", italic=True))
        self.comment_end = QRegularExpression(r"\*/")

    def _build_rules(self) -> None:
        comment = _fmt("#6a9955", italic=True)
        if self.is_markdown:
            self.rules.append((QRegularExpression(r"^#{1,6}\s.*$"), _fmt("#569cd6", bold=True)))
            self.rules.append((QRegularExpression(r"`[^`\n]+`"), _fmt("#ce9178")))
            self.rules.append((QRegularExpression(r"\*\*[^*\n]+\*\*"), _fmt("#dcdcaa", bold=True)))
            self.rules.append((QRegularExpression(r"^\s*[-*+]\s"), _fmt("#4ec9b0")))
        self.rules.append((QRegularExpression(r"\b(0[xX][0-9a-fA-F]+|[0-9]+\.?[0-9]*)\b"), self.number))
        self.rules.append((QRegularExpression(r'"[^"\n]*"'), self.string))
        self.rules.append((QRegularExpression(r"'[^'\n]*'"), self.string))
        self.rules.append((QRegularExpression(r"[()\[\]{}]"), self.bracket))
        if self.hash_comments:
            self.rules.append((QRegularExpression(r"#[^\n]*"), comment))
        self.rules.append((QRegularExpression(r"//[^\n]*"), comment))
        if self.language.lower() in ("json", "yaml", "toml", "ini", "config"):
            self.rules.append((QRegularExpression(r'"[A-Za-z0-9_\-.]*"\s*:'), self.key))
            self.rules.append((QRegularExpression(r"^[A-Za-z0-9_.\-]+(?=\s*[:=])"), self.key))
        if self.language.lower() in ("html", "xml"):
            self.rules.append((QRegularExpression(r"</?[A-Za-z][A-Za-z0-9\-]*"), self.tag))
            self.rules.append((QRegularExpression(r"[A-Za-z\-]+(?==)"), self.key))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self.rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        # Multi-line /* ... */ comments.
        start = 0
        if self.previousBlockState() == 1:
            start = -1
        while start >= 0:
            begin_match = self.comment_start[0].match(text, start)
            if not begin_match.hasMatch():
                break
            begin = begin_match.capturedStart()
            end_match = self.comment_end.match(text, begin + 2)
            length = (end_match.capturedEnd() - begin) if end_match.hasMatch() else (len(text) - begin)
            self.setFormat(begin, length, _fmt("#6a9955", italic=True))
            if not end_match.hasMatch():
                self.setCurrentBlockState(1)
                return
            start = end_match.capturedEnd()


# --------------------------------------------------------------------------------------
# Code intelligence: diagnostics, snippets, completion data, formatting
# --------------------------------------------------------------------------------------


@dataclass
class Diagnostic:
    """One problem found in a file (line/col are zero-based)."""

    line: int
    col: int
    end_col: int
    severity: str          # "error" | "warning" | "info"
    message: str
    source: str = "pyforge"
    code: str = ""


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_COLOR = {"error": "#f14c4c", "warning": "#cca700", "info": "#3794ff"}
SEVERITY_ICON = {"error": "✖", "warning": "▲", "info": "●"}

PYTHON_SUFFIXES = (".py", ".pyw", ".pyi")

PY_KEYWORDS = sorted(set(keyword.kwlist) | {"match", "case", "self", "cls", "print"})
PY_BUILTINS = sorted(n for n in dir(builtins) if not n.startswith("_"))

# Standard-library modules that are safe to import purely to list their attributes.
SAFE_STDLIB = {
    "math", "random", "time", "datetime", "itertools", "functools", "collections", "string",
    "statistics", "textwrap", "shutil", "pathlib", "json", "re", "os", "sys", "subprocess",
    "threading", "typing", "dataclasses", "enum", "hashlib", "base64", "csv", "copy", "heapq",
    "bisect", "operator", "decimal", "fractions", "uuid", "logging", "argparse", "tempfile",
    "glob", "io", "struct", "pprint", "inspect", "contextlib", "zipfile", "tarfile", "sqlite3",
    "socket", "secrets", "platform", "traceback", "unittest", "asyncio", "queue", "abc",
}

BUILTIN_SNIPPETS = {
    "def": "def ${1:name}(${2:args}):\n    ${3:pass}$0",
    "class": "class ${1:Name}:\n    def __init__(self${2}):\n        ${3:pass}$0",
    "init": "def __init__(self${1}):\n    ${2:pass}$0",
    "ifmain": "if __name__ == \"__main__\":\n    ${1:main()}$0",
    "main": "def main() -> None:\n    ${1:pass}\n\n\nif __name__ == \"__main__\":\n    main()$0",
    "if": "if ${1:condition}:\n    ${2:pass}$0",
    "ife": "if ${1:condition}:\n    ${2:pass}\nelse:\n    ${3:pass}$0",
    "elif": "elif ${1:condition}:\n    ${2:pass}$0",
    "for": "for ${1:item} in ${2:items}:\n    ${3:pass}$0",
    "fori": "for ${1:i} in range(${2:n}):\n    ${3:pass}$0",
    "fore": "for ${1:i}, ${2:item} in enumerate(${3:items}):\n    ${4:pass}$0",
    "while": "while ${1:condition}:\n    ${2:pass}$0",
    "try": "try:\n    ${1:pass}\nexcept ${2:Exception} as ${3:exc}:\n    ${4:raise}$0",
    "tryf": "try:\n    ${1:pass}\nexcept ${2:Exception} as ${3:exc}:\n    ${4:raise}\nfinally:\n    ${5:pass}$0",
    "with": "with ${1:open(path)} as ${2:f}:\n    ${3:pass}$0",
    "wopen": "with open(${1:path}, \"${2:r}\", encoding=\"utf-8\") as ${3:f}:\n    ${4:data = f.read()}$0",
    "dc": "@dataclass\nclass ${1:Name}:\n    ${2:field}: ${3:int}$0",
    "prop": "@property\ndef ${1:name}(self):\n    ${2:return None}$0",
    "log": "logger = logging.getLogger(__name__)$0",
    "argp": ("parser = argparse.ArgumentParser(description=\"${1:description}\")\n"
             "parser.add_argument(\"${2:name}\", help=\"${3:help}\")\n"
             "args = parser.parse_args()$0"),
    "test": "def test_${1:name}():\n    ${2:assert True}$0",
    "lam": "lambda ${1:x}: ${2:x}$0",
}

_USER_SNIPPETS_CACHE: dict = {"mtime": None, "data": {}}
SNIPPET_FILE = CONFIG_DIR / "snippets.json"


def get_snippets(python_mode: bool) -> dict:
    """Built-in Python snippets merged with the user's ~/.pyforge/snippets.json."""
    try:
        mtime = SNIPPET_FILE.stat().st_mtime if SNIPPET_FILE.exists() else None
    except OSError:
        mtime = None
    if mtime != _USER_SNIPPETS_CACHE["mtime"]:
        data = {}
        if mtime is not None:
            try:
                raw = json.loads(SNIPPET_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {str(k): str(v) for k, v in raw.items()}
            except Exception:
                data = {}
        _USER_SNIPPETS_CACHE.update(mtime=mtime, data=data)
    merged = dict(BUILTIN_SNIPPETS) if python_mode else {}
    merged.update(_USER_SNIPPETS_CACHE["data"])
    return merged


_SNIPPET_TOKEN = re.compile(r"\$\{(\d+):([^}]*)\}|\$\{(\d+)\}|\$(\d+)")


def parse_snippet(template: str, indent: str) -> tuple[str, list[tuple[int, int]]]:
    """Expand ``${1:default}`` / ``$0`` markers; return (text, ordered [(start, end)] stops)."""
    template = template.replace("\n", "\n" + indent)
    out: list[str] = []
    found: dict[int, tuple[int, int]] = {}
    length = 0
    last = 0
    for match in _SNIPPET_TOKEN.finditer(template):
        chunk = template[last:match.start()]
        out.append(chunk)
        length += len(chunk)
        if match.group(1) is not None:
            index, default = int(match.group(1)), match.group(2)
        else:
            index, default = int(match.group(3) or match.group(4)), ""
        out.append(default)
        found.setdefault(index, (length, length + len(default)))
        length += len(default)
        last = match.end()
    tail = template[last:]
    out.append(tail)
    length += len(tail)
    found.setdefault(0, (length, length))
    order = sorted((i for i in found if i != 0)) + [0]
    return "".join(out), [found[i] for i in order]


_GENERIC_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _name_of(node) -> str:
    return getattr(node, "id", "") or getattr(node, "attr", "")


class _LintVisitor(ast.NodeVisitor):
    """Small, conservative AST linter used when pyflakes is not available."""

    def __init__(self, is_init: bool) -> None:
        self.is_init = is_init
        self.imports: list[tuple[str, str, ast.AST]] = []
        self.used: set[str] = set()
        self.exported: set[str] = set()
        self.diags: list[Diagnostic] = []
        self.guard = 0

    # imports -------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        if not self.guard:
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                self.imports.append((bound, alias.name, node))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.guard or node.module == "__future__":
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self.imports.append((bound, f"{'.' * node.level}{node.module or ''}.{alias.name}".strip("."), node))

    def _guarded(self, node) -> None:
        self.guard += 1
        self.generic_visit(node)
        self.guard -= 1

    visit_Try = _guarded
    visit_TryStar = _guarded

    def visit_If(self, node: ast.If) -> None:
        if "TYPE_CHECKING" in ast.dump(node.test):
            self._guarded(node)
        else:
            self.generic_visit(node)

    # usage ---------------------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Store):
            self.used.add(node.id)

    def visit_Constant(self, node: ast.Constant) -> None:
        # String annotations / forward references: count their identifiers as used.
        value = node.value
        if isinstance(value, str) and len(value) < 160 and re.fullmatch(r"[\w\.\[\], |\"']+", value):
            self.used.update(re.findall(r"\w+", value))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            self.exported.add(element.value)
        self.generic_visit(node)

    # style checks --------------------------------------------------------------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.diags.append(Diagnostic(
                node.lineno - 1, node.col_offset, node.col_offset + 6, "warning",
                "Bare 'except:' also catches KeyboardInterrupt and SystemExit — "
                "catch 'Exception' instead.", "pyforge", "bare-except"))
        self.generic_visit(node)

    def _check_defaults(self, node) -> None:
        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
        for default in defaults:
            mutable = isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call) and _name_of(default.func) in ("list", "dict", "set"))
            if mutable:
                self.diags.append(Diagnostic(
                    default.lineno - 1, default.col_offset,
                    getattr(default, "end_col_offset", default.col_offset + 1)
                    if getattr(default, "end_lineno", default.lineno) == default.lineno
                    else default.col_offset + 1,
                    "warning", "Mutable default argument is shared between calls — "
                    "use None and create it inside the function.", "pyforge", "mutable-default"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_defaults(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant) \
                    and comparator.value is None:
                self.diags.append(Diagnostic(
                    node.lineno - 1, node.col_offset, node.col_offset + 2, "info",
                    "Comparison to None should use 'is' / 'is not'.", "pyforge", "none-comparison"))
        self.generic_visit(node)

    def finish(self) -> list[Diagnostic]:
        if not self.is_init:
            for bound, full, node in self.imports:
                if bound in self.used or bound in self.exported:
                    continue
                end = getattr(node, "end_col_offset", None)
                single = getattr(node, "end_lineno", node.lineno) == node.lineno
                self.diags.append(Diagnostic(
                    node.lineno - 1, node.col_offset,
                    end if (single and end) else node.col_offset + 6,
                    "warning", f"'{full}' imported but unused", "pyforge", "unused-import"))
        return self.diags


def analyze_python(text: str, path=None, collect_warnings: bool = True) -> list[Diagnostic]:
    """Syntax errors, compiler warnings and a few safe lint checks for a Python source."""
    diagnostics: list[Diagnostic] = []
    filename = str(path) if path else "<editor>"
    caught = []
    try:
        if collect_warnings:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                tree = ast.parse(text, filename=filename)
        else:
            tree = ast.parse(text, filename=filename)
    except SyntaxError as exc:
        line = max(0, (exc.lineno or 1) - 1)
        col = max(0, (exc.offset or 1) - 1)
        end = (getattr(exc, "end_offset", None) or 0) - 1
        if getattr(exc, "end_lineno", None) not in (None, exc.lineno):
            end = -1
        diagnostics.append(Diagnostic(line, col, end if end > col else -1, "error",
                                      f"{exc.msg}", "python", "syntax-error"))
        return diagnostics
    except (ValueError, MemoryError, RecursionError) as exc:
        diagnostics.append(Diagnostic(0, 0, -1, "error", str(exc), "python", "parse-error"))
        return diagnostics
    for item in caught:
        if getattr(item, "lineno", None) and issubclass(item.category, (SyntaxWarning, DeprecationWarning)):
            diagnostics.append(Diagnostic(item.lineno - 1, 0, -1, "warning",
                                          str(item.message), "python", "compiler-warning"))
    is_init = bool(path) and Path(str(path)).name == "__init__.py"
    visitor = _LintVisitor(is_init)
    try:
        visitor.visit(tree)
        diagnostics.extend(visitor.finish())
    except RecursionError:
        pass
    diagnostics.sort(key=lambda d: (d.line, d.col))
    return diagnostics


def analyze_json(text: str) -> list[Diagnostic]:
    if not text.strip():
        return []
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return [Diagnostic(max(0, exc.lineno - 1), max(0, exc.colno - 1), -1, "error",
                           exc.msg, "json", "json-error")]
    except Exception:
        return []
    return []


_FLAKES_LINE = re.compile(r"^[^:]*:(\d+):(?:(\d+):?)?\s+(.*)$")


def parse_pyflakes_output(output: str) -> list[Diagnostic]:
    diagnostics = []
    for raw in output.splitlines():
        match = _FLAKES_LINE.match(raw.strip())
        if not match:
            continue
        line = max(0, int(match.group(1)) - 1)
        col = max(0, int(match.group(2) or 1) - 1)
        message = match.group(3).strip()
        severity = "error" if re.search(r"undefined name|syntax|invalid|unexpected", message, re.I) \
            else "warning"
        code = "unused-import" if "imported but unused" in message else (
            "undefined-name" if "undefined name" in message else "pyflakes")
        diagnostics.append(Diagnostic(line, col, -1, severity, message, "pyflakes", code))
    return diagnostics


def run_hidden(args: list[str], input_text: str | None = None, cwd: str | None = None,
               timeout: float = 20.0, env: dict | None = None) -> tuple[int, str, str]:
    """subprocess.run without flashing a console window; never raises."""
    try:
        full_env = None
        if env:
            full_env = dict(os.environ)
            full_env.update(env)
        proc = subprocess.run(
            args, input=input_text, capture_output=True, text=True, timeout=timeout,
            cwd=cwd, encoding="utf-8", errors="replace", env=full_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except Exception as exc:  # missing executable, permission problems, ...
        return 127, "", str(exc)


def basic_cleanup(text: str) -> str:
    """Interpreter-free formatting: trim trailing space, tabs→4 spaces in indents, tidy blanks."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.rstrip()
        lead = len(stripped) - len(stripped.lstrip(" \t"))
        if "\t" in stripped[:lead]:
            stripped = stripped[:lead].replace("\t", "    ") + stripped[lead:]
        lines.append(stripped)
    cleaned: list[str] = []
    blanks = 0
    for line in lines:
        blanks = blanks + 1 if not line else 0
        if blanks <= 2:
            cleaned.append(line)
    return "\n".join(cleaned).rstrip("\n") + "\n"


def format_python_source(text: str, interpreter: str, cwd: str | None = None) -> tuple[str | None, str]:
    """Format with black (or ruff) from the configured interpreter.

    Returns (new_text, message). new_text is None when nothing could be done.
    """
    if interpreter:
        rc, out, err = run_hidden([interpreter, "-m", "black", "-q", "-"], text, cwd, timeout=25)
        if rc == 0:
            return out, "Formatted with black."
        if rc == 123 or "error:" in err.lower() or "cannot parse" in err.lower():
            first = (err.strip().splitlines() or ["black could not format this file."])[0]
            return None, first
        rc, out, err = run_hidden([interpreter, "-m", "ruff", "format", "--stdin-filename", "x.py", "-"],
                                  text, cwd, timeout=25)
        if rc == 0 and out:
            return out, "Formatted with ruff."
    return basic_cleanup(text), ("Applied basic cleanup — install 'black' in the selected "
                                 "interpreter for full formatting.")


def apply_text_minimally(editor: "QPlainTextEdit", new_text: str) -> None:
    """Replace the document text with line-level edits so undo, cursor and scroll survive."""
    old_text = editor.toPlainText()
    if old_text == new_text:
        return
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    document = editor.document()
    scroll = editor.verticalScrollBar().value()
    cursor = editor.textCursor()
    line, column = cursor.blockNumber(), cursor.positionInBlock()
    edit = QTextCursor(document)
    edit.beginEditBlock()
    for tag, i1, i2, j1, j2 in reversed(matcher.get_opcodes()):
        if tag == "equal":
            continue
        replacement = "\n".join(new_lines[j1:j2])
        if i1 == i2:                                   # pure insertion before old line i1
            if i1 < len(old_lines):
                block = document.findBlockByNumber(i1)
                edit.setPosition(block.position())
                edit.insertText(replacement + "\n")
            else:
                block = document.findBlockByNumber(len(old_lines) - 1)
                edit.setPosition(block.position() + block.length() - 1)
                edit.insertText("\n" + replacement)
            continue
        first = document.findBlockByNumber(i1)
        last = document.findBlockByNumber(i2 - 1)
        edit.setPosition(first.position())
        edit.setPosition(last.position() + last.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        if j1 == j2:                                   # pure deletion: also swallow a newline
            if last.next().isValid():
                edit.setPosition(last.position() + last.length(), QTextCursor.MoveMode.KeepAnchor)
            elif first.previous().isValid():
                edit.setPosition(first.position() - 1)
                edit.setPosition(last.position() + last.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            edit.removeSelectedText()
        else:
            edit.insertText(replacement)
    edit.endEditBlock()
    target = document.findBlockByNumber(min(line, document.blockCount() - 1))
    restore = QTextCursor(target)
    restore.setPosition(target.position() + min(column, max(0, target.length() - 1)))
    editor.setTextCursor(restore)
    editor.verticalScrollBar().setValue(scroll)


def find_symbols(text: str, suffix: str = ".py") -> list[tuple[str, str, int]]:
    """Cheap symbol scan for Go-to-Symbol: [(kind, qualified name, zero-based line)]."""
    symbols: list[tuple[str, str, int]] = []
    if suffix in PYTHON_SUFFIXES or not suffix:
        scope: list[tuple[int, str]] = []
        pattern = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_]\w*)")
        for number, line in enumerate(text.splitlines()):
            match = pattern.match(line)
            if not match:
                continue
            indent = len(match.group(1).expandtabs(4))
            while scope and scope[-1][0] >= indent:
                scope.pop()
            kind = "class" if match.group(2) == "class" else (
                "method" if scope and scope[-1][1][:1].isupper() else "function")
            qualified = ".".join([s[1] for s in scope] + [match.group(3)])
            symbols.append((kind, qualified, number))
            scope.append((indent, match.group(3)))
        return symbols
    generic = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+|class\s+|def\s+|fn\s+|func\s+)"
                         r"([A-Za-z_$][\w$]*)")
    for number, line in enumerate(text.splitlines()):
        match = generic.match(line)
        if match:
            symbols.append(("function", match.group(1), number))
    return symbols


_JEDI_STATE: dict = {"module": None, "tried": False}


def get_jedi():
    """Import jedi lazily (it is optional and slow to import)."""
    if not _JEDI_STATE["tried"]:
        _JEDI_STATE["tried"] = True
        try:
            import jedi  # type: ignore
            _JEDI_STATE["module"] = jedi
        except Exception:
            _JEDI_STATE["module"] = None
    return _JEDI_STATE["module"]


# --------------------------------------------------------------------------------------
# Editor widgets
# --------------------------------------------------------------------------------------


class BlockData(QTextBlockUserData):
    """Per-line state that must travel with the line when text above it changes."""

    def __init__(self) -> None:
        super().__init__()
        self.folded = False


MARK_W = 8       # git/diagnostic strip at the far left of the gutter
FOLD_W = 14      # fold arrows at the far right of the gutter
BRACKET_OPEN = "([{"
BRACKET_CLOSE = ")]}"
BRACKET_PAIR = {"(": ")", "[": "]", "{": "}"}
BRACKET_BACK = {")": "(", "]": "[", "}": "{"}


class LineNumberArea(QWidget):
    """Gutter painted by CodeEditor (line numbers, git marks, problems, fold arrows)."""

    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.line_number_area_paint_event(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.editor.gutter_clicked(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        over_fold = event.position().x() >= self.width() - FOLD_W and \
            self.editor.fold_start_at(event.position().y()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if over_fold
                       else Qt.CursorShape.ArrowCursor)

    def event(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip:
            text = self.editor.gutter_tooltip(event.pos().y())
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with a gutter, code folding, completion, snippets and smart typing."""

    cursor_info_changed = pyqtSignal(int, int)
    modification_changed = pyqtSignal(bool)

    def __init__(self, parent=None, font_size: int = 11) -> None:
        super().__init__(parent)
        self.setFont(monospace_font(font_size))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * 4)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursorWidth(2)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(COLOR["bg"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(COLOR["text"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR["selection"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)

        # ---- feature switches (EditorTab / MainWindow flip these) -----------------
        self.python_mode = True
        self.auto_close = True
        self.completion_enabled = True
        self.completion_min_chars = 2
        self.jedi_enabled = True
        self.file_path: Path | None = None
        self.extra_words_provider = None          # callable -> iterable[str]

        # ---- decorations ------------------------------------------------------------
        self.diagnostics: list[Diagnostic] = []
        self._diag_by_line: dict[int, str] = {}
        self.git_marks: dict[int, str] = {}       # line -> "add" | "mod" | "del"
        self._sel_layers: dict[str, list] = {"line": [], "bracket": [], "diag": []}
        self._fold_cache_rev = -1
        self._fold_cache: dict[int, int] = {}
        self._has_folds = False
        self._fold_timer = QTimer(self)
        self._fold_timer.setSingleShot(True)
        self._fold_timer.setInterval(160)
        self._fold_timer.timeout.connect(self._apply_folds)
        self.textChanged.connect(self._on_text_changed_for_folds)

        # ---- completion -------------------------------------------------------------
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(10)
        self._completion_model = QStringListModel(self)
        self._completer.setModel(self._completion_model)
        self._completer.activated[str].connect(self._insert_completion)
        self._completion_prefix_len = 0
        popup = self._completer.popup()
        popup.setStyleSheet(
            "QListView { background: #252526; color: #cccccc; border: 1px solid #454545;"
            " font-family: Consolas, 'DejaVu Sans Mono', monospace; }"
            "QListView::item { padding: 2px 8px; }"
            "QListView::item:selected { background: #04395e; color: #ffffff; }"
        )
        self._words_cache: set[str] = set()
        self._words_rev = -1
        self._words_time = 0.0

        # ---- snippets ---------------------------------------------------------------
        self._snippet_stops: list[QTextCursor] = []
        self._snippet_index = 0

        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.modificationChanged.connect(self.modification_changed.emit)
        self._update_line_number_area_width(0)
        self._highlight_current_line()

    # ------------------------------------------------------------------ gutter
    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return MARK_W + self.fontMetrics().horizontalAdvance("9") * digits + 8 + FOLD_W

    def _update_line_number_area_width(self, _count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            cr.left(), cr.top(), self.line_number_area_width(), cr.height()
        )

    def _block_at_gutter_y(self, y: float):
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid():
            height = self.blockBoundingRect(block).height()
            if block.isVisible() and top <= y <= top + height:
                return block
            top += height
            if top > self.viewport().height() + 4:
                break
            block = block.next()
        return None

    def fold_start_at(self, y: float):
        block = self._block_at_gutter_y(y)
        if block is not None and block.blockNumber() in self._fold_ranges():
            return block
        return None

    def gutter_clicked(self, x: float, y: float) -> None:
        block = self._block_at_gutter_y(y)
        if block is None:
            return
        if x >= self.line_number_area.width() - FOLD_W and block.blockNumber() in self._fold_ranges():
            self.toggle_fold(block.blockNumber())
            return
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        self.setTextCursor(cursor)

    def gutter_tooltip(self, y: float) -> str:
        block = self._block_at_gutter_y(y)
        if block is None:
            return ""
        number = block.blockNumber()
        parts = [d.message for d in self.diagnostics if d.line == number][:4]
        mark = self.git_marks.get(number)
        if mark:
            parts.append({"add": "Added line (git)", "mod": "Modified line (git)",
                          "del": "Lines removed here (git)"}[mark])
        return "\n".join(parts)

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(event.rect(), QColor(COLOR["bg_alt"]))

        ranges = self._fold_ranges()
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()

        current_line = self.textCursor().blockNumber()
        normal = QColor("#858585")
        active = QColor("#c6c6c6")
        font = self.font()
        line_h = self.fontMetrics().height()
        width = self.line_number_area.width()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                height = int(bottom - top)
                mark = self.git_marks.get(block_number)
                if mark == "add":
                    painter.fillRect(0, int(top), 3, height, QColor("#2ea043"))
                elif mark == "mod":
                    painter.fillRect(0, int(top), 3, height, QColor("#2f81f7"))
                elif mark == "del":
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#f85149"))
                    y = int(bottom)
                    painter.drawPolygon(QPolygonF([QPointF(0, y - 4), QPointF(5, y), QPointF(0, y + 4)]))
                severity = self._diag_by_line.get(block_number)
                if severity:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(SEVERITY_COLOR[severity]))
                    painter.drawEllipse(QPointF(5.5, top + line_h / 2.0), 2.0, 2.0)
                painter.setPen(active if block_number == current_line else normal)
                painter.setFont(font)
                painter.drawText(
                    MARK_W, int(top), width - MARK_W - FOLD_W - 4, line_h,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(block_number + 1),
                )
                if block_number in ranges:
                    data = block.userData()
                    folded = bool(data is not None and getattr(data, "folded", False))
                    cx, cy = width - FOLD_W / 2.0 - 1, top + line_h / 2.0
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#c6c6c6" if folded else "#6b6b6b"))
                    if folded:
                        poly = QPolygonF([QPointF(cx - 2, cy - 4), QPointF(cx + 3, cy), QPointF(cx - 2, cy + 4)])
                    else:
                        poly = QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx + 4, cy - 2), QPointF(cx, cy + 3)])
                    painter.drawPolygon(poly)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    # ------------------------------------------------------------------ extra selections
    def _apply_extra_selections(self) -> None:
        merged: list = []
        for key in ("line", "bracket", "diag"):
            merged.extend(self._sel_layers[key])
        self.setExtraSelections(merged)

    def _highlight_current_line(self) -> None:
        if self.isReadOnly():
            self._sel_layers["line"] = []
        else:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#232323"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            self._sel_layers["line"] = [selection]
        self._apply_extra_selections()

    def _on_cursor_moved(self) -> None:
        block = self.textCursor().block()
        if not block.isVisible():
            self.reveal_block(block.blockNumber())
        self._highlight_current_line()
        self._update_bracket_match()
        cursor = self.textCursor()
        self.cursor_info_changed.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)
        self.line_number_area.update()

    # ------------------------------------------------------------------ brackets
    def _update_bracket_match(self) -> None:
        self._sel_layers["bracket"] = []
        cursor = self.textCursor()
        if not cursor.hasSelection():
            doc = self.document()
            pos = cursor.position()
            for probe in (pos - 1, pos):
                if probe < 0 or probe >= doc.characterCount() - 1:
                    continue
                ch = doc.characterAt(probe)
                other = -1
                if ch in BRACKET_OPEN:
                    other = self._scan_bracket(probe, ch, BRACKET_PAIR[ch], 1)
                elif ch in BRACKET_CLOSE:
                    other = self._scan_bracket(probe, ch, BRACKET_BACK[ch], -1)
                else:
                    continue
                good = other >= 0
                for position in ([probe, other] if good else [probe]):
                    selection = QTextEdit.ExtraSelection()
                    selection.format.setBackground(QColor("#3a3d41" if good else "#5a1d1d"))
                    if good:
                        selection.format.setForeground(QColor("#ffd700"))
                    selection.cursor = QTextCursor(doc)
                    selection.cursor.setPosition(position)
                    selection.cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
                    self._sel_layers["bracket"].append(selection)
                break
        self._apply_extra_selections()

    def _scan_bracket(self, start: int, ch: str, target: str, step: int) -> int:
        doc = self.document()
        total = doc.characterCount()
        depth = 0
        pos = start
        limit = 20000
        while 0 <= pos < total and limit > 0:
            current = doc.characterAt(pos)
            if current == ch:
                depth += 1
            elif current == target:
                depth -= 1
                if depth == 0:
                    return pos
            pos += step
            limit -= 1
        return -1

    # ------------------------------------------------------------------ diagnostics / git
    @staticmethod
    def _extent(text: str, col: int) -> int:
        match = re.compile(r"\w+|\S").match(text, col)
        return match.end() if match else min(len(text), col + 1)

    def set_diagnostics(self, diagnostics: list) -> None:
        self.diagnostics = list(diagnostics)[:500]
        self._diag_by_line = {}
        layer = []
        document = self.document()
        for diag in self.diagnostics:
            block = document.findBlockByNumber(diag.line)
            if not block.isValid():
                continue
            text = block.text()
            col = min(max(0, diag.col), len(text))
            end = diag.end_col if diag.end_col > col else self._extent(text, col)
            end = min(end, len(text))
            if end <= col:
                col, end = max(0, len(text.rstrip()) - 1), len(text.rstrip())
                if end <= col:
                    continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            selection.format.setUnderlineColor(QColor(SEVERITY_COLOR.get(diag.severity, "#f14c4c")))
            selection.cursor = QTextCursor(document)
            selection.cursor.setPosition(block.position() + col)
            selection.cursor.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
            layer.append(selection)
            current = self._diag_by_line.get(diag.line)
            if current is None or SEVERITY_ORDER[diag.severity] < SEVERITY_ORDER[current]:
                self._diag_by_line[diag.line] = diag.severity
        self._sel_layers["diag"] = layer
        self._apply_extra_selections()
        self.line_number_area.update()

    def set_git_marks(self, marks: dict) -> None:
        self.git_marks = dict(marks)
        self.line_number_area.update()

    def viewportEvent(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip and self.diagnostics:
            cursor = self.cursorForPosition(event.pos())
            line, col = cursor.blockNumber(), cursor.positionInBlock()
            messages = []
            for diag in self.diagnostics:
                if diag.line != line:
                    continue
                text = cursor.block().text()
                end = diag.end_col if diag.end_col > diag.col else self._extent(text, diag.col)
                if diag.col <= col <= max(end, diag.col + 1):
                    messages.append(f"{SEVERITY_ICON[diag.severity]} {diag.message}  [{diag.source}]")
            if messages:
                QToolTip.showText(event.globalPos(), "\n".join(messages[:4]), self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    # ------------------------------------------------------------------ folding
    @staticmethod
    def _indent_width(text: str) -> int:
        expanded = text.expandtabs(4)
        return len(expanded) - len(expanded.lstrip())

    def _fold_ranges(self) -> dict:
        """{start_line: last_line} for every indentation block (cached per document revision)."""
        document = self.document()
        revision = document.revision()
        if revision == self._fold_cache_rev:
            return self._fold_cache
        ranges: dict[int, int] = {}
        if 0 < document.blockCount() <= 60000:
            stack: list[tuple[int, int]] = []
            previous: tuple[int, int] | None = None
            block = document.begin()
            index = 0
            while block.isValid():
                text = block.text()
                if text.strip():
                    indent = self._indent_width(text)
                    while stack and stack[-1][0] >= indent:
                        _indent, start = stack.pop()
                        if previous is not None and previous[0] > start:
                            ranges[start] = previous[0]
                    if previous is not None and previous[1] < indent:
                        stack.append((previous[1], previous[0]))
                    previous = (index, indent)
                block = block.next()
                index += 1
            while stack:
                _indent, start = stack.pop()
                if previous is not None and previous[0] > start:
                    ranges[start] = previous[0]
        self._fold_cache = ranges
        self._fold_cache_rev = revision
        return ranges

    def _flag(self, block, create: bool = False):
        data = block.userData()
        if data is None and create:
            data = BlockData()
            block.setUserData(data)
        return data

    def _on_text_changed_for_folds(self) -> None:
        if self._has_folds:
            self._fold_timer.start()

    def _apply_folds(self) -> None:
        """Make block visibility match the folded flags (also repairs stale folds)."""
        ranges = self._fold_ranges()
        document = self.document()
        hidden_until = -1
        first_pos = last_end = None
        any_folded = False
        block = document.begin()
        index = 0
        while block.isValid():
            want_visible = index > hidden_until
            data = block.userData()
            if data is not None and getattr(data, "folded", False):
                if index in ranges:
                    any_folded = True
                    if want_visible:
                        hidden_until = max(hidden_until, ranges[index])
                elif want_visible:
                    data.folded = False
            if block.isVisible() != want_visible:
                block.setVisible(want_visible)
                lines = block.layout().lineCount() if block.layout() is not None else 1
                block.setLineCount(max(1, lines) if want_visible else 0)
                if first_pos is None:
                    first_pos = block.position()
                last_end = block.position() + block.length()
            block = block.next()
            index += 1
        self._has_folds = any_folded
        if first_pos is not None:
            document.markContentsDirty(first_pos, max(1, last_end - first_pos))
        self.viewport().update()
        self.line_number_area.update()

    def toggle_fold(self, line: int) -> None:
        if line not in self._fold_ranges():
            return
        block = self.document().findBlockByNumber(line)
        data = self._flag(block, create=True)
        data.folded = not data.folded
        if data.folded:
            cursor = self.textCursor()
            if line < cursor.blockNumber() <= self._fold_ranges()[line]:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self.setTextCursor(cursor)
        self._apply_folds()

    def fold_at_cursor(self) -> None:
        line = self.textCursor().blockNumber()
        best = None
        for start, end in self._fold_ranges().items():
            if start <= line <= end and (best is None or start > best):
                best = start
        if best is not None:
            self.toggle_fold(best)

    def fold_all(self) -> None:
        document = self.document()
        for start in self._fold_ranges():
            self._flag(document.findBlockByNumber(start), create=True).folded = True
        self._apply_folds()

    def unfold_all(self) -> None:
        block = self.document().begin()
        while block.isValid():
            data = block.userData()
            if data is not None:
                data.folded = False
            block = block.next()
        self._apply_folds()

    def reveal_block(self, line: int) -> None:
        document = self.document()
        changed = False
        for start, end in self._fold_ranges().items():
            if start < line <= end:
                data = document.findBlockByNumber(start).userData()
                if data is not None and data.folded:
                    data.folded = False
                    changed = True
        if changed:
            self._apply_folds()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._has_folds:
            return
        ranges = self._fold_ranges()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        metrics = self.fontMetrics()
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        margin = self.document().documentMargin() + self.contentOffset().x()
        while block.isValid() and top <= event.rect().bottom():
            height = self.blockBoundingRect(block).height()
            number = block.blockNumber()
            data = block.userData()
            if block.isVisible() and data is not None and getattr(data, "folded", False) \
                    and number in ranges:
                label = f"⋯ {ranges[number] - number} lines"
                x = margin + metrics.horizontalAdvance(block.text().expandtabs(4)) + 10
                rect = QRectF(x, top + 1, metrics.horizontalAdvance(label) + 12, metrics.height() - 2)
                painter.setPen(QPen(QColor("#4b4b4b")))
                painter.setBrush(QBrush(QColor("#2d2d2d")))
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QColor("#9d9d9d"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            top += height
            block = block.next()

    # ------------------------------------------------------------------ behaviour
    def set_font_size(self, size: int) -> None:
        font = self.font()
        font.setPointSize(size)
        self.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * 4)
        self._update_line_number_area_width(0)

    def set_word_wrap(self, enabled: bool) -> None:
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def set_whitespace_visible(self, enabled: bool) -> None:
        option = self.document().defaultTextOption()
        if enabled:
            option.setFlags(QTextOption.Flag.ShowTabsAndSpaces)
        else:
            option.setFlags(QTextOption.Flag(0))
        self.document().setDefaultTextOption(option)

    def set_scroll_past_end(self, enabled: bool) -> None:
        """Keep the last line at the top of the viewport (VS Code 'scroll past end')."""
        self.setCenterOnScroll(bool(enabled))

    # ------------------------------------------------------------------ completion
    def _document_words(self) -> set:
        now = time.monotonic()
        revision = self.document().revision()
        if revision != self._words_rev and (now - self._words_time > 0.35 or not self._words_cache):
            self._words_cache = set(_GENERIC_IDENT.findall(self.toPlainText()[:400000]))
            self._words_rev = revision
            self._words_time = now
        return self._words_cache

    def _completion_context(self):
        cursor = self.textCursor()
        before = cursor.block().text()[:cursor.positionInBlock()]
        match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)$", before)
        prefix = match.group(1) if match else ""
        head = before[:len(before) - len(prefix)]
        after_dot = head.endswith(".")
        base = ""
        if after_dot:
            found = re.search(r"([A-Za-z_][\w\.]*)\.$", head)
            base = found.group(1) if found else ""
        return prefix, after_dot, base, before

    def _attribute_candidates(self, base: str) -> list:
        names: set = set()
        text = self.toPlainText()[:400000]
        if base in ("self", "cls"):
            names.update(re.findall(r"\bself\.([A-Za-z_]\w*)", text))
            names.update(re.findall(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", text, re.M))
        elif base:
            parts = base.split(".")
            obj = sys.modules.get(parts[0])
            if obj is None and parts[0] in SAFE_STDLIB:
                try:
                    obj = importlib.import_module(parts[0])
                except Exception:
                    obj = None
            for part in parts[1:]:
                obj = getattr(obj, part, None) if obj is not None else None
            if obj is not None:
                try:
                    names.update(n for n in dir(obj) if not n.startswith("_"))
                except Exception:
                    pass
        names.update(re.findall(r"\.([A-Za-z_]\w{2,})", text))
        return list(names)

    def _jedi_completions(self) -> list:
        jedi = get_jedi()
        if jedi is None:
            return []
        text = self.toPlainText()
        if len(text) > 300000:
            return []
        cursor = self.textCursor()
        try:
            script = jedi.Script(code=text, path=str(self.file_path) if self.file_path else None)
            return [c.name for c in script.complete(cursor.blockNumber() + 1,
                                                    cursor.positionInBlock())[:300]]
        except Exception:
            return []

    def _completion_candidates(self, prefix: str, after_dot: bool, base: str, forced: bool) -> list:
        items: list = []
        if self.python_mode:
            if (after_dot or forced) and self.jedi_enabled:
                items = self._jedi_completions()
                if items:
                    return items
            if after_dot:
                return self._attribute_candidates(base)
            items = list(PY_KEYWORDS) + list(PY_BUILTINS)
        elif after_dot:
            return self._attribute_candidates(base)
        items.extend(self._document_words())
        if self.extra_words_provider is not None:
            try:
                items.extend(self.extra_words_provider())
            except Exception:
                pass
        return items

    def hide_completions(self) -> None:
        popup = self._completer.popup()
        if popup is not None and popup.isVisible():
            popup.hide()

    def update_completions(self, forced: bool = False) -> None:
        if (not self.completion_enabled and not forced) or self.isReadOnly():
            return
        if self.textCursor().hasSelection():
            self.hide_completions()
            return
        prefix, after_dot, base, before = self._completion_context()
        if not forced:
            if before.lstrip().startswith("#") or before.count('"') % 2 or before.count("'") % 2:
                self.hide_completions()
                return
            if not after_dot and len(prefix) < self.completion_min_chars:
                self.hide_completions()
                return
        candidates = self._completion_candidates(prefix, after_dot, base, forced)
        snippet_words: set = set()
        if not after_dot and prefix and not before[:len(before) - len(prefix)].strip():
            snippet_words = {w for w in get_snippets(self.python_mode) if w.startswith(prefix)}
            candidates = list(candidates) + list(snippet_words)
        unique = sorted({c for c in candidates if c and (c != prefix or c in snippet_words)},
                        key=lambda s: (s.lower(), s))
        self._completion_model.setStringList(unique[:2500])
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self.hide_completions()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        self._completion_prefix_len = len(prefix)
        rect = self.cursorRect()
        rect.translate(self.viewport().pos())
        rect.setWidth(min(460, popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 24))
        self._completer.complete(rect)

    def _insert_completion(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor,
                            self._completion_prefix_len)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        if text in get_snippets(self.python_mode):
            self.try_expand_snippet()

    # ------------------------------------------------------------------ snippets
    def try_expand_snippet(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        line = cursor.block().text()
        column = cursor.positionInBlock()
        match = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", line[:column])
        if not match:
            return False
        word = match.group(0)
        template = get_snippets(self.python_mode).get(word)
        if template is None or line[:match.start()].strip():
            return False
        text, stops = parse_snippet(template, line[:match.start()])
        start = cursor.block().position() + match.start()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(start + len(word), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        cursor.endEditBlock()
        self._snippet_stops = []
        for first, last in stops:
            tracker = QTextCursor(self.document())
            tracker.setPosition(start + first)
            tracker.setPosition(start + last, QTextCursor.MoveMode.KeepAnchor)
            self._snippet_stops.append(tracker)
        self._snippet_index = 0
        self.setTextCursor(QTextCursor(self._snippet_stops[0]))
        if len(self._snippet_stops) == 1:
            self._snippet_stops = []
        return True

    def snippet_active(self) -> bool:
        return bool(self._snippet_stops)

    def next_snippet_stop(self) -> None:
        self._snippet_index += 1
        if self._snippet_index >= len(self._snippet_stops):
            self._snippet_stops = []
            return
        self.setTextCursor(QTextCursor(self._snippet_stops[self._snippet_index]))
        if self._snippet_index == len(self._snippet_stops) - 1:
            self._snippet_stops = []

    # ------------------------------------------------------------------ typing helpers
    def _neighbours(self) -> tuple[str, str, str]:
        cursor = self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        return text, (text[col - 1] if col > 0 else ""), (text[col] if col < len(text) else "")

    def _handle_pair_typing(self, ch: str) -> bool:
        cursor = self.textCursor()
        text, prev, nxt = self._neighbours()
        col = cursor.positionInBlock()
        closers_ok = nxt == "" or nxt.isspace() or nxt in ")]},:;"
        if ch in BRACKET_PAIR:
            if cursor.hasSelection():
                selected = cursor.selectedText()
                start = cursor.selectionStart()
                cursor.insertText(ch + selected + BRACKET_PAIR[ch])
                cursor.setPosition(start + 1)
                cursor.setPosition(start + 1 + len(selected), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor)
                return True
            if closers_ok:
                cursor.insertText(ch + BRACKET_PAIR[ch])
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.setTextCursor(cursor)
                return True
            return False
        if ch in BRACKET_CLOSE:
            if not cursor.hasSelection() and nxt == ch:
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return True
            return False
        if ch in "\"'":
            if cursor.hasSelection():
                selected = cursor.selectedText()
                start = cursor.selectionStart()
                cursor.insertText(ch + selected + ch)
                cursor.setPosition(start + 1)
                cursor.setPosition(start + 1 + len(selected), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor)
                return True
            if nxt == ch and prev != "\\":
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return True
            before = text[:col]
            if self.python_mode and before.endswith(ch * 2) and not before.endswith(ch * 3) and closers_ok:
                cursor.insertText(ch * 4)
                for _ in range(3):
                    cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.setTextCursor(cursor)
                return True
            if prev.isalnum() and not (prev in "rRbBfFuU" and (col < 2 or not text[col - 2].isalnum())):
                return False
            if prev == "\\" or not closers_ok:
                return False
            cursor.insertText(ch + ch)
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return True
        return False

    def _smart_backspace(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        text, prev, nxt = self._neighbours()
        col = cursor.positionInBlock()
        if self.auto_close and prev and nxt and (
                (prev in BRACKET_PAIR and BRACKET_PAIR[prev] == nxt)
                or (prev in "\"'" and prev == nxt)):
            cursor.deletePreviousChar()
            cursor.deleteChar()
            self.setTextCursor(cursor)
            return True
        if col > 0 and not text[:col].strip(" ") and " " in text[:col] and "\t" not in text[:col]:
            remove = col % 4 or 4
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, remove)
            cursor.removeSelectedText()
            self.setTextCursor(cursor)
            return True
        return False

    def _indent_selection_lines(self, outdent: bool = False) -> None:
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart()).blockNumber()
        last_block = document.findBlock(cursor.selectionEnd())
        if cursor.hasSelection() and cursor.selectionEnd() == last_block.position() and last_block.blockNumber() > first:
            last = last_block.blockNumber() - 1
        else:
            last = last_block.blockNumber()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        for number in range(first, last + 1):
            block = document.findBlockByNumber(number)
            edit.setPosition(block.position())
            if outdent:
                text = block.text()
                remove = 0
                if text.startswith("\t"):
                    remove = 1
                else:
                    while remove < 4 and remove < len(text) and text[remove] == " ":
                        remove += 1
                if remove:
                    edit.setPosition(block.position() + remove, QTextCursor.MoveMode.KeepAnchor)
                    edit.removeSelectedText()
            elif block.text().strip():
                edit.insertText("    ")
        edit.endEditBlock()

    def _outdent(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._indent_selection_lines(outdent=True)
            return
        block_text = cursor.block().text()
        remove = 0
        if block_text.startswith("\t"):
            remove = 1
        else:
            for char in block_text[:4]:
                if char == " ":
                    remove += 1
                else:
                    break
        if remove:
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove
            )
            cursor.removeSelectedText()
            cursor.endEditBlock()

    def _handle_enter(self, event) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()
        column = cursor.positionInBlock()
        before = line[:column].rstrip()
        indentation = re.match(r"[ \t]*", line).group(0)
        _text, prev, nxt = self._neighbours()
        if self.auto_close and prev in BRACKET_PAIR and nxt == BRACKET_PAIR[prev]:
            cursor.insertText("\n" + indentation + "    " + "\n" + indentation)
            cursor.movePosition(QTextCursor.MoveOperation.Up)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self.setTextCursor(cursor)
            return
        if before.endswith(":") or before.endswith(("(", "[", "{")):
            indentation += "    "
        elif self.python_mode and re.match(r"(pass|break|continue|return\b|raise\b)", before.strip()) \
                and before.count("(") == before.count(")") and len(indentation) >= 4:
            indentation = indentation[:-4] if indentation.endswith("    ") else indentation[:-1]
        super().keyPressEvent(event)
        if indentation:
            self.insertPlainText(indentation)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier) and not bool(mods & Qt.KeyboardModifier.AltModifier)
        popup = self._completer.popup()
        popup_open = popup is not None and popup.isVisible()
        if popup_open and key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            typed = self._completion_context()[0]
            if popup.currentIndex().isValid() and popup.currentIndex().data() == typed:
                popup.hide()                      # word already complete: plain newline
                popup_open = False
        if popup_open and key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape,
                                  Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()
            return
        if ctrl and key == Qt.Key.Key_Space:
            self.update_completions(forced=True)
            return
        if key == Qt.Key.Key_Escape and self.snippet_active():
            self._snippet_stops = []
            return
        if self.isReadOnly():
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Tab and not ctrl:
            cursor = self.textCursor()
            if self.snippet_active():
                self.next_snippet_stop()
                return
            if cursor.hasSelection() and cursor.document().findBlock(cursor.selectionStart()) != \
                    cursor.document().findBlock(cursor.selectionEnd()):
                self._indent_selection_lines()
                return
            if self.try_expand_snippet():
                return
            self.insertPlainText("    ")
            return
        if key == Qt.Key.Key_Backtab:
            self._outdent()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._snippet_stops = []
            self._handle_enter(event)
            return
        if key == Qt.Key.Key_Backspace and not mods & (Qt.KeyboardModifier.ControlModifier
                                                       | Qt.KeyboardModifier.AltModifier):
            if self._smart_backspace():
                if self._completer.popup().isVisible():
                    self.update_completions()
                return
        text = event.text()
        if self.auto_close and len(text) == 1 and (text in BRACKET_PAIR or text in BRACKET_CLOSE or text in "\"'") \
                and not ctrl:
            if self._handle_pair_typing(text):
                return
        super().keyPressEvent(event)
        if not self.completion_enabled:
            return
        if text and (text.isalnum() or text in "_.") and not ctrl:
            self.update_completions()
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self._completer.popup().isVisible():
            self.update_completions()
        elif popup_open and key not in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
                                        Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.hide_completions()


class FindBar(QWidget):
    """VS Code style find / replace bar (Ctrl+F, Ctrl+H, F3, Shift+F3, Esc)."""

    def __init__(self, editor: CodeEditor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QWidget#findBar { background: #252526; border-bottom: 1px solid #2b2b2b; }"
        )
        self.setObjectName("findBar")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setMinimumWidth(220)
        self.find_edit.textChanged.connect(self.search_from_cursor)
        self.find_edit.returnPressed.connect(self.find_next)
        find_row.addWidget(self.find_edit)

        self.prev_button = QPushButton("↑")
        self.prev_button.setToolTip("Previous match (Shift+F3)")
        self.prev_button.setFixedWidth(30)
        self.prev_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.prev_button)

        self.next_button = QPushButton("↓")
        self.next_button.setToolTip("Next match (F3)")
        self.next_button.setFixedWidth(30)
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        self.count_label = QLabel("")
        self.count_label.setObjectName("hint")
        self.count_label.setMinimumWidth(90)
        find_row.addWidget(self.count_label)

        self.case_check = QCheckBox("Aa")
        self.case_check.setToolTip("Match case")
        self.case_check.toggled.connect(self.search_from_cursor)
        find_row.addWidget(self.case_check)

        self.word_check = QCheckBox("|ab|")
        self.word_check.setToolTip("Whole word")
        self.word_check.toggled.connect(self.search_from_cursor)
        find_row.addWidget(self.word_check)

        self.regex_check = QCheckBox(".*")
        self.regex_check.setToolTip("Regular expression")
        self.regex_check.toggled.connect(self.search_from_cursor)
        find_row.addWidget(self.regex_check)

        find_row.addStretch(1)
        self.replace_toggle = QToolButton()
        self.replace_toggle.setText("Replace ▾")
        self.replace_toggle.setToolTip("Show the replace row (Ctrl+H)")
        self.replace_toggle.setCheckable(True)
        self.replace_toggle.toggled.connect(self._toggle_replace)
        find_row.addWidget(self.replace_toggle)

        close_button = QToolButton()
        close_button.setText("✕")
        close_button.setToolTip("Close (Esc)")
        close_button.clicked.connect(self.hide_bar)
        find_row.addWidget(close_button)
        outer.addLayout(find_row)

        self.replace_row = QWidget()
        replace_layout = QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.setSpacing(4)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with")
        self.replace_edit.setMinimumWidth(220)
        replace_layout.addWidget(self.replace_edit)
        replace_button = QPushButton("Replace")
        replace_button.clicked.connect(self.replace_current)
        replace_layout.addWidget(replace_button)
        replace_all_button = QPushButton("Replace All")
        replace_all_button.clicked.connect(self.replace_all)
        replace_layout.addWidget(replace_all_button)
        replace_layout.addStretch(1)
        self.replace_row.setVisible(False)
        outer.addWidget(self.replace_row)

    def open_bar(self, replace: bool = False, seed: str | None = None) -> None:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if selected and "\n" not in selected:
            self.find_edit.setText(selected)
        elif seed:
            self.find_edit.setText(seed)
        self.replace_toggle.setChecked(replace)
        self.replace_row.setVisible(replace)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.search_from_cursor(keep_selection=True)

    def hide_bar(self) -> None:
        self.hide()
        self.editor.setFocus()

    def _toggle_replace(self, checked: bool) -> None:
        self.replace_row.setVisible(checked)
        if checked:
            self.replace_edit.setFocus()
            self.replace_edit.selectAll()

    # ------------------------------------------------------------------ searching
    def _flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.word_check.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def _pattern(self) -> QRegularExpression | None:
        text = self.find_edit.text()
        if not text:
            return None
        expression = text
        if self.word_check.isChecked() and self.regex_check.isChecked():
            expression = rf"\b(?:{expression})\b"
        elif self.word_check.isChecked():
            expression = rf"\b{QRegularExpression.escape(expression)}\b"
        elif not self.regex_check.isChecked():
            expression = QRegularExpression.escape(expression)
        pattern = QRegularExpression(expression)
        if self.case_check.isChecked():
            pattern.setPatternOptions(QRegularExpression.PatternOption.NoPatternOption)
        else:
            pattern.setPatternOptions(
                QRegularExpression.PatternOption.CaseInsensitiveOption
            )
        return pattern if pattern.isValid() else None

    def _count_matches(self) -> tuple[int, int]:
        pattern = self._pattern()
        if pattern is None:
            return 0, -1
        document = self.editor.document()
        cursor = QTextCursor(document)
        position = 0
        current = -1
        count = 0
        selection_start = self.editor.textCursor().selectionStart()
        while True:
            cursor = document.find(pattern, position)
            if cursor.isNull():
                break
            if current < 0 and cursor.selectionStart() >= selection_start:
                current = count
            count += 1
            position = max(cursor.selectionEnd(), cursor.selectionStart() + 1)
        return count, current

    def _update_count(self) -> None:
        pattern = self._pattern()
        if pattern is None:
            self.count_label.setText("")
            self.count_label.setStyleSheet("color: #8b8b8b;")
            return
        count, current = self._count_matches()
        if count == 0:
            self.count_label.setText("No results")
            self.count_label.setStyleSheet("color: #f14c4c;")
        else:
            label = f"{current + 1} of {count}" if current >= 0 else f"{count} matches"
            self.count_label.setText(label)
            self.count_label.setStyleSheet("color: #8b8b8b;")

    def search_from_cursor(self, *_args, keep_selection: bool = False) -> None:
        pattern = self._pattern()
        if pattern is None:
            self._update_count()
            return
        cursor = self.editor.textCursor()
        if keep_selection and cursor.hasSelection():
            cursor.setPosition(cursor.selectionStart())
        match = self.editor.document().find(pattern, cursor)
        if match.isNull():
            # wrap around to the top
            match = self.editor.document().find(pattern, 0)
        if not match.isNull():
            self.editor.setTextCursor(match)
            self.editor.ensureCursorVisible()
        self._update_count()

    def find_next(self) -> None:
        pattern = self._pattern()
        if pattern is None:
            return
        cursor = self.editor.textCursor()
        start = max(cursor.selectionEnd(), cursor.position())
        match = self.editor.document().find(pattern, start)
        if match.isNull():
            match = self.editor.document().find(pattern, 0)
        if not match.isNull():
            self.editor.setTextCursor(match)
            self.editor.ensureCursorVisible()
        self._update_count()

    def find_previous(self) -> None:
        pattern = self._pattern()
        if pattern is None:
            return
        cursor = self.editor.textCursor()
        match = self.editor.document().find(
            pattern, max(0, cursor.selectionStart()),
            QTextDocument.FindFlag.FindBackward,
        )
        if match.isNull():
            end_cursor = QTextCursor(self.editor.document())
            end_cursor.movePosition(QTextCursor.MoveOperation.End)
            match = self.editor.document().find(
                pattern, end_cursor, QTextDocument.FindFlag.FindBackward
            )
        if not match.isNull():
            self.editor.setTextCursor(match)
            self.editor.ensureCursorVisible()
        self._update_count()

    def replace_current(self) -> None:
        cursor = self.editor.textCursor()
        replacement = self.replace_edit.text()
        if cursor.hasSelection():
            cursor.insertText(replacement)
        self.find_next()

    def replace_all(self) -> None:
        pattern = self._pattern()
        if pattern is None:
            return
        document = self.editor.document()
        replacement = self.replace_edit.text()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        count = 0
        position = 0
        while True:
            match = document.find(pattern, position)
            if match.isNull():
                break
            match.insertText(replacement)
            count += 1
            position = max(match.selectionEnd(), match.selectionStart() + 1)
        cursor.endEditBlock()
        self.editor.setFocus()
        self._update_count()
        self.count_label.setText(f"Replaced {count}")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide_bar()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_previous()
            else:
                self.find_next()
            return
        super().keyPressEvent(event)


class EditorTab(QWidget):
    """A text/code document tab."""

    KIND = "text"

    def __init__(self, path: Path | None, text: str = "", parent=None,
                 font_size: int = 11, wrap: bool = False) -> None:
        super().__init__(parent)
        self.path = Path(path) if path else None
        self.encoding = "utf-8"
        self.is_new_unsaved = path is None
        self.untitled_name: str | None = None
        self._last_saved_text = text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.editor = CodeEditor(self, font_size=font_size)
        self.path_rel = ""
        self._cfg_auto_close = True
        self._cfg_completion = True
        self._cfg_jedi = True
        self.editor.set_word_wrap(wrap)
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        layout.addWidget(self.editor)

        # ---- find / replace bar (Ctrl+F / Ctrl+H) ------------------------------
        self.find_bar = FindBar(self.editor, self)
        layout.addWidget(self.find_bar)

        # ---- live preview (Markdown / HTML) ------------------------------------
        self.preview_kind = PREVIEW_KINDS.get(self.path.suffix.lower()) if self.path else None
        self.preview_widget = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(450)
        self._preview_timer.timeout.connect(self.refresh_preview)
        if self.preview_kind:
            self.split = QSplitter(Qt.Orientation.Horizontal)
            self.split.addWidget(self.editor)
            if self.preview_kind == "web":
                self.preview_widget = WebPreviewWidget(
                    text, self.path if self.path and self.path.exists() else None, self
                )
            else:
                self.preview_widget = MarkdownPreview(self)
                self.preview_widget.set_source(text)
            self.split.addWidget(self.preview_widget)
            self.split.setStretchFactor(0, 1)
            self.split.setStretchFactor(1, 1)
            self.split.setSizes([600, 600])
            layout.addWidget(self.split, 1)
            self.editor.textChanged.connect(self._preview_timer.start)
        else:
            self.split = None

        self.highlighter = None
        self.apply_highlighter()

    # ------------------------------------------------------------------ helpers
    def apply_highlighter(self) -> None:
        self.highlighter = None
        if self.path and self.path.suffix.lower() in (".py", ".pyw", ".pyi"):
            self.highlighter = PythonHighlighter(self.editor.document())
        else:
            self.highlighter = GenericHighlighter(
                self.editor.document(), language_for_path(self.path)
            )
        self._sync_editor_mode()

    def configure_editor(self, auto_close=None, completion=None, jedi=None) -> None:
        if auto_close is not None:
            self._cfg_auto_close = bool(auto_close)
        if completion is not None:
            self._cfg_completion = bool(completion)
        if jedi is not None:
            self._cfg_jedi = bool(jedi)
        self._sync_editor_mode()

    def _sync_editor_mode(self) -> None:
        suffix = self.path.suffix.lower() if self.path else ""
        plain = suffix in (".txt", ".md", ".rst", ".log", ".csv", ".tsv")
        editor = self.editor
        editor.file_path = self.path
        editor.python_mode = suffix in PYTHON_SUFFIXES or self.path is None
        editor.auto_close = self._cfg_auto_close and not plain
        editor.completion_enabled = self._cfg_completion and not plain
        editor.jedi_enabled = self._cfg_jedi

    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.editor.document().setModified(True)

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def mark_saved(self, text: str | None = None) -> None:
        self._last_saved_text = self.text() if text is None else text
        self.editor.document().setModified(False)

    def reload_from_disk(self) -> bool:
        if not self.path or not self.path.exists():
            return False
        try:
            text, encoding = read_text_file(self.path)
        except Exception:
            return False
        self.encoding = encoding
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self._last_saved_text = text
        self.apply_highlighter()
        self.refresh_preview()
        return True

    def save(self, path: Path | None = None) -> bool:
        target = Path(path) if path else self.path
        if target is None:
            return False
        try:
            if target.suffix.lower() == ".py" and not self.text().endswith("\n"):
                pass  # never silently rewrite the user's content
            target.write_text(self.text(), encoding="utf-8", newline="\n")
        except Exception:
            try:
                target.write_text(self.text(), encoding="utf-8")
            except Exception:
                return False
        self.path = target
        self.encoding = "utf-8"
        self.is_new_unsaved = False
        self.mark_saved()
        self._sync_editor_mode()
        if isinstance(self.highlighter, GenericHighlighter):
            self.apply_highlighter()
        self.refresh_preview()
        return True

    def display_name(self) -> str:
        if self.path:
            return self.path.name
        return self.untitled_name or "Untitled"

    def tooltip(self) -> str:
        return str(self.path) if self.path else "Unsaved file (not yet on disk)"

    def set_font_size(self, size: int) -> None:
        self.editor.set_font_size(size)

    def set_word_wrap(self, enabled: bool) -> None:
        self.editor.set_word_wrap(enabled)

    # ------------------------------------------------------------------ theming
    def has_preview(self) -> bool:
        return self.preview_widget is not None

    def preview_visible(self) -> bool:
        return bool(self.preview_widget and self.preview_widget.isVisible())

    def set_preview_visible(self, visible: bool) -> None:
        if self.preview_widget is None:
            return
        self.preview_widget.setVisible(visible)
        if visible:
            self.refresh_preview()

    def refresh_preview(self) -> None:
        if self.preview_widget is None:
            return
        text = self.text()
        if self.preview_kind == "web":
            base = self.path if (self.path and self.path.exists()) else None
            self.preview_widget.set_content(text, base)
        else:
            position = self.editor.verticalScrollBar().value()
            self.preview_widget.set_source(text)
            self.preview_widget.verticalScrollBar().setValue(position)

    # ------------------------------------------------------------------ find / goto
    def show_find(self, replace: bool = False) -> None:
        self.find_bar.open_bar(replace=replace)

    def find_next(self) -> None:
        self.find_bar.find_next()

    def find_previous(self) -> None:
        self.find_bar.find_previous()

    def goto_line(self, line: int, column: int = 0) -> None:
        block = self.editor.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        if column > 0:
            cursor.setPosition(block.position() + min(column, max(0, block.length() - 1)))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.editor.setFocus()

    # ------------------------------------------------------------------ formatting
    def _selected_or_all(self) -> QTextCursor:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.Document)
        return cursor

    def comment_toggle(self) -> None:
        cursor = self.editor.textCursor()
        document = self.editor.document()
        prefix = "# " if (self.path and self.path.suffix.lower() == ".py") else "// "
        if self.path and self.path.suffix.lower() in (".html", ".htm"):
            prefix = "<!-- "
        start_block = document.findBlock(cursor.selectionStart())
        end_block = document.findBlock(cursor.selectionEnd())
        blocks = []
        block = start_block
        while block.isValid():
            blocks.append(block)
            if block == end_block:
                break
            block = block.next()
        all_commented = all(
            b.text().lstrip().startswith(prefix.strip()) for b in blocks if b.text().strip()
        )
        cursor.beginEditBlock()
        for block in blocks:
            block_cursor = QTextCursor(block)
            text = block.text()
            if not text.strip():
                continue
            if all_commented:
                stripped = text.lstrip()
                column_start = len(text) - len(stripped)
                block_cursor.setPosition(block.position() + column_start)
                for _ in range(len(prefix)):
                    block_cursor.deleteChar()
            else:
                block_cursor.setPosition(block.position() + (len(text) - len(text.lstrip())))
                block_cursor.insertText(prefix)
        cursor.endEditBlock()

    def indent_selection(self) -> None:
        cursor = self.editor.textCursor()
        cursor.insertText("    ")

    def duplicate_line(self) -> None:
        cursor = self.editor.textCursor()
        text = cursor.block().text()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + text)
        self.editor.setTextCursor(cursor)

    def delete_line(self) -> None:
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deleteChar()
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)

    def move_line(self, direction: int) -> None:
        cursor = self.editor.textCursor()
        block = cursor.block()
        text = block.text()
        column = cursor.positionInBlock()
        if direction < 0:
            previous = block.previous()
            if not previous.isValid():
                return
            start = previous.position()
            end = block.position() + len(text)
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(text + "\n" + previous.text())
            cursor.endEditBlock()
            cursor.setPosition(start + column)
        else:
            following = block.next()
            if not following.isValid():
                return
            start = block.position()
            end = following.position() + len(following.text())
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(following.text() + "\n" + text)
            cursor.endEditBlock()
            cursor.setPosition(start + len(following.text()) + 1 + column)
        self.editor.setTextCursor(cursor)

    def format_json(self) -> bool:
        try:
            data = json.loads(self.text())
        except Exception:
            return False
        self.set_text(json.dumps(data, indent=2, ensure_ascii=False))
        return True

    def sort_lines(self) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            text = QTextCursor(self.editor.document())
            text.setPosition(start)
            text.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            lines = text.selectedText().replace("\u2029", "\n").split("\n")
            lines.sort()
            text.insertText("\n".join(lines))
        else:
            lines = self.text().split("\n")
            lines.sort()
            self.set_text("\n".join(lines))


class MarkdownPreview(QTextBrowser):
    """Rendered Markdown view (headings, lists, code, tables)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setStyleSheet(
            "QTextBrowser { background: #1e1e1e; color: #d4d4d4; border: none;"
            " padding: 18px 26px; font-size: 13px; selection-background-color: #264f78; }"
        )
        self.document().setDefaultStyleSheet(
            "pre { background: #252526; color: #ce9178; padding: 8px; }"
            "code { background: #252526; color: #ce9178; }"
            "a { color: #4daafc; }"
            "h1, h2, h3 { color: #ffffff; }"
            "blockquote { color: #9d9d9d; }"
            "table { border-collapse: collapse; }"
            "th, td { border: 1px solid #3c3c3c; padding: 4px 8px; }"
        )

    def set_source(self, text: str) -> None:
        self.setMarkdown(text)


class WebPreviewWidget(QWidget):
    """Live HTML preview. Uses QtWebEngine when present, QTextBrowser otherwise."""

    def __init__(self, text: str = "", base_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.base_path = base_path
        self._engine_available = False
        self._content = text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(6)
        self.info_label = QLabel("Preview")
        self.info_label.setObjectName("hint")
        toolbar_layout.addWidget(self.info_label, 1)
        reload_button = QPushButton("Reload")
        reload_button.setToolTip("Re-render the current buffer")
        reload_button.clicked.connect(self.reload)
        toolbar_layout.addWidget(reload_button)
        external_button = QPushButton("Open in Browser")
        external_button.clicked.connect(self.open_external)
        toolbar_layout.addWidget(external_button)
        layout.addWidget(toolbar)

        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: WPS433

            self.view = QWebEngineView(self)
            profile = self.view.page().profile()
            try:
                profile.setHttpUserAgent("PyForgeIDE/" + APP_VERSION)
            except Exception:
                pass
            self._engine_available = True
        except Exception:
            self.view = QTextBrowser(self)
            self.view.setOpenExternalLinks(False)
            self.view.setStyleSheet(
                "QTextBrowser { background: #181818; color: #cccccc; border: none; padding: 12px; }"
            )
            self._engine_available = False
        layout.addWidget(self.view, 1)
        self.reload()

    # ------------------------------------------------------------------ rendering
    def reload(self) -> None:
        if self._engine_available:
            url = QUrl.fromLocalFile(str(self.base_path)) if self.base_path else QUrl("about:blank")
            self.view.setHtml(self._content, url)
            self.info_label.setText(
                f"HTML preview · {'full engine' if self._engine_available else 'basic'} "
                f"· {len(self._content):,} chars"
            )
        else:
            self.view.setHtml(
                "<div style='font-family:sans-serif; color:#cccccc;'>"
                "<div style='background:#3a2f1c; border:1px solid #d7ba7d; color:#d7ba7d;"
                " padding:8px; margin-bottom:12px; font-size:11px;'>"
                "QtWebEngine is not available in this environment, so this is a basic "
                "HTML render. Install the QtWebEngine component for full CSS/JS preview."
                "</div>" + self._content + "</div>"
            )
            self.info_label.setText("HTML preview · basic renderer")

    def set_content(self, text: str, base_path: Path | None = None) -> None:
        self._content = text
        if base_path is not None:
            self.base_path = base_path
        self.reload()

    def open_external(self) -> None:
        if not self.base_path or not Path(self.base_path).exists():
            QMessageBox.information(
                self, APP_NAME, "Save the file first to open it in your default browser."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.base_path)))


class MediaTab(QWidget):
    """Audio / video files open in the user's default player, with a clear notice."""

    KIND = "media"

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)
        title = QLabel(f"🎬  {self.path.name}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #cccccc;")
        layout.addWidget(title)
        try:
            size = human_size(self.path.stat().st_size)
        except OSError:
            size = "unknown size"
        details = QLabel(
            f"{self.path.suffix.upper().lstrip('.')} media · {size}<br>"
            "<span style='color:#8b8b8b'>Audio and video are played by your system player.</span>"
        )
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(details)
        row = QHBoxLayout()
        row.addStretch(1)
        play = QPushButton("Play in Default Player")
        play.setObjectName("primary")
        play.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
        )
        row.addWidget(play)
        reveal = QPushButton("Show in Folder")
        reveal.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))
        )
        row.addWidget(reveal)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def display_name(self) -> str:
        return self.path.name

    def tooltip(self) -> str:
        return str(self.path)

    def is_modified(self) -> bool:
        return False

    def save(self, path=None) -> bool:
        return True


class ImageTab(QWidget):
    """Scrollable image preview with pixel dimensions."""

    KIND = "image"

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("card")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        self.info = QLabel("")
        self.info.setObjectName("hint")
        header_layout.addWidget(self.info)
        header_layout.addStretch(1)
        fit_button = QPushButton("Fit to Window")
        fit_button.clicked.connect(lambda: self.render(fit=True))
        actual_button = QPushButton("Actual Size")
        actual_button.clicked.connect(lambda: self.render(fit=False))
        header_layout.addWidget(fit_button)
        header_layout.addWidget(actual_button)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: #181818; border: none; }")
        self.label = QLabel("Loading image…")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.label)
        layout.addWidget(self.scroll, 1)

        self.pixmap = QPixmap(str(self.path))
        if self.pixmap.isNull():
            self.info.setText(f"Unable to decode image · {self.path.name}")
            self.label.setText("<span style='color:#f14c4c'>Cannot render this image.</span>")
        else:
            self.info.setText(
                f"{self.pixmap.width()} × {self.pixmap.height()} px · "
                f"{human_size(self.path.stat().st_size)} · {self.path.suffix.upper().lstrip('.')}"
            )
            self.render(fit=True)

    def render(self, fit: bool = True) -> None:
        if self.pixmap.isNull():
            return
        if fit:
            viewport = self.scroll.viewport().size() - QSize(24, 24)
            scaled = self.pixmap.scaled(
                max(64, viewport.width()), max(64, viewport.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.label.setPixmap(scaled)
        else:
            self.label.setPixmap(self.pixmap)

    def display_name(self) -> str:
        return self.path.name

    def tooltip(self) -> str:
        return str(self.path)

    def is_modified(self) -> bool:
        return False

    def save(self, path: Path | None = None) -> bool:
        return True


class BinaryTab(QWidget):
    """Graceful notice for binary files, with an opt-in raw-text view."""

    KIND = "binary"

    def __init__(self, path: Path, reason: str = "Binary or non-UTF8 file", parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.reason = reason
        self.raw_editor: CodeEditor | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notice = QWidget()
        notice_layout = QVBoxLayout(self.notice)
        notice_layout.setContentsMargins(48, 40, 48, 40)
        notice_layout.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(self._build_icon())
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        notice_layout.addWidget(icon)

        title = QLabel("Binary file cannot be displayed in text editor")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #cccccc;")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        notice_layout.addWidget(title)

        try:
            size = human_size(self.path.stat().st_size)
        except OSError:
            size = "unknown size"
        details = QLabel(
            f"{self.path.name}  ·  {size}  ·  {self.path.suffix.upper().lstrip('.') or 'no extension'}"
            f"<br><span style='color:#8b8b8b'>{self.reason}</span><br>"
            f"<span style='color:#6b6b6b; font-size:11px'>{self.path}</span>"
        )
        details.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        details.setTextFormat(Qt.TextFormat.RichText)
        details.setWordWrap(True)
        notice_layout.addWidget(details)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.raw_button = QPushButton("Open Anyway as Raw Text")
        self.raw_button.setObjectName("primary")
        self.raw_button.clicked.connect(self.open_as_raw_text)
        reveal_button = QPushButton("Open Containing Folder")
        reveal_button.clicked.connect(self.reveal_in_file_manager)
        buttons.addWidget(self.raw_button)
        buttons.addWidget(reveal_button)
        buttons.addStretch(1)
        notice_layout.addSpacing(6)
        notice_layout.addLayout(buttons)
        notice_layout.addStretch(1)

        layout.addWidget(self.notice, 1)

    def _build_icon(self) -> QPixmap:
        pixmap = QPixmap(56, 56)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#d7ba7d"))
        painter.setBrush(QColor(37, 37, 38))
        painter.drawRoundedRect(6, 2, 44, 52, 6, 6)
        painter.setPen(QColor("#8b8b8b"))
        font = QFont(monospace_family(), 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "BIN")
        painter.end()
        return pixmap

    def reveal_in_file_manager(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def open_as_raw_text(self) -> None:
        layout = self.layout()
        if self.raw_editor is not None:
            return
        try:
            raw = self.path.read_bytes()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not read file:\n{exc}")
            return
        if len(raw) > MAX_TEXT_BYTES:
            QMessageBox.warning(
                self, APP_NAME,
                f"{self.path.name} is {human_size(len(raw))}. Raw view is limited to "
                f"{human_size(MAX_TEXT_BYTES)} to keep the IDE responsive.",
            )
            raw = raw[:MAX_TEXT_BYTES]
        text = raw.decode("utf-8", errors="replace")
        # Render control characters as visible glyphs so nothing breaks the widget.
        text = "".join(
            ch if (ch.isprintable() or ch in "\n\t") else f"·{ord(ch):02x}"
            for ch in text
        )
        self.raw_editor = CodeEditor(self)
        self.raw_editor.setPlainText(text)
        self.raw_editor.setReadOnly(True)
        self.notice.hide()
        layout.addWidget(self.raw_editor, 1)
        self.raw_button.setEnabled(False)

    def display_name(self) -> str:
        return self.path.name

    def tooltip(self) -> str:
        return str(self.path)

    def is_modified(self) -> bool:
        return False

    def save(self, path: Path | None = None) -> bool:
        return True


# --------------------------------------------------------------------------------------
# Background workers (QThread) – every network / blocking call lives here
# --------------------------------------------------------------------------------------


class ShellWorker(QThread):
    """Owns a real interactive QProcess shell and a small job queue.

    Commands are written to the shell's stdin exactly as a human would type them, so
    interactive programs (input(), pip prompts, ssh, ...) behave natively. Signals are
    queued back to the GUI thread, keeping the interface fully responsive.
    """

    output_ready = pyqtSignal(str)
    state_changed = pyqtSignal(str)          # idle | busy | ready
    shell_started = pyqtSignal(str)          # shell executable
    shell_failed = pyqtSignal(str)
    command_finished = pyqtSignal()

    def __init__(self, shell_path: str, cwd: str | None = None) -> None:
        super().__init__()
        self.shell_path = shell_path or default_shell()
        self.cwd = cwd or str(Path.home())
        self.process: QProcess | None = None
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self._jobs_pending = 0
        self._running = False
        self._quit_requested = False

    # ------------------------------------------------------------------ lifecycle
    def run(self) -> None:  # noqa: D401 - QThread entry point
        """Own the QProcess for the lifetime of the thread.

        Everything here (process creation, reads, writes) happens on this worker
        thread; only plain-string signals cross over to the GUI thread.
        """
        self.process = QProcess()
        self.process.setProgram(self.shell_path)
        self.process.setArguments(self._shell_arguments())
        self.process.setWorkingDirectory(self.cwd)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = self.process.processEnvironment()
        if env.isEmpty():
            # systemEnvironment() is a list of "KEY=VALUE" strings, not a QProcessEnvironment.
            env = QProcessEnvironment()
            for entry in self.process.systemEnvironment():
                key, _sep, value = entry.partition("=")
                if key:
                    env.insert(key, value)
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("TERM", "dumb")
        env.insert("CLICOLOR", "0")
        env.insert("NO_COLOR", "1")
        self.process.setProcessEnvironment(env)
        self.process.start()

        if not self.process.waitForStarted(12000):
            self.shell_failed.emit(
                f"Could not start {self.shell_path}: {self.process.errorString()}"
            )
            self.process = None
            return

        self._running = True
        self.shell_started.emit(self.shell_path)
        self.state_changed.emit("ready")

        while self._running:
            if self.process is None:
                break
            self.process.waitForReadyRead(25)
            data = bytes(self.process.readAllStandardOutput())
            if data:
                self._emit_bytes(data)
            self._flush_queue()
            if self.process.state() == QProcess.ProcessState.NotRunning:
                self.output_ready.emit(
                    f"\n[shell exited with code {self.process.exitCode()}]\n"
                )
                break

        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(2000)
        self.process = None

    def _shell_arguments(self) -> list[str]:
        name = shell_executable_name(self.shell_path)
        flags = ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "-"]
        if name in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
            return flags
        if name in ("cmd.exe", "cmd"):
            return ["/Q", "/K", "chcp 65001>nul"]
        # Non-interactive stdin mode on purpose: no readline line-editing means our
        # queued command lines are never garbled, and child programs still receive
        # stdin from the pipe (so input() works). We draw our own prompt.
        if name.endswith("bash"):
            return ["--noprofile", "--norc"]
        if name.endswith("zsh"):
            return ["-f"]
        return []

    # ------------------------------------------------------------------ output
    def _emit_bytes(self, data: bytes) -> None:
        """Strip ANSI escapes, detect the completion marker, forward clean text."""
        text = data.decode("utf-8", errors="replace")
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if SHELL_DONE_MARKER in text:
            parts = text.split(SHELL_DONE_MARKER)
            for index, part in enumerate(parts):
                if part:
                    self.output_ready.emit(part)
                if index < len(parts) - 1:
                    with self._lock:
                        self._jobs_pending = max(0, self._jobs_pending - 1)
                    self.state_changed.emit("idle")
                    self.command_finished.emit()
        else:
            self.output_ready.emit(text)

    # ------------------------------------------------------------------ job queue
    def submit_command(self, command: str, job: bool = True) -> None:
        """Queue a line for the shell. Jobs get a completion marker on the same line,
        so a running program still owns stdin (input() keeps working)."""
        with self._lock:
            self._pending.append({"command": command, "job": bool(job)})
            if job:
                self._jobs_pending += 1

    def has_active_job(self) -> bool:
        """True while a queued/running job owns stdin. Thread-safe and immediate."""
        with self._lock:
            return self._jobs_pending > 0

    def submit_input(self, text: str) -> None:
        """Send stdin to whatever is currently running in the shell."""
        with self._lock:
            self._pending.append({"command": text, "job": False})

    def _with_marker(self, command: str) -> str:
        """Append a completion marker using syntax the running shell understands."""
        kind = shell_kind(self.shell_path)
        if kind == "cmd":
            return f"{command} & echo {SHELL_DONE_MARKER}"
        # Always emit the marker (even after a failed or interrupted command) so the
        # terminal's busy/idle badge can never get stuck.
        return f"{command}; echo {SHELL_DONE_MARKER}"

    def _flush_queue(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                payload = self._pending.pop(0)
            if self.process is None or self.process.state() != QProcess.ProcessState.Running:
                return
            command = payload["command"]
            if payload["job"]:
                command = self._with_marker(command)
                # Tell the UI a job owns the terminal now: anything typed until the
                # marker comes back is stdin for the running program, not a command.
                self.state_changed.emit("busy")
            self._write(command)

    def _write(self, text: str) -> None:
        if self.process is None or self.process.state() != QProcess.ProcessState.Running:
            return
        if not text.endswith("\n"):
            text += "\n"
        self.process.write(text.encode("utf-8"))

    def cd(self, directory: str) -> None:
        target = shell_quote(str(directory), self.shell_path)
        if shell_kind(self.shell_path) == "cmd":
            self.submit_command(f"cd /d {target}", job=False)
        else:
            self.submit_command(f"cd {target}", job=False)

    def restart(self, shell_path: str, cwd: str | None = None) -> None:
        self.stop()
        self.shell_path = shell_path
        if cwd:
            self.cwd = cwd
        self.start()

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


class PypiSearchWorker(QThread):
    """Queries the live PyPI API / simple index in the background."""

    results_ready = pyqtSignal(list, str)     # rows, status message
    progress = pyqtSignal(str)

    def __init__(self, query: str, installed: set[str], limit: int = 60) -> None:
        super().__init__()
        self.query = (query or "").strip()
        self.installed = {name.lower() for name in installed}
        self.limit = limit

    # ------------------------------------------------------------------ helpers
    def _get(self, url: str, **kwargs):
        if requests is None:
            raise RuntimeError(
                "The 'requests' package is required for PyPI search. "
                "Install it with: pip install requests"
            )
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        return requests.get(url, headers=headers, timeout=kwargs.pop("timeout", 20), **kwargs)

    def _json_info(self, name: str) -> dict | None:
        try:
            response = self._get(PYPI_JSON_URL.format(name=name), timeout=15)
            if response.status_code != 200:
                return None
            data = response.json()
            info = data.get("info", {})
            return {
                "name": info.get("name") or name,
                "version": info.get("version") or "",
                "summary": (info.get("summary") or "").strip() or "No description provided.",
            }
        except Exception:
            return None

    @staticmethod
    def _rank(name: str, summary: str, query: str) -> tuple:
        lowered = name.lower()
        if lowered == query:
            bucket = 0
        elif lowered.startswith(query):
            bucket = 1
        elif query in lowered:
            bucket = 2
        else:
            bucket = 3
        return (bucket, len(name), lowered)

    def _candidates_from_index(self) -> list[str]:
        """Scan the PyPI simple index (streamed) for names matching the query."""
        matches: list[str] = []
        needle = self.query.lower()
        response = self._get(PYPI_INDEX_URL, stream=True, timeout=45)
        response.raw.decode_content = True
        pattern = re.compile(r'<a [^>]*>([^<]+)</a>')
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            for name in pattern.findall(raw_line):
                name = name.strip()
                if needle in name.lower():
                    matches.append(name)
            if len(matches) >= 4000:
                break
        response.close()
        matches.sort(key=lambda n: (not n.lower().startswith(needle), len(n), n.lower()))
        return matches[: self.limit * 2]

    # ------------------------------------------------------------------ run
    def run(self) -> None:  # noqa: D102
        if not self.query:
            self.results_ready.emit([], "Type a package name (or part of one) to search PyPI.")
            return
        rows: list[dict] = []
        message = ""
        try:
            # 1) Exact / near-exact package: full metadata straight from the JSON API.
            self.progress.emit(f'Looking up "{self.query}" on pypi.org…')
            info = self._json_info(self.query)
            if info:
                rows.append(info)
                message = f'Exact match for "{self.query}" plus related packages.'

            # 2) Broader discovery through the simple index (not rate limited).
            self.progress.emit("Scanning the PyPI index for related packages…")
            try:
                candidates = self._candidates_from_index()
            except Exception as exc:
                candidates = []
                message = f'Index scan unavailable ({exc}). Showing the exact-match result only.'
            candidates = [c for c in candidates if c.lower() != self.query.lower()]

            if candidates and requests is not None:
                def fetch(name: str) -> dict | None:
                    return self._json_info(name)

                with ThreadPoolExecutor(max_workers=8) as pool:
                    for item in pool.map(fetch, candidates):
                        if len(rows) >= self.limit:
                            break
                        if item:
                            rows.append(item)

            # 3) De-duplicate and rank.
            seen: set[str] = set()
            unique: list[dict] = []
            for row in rows:
                key = row["name"].lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            unique.sort(key=lambda r: self._rank(r["name"], r["summary"], self.query.lower()))
            unique = unique[: self.limit]

            for row in unique:
                row["installed"] = row["name"].lower() in self.installed
            if not unique:
                message = f'No packages matched "{self.query}".'
            elif not message:
                message = f'{len(unique)} packages matched "{self.query}".'
        except Exception as exc:
            message = f"PyPI search failed: {exc}"
            unique = []
        self.results_ready.emit(unique, message)


class PackageListWorker(QThread):
    """Runs ``pip list --format=json`` for the configured interpreter, off-thread."""

    finished_list = pyqtSignal(list, str)

    def __init__(self, interpreter: str) -> None:
        super().__init__()
        self.interpreter = interpreter

    def run(self) -> None:  # noqa: D102
        command = [
            self.interpreter, "-m", "pip", "list", "--format=json",
            "--disable-pip-version-check",
        ]
        try:
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=120, creationflags=creation,
            )
            if proc.returncode != 0:
                self.finished_list.emit([], (proc.stderr or proc.stdout or "").strip())
                return
            payload = json.loads(proc.stdout or "[]")
            packages = sorted(
                ({"name": p.get("name", ""), "version": p.get("version", "")} for p in payload
                 if p.get("name")),
                key=lambda p: p["name"].lower(),
            )
            self.finished_list.emit(packages, "")
        except FileNotFoundError:
            self.finished_list.emit([], "Python interpreter not found.")
        except Exception as exc:
            self.finished_list.emit([], str(exc))


class InstalledListWorker(QThread):
    """Quick 'what is already installed?' query used by the PyPI table."""

    done = pyqtSignal(set)

    def __init__(self, interpreter: str) -> None:
        super().__init__()
        self.interpreter = interpreter

    def run(self) -> None:  # noqa: D102
        names: set[str] = set()
        try:
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                [self.interpreter, "-m", "pip", "list", "--format=json",
                 "--disable-pip-version-check"],
                capture_output=True, text=True, timeout=120, creationflags=creation,
            )
            if proc.returncode == 0:
                for item in json.loads(proc.stdout or "[]"):
                    if item.get("name"):
                        names.add(item["name"].lower())
        except Exception:
            names = set()
        self.done.emit(names)


class AIWorker(QThread):
    """Calls Ollama / OpenAI / Anthropic compatible chat endpoints off the GUI thread."""

    chunk = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, provider: str, api_key: str, model: str, base_url: str,
                 messages: list[dict], temperature: float = 0.2) -> None:
        super().__init__()
        self.provider = (provider or "ollama").lower()
        self.api_key = api_key or ""
        self.model = model or "qwen2.5-coder"
        self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")
        self.messages = messages
        self.temperature = temperature
        self._cancelled = False
        self._timeout = 300

    def cancel(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------------ request shapes
    def _endpoint_and_payload(self) -> tuple[str, dict, dict]:
        if requests is None:
            raise RuntimeError(
                "The 'requests' package is required for the AI assistant. "
                "Install it with: pip install requests"
            )
        base = self.base_url
        if self.provider == "anthropic":
            url = base if base.rstrip("/").endswith("/messages") else f"{base}/messages"
            headers = {
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            system = "\n\n".join(m["content"] for m in self.messages if m["role"] == "system")
            payload = {
                "model": self.model,
                "max_tokens": 8192,
                "temperature": self.temperature,
                "stream": True,
                "messages": [
                    {"role": m["role"], "content": m["content"]}
                    for m in self.messages if m["role"] in ("user", "assistant")
                ],
            }
            if system:
                payload["system"] = system
            return url, payload, headers

        # Ollama and OpenAI both speak the OpenAI chat-completions dialect.
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        elif base.endswith("/chat/completions"):
            url = base
        else:
            url = f"{base}/v1/chat/completions" if self.provider == "ollama" else f"{base}/chat/completions"
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "stream": True,
        }
        return url, payload, headers

    # ------------------------------------------------------------------ run
    def run(self) -> None:  # noqa: D102
        collected: list[str] = []
        try:
            url, payload, headers = self._endpoint_and_payload()
            response = requests.post(
                url, json=payload, headers=headers, stream=True, timeout=self._timeout
            )
            if response.status_code >= 400:
                detail = response.text[:1200]
                response.close()
                self.failed.emit(
                    f"{self.provider.title()} returned HTTP {response.status_code}.\n\n{detail}"
                )
                return

            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                # Non-streaming fallback (some proxies ignore "stream": true).
                data = response.json()
                text = self._extract_full_response(data)
                response.close()
                if text:
                    self.chunk.emit(text)
                    collected.append(text)
                self.finished_ok.emit("".join(collected))
                return

            for raw_line in response.iter_lines(decode_unicode=True):
                if self._cancelled:
                    break
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = self._extract_delta(event)
                if piece:
                    collected.append(piece)
                    self.chunk.emit(piece)
                if event.get("type") == "message_stop":
                    break
            response.close()
            if self._cancelled:
                self.finished_ok.emit("".join(collected) + "\n\n[generation cancelled]")
            else:
                self.finished_ok.emit("".join(collected))
        except Exception as exc:
            self.failed.emit(self._friendly_error(exc))

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        name = type(exc).__name__
        message = str(exc)
        if "Connection refused" in message or "NewConnectionError" in message or name == "ConnectionError":
            return (
                "Could not connect to the AI provider.\n\n"
                "• Ollama: make sure it is running (`ollama serve`) and the URL is "
                "http://localhost:11434/v1\n"
                "• Cloud providers: check your internet connection, API key and base URL.\n\n"
                f"Details: {message}"
            )
        if name == "ReadTimeout" or "timed out" in message.lower():
            return f"The AI request timed out. Try a smaller model or a shorter prompt.\n\n{message}"
        return f"{name}: {message}"

    def _extract_delta(self, event: dict) -> str:
        try:
            if self.provider == "anthropic":
                if event.get("type") == "content_block_delta":
                    return event.get("delta", {}).get("text", "") or ""
                return ""
            choices = event.get("choices") or []
            if not choices:
                return ""
            choice = choices[0]
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if not text:
                text = (choice.get("message") or {}).get("content") or ""
            return text or ""
        except Exception:
            return ""

    def _extract_full_response(self, data: dict) -> str:
        try:
            if self.provider == "anthropic":
                blocks = data.get("content") or []
                return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            choices = data.get("choices") or []
            if choices:
                return (choices[0].get("message") or {}).get("content") or ""
        except Exception:
            pass
        return ""


# --------------------------------------------------------------------------------------
# UI: small reusable widgets
# --------------------------------------------------------------------------------------


class PanelHeader(QWidget):
    """Compact VS Code style panel header with a title and optional actions."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 6, 6)
        self._layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self._layout.addWidget(self.title_label)
        self._layout.addStretch(1)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_button(self, text: str, tooltip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        self._layout.addWidget(button)
        return button


def make_icon(kind: str, color: str = "#cccccc", size: int = 20):
    """Draw a small monochrome icon so the UI never depends on emoji fonts."""
    from PyQt6.QtGui import QIcon, QPen

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    margin = size * 0.16
    box = size - margin * 2

    if kind == "explorer":
        painter.drawRect(int(margin), int(margin + box * 0.18), int(box), int(box * 0.72))
        painter.drawLine(int(margin), int(margin + box * 0.34),
                         int(margin + box * 0.42), int(margin + box * 0.34))
    elif kind == "search":
        painter.drawEllipse(int(margin), int(margin), int(box * 0.66), int(box * 0.66))
        painter.drawLine(int(margin + box * 0.6), int(margin + box * 0.6), int(margin + box), int(margin + box))
    elif kind == "files":
        painter.drawRect(int(margin + box * 0.22), int(margin), int(box * 0.78), int(box * 0.78))
        painter.drawRect(int(margin), int(margin + box * 0.22), int(box * 0.78), int(box * 0.78))
    elif kind == "quickopen":
        painter.drawLine(int(margin), int(margin + box * 0.5), int(margin + box), int(margin + box * 0.5))
        painter.drawLine(int(margin + box * 0.62), int(margin + box * 0.18),
                         int(margin + box), int(margin + box * 0.5))
        painter.drawLine(int(margin + box * 0.62), int(margin + box * 0.82),
                         int(margin + box), int(margin + box * 0.5))
    elif kind == "outline":
        for index in range(3):
            y = margin + box * (0.2 + index * 0.3)
            painter.drawEllipse(int(margin), int(y), 2, 2)
            painter.drawLine(int(margin + box * 0.22), int(y + 1), int(margin + box), int(y + 1))
    elif kind == "terminal":
        painter.drawRect(int(margin), int(margin + box * 0.12), int(box), int(box * 0.76))
        painter.drawLine(int(margin + box * 0.2), int(margin + box * 0.34),
                         int(margin + box * 0.4), int(margin + box * 0.5))
        painter.drawLine(int(margin + box * 0.4), int(margin + box * 0.5),
                         int(margin + box * 0.2), int(margin + box * 0.66))
    elif kind == "packages":
        painter.drawRect(int(margin), int(margin + box * 0.2), int(box), int(box * 0.7))
        painter.drawLine(int(margin), int(margin + box * 0.42), int(margin + box),
                         int(margin + box * 0.42))
        painter.drawLine(int(margin + box * 0.35), int(margin + box * 0.42),
                         int(margin + box * 0.35), int(margin + box * 0.62))
        painter.drawLine(int(margin + box * 0.65), int(margin + box * 0.42),
                         int(margin + box * 0.65), int(margin + box * 0.62))
    elif kind == "build":
        painter.drawRect(int(margin + box * 0.1), int(margin + box * 0.55), int(box * 0.55), int(box * 0.3))
        painter.drawLine(int(margin + box * 0.5), int(margin + box * 0.55),
                         int(margin + box * 0.85), int(margin + box * 0.15))
        painter.drawLine(int(margin + box * 0.7), int(margin), int(margin + box), int(margin + box * 0.3))
    elif kind == "ai":
        painter.drawLine(int(margin + box * 0.5), int(margin), int(margin + box * 0.5), int(margin + box))
        painter.drawLine(int(margin), int(margin + box * 0.5), int(margin + box), int(margin + box * 0.5))
        painter.drawLine(int(margin + box * 0.22), int(margin + box * 0.22),
                         int(margin + box * 0.78), int(margin + box * 0.78))
        painter.drawLine(int(margin + box * 0.78), int(margin + box * 0.22),
                         int(margin + box * 0.22), int(margin + box * 0.78))
    elif kind == "settings":
        painter.drawEllipse(int(margin + box * 0.22), int(margin + box * 0.22),
                            int(box * 0.56), int(box * 0.56))
        for dx, dy in ((0.5, 0.0), (0.5, 1.0), (0.0, 0.5), (1.0, 0.5)):
            painter.drawPoint(int(margin + box * dx), int(margin + box * dy))
    elif kind == "git":
        r = box * 0.13
        x1, x2 = margin + box * 0.25, margin + box * 0.78
        top, bottom, mid = margin + box * 0.16, margin + box * 0.84, margin + box * 0.42
        painter.drawLine(QPointF(x1, top + r), QPointF(x1, bottom - r))
        painter.drawEllipse(QPointF(x1, top), r, r)
        painter.drawEllipse(QPointF(x1, bottom), r, r)
        painter.drawEllipse(QPointF(x2, mid), r, r)
        painter.drawLine(QPointF(x2 - r, mid + r * 0.6), QPointF(x1, mid + box * 0.3))
    elif kind == "problems":
        painter.drawEllipse(int(margin), int(margin), int(box), int(box))
        painter.drawLine(QPointF(size / 2, margin + box * 0.28), QPointF(size / 2, margin + box * 0.58))
        painter.drawPoint(QPointF(size / 2, margin + box * 0.78))
    elif kind == "tests":
        painter.drawRoundedRect(QRectF(margin, margin, box, box), 3, 3)
        painter.drawLine(QPointF(margin + box * 0.25, margin + box * 0.52),
                         QPointF(margin + box * 0.45, margin + box * 0.72))
        painter.drawLine(QPointF(margin + box * 0.45, margin + box * 0.72),
                         QPointF(margin + box * 0.78, margin + box * 0.3))
    elif kind == "palette":
        painter.drawLine(QPointF(margin + box * 0.12, margin + box * 0.22), QPointF(margin + box * 0.46, margin + box * 0.5))
        painter.drawLine(QPointF(margin + box * 0.46, margin + box * 0.5), QPointF(margin + box * 0.12, margin + box * 0.78))
        painter.drawLine(QPointF(margin + box * 0.55, margin + box * 0.8), QPointF(margin + box * 0.95, margin + box * 0.8))
    painter.end()
    return QIcon(pixmap)


def make_badge(text: str, color: str = "#4ec9b0") -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {color}; border: 1px solid {color}; border-radius: 7px;"
        "padding: 1px 7px; font-size: 10px; font-weight: 600;"
    )
    return label


# --------------------------------------------------------------------------------------
# UI: project explorer
# --------------------------------------------------------------------------------------


class ExplorerPanel(QWidget):
    """VS Code style project tree with full right-click file operations."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.project_root: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- header -------------------------------------------------------------
        header = QFrame()
        header.setStyleSheet("QFrame { background-color: #252526; border-bottom: 1px solid #2b2b2b; }")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 6, 8)
        header_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.project_label = QLabel("NO FOLDER OPEN")
        self.project_label.setStyleSheet(
            "color: #cccccc; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;"
        )
        self.project_label.setToolTip("Current project folder")
        title_row.addWidget(self.project_label)
        title_row.addStretch(1)
        header_layout.addLayout(title_row)

        # --- current folder (editable, so the explorer can be moved anywhere) ----
        path_row = QHBoxLayout()
        path_row.setSpacing(3)
        self.up_button = QToolButton()
        self.up_button.setText("↑")
        self.up_button.setToolTip("Go to the parent folder")
        self.up_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.up_button.clicked.connect(self.go_up)
        path_row.addWidget(self.up_button)

        self.path_bar = QLineEdit()
        self.path_bar.setPlaceholderText("Folder path — press Enter to open")
        self.path_bar.setToolTip("Type or paste any folder path and press Enter to load it here")
        self.path_bar.setClearButtonEnabled(False)
        self.path_bar.returnPressed.connect(self._path_bar_entered)
        self.path_bar.setStyleSheet(
            "QLineEdit { background: #1e1e1e; border: 1px solid #3c3c3c; border-radius: 3px;"
            " padding: 3px 6px; font-size: 11px; }"
        )
        path_row.addWidget(self.path_bar, 1)

        self.roots_button = QToolButton()
        self.roots_button.setText("▾")
        self.roots_button.setToolTip("Jump to a common location or drive")
        self.roots_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.roots_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.roots_button.setMenu(self._build_roots_menu())
        path_row.addWidget(self.roots_button)
        header_layout.addLayout(path_row)

        # --- filter ---------------------------------------------------------------
        filter_row = QHBoxLayout()
        filter_row.setSpacing(3)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter files, e.g. *.py")
        self.filter_edit.setToolTip("Wildcard filter applied to the tree (leave empty for all files)")
        self.filter_edit.setStyleSheet(
            "QLineEdit { background: #1e1e1e; border: 1px solid #3c3c3c; border-radius: 3px;"
            " padding: 3px 6px; font-size: 11px; }"
        )
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_edit, 1)

        self.hidden_button = QToolButton()
        self.hidden_button.setText("◌")
        self.hidden_button.setCheckable(True)
        self.hidden_button.setToolTip("Show hidden / dot files")
        self.hidden_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hidden_button.toggled.connect(self._toggle_hidden)
        filter_row.addWidget(self.hidden_button)
        header_layout.addLayout(filter_row)

        # --- actions --------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(2)
        for text, tip, slot in (
            ("Open", "Open Folder…  (Ctrl+K, Ctrl+O)", self.open_folder),
            ("+ File", "New File", self.new_file),
            ("+ Dir", "New Folder", self.new_folder),
            ("Collapse", "Collapse all folders", self.collapse_all),
            ("⟳", "Refresh", self.refresh),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QToolButton { color: #cccccc; padding: 3px 7px; border-radius: 3px;"
                " background: #2f3134; border: 1px solid #3c3c3c; font-size: 11px; }"
                "QToolButton:hover { background: #3a3d41; }"
            )
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        header_layout.addLayout(actions)
        outer.addWidget(header)

        # --- tree ---------------------------------------------------------------
        self.model = QFileSystemModel(self)
        self.model.setRootPath(QDir.homePath())
        self.model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs
        )
        self.model.setReadOnly(False)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(QDir.homePath()))
        self.tree.setHeaderHidden(True)
        for column in range(1, 4):          # hide size / type / date-modified
            self.tree.setColumnHidden(column, True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(13)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.clicked.connect(self._on_clicked)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        self.tree.setStyleSheet(
            "QTreeView { background: #252526; } QTreeView::item { height: 22px; }"
        )
        outer.addWidget(self.tree, 1)

        self.hidden_button.setChecked(bool(self.owner.config.get("show_hidden_files", False)))
        self._clipboard_path = None
        self._clipboard_cut = False

        self.hint = QLabel("Open a folder to start exploring your project.")
        self.hint.setObjectName("hint")
        self.hint.setContentsMargins(12, 6, 12, 10)
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

    # ------------------------------------------------------------------ helpers
    def path_for_index(self, index: QModelIndex) -> Path | None:
        if not index.isValid():
            return None
        raw = self.model.filePath(index)
        return Path(raw) if raw else None

    def current_directory(self) -> Path:
        index = self.tree.currentIndex()
        while index.isValid() and not self.model.isDir(index):
            index = index.parent()
        path = self.path_for_index(index)
        if path:
            return path
        return self.project_root or Path.home()

    # ------------------------------------------------------------------ project
    def set_project(self, folder: str | Path) -> None:
        path = Path(folder)
        if not path.is_dir():
            return
        self.project_root = path
        self.model.setRootPath(str(path))
        self.tree.setRootIndex(self.model.index(str(path)))
        name = path.name or str(path)
        self.project_label.setText(name.upper())
        self.project_label.setToolTip(str(path))
        self.path_bar.setText(str(path))
        self.hint.setText(f"{path}")
        self._refresh_roots_menu()
        self._apply_filter(self.filter_edit.text())
        self.owner.config.set("last_project", str(path))
        self.owner.config.save()
        self.owner.on_project_opened(path)

    def open_folder(self) -> None:
        self.owner.open_folder_dialog()

    def refresh(self) -> None:
        if self.project_root:
            self.model.setRootPath("")
            self.model.setRootPath(str(self.project_root))
            self.tree.setRootIndex(self.model.index(str(self.project_root)))

    def collapse_all(self) -> None:
        self.tree.collapseAll()
        if self.project_root:
            self.tree.setRootIndex(self.model.index(str(self.project_root)))

    def reveal(self, path: Path) -> None:
        if not path:
            return
        path = Path(path)
        if not self.project_root:
            return
        try:
            path.relative_to(self.project_root)
        except ValueError:
            return
        index = self.model.index(str(path))
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    # ------------------------------------------------------------------ navigation
    def _build_roots_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, path in self._common_roots():
            action = menu.addAction(label)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self.set_project(p))
        return menu

    @staticmethod
    def _common_roots() -> list[tuple[str, Path]]:
        roots: list[tuple[str, Path]] = [("🏠  Home", Path.home())]
        if is_windows():
            import string as _string

            for letter in _string.ascii_uppercase:
                drive = Path(f"{letter}:\\")
                try:
                    if drive.exists():
                        roots.append((f"💽  {letter}:\\", drive))
                except OSError:
                    continue
        else:
            for candidate in ("/home", "/tmp", "/opt", "/usr/local", "/"):
                if Path(candidate).is_dir():
                    roots.append((f"📁  {candidate}", Path(candidate)))
        for name in ("Desktop", "Documents", "Downloads", "Projects"):
            candidate = Path.home() / name
            if candidate.is_dir():
                roots.insert(1, (f"▸  {name}", candidate))
        return roots

    def _refresh_roots_menu(self) -> None:
        self.roots_button.setMenu(self._build_roots_menu())

    def _path_bar_entered(self) -> None:
        raw = self.path_bar.text().strip().strip('"')
        if not raw:
            return
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            self.set_project(candidate)
        elif candidate.is_file():
            self.set_project(candidate.parent)
            self.owner.open_file(candidate)
        else:
            self.owner.flash(f"Not a folder: {raw}")
            self.path_bar.setText(str(self.project_root or ""))

    def go_up(self) -> None:
        if not self.project_root:
            return
        parent = self.project_root.parent
        if parent != self.project_root and parent.is_dir():
            self.set_project(parent)

    def _apply_filter(self, text: str) -> None:
        pattern = text.strip()
        if pattern:
            if "*" not in pattern and "?" not in pattern:
                pattern = f"*{pattern}*"
            self.model.setNameFilters([pattern, pattern + "/*"])
            self.model.setNameFilterDisables(False)
        else:
            self.model.setNameFilters([])
            self.model.setNameFilterDisables(True)

    def _toggle_hidden(self, show: bool) -> None:
        self.owner.config.set("show_hidden_files", bool(show))
        self.owner.config.save()
        self._rebuild_model()

    def _rebuild_model(self) -> None:
        """Recreate the model so filter changes apply immediately and reliably."""
        root = self.project_root
        filters = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs
        if self.owner.config.get("show_hidden_files"):
            filters |= QDir.Filter.Hidden | QDir.Filter.System
        self.model.setFilter(filters)
        if root:
            self.model.setRootPath(str(root))
            self.tree.setRootIndex(self.model.index(str(root)))
        self._apply_filter(self.filter_edit.text())

    # ------------------------------------------------------------------ clicks
    def _on_clicked(self, index: QModelIndex) -> None:
        path = self.path_for_index(index)
        if path and path.is_file():
            self.owner.open_file(path)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        path = self.path_for_index(index)
        if path and path.is_file():
            self.owner.open_file(path)

    # ------------------------------------------------------------------ file ops
    def new_file(self) -> None:
        directory = self.current_directory()
        name, ok = QInputDialog.getText(self, "New File", f"New file name in:\n{directory}")
        if not ok or not name.strip():
            return
        target = directory / name.strip()
        if target.exists():
            QMessageBox.warning(self, APP_NAME, f"{target.name} already exists.")
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not create file:\n{exc}")
            return
        self.refresh()
        self.owner.open_file(target)

    def new_folder(self) -> None:
        directory = self.current_directory()
        name, ok = QInputDialog.getText(self, "New Folder", f"New folder name in:\n{directory}")
        if not ok or not name.strip():
            return
        target = directory / name.strip()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not create folder:\n{exc}")
            return
        self.refresh()

    def rename(self, path: Path) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename", f"Rename {path.name} to:", text=path.name)
        if not ok or not new_name.strip() or new_name.strip() == path.name:
            return
        target = path.with_name(new_name.strip())
        if target.exists():
            QMessageBox.warning(self, APP_NAME, f"{target.name} already exists.")
            return
        try:
            path.rename(target)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Rename failed:\n{exc}")
            return
        self.owner.on_path_renamed(path, target)
        self.refresh()

    def delete(self, path: Path) -> None:
        kind = "folder and everything inside it" if path.is_dir() else "file"
        confirm = QMessageBox.question(
            self, "Delete", f"Delete this {kind}?\n\n{path}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Delete failed:\n{exc}")
            return
        self.owner.on_path_deleted(path)
        self.refresh()

    def copy_path(self, path: Path) -> None:
        QApplication.clipboard().setText(str(path))
        self.owner.flash(f"Copied path: {path}")

    def reveal_in_explorer(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path.is_file() else path)))

    def _show_context_menu(self, position) -> None:
        index = self.tree.indexAt(position)
        path = self.path_for_index(index)
        menu = QMenu(self)

        if path is None or path == self.project_root:
            menu.addAction("Open Folder…", self.open_folder)
            menu.addAction("New File…", self.new_file)
            menu.addAction("New Folder…", self.new_folder)
            if self.project_root:
                menu.addSeparator()
                menu.addAction("Reveal in File Manager", lambda: self.reveal_in_explorer(self.project_root))
                menu.addAction("Copy Path", lambda: self.copy_path(self.project_root))
        elif path.is_dir():
            menu.addAction("New File…", self.new_file)
            menu.addAction("New Folder…", self.new_folder)
            menu.addSeparator()
            menu.addAction("Rename…", lambda: self.rename(path))
            menu.addAction("Delete", lambda: self.delete(path))
            menu.addSeparator()
            menu.addAction("Copy Path", lambda: self.copy_path(path))
            menu.addAction("Reveal in File Manager", lambda: self.reveal_in_explorer(path))
            menu.addAction("Open as Project Folder", lambda: self.set_project(path))
        else:
            menu.addAction("Open", lambda: self.owner.open_file(path))
            menu.addAction("Open With Default App", lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))))
            if path.suffix.lower() in RUN_TARGETS or path.suffix.lower() in PREVIEW_KINDS:
                menu.addAction("Run / Preview", lambda: self.owner.run_file(path))
            menu.addSeparator()
            menu.addAction("Copy", lambda: self._clipboard_copy(path))
            menu.addAction("Cut", lambda: self._clipboard_cut(path))
            menu.addAction("Duplicate", lambda: self.duplicate(path))
            menu.addAction("Rename…", lambda: self.rename(path))
            menu.addAction("Delete", lambda: self.delete(path))
            menu.addSeparator()
            menu.addAction("New File…", self.new_file)
            menu.addAction("New Folder…", self.new_folder)
            menu.addSeparator()
            menu.addAction("Copy Path", lambda: self.copy_path(path))
            menu.addAction("Copy Relative Path", lambda: self._copy_relative(path))
            menu.addAction("Reveal in File Manager", lambda: self.reveal_in_explorer(path))
            menu.addAction("Open Terminal Here",
                           lambda: self.owner.open_terminal_at(path.parent))

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _clipboard_copy(self, path: Path) -> None:
        QApplication.clipboard().setText(str(path))
        self._clipboard_path = path
        self._clipboard_cut = False
        self.owner.flash(f"Copied {path.name} — use Ctrl+V in the tree to paste")

    def _clipboard_cut(self, path: Path) -> None:
        QApplication.clipboard().setText(str(path))
        self._clipboard_path = path
        self._clipboard_cut = True
        self.owner.flash(f"Cut {path.name} — use Ctrl+V in the tree to move it")

    def paste(self) -> None:
        source = getattr(self, "_clipboard_path", None)
        if not source or not Path(source).exists():
            self.owner.flash("Nothing to paste here.")
            return
        target_dir = self.current_directory()
        source = Path(source)
        destination = target_dir / source.name
        if destination.exists():
            stem, suffix = destination.stem, destination.suffix
            index = 2
            while destination.exists():
                destination = target_dir / f"{stem}_copy{index}{suffix}"
                index += 1
        try:
            if getattr(self, "_clipboard_cut", False):
                shutil.move(str(source), str(destination))
                self.owner.on_path_renamed(source, destination)
                self._clipboard_path = None
            else:
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Paste failed:\n{exc}")
            return
        self.refresh()
        self.owner.flash(f"Pasted into {target_dir}")

    def duplicate(self, path: Path) -> None:
        self._clipboard_path = Path(path)
        self._clipboard_cut = False
        self.paste()

    def _copy_relative(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.project_root) if self.project_root else path
        except ValueError:
            relative = path
        QApplication.clipboard().setText(str(relative))
        self.owner.flash(f"Copied relative path: {relative}")


# --------------------------------------------------------------------------------------
# UI: terminal
# --------------------------------------------------------------------------------------


class TerminalPanel(QWidget):
    """Interactive shell surface: live output console + stdin/command input bar."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.worker: ShellWorker | None = None
        self.busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 6, 4)
        header_layout.setSpacing(6)
        title = QLabel("TERMINAL")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        self.shell_label = QLabel("starting…")
        self.shell_label.setObjectName("hint")
        header_layout.addWidget(self.shell_label)
        header_layout.addStretch(1)
        self.status_badge = make_badge("IDLE", "#8b8b8b")
        header_layout.addWidget(self.status_badge)
        for text, tip, slot in (
            ("Clear", "Clear the terminal output", self.clear),
            ("Restart", "Restart the shell", self.restart_shell),
            ("Kill", "Interrupt the running program (Ctrl+C)", self.interrupt),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            header_layout.addWidget(button)
        layout.addWidget(header)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(monospace_font(10))
        self.output.setMaximumBlockCount(6000)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.output.setFrameShape(QFrame.Shape.NoFrame)
        self.output.setStyleSheet(
            "QPlainTextEdit { background: #181818; color: #cccccc; border: none;"
            " padding: 4px; selection-background-color: #264f78; }"
        )
        self.output.setPlaceholderText("Terminal output appears here…")
        layout.addWidget(self.output, 1)

        input_row = QFrame()
        input_row.setStyleSheet("QFrame { background: #1f1f1f; border-top: 1px solid #2b2b2b; }")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(6)
        self.prompt_label = QLabel("$")
        self.prompt_label.setFont(monospace_font(11, bold=True))
        self.prompt_label.setStyleSheet("color: #4ec9b0;")
        input_layout.addWidget(self.prompt_label)
        self.input = QLineEdit()
        self.input.setFont(monospace_font(10))
        self.input.setPlaceholderText("Type a shell command, or answer a running program's prompt…")
        self.input.returnPressed.connect(self.submit)
        input_layout.addWidget(self.input, 1)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.submit)
        input_layout.addWidget(self.send_button)
        layout.addWidget(input_row)

        self.output.appendPlainText(
            "PyForge terminal — a real shell, not a simulation.\n"
            "Commands run natively (input(), pip, git, ssh … all work).\n"
        )

    # ------------------------------------------------------------------ lifecycle
    def start(self, shell_path: str, cwd: str | None = None) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.worker = ShellWorker(shell_path, cwd)
        self.worker.output_ready.connect(self._append)
        self.worker.state_changed.connect(self._on_state)
        self.worker.shell_started.connect(self._on_shell_started)
        self.worker.shell_failed.connect(self._on_shell_failed)
        self.worker.start()

    def _on_shell_started(self, shell_path: str) -> None:
        self.shell_label.setText(shell_executable_name(shell_path) or shell_path)
        self.shell_label.setToolTip(shell_path)

    def _on_shell_failed(self, message: str) -> None:
        self._append(f"[shell error] {message}\n")
        self.owner.flash("Terminal shell failed to start — check Settings → Shell.")

    def _on_state(self, state: str) -> None:
        self.busy = state == "busy"
        color = "#e2c08d" if self.busy else "#4ec9b0"
        self.status_badge.setText("RUNNING" if self.busy else "IDLE")
        self.status_badge.setStyleSheet(
            f"color: {color}; border: 1px solid {color}; border-radius: 7px;"
            "padding: 1px 7px; font-size: 10px; font-weight: 600;"
        )
        self.prompt_label.setStyleSheet(
            f"color: {'#e2c08d' if self.busy else '#4ec9b0'};"
        )
        self.input.setPlaceholderText(
            "Program is waiting — type input and press Enter…" if self.busy
            else "Type a shell command, or answer a running program's prompt…"
        )

    def set_workdir(self, directory: Path | str) -> None:
        """Move the shell (and therefore every subsequent command) to `directory`."""
        target = Path(directory)
        if not target.is_dir():
            return
        if self.worker is not None:
            self.worker.cd(str(target))
        self.owner.flash(f"Terminal working directory: {target}")

    def restart_shell(self) -> None:
        shell = self.owner.config.get("terminal_shell") or default_shell()
        cwd = self.owner.current_working_directory()
        self._append(f"\n[restarting {shell}]\n")
        self.busy = False
        self.start(shell, str(cwd))

    def interrupt(self) -> None:
        """Send Ctrl+C to the shell's foreground process."""
        if self.worker and self.worker.process is not None:
            self._append("\n[Ctrl+C sent]\n")
            self.worker.process.write(b"\x03")
            if is_windows():
                self.worker.submit_input("")  # nudge cmd/powershell to redraw

    # ------------------------------------------------------------------ I/O
    def _append(self, text: str) -> None:
        if not text:
            return
        cursor = self.output.textCursor()
        self.output.appendPlainText(text.rstrip("\n"))
        self.output.setTextCursor(cursor)
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def write(self, text: str) -> None:
        self._append(text)

    def run_command(self, command: str, echo: bool = True) -> None:
        """Send a shell command (used by Run, pip install, etc.)."""
        if self.worker is None:
            shell = self.owner.config.get("terminal_shell") or default_shell()
            self.start(shell, str(self.owner.current_working_directory()))
            QTimer.singleShot(900, lambda: self.worker.submit_command(command, job=True))
            if echo:
                self._append(f"\n$ {command}\n")
            return
        self.worker.submit_command(command, job=True)
        if echo:
            self._append(f"\n$ {command}\n")

    def submit(self) -> None:
        text = self.input.text()
        if not text.strip():
            return
        self.input.clear()
        if self.worker is None:
            return
        run_is_active = self.busy or self.worker.has_active_job()
        if run_is_active:
            self.worker.submit_input(text)
            self._append(f"» {text}")
        else:
            self.worker.submit_command(text, job=True)
        self.input.setFocus()

    def clear(self) -> None:
        self.output.clear()

    def shutdown(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None


# --------------------------------------------------------------------------------------
# UI: PyPI package manager
# --------------------------------------------------------------------------------------


class PackagesPanel(QWidget):
    """Live PyPI search plus real pip install / uninstall through the terminal."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.search_worker: PypiSearchWorker | None = None
        self.list_worker: PackageListWorker | None = None
        self.installed_worker: InstalledListWorker | None = None
        self.installed: set[str] = set()
        self.rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- search row ---------------------------------------------------------
        top = QFrame()
        top.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(8, 8, 8, 8)
        top_layout.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search PyPI — e.g. requests, pandas, flask…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.search)
        search_row.addWidget(self.search_input, 1)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("primary")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_button)
        top_layout.addLayout(search_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.installed_button = QPushButton("Show Installed")
        self.installed_button.setToolTip("List every package installed for the configured interpreter")
        self.installed_button.clicked.connect(self.show_installed)
        action_row.addWidget(self.installed_button)

        self.install_button = QPushButton("Install Selected")
        self.install_button.setToolTip("Run `pip install` for the selected packages in the terminal")
        self.install_button.clicked.connect(self.install_selected)
        action_row.addWidget(self.install_button)

        self.uninstall_button = QPushButton("Uninstall Selected")
        self.uninstall_button.setToolTip("Run `pip uninstall -y` for the selected packages")
        self.uninstall_button.clicked.connect(self.uninstall_selected)
        action_row.addWidget(self.uninstall_button)
        action_row.addStretch(1)
        top_layout.addLayout(action_row)

        self.status = QLabel("Search PyPI for a library, or list what is already installed.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        top_layout.addWidget(self.status)
        layout.addWidget(top)

        # --- results table ------------------------------------------------------
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Package", "Version", "Status", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 90)
        self.table.cellDoubleClicked.connect(
            lambda row, _col: self.table.selectRow(row)
        )
        layout.addWidget(self.table, 1)

        QTimer.singleShot(400, self.refresh_installed_silently)

    # ------------------------------------------------------------------ helpers
    def _interpreter(self) -> str:
        return self.owner.config.get("python_path") or detect_python_interpreter()

    def _selected_names(self) -> list[str]:
        names: list[str] = []
        for index in self.table.selectionModel().selectedRows() if self.table.selectionModel() else []:
            item = self.table.item(index.row(), 0)
            if item and item.text() and item.text() not in names:
                names.append(item.text())
        if not names:
            current = self.table.currentRow()
            item = self.table.item(current, 0) if current >= 0 else None
            if item:
                names.append(item.text())
        return names

    def _pip_base(self) -> str:
        """`& "python.exe" -m pip` on PowerShell, `"python" -m pip` elsewhere."""
        shell = self.owner.terminal_shell_path()
        return build_command(self._interpreter(), "-m pip", shell)

    # ------------------------------------------------------------------ installed
    def refresh_installed_silently(self) -> None:
        if self.installed_worker is not None and self.installed_worker.isRunning():
            return
        self.installed_worker = InstalledListWorker(self._interpreter())
        self.installed_worker.done.connect(self._on_installed_set)
        self.installed_worker.start()

    def _on_installed_set(self, names: set) -> None:
        self.installed = names
        if self.rows:
            self._populate(self.rows)

    def show_installed(self) -> None:
        if self.list_worker is not None and self.list_worker.isRunning():
            return
        self.status.setText(f"Listing installed packages for {self._interpreter()}…")
        self.search_button.setEnabled(False)
        self.list_worker = PackageListWorker(self._interpreter())
        self.list_worker.finished_list.connect(self._on_package_list)
        self.list_worker.start()

    def _on_package_list(self, packages: list, error: str) -> None:
        self.search_button.setEnabled(True)
        if error:
            self.status.setText(f"pip list failed: {error}")
            return
        self.rows = [
            {"name": p["name"], "version": p["version"], "summary": "Installed package",
             "installed": True}
            for p in packages
        ]
        self.installed = {p["name"].lower() for p in packages}
        self._populate(self.rows)
        self.status.setText(f"{len(packages)} packages installed for this interpreter.")

    # ------------------------------------------------------------------ search
    def search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            self.status.setText("Type a package name to search PyPI.")
            return
        if self.search_worker is not None and self.search_worker.isRunning():
            return
        self.search_button.setEnabled(False)
        self.search_button.setText("Searching…")
        self.status.setText(f'Searching PyPI for "{query}"…')
        self.search_worker = PypiSearchWorker(query, self.installed)
        self.search_worker.results_ready.connect(self._on_search_results)
        self.search_worker.progress.connect(self.status.setText)
        self.search_worker.start()

    def _on_search_results(self, rows: list, message: str) -> None:
        self.search_button.setEnabled(True)
        self.search_button.setText("Search")
        self.rows = rows
        self._populate(rows)
        self.status.setText(message)

    def _populate(self, rows: list) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.table.insertRow(row_index)
            name_item = QTableWidgetItem(row.get("name", ""))
            name_item.setFont(QFont(self.font().family(), self.font().pointSize(),
                                    QFont.Weight.DemiBold))
            version_item = QTableWidgetItem(row.get("version", ""))
            installed = row.get("name", "").lower() in self.installed
            status_item = QTableWidgetItem("installed" if installed else "not installed")
            status_item.setForeground(QColor("#4ec9b0" if installed else "#8b8b8b"))
            summary_item = QTableWidgetItem(row.get("summary", ""))
            summary_item.setToolTip(row.get("summary", ""))
            for column, item in enumerate((name_item, version_item, status_item, summary_item)):
                self.table.setItem(row_index, column, item)
        self.table.setSortingEnabled(True)

    # ------------------------------------------------------------------ actions
    def _run_pip(self, arguments: str, description: str) -> None:
        command = f"{self._pip_base()} {arguments}"
        self.owner.show_terminal()
        self.owner.terminal.run_command(command)
        self.owner.flash(description)
        QTimer.singleShot(4000, self.refresh_installed_silently)

    def install_selected(self) -> None:
        names = self._selected_names()
        if not names:
            QMessageBox.information(self, APP_NAME, "Select one or more packages first.")
            return
        shell = self.owner.terminal_shell_path()
        self._run_pip("install " + " ".join(shell_quote(n, shell) for n in names),
                      f"Installing {', '.join(names)}…")

    def uninstall_selected(self) -> None:
        names = self._selected_names()
        if not names:
            QMessageBox.information(self, APP_NAME, "Select one or more packages first.")
            return
        confirm = QMessageBox.question(
            self, "Uninstall",
            "Uninstall the following packages from this interpreter?\n\n" + "\n".join(names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        shell = self.owner.terminal_shell_path()
        self._run_pip("uninstall -y " + " ".join(shell_quote(n, shell) for n in names),
                      f"Uninstalling {', '.join(names)}…")

    def shutdown(self) -> None:
        for worker in (self.search_worker, self.list_worker, self.installed_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)


# --------------------------------------------------------------------------------------
# UI: document outline
# --------------------------------------------------------------------------------------

PY_SYMBOL_RE = re.compile(r"^(\s*)(class|def|async\s+def)\s+([A-Za-z_][A-Za-z0-9_]*)")
GENERIC_SYMBOL_RES = [
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:def|module)\s+([A-Za-z_][\w!?]*)"),
]
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HTML_ID_RE = re.compile(r"<\s*(section|div|h[1-6])\b[^>]*id=[\"']([^\"']+)[\"']", re.I)


class OutlinePanel(QWidget):
    """Symbol tree for the active editor — click a symbol to jump to it."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.rebuild)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 6, 4)
        title = QLabel("OUTLINE")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        header_layout.addWidget(self.summary, 1)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Refresh symbols")
        refresh.clicked.connect(self.rebuild)
        header_layout.addWidget(refresh)
        layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget { background: #252526; border: none; }")
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemActivated.connect(self._on_item_clicked)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel("Open a file to see its symbols.")
        self.empty.setObjectName("hint")
        self.empty.setContentsMargins(12, 8, 12, 8)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

    # ------------------------------------------------------------------ helpers
    def schedule_rebuild(self) -> None:
        self._timer.start()

    def clear(self) -> None:
        self.tree.clear()
        self.summary.setText("")
        self.empty.setText("Open a file to see its symbols.")
        self.empty.show()

    def _add_item(self, parent, text: str, icon: str, line: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"{icon}  {text}"])
        item.setData(0, Qt.ItemDataRole.UserRole, line)
        item.setToolTip(0, f"{text} — line {line + 1}")
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def rebuild(self) -> None:
        tab = self.owner.active_editor_tab()
        self.tree.clear()
        if tab is None:
            self.summary.setText("")
            self.empty.setText("Open a file to see its symbols.")
            self.empty.show()
            return
        path = tab.path
        suffix = path.suffix.lower() if path else ".py"
        text = tab.text()
        count = 0

        if suffix in (".py", ".pyw", ".pyi"):
            stack: list[tuple[int, QTreeWidgetItem]] = []
            for number, line in enumerate(text.splitlines()):
                match = PY_SYMBOL_RE.match(line)
                if not match:
                    continue
                indent = len(match.group(1).replace("\t", "    "))
                kind = "class" if match.group(2) == "class" else "def"
                name = match.group(3)
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                parent = stack[-1][1] if stack else None
                item = self._add_item(
                    parent, name, "◆" if kind == "class" else "ƒ", number
                )
                stack.append((indent, item))
                count += 1
        elif suffix in (".md", ".markdown"):
            for number, line in enumerate(text.splitlines()):
                match = MD_HEADING_RE.match(line)
                if match:
                    level = len(match.group(1))
                    self._add_item(None, match.group(2).strip(), "§" * min(level, 3), number)
                    count += 1
        elif suffix in (".js", ".jsx", ".ts", ".tsx", ".rb"):
            for number, line in enumerate(text.splitlines()):
                for pattern in GENERIC_SYMBOL_RES:
                    match = pattern.match(line)
                    if match:
                        self._add_item(None, match.group(1), "ƒ", number)
                        count += 1
                        break
        elif suffix in (".html", ".htm"):
            for number, line in enumerate(text.splitlines()):
                match = HTML_ID_RE.search(line)
                if match:
                    self._add_item(None, f"{match.group(1).lower()} #{match.group(2)}", "#", number)
                    count += 1
        else:
            for number, line in enumerate(text.splitlines()):
                stripped = line.strip()
                if stripped.endswith(":") and len(stripped) < 60 and not stripped.startswith(("#", "//")):
                    self._add_item(None, stripped[:-1], "•", number)
                    count += 1

        self.empty.setVisible(count == 0)
        if count == 0:
            self.empty.setText("No symbols found in this file.")
        self.summary.setText(f"{count} symbols" if count else "")

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        tab = self.owner.active_editor_tab()
        if tab is not None and line is not None:
            tab.goto_line(int(line) + 1)


# --------------------------------------------------------------------------------------
# UI: build / packaging
# --------------------------------------------------------------------------------------

BUILD_PRESETS = {
    "Windows .exe (onefile, no console)": [
        "--onefile", "--windowed", "--name", "{name}", "--clean", "{script}",
    ],
    "Windows .exe (onefile, console)": [
        "--onefile", "--console", "--name", "{name}", "--clean", "{script}",
    ],
    "Windows .exe (onefile + icon)": [
        "--onefile", "--windowed", "--name", "{name}", "--icon", "{icon}",
        "--clean", "{script}",
    ],
    "Windows .exe (onedir, faster start)": [
        "--onedir", "--windowed", "--name", "{name}", "--clean", "{script}",
    ],
    "Linux / macOS binary (onefile)": [
        "--onefile", "--name", "{name}", "--clean", "{script}",
    ],
    "Add data folder (--add-data)": [
        "--onefile", "--windowed", "--name", "{name}", "--add-data",
        "{data}{sep}.", "{script}",
    ],
    "Compile with Nuitka (native)": [
        "--standalone", "--onefile", "--assume-yes-for-downloads", "{script}",
    ],
}


class BuildPanel(QWidget):
    """One-click packaging/compilation for the active script (PyInstaller, Nuitka...)."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 6, 4)
        title = QLabel("BUILD & PACKAGE")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        open_dist = QToolButton()
        open_dist.setText("Open dist")
        open_dist.setToolTip("Open the folder containing the built artifact")
        open_dist.clicked.connect(self.open_dist_folder)
        header_layout.addWidget(open_dist)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel("Script"), 0, 0)
        self.script_label = QLabel("—")
        self.script_label.setObjectName("hint")
        self.script_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(self.script_label, 0, 1, 1, 2)

        grid.addWidget(QLabel("Preset"), 1, 0)
        self.preset_combo = QComboBox()
        for name in BUILD_PRESETS:
            self.preset_combo.addItem(name, name)
        grid.addWidget(self.preset_combo, 1, 1, 1, 2)

        grid.addWidget(QLabel("Output name"), 2, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("optional — defaults to the script name")
        grid.addWidget(self.name_edit, 2, 1, 1, 2)

        grid.addWidget(QLabel("Icon / data"), 3, 0)
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("optional path for --icon or --add-data")
        grid.addWidget(self.extra_edit, 3, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_extra)
        grid.addWidget(browse, 3, 2)
        body_layout.addLayout(grid)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.build_button = QPushButton("▶  Build")
        self.build_button.setObjectName("primary")
        self.build_button.setToolTip("Run PyInstaller/Nuitka in the terminal (Ctrl+Shift+B)")
        self.build_button.clicked.connect(self.build)
        button_row.addWidget(self.build_button)
        install_button = QPushButton("Install PyInstaller")
        install_button.setToolTip("pip install pyinstaller for the configured interpreter")
        install_button.clicked.connect(self.install_pyinstaller)
        button_row.addWidget(install_button)
        copy_button = QPushButton("Copy Command")
        copy_button.clicked.connect(self.copy_command)
        button_row.addWidget(copy_button)
        button_row.addStretch(1)
        body_layout.addLayout(button_row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(monospace_font(10))
        self.preview.setFixedHeight(92)
        self.preview.setStyleSheet(
            "QPlainTextEdit { background: #181818; border: 1px solid #2b2b2b; color: #9cdcfe; }"
        )
        body_layout.addWidget(self.preview, 1)

        self.hint = QLabel(
            "Packaging runs in the terminal with your configured interpreter, so you can watch "
            "every step. Artifacts land in dist/ (build/ holds intermediate files)."
        )
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        body_layout.addWidget(self.hint)
        layout.addWidget(body, 1)

        self.preset_combo.currentIndexChanged.connect(self._refresh_preview)
        self.name_edit.textChanged.connect(self._refresh_preview)
        self.extra_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    # ------------------------------------------------------------------ helpers
    def _active_script(self) -> Path | None:
        tab = self.owner.active_editor_tab()
        if tab is None or tab.path is None:
            return None
        return Path(tab.path)

    def _dist_dir(self) -> Path:
        script = self._active_script()
        base = script.parent if script else self.owner.current_working_directory()
        return base / "dist"

    def open_dist_folder(self) -> None:
        target = self._dist_dir()
        if not target.is_dir():
            QMessageBox.information(self, APP_NAME, "Nothing has been built yet — dist/ is missing.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _browse_extra(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select icon or data file",
            str(self.owner.current_working_directory()),
            "Icons (*.ico *.png *.icns);;All files (*)",
        )
        if path:
            self.extra_edit.setText(path)

    def _arguments(self) -> list[str]:
        preset = self.preset_combo.currentData()
        script = self._active_script()
        name = self.name_edit.text().strip() or (script.stem if script else "app")
        separator = ";" if is_windows() else ":"
        values = {
            "name": name,
            "script": str(script) if script else "app.py",
            "icon": self.extra_edit.text().strip() or (str(script) if script else "app.py"),
            "data": self.extra_edit.text().strip() or ".",
            "sep": separator,
        }
        template = BUILD_PRESETS.get(preset, BUILD_PRESETS["Windows .exe (onefile, no console)"])
        return [part.format(**values) if "{" in part else part for part in template]

    def command(self) -> str:
        """Full shell-ready command line for the current preset."""
        shell = self.owner.terminal_shell_path()
        preset = self.preset_combo.currentData() or ""
        tool = "nuitka" if "Nuitka" in preset else "pyinstaller"
        arguments = " ".join(shell_quote(part, shell) for part in self._arguments())
        module_args = f"-m {tool} {arguments}"
        return build_command(self.owner._interpreter(), module_args, shell)

    def _refresh_preview(self, *_args) -> None:
        script = self._active_script()
        self.script_label.setText(str(script) if script else "open a saved .py file to build")
        self.build_button.setEnabled(script is not None)
        self.preview.setPlainText(self.command())

    def refresh(self) -> None:
        self._refresh_preview()

    def copy_command(self) -> None:
        QApplication.clipboard().setText(self.command())
        self.owner.flash("Build command copied to the clipboard.")

    def install_pyinstaller(self) -> None:
        shell = self.owner.terminal_shell_path()
        command = build_command(
            self.owner._interpreter(), "-m pip install --upgrade pyinstaller", shell
        )
        self.owner.show_terminal()
        self.owner.terminal.run_command(command)

    def build(self) -> None:
        script = self._active_script()
        if script is None:
            QMessageBox.information(
                self, APP_NAME,
                "Open and save the Python file you want to compile, then press Build.",
            )
            return
        tab = self.owner.active_editor_tab()
        if tab is not None and tab.is_modified() and not self.owner.save_tab(tab):
            return
        command = self.command()
        self.owner.show_terminal()
        self.owner.terminal.set_workdir(script.parent)
        self.owner.terminal.write(
            f"\n— building {script.name} → dist/ —\n"
        )
        self.owner.terminal.run_command(command)
        self.owner.flash(f"Building {script.name} — watch the terminal for progress.")
        QTimer.singleShot(1500, self.refresh)


# --------------------------------------------------------------------------------------
# UI: AI assistant
# --------------------------------------------------------------------------------------

AI_SYSTEM_ASK = (
    "You are PyForge AI, a concise senior software engineer embedded in a desktop IDE. "
    "Answer questions about the user's code accurately and briefly. When you show code, "
    "use fenced code blocks with the correct language tag. If the context is insufficient, "
    "say what you need instead of guessing."
)

AI_SYSTEM_EDIT = (
    "You are PyForge AI in DIRECT EDIT mode. Rewrite the provided file or selection exactly "
    "as instructed and return ONLY the complete, raw replacement content.\n"
    "Rules:\n"
    "1. No markdown, no code fences, no backticks around the result.\n"
    "2. No explanations, no preamble, no trailing commentary.\n"
    "3. Return the full content that should replace the target region, preserving the "
    "file's indentation style, imports and structure unless the instruction says otherwise.\n"
    "4. The output must be directly pasteable — it is written straight into the editor."
)


class AIPanel(QWidget):
    """Multi-provider AI assistant with Ask mode and Direct Edit mode."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.worker: AIWorker | None = None
        self.history: list[dict] = []
        self.mode = "ask"
        self.snapshot: dict | None = None      # {"path", "text", "selection_only", "tab"}
        self._stream_buffer: list[str] = []
        self._streaming = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- header -------------------------------------------------------------
        header = QFrame()
        header.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.model_label = QLabel("")
        self.model_label.setObjectName("hint")
        self.model_label.setStyleSheet("color: #8b8b8b; font-weight: 600;")
        row.addWidget(self.model_label)
        row.addStretch(1)
        settings_button = QToolButton()
        settings_button.setText("⚙")
        settings_button.setToolTip("AI settings")
        settings_button.clicked.connect(self.owner.open_settings)
        row.addWidget(settings_button)
        header_layout.addLayout(row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self.ask_button = QPushButton("Ask Mode")
        self.edit_button = QPushButton("Direct Edit Mode")
        for button in (self.ask_button, self.edit_button):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            mode_row.addWidget(button)
        self.ask_button.setChecked(True)
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        self.ask_button.clicked.connect(lambda: self.set_mode("ask"))
        self.edit_button.clicked.connect(lambda: self.set_mode("edit"))
        self._style_mode_buttons()
        header_layout.addLayout(mode_row)

        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("hint")
        self.mode_hint.setWordWrap(True)
        header_layout.addWidget(self.mode_hint)
        layout.addWidget(header)

        # --- chat log -----------------------------------------------------------
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        self.chat.setStyleSheet(
            "QTextBrowser { background: #1e1e1e; border: none; padding: 8px; "
            "selection-background-color: #264f78; }"
        )
        layout.addWidget(self.chat, 1)

        # --- prompt -------------------------------------------------------------
        prompt_frame = QFrame()
        prompt_frame.setStyleSheet("QFrame { background: #252526; border-top: 1px solid #2b2b2b; }")
        prompt_layout = QVBoxLayout(prompt_frame)
        prompt_layout.setContentsMargins(8, 8, 8, 8)
        prompt_layout.setSpacing(6)

        self.context_label = QLabel("Context: none")
        self.context_label.setObjectName("hint")
        self.context_label.setWordWrap(True)
        prompt_layout.addWidget(self.context_label)

        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Ask about the current file or selection…  (Ctrl+Enter to send)"
        )
        self.prompt.setFixedHeight(84)
        self.prompt.setFont(monospace_font(10))
        self.prompt.installEventFilter(self)
        prompt_layout.addWidget(self.prompt)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send)
        buttons.addWidget(self.send_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.stop_button)

        self.undo_button = QPushButton("Undo AI Edit")
        self.undo_button.setToolTip("Revert the most recent Direct Edit change")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_edit)
        buttons.addWidget(self.undo_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_chat)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        prompt_layout.addLayout(buttons)
        layout.addWidget(prompt_frame)

        self.set_mode("ask")
        self.update_provider_label()
        self._render_history()

    # ------------------------------------------------------------------ small utils
    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.prompt and event.type() == event.Type.KeyPress:
            if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.send()
                return True
        return super().eventFilter(watched, event)

    def _style_mode_buttons(self) -> None:
        active = (
            "QPushButton { background: #007acc; border: 1px solid #1177bb; color: white;"
            " font-weight: 600; padding: 4px 10px; border-radius: 3px; }"
        )
        idle = (
            "QPushButton { background: #2f3134; border: 1px solid #3c3c3c; color: #cccccc;"
            " padding: 4px 10px; border-radius: 3px; }"
            "QPushButton:hover { background: #3a3d41; }"
        )
        self.ask_button.setStyleSheet(active if self.mode == "ask" else idle)
        self.edit_button.setStyleSheet(active if self.mode == "edit" else idle)

    def update_provider_label(self) -> None:
        provider = (self.owner.config.get("ai_provider") or "ollama").lower()
        model = self.owner.config.get("model_name") or "qwen2.5-coder"
        pretty = {"ollama": "Ollama", "openai": "OpenAI", "anthropic": "Anthropic"}.get(
            provider, provider.title()
        )
        self.model_label.setText(f"{pretty} · {model}")
        if provider == "ollama":
            self.model_label.setToolTip(
                f"Local endpoint: {self.owner.config.get('ollama_url')}"
            )
        self._update_context_label()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.ask_button.setChecked(mode == "ask")
        self.edit_button.setChecked(mode == "edit")
        self._style_mode_buttons()
        if mode == "ask":
            self.mode_hint.setText(
                "Ask Mode reads your selection (or the whole active file) and answers in the chat log."
            )
            self.prompt.setPlaceholderText(
                "Ask about the current file or selection…  (Ctrl+Enter to send)"
            )
        else:
            self.mode_hint.setText(
                "Direct Edit Mode rewrites the selection (or the whole file) on disk — "
                "no markdown, no chatter. Undo AI Edit reverts it."
            )
            self.prompt.setPlaceholderText(
                "Describe the change, e.g. 'add type hints and docstrings'"
            )
        self._update_context_label()

    # ------------------------------------------------------------------ context
    def _active_tab(self):
        return self.owner.active_editor_tab()

    def _update_context_label(self) -> None:
        tab = self._active_tab()
        if tab is None:
            self.context_label.setText("Context: no editor open")
            return
        selection = tab.editor.textCursor().selectedText()
        name = tab.display_name()
        if selection.strip():
            self.context_label.setText(
                f"Context: selection · {len(selection)} chars · {name}"
            )
        else:
            lines = tab.editor.blockCount()
            self.context_label.setText(f"Context: whole file · {lines} lines · {name}")

    # ------------------------------------------------------------------ chat rendering
    def _render_history(self, streaming_text: str | None = None) -> None:
        if not self.history and streaming_text is None:
            self.chat.setHtml(
                "<div style='color:#8b8b8b; font-family:sans-serif; font-size:12px;'>"
                "<p style='font-size:13px; color:#cccccc;'><b>PyForge AI</b></p>"
                "<p>Ask questions about your code, or switch to Direct Edit Mode to have the "
                "model rewrite the file for you.</p>"
                "<p style='color:#6b6b6b;'>Selection is used when present, otherwise the whole "
                "active file. Configure the provider in Settings (Ctrl+,).</p></div>"
            )
            return
        blocks = [self._bubble(m["role"], m["content"]) for m in self.history]
        if streaming_text is not None:
            blocks.append(self._bubble("assistant", streaming_text, streaming=True))
        self.chat.setHtml("".join(blocks))
        self._scroll_to_bottom()

    def _bubble(self, role: str, content: str, streaming: bool = False) -> str:
        import html as html_module

        if role == "assistant":
            header = "PyForge AI" + (" · typing…" if streaming else "")
            return (
                "<div style='margin:10px 0; font-family:sans-serif; font-size:12px;'>"
                f"<div style='color:#4ec9b0; font-weight:700; margin-bottom:3px;'>{header}</div>"
                "<div style='color:#cccccc;'><pre style=\"white-space:pre-wrap; "
                "font-family:Consolas,monospace; font-size:12px; margin:0; color:#d4d4d4;\">"
                f"{html_module.escape(content)}</pre></div></div>"
            )
        return (
            "<div style='margin:10px 0; padding:6px 8px; background:#252526; "
            "border-left:3px solid #007acc; font-family:sans-serif; font-size:12px;'>"
            "<div style='color:#8b8b8b; font-weight:700; margin-bottom:3px;'>You</div>"
            "<div style='color:#cccccc;'><pre style=\"white-space:pre-wrap; "
            "font-family:Consolas,monospace; font-size:12px; margin:0;\">"
            f"{html_module.escape(content)}</pre></div></div>"
        )

    def _append_stream_chunk(self, chunk: str) -> None:
        self._stream_buffer.append(chunk)
        self._render_history(streaming_text="".join(self._stream_buffer))

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.chat.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_chat(self) -> None:
        self.history = []
        self._stream_buffer = []
        self._render_history()

    # ------------------------------------------------------------------ send
    def _messages_for_request(self, prompt: str, context: str, mode: str) -> list[dict]:
        system = AI_SYSTEM_ASK if mode == "ask" else AI_SYSTEM_EDIT
        content = prompt
        if context:
            label = "SELECTION" if mode == "ask" else "TARGET CONTENT"
            content = (
                f"{prompt}\n\n----- {label} -----\n{context}\n----- END {label} -----"
            )
        messages = [{"role": "system", "content": system}]
        if mode == "ask":
            for message in self.history[-8:]:
                messages.append({"role": message["role"], "content": message["content"]})
        messages.append({"role": "user", "content": content})
        return messages

    def send(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.owner.flash("The AI is still answering — press Stop first.")
            return
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.owner.flash("Type an instruction for the AI first.")
            return
        tab = self._active_tab()
        selection = ""
        if tab is not None:
            selection = tab.editor.textCursor().selectedText().replace("\u2029", "\n")
        whole_file = ""
        if tab is not None:
            whole_file = tab.editor.toPlainText()
        context = selection if selection.strip() else whole_file

        provider = self.owner.config.get("ai_provider") or "ollama"
        api_key = self.owner.config.get("api_key") or ""
        model = self.owner.config.get("model_name") or "qwen2.5-coder"
        base_url = self.owner.config.get("ollama_url") or "http://localhost:11434/v1"

        if provider in ("openai", "anthropic") and not api_key:
            QMessageBox.warning(
                self, APP_NAME,
                f"{provider.title()} needs an API key.\n\nOpen Settings (Ctrl+,) and paste one.",
            )
            return

        self.prompt.clear()
        self.history.append({"role": "user", "content": prompt})
        self._stream_buffer = []
        self._streaming = True
        self._render_history(streaming_text="")

        messages = self._messages_for_request(prompt, context, self.mode)
        self.worker = AIWorker(provider, api_key, model, base_url, messages)
        self.worker.chunk.connect(self._append_stream_chunk)
        self.worker.finished_ok.connect(
            lambda full: self._on_ai_finished(full, tab, selection, prompt)
        )
        self.worker.failed.connect(self._on_ai_failed)
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.owner.flash(f"PyForge AI ({provider}) is thinking…")
        self.worker.start()

    def _on_ai_finished(self, full_text: str, tab, selection: str, prompt: str) -> None:
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._streaming = False
        text = full_text.strip()
        self.history.append({"role": "assistant", "content": text or "(empty response)"})
        self._render_history()

        if self.mode == "edit":
            if not text:
                self.owner.flash("The AI returned nothing — file left untouched.")
                return
            self._apply_edit(text, tab, bool(selection.strip()), prompt)
        else:
            self.owner.flash("AI response received.")

    def _on_ai_failed(self, message: str) -> None:
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._streaming = False
        self.history.append({"role": "assistant", "content": f"⚠ Error: {message}"})
        self._render_history()
        self.owner.flash("AI request failed — see the AI panel for details.")

    def stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.owner.flash("Cancelling AI generation…")
        self.stop_button.setEnabled(False)

    # ------------------------------------------------------------------ edit mode
    @staticmethod
    def _strip_fences(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        cleaned = cleaned.strip("\n")
        return cleaned

    def _apply_edit(self, raw_text: str, tab, selection_only: bool, prompt: str) -> None:
        if tab is None or getattr(tab, "KIND", "") != "text":
            QMessageBox.information(
                self, APP_NAME, "Open a text or code file before using Direct Edit Mode."
            )
            return
        new_text = self._strip_fences(raw_text)
        cursor = tab.editor.textCursor()
        before_all = tab.editor.toPlainText()
        self.snapshot = {
            "path": str(tab.path) if tab.path else None,
            "text": before_all,
            "full_text_before": before_all,
            "prompt": prompt,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        if selection_only and cursor.hasSelection():
            start = cursor.selectionStart()
            cursor.beginEditBlock()
            cursor.insertText(new_text)
            cursor.endEditBlock()
            cursor.setPosition(start)
            tab.editor.setTextCursor(cursor)
        else:
            tab.editor.setPlainText(new_text)
        tab.editor.document().setModified(True)
        self.undo_button.setEnabled(True)
        self.owner.flash("AI edit applied — use Undo AI Edit to revert.")

    def undo_edit(self) -> None:
        if not self.snapshot:
            return
        tab = self._active_tab()
        target_path = self.snapshot.get("path")
        if tab is None or (target_path and (tab.path is None or str(tab.path) != target_path)):
            if target_path:
                tab = self.owner.open_file(Path(target_path))
        if tab is None or getattr(tab, "KIND", "") != "text":
            QMessageBox.information(self, APP_NAME, "The edited file is no longer open.")
            return
        cursor_position = tab.editor.textCursor().position()
        tab.editor.setPlainText(self.snapshot["text"])
        tab.editor.document().setModified(True)
        if cursor_position <= len(self.snapshot["text"]):
            cursor = tab.editor.textCursor()
            cursor.setPosition(cursor_position)
            tab.editor.setTextCursor(cursor)
        self.owner.flash(
            f"Reverted AI edit from {self.snapshot.get('timestamp', 'earlier')}."
        )
        self.undo_button.setEnabled(False)
        self.snapshot = None

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)


# --------------------------------------------------------------------------------------
# UI: settings dialog
# --------------------------------------------------------------------------------------

PROVIDERS = [
    ("ollama", "Ollama (Local)"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
]


class SettingsDialog(QDialog):
    """Edits every persisted setting, including the frozen-exe Python path."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setWindowTitle("Settings — PyForge IDE")
        self.setMinimumWidth(620)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- runtime ------------------------------------------------------------
        runtime_box = QGroupBox("Runtime")
        runtime_layout = QGridLayout(runtime_box)
        runtime_layout.setColumnStretch(1, 1)

        runtime_layout.addWidget(QLabel("Python interpreter"), 0, 0)
        self.python_edit = QLineEdit(owner.config.get("python_path", ""))
        self.python_edit.setPlaceholderText(r"C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe")
        runtime_layout.addWidget(self.python_edit, 0, 1)
        python_browse = QPushButton("Browse…")
        python_browse.clicked.connect(self._browse_python)
        runtime_layout.addWidget(python_browse, 0, 2)
        detect_button = QPushButton("Auto-detect")
        detect_button.clicked.connect(self._autodetect_python)
        runtime_layout.addWidget(detect_button, 0, 3)

        runtime_layout.addWidget(QLabel("Terminal shell"), 1, 0)
        self.shell_edit = QLineEdit(owner.config.get("terminal_shell", ""))
        self.shell_edit.setPlaceholderText(default_shell())
        runtime_layout.addWidget(self.shell_edit, 1, 1)
        shell_browse = QPushButton("Browse…")
        shell_browse.clicked.connect(self._browse_shell)
        runtime_layout.addWidget(shell_browse, 1, 2)

        hint = QLabel(
            "A frozen .exe has no interpreter of its own — point this at your installed "
            "python.exe so Run (F5) and pip work."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        runtime_layout.addWidget(hint, 2, 0, 1, 4)
        layout.addWidget(runtime_box)

        # --- AI -----------------------------------------------------------------
        ai_box = QGroupBox("AI Assistant")
        ai_layout = QGridLayout(ai_box)
        ai_layout.setColumnStretch(1, 1)

        ai_layout.addWidget(QLabel("Provider"), 0, 0)
        self.provider_combo = QComboBox()
        for value, label in PROVIDERS:
            self.provider_combo.addItem(label, value)
        current_provider = (owner.config.get("ai_provider") or "ollama").lower()
        for index in range(self.provider_combo.count()):
            if self.provider_combo.itemData(index) == current_provider:
                self.provider_combo.setCurrentIndex(index)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        ai_layout.addWidget(self.provider_combo, 0, 1)

        ai_layout.addWidget(QLabel("API key"), 1, 0)
        self.key_edit = QLineEdit(owner.config.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Leave blank for Ollama")
        ai_layout.addWidget(self.key_edit, 1, 1)

        ai_layout.addWidget(QLabel("Model name"), 2, 0)
        self.model_edit = QLineEdit(owner.config.get("model_name", "qwen2.5-coder"))
        self.model_edit.setPlaceholderText("qwen2.5-coder")
        ai_layout.addWidget(self.model_edit, 2, 1)

        ai_layout.addWidget(QLabel("Base URL"), 3, 0)
        self.url_edit = QLineEdit(
            owner.config.get("ollama_url", "http://localhost:11434/v1")
        )
        ai_layout.addWidget(self.url_edit, 3, 1)
        self.url_hint = QLabel("")
        self.url_hint.setObjectName("hint")
        self.url_hint.setWordWrap(True)
        ai_layout.addWidget(self.url_hint, 4, 0, 1, 2)
        layout.addWidget(ai_box)

        # --- editor -------------------------------------------------------------
        editor_box = QGroupBox("Editor")
        editor_layout = QGridLayout(editor_box)
        editor_layout.addWidget(QLabel("Font size"), 0, 0)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(7, 28)
        self.font_spin.setValue(int(owner.config.get("font_size", 11) or 11))
        editor_layout.addWidget(self.font_spin, 0, 1)
        self.wrap_check = QCheckBox("Wrap long lines")
        self.wrap_check.setChecked(bool(owner.config.get("wrap_lines", False)))
        editor_layout.addWidget(self.wrap_check, 0, 2)
        editor_layout.setColumnStretch(3, 1)
        config_path_label = QLabel(
            f"Settings file: <span style='color:#8b8b8b'>{CONFIG_FILE}</span>"
        )
        config_path_label.setTextFormat(Qt.TextFormat.RichText)
        config_path_label.setObjectName("hint")
        editor_layout.addWidget(config_path_label, 1, 0, 1, 4)
        layout.addWidget(editor_box)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_provider_changed()

    # ------------------------------------------------------------------ helpers
    def _on_provider_changed(self, *_args) -> None:
        provider = self.provider_combo.currentData()
        if provider == "ollama":
            self.key_edit.setEnabled(True)
            self.key_edit.setPlaceholderText("Leave blank for Ollama")
            self.url_hint.setText(
                "Ollama needs no API key. Default endpoint: http://localhost:11434/v1 "
                "(start it with `ollama serve`, then `ollama pull qwen2.5-coder`)."
            )
            if self.url_edit.text().strip() in ("", "https://api.openai.com/v1",
                                                "https://api.anthropic.com/v1"):
                self.url_edit.setText("http://localhost:11434/v1")
        elif provider == "openai":
            self.key_edit.setEnabled(True)
            self.key_edit.setPlaceholderText("sk-…")
            self.url_hint.setText("OpenAI endpoint: https://api.openai.com/v1")
            if "localhost" in self.url_edit.text() or self.url_edit.text().strip() == "":
                self.url_edit.setText("https://api.openai.com/v1")
        else:
            self.key_edit.setEnabled(True)
            self.key_edit.setPlaceholderText("sk-ant-…")
            self.url_hint.setText("Anthropic endpoint: https://api.anthropic.com/v1")
            if "localhost" in self.url_edit.text() or self.url_edit.text().strip() == "":
                self.url_edit.setText("https://api.anthropic.com/v1")

    def _browse_python(self) -> None:
        filters = "Python interpreter (python.exe python3);;All files (*)" if is_windows() \
            else "Python interpreter (python3 python);;All files (*)"
        start = self.python_edit.text() or (str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Select Python interpreter", start, filters)
        if path:
            self.python_edit.setText(path)

    def _browse_shell(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select terminal shell", self.shell_edit.text() or str(Path.home())
        )
        if path:
            self.shell_edit.setText(path)

    def _autodetect_python(self) -> None:
        self.python_edit.setText(detect_python_interpreter())

    def values(self) -> dict:
        return {
            "python_path": self.python_edit.text().strip(),
            "terminal_shell": self.shell_edit.text().strip() or default_shell(),
            "ai_provider": self.provider_combo.currentData(),
            "api_key": self.key_edit.text().strip(),
            "model_name": self.model_edit.text().strip() or "qwen2.5-coder",
            "ollama_url": self.url_edit.text().strip() or "http://localhost:11434/v1",
            "font_size": int(self.font_spin.value()),
            "wrap_lines": bool(self.wrap_check.isChecked()),
        }


# --------------------------------------------------------------------------------------
# UI: welcome tab
# --------------------------------------------------------------------------------------

WELCOME_HTML = f"""
<div style="font-family: 'Segoe UI', sans-serif; color: #cccccc; padding: 40px 8px 0 8px;">
  <div style="font-size: 30px; font-weight: 700; color: #ffffff;">
    PyForge <span style="color: #007acc;">IDE</span>
  </div>
  <div style="color: #8b8b8b; margin-top: 6px; font-size: 13px;">
    Single-file PyQt6 IDE · version {APP_VERSION}
  </div>
  <table style="margin-top: 28px; border-spacing: 0 10px; font-size: 13px;">
    <tr><td style="color:#4ec9b0; width:150px;"><b>Ctrl+O</b></td><td>Open a file</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+K, Ctrl+O</b></td><td>Open a project folder</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+Shift+P</b></td><td>Command palette — run anything by name</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+Space</b></td><td>Code suggestions · Tab expands snippets (try <i>def</i>, <i>for</i>, <i>ifmain</i>)</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Shift+Alt+F</b></td><td>Format document (black / ruff)</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+Shift+G</b></td><td>Source control · <b>Ctrl+Alt+T</b> tests · <b>Ctrl+Shift+M</b> problems</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+N / Ctrl+S</b></td><td>New file · Save</td></tr>
    <tr><td style="color:#4ec9b0;"><b>F5</b></td><td>Run the active script in the real terminal</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+,</b></td><td>Settings (Python path, AI provider, API key)</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+Alt+P</b></td><td>Focus the PyPI package manager</td></tr>
    <tr><td style="color:#4ec9b0;"><b>Ctrl+Alt+A</b></td><td>Focus the AI assistant</td></tr>
  </table>
  <div style="margin-top: 26px; color: #8b8b8b; font-size: 12px; line-height: 1.6;">
    Every panel — Explorer, Terminal, Packages, AI Assistant — can be dragged, floated,
    resized, stacked or tabbed anywhere. View → Reset Layout puts everything back.
  </div>
</div>
"""


class WelcomeTab(QWidget):
    KIND = "welcome"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("QTextBrowser { background: #1e1e1e; border: none; }")
        browser.setHtml(WELCOME_HTML)
        layout.addWidget(browser)

    def display_name(self) -> str:
        return "Welcome"

    def tooltip(self) -> str:
        return "PyForge IDE — welcome"

    def is_modified(self) -> bool:
        return False

    def save(self, path=None) -> bool:
        return True


# --------------------------------------------------------------------------------------
# Dialogs: quick open, go to line, project search
# --------------------------------------------------------------------------------------


class ProjectSearchWorker(QThread):
    """Recursive text search across the project, off the GUI thread."""

    results_ready = pyqtSignal(list, int, bool)

    def __init__(self, root: Path, query: str, file_filter: str = "",
                 case_sensitive: bool = False, use_regex: bool = False,
                 limit: int = 3000) -> None:
        super().__init__()
        self.root = Path(root)
        self.query = query
        self.file_filter = file_filter.strip()
        self.case_sensitive = case_sensitive
        self.use_regex = use_regex
        self.limit = limit

    def run(self) -> None:  # noqa: D102
        matches: list[dict] = []
        scanned = 0
        truncated = False
        try:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            pattern = re.compile(self.query if self.use_regex else re.escape(self.query), flags)
        except re.error as exc:
            self.results_ready.emit([{"error": f"Invalid regular expression: {exc}"}], 0, False)
            return
        for path in iter_project_files(self.root):
            if len(matches) >= self.limit:
                truncated = True
                break
            if self.file_filter and self.file_filter.lower() not in str(path).lower():
                continue
            if not is_probably_text_path(path) and not looks_like_text(path):
                continue
            try:
                if path.stat().st_size > MAX_TEXT_BYTES:
                    continue
                text, _encoding = read_text_file(path)
            except Exception:
                continue
            scanned += 1
            for number, line in enumerate(text.splitlines(), start=1):
                for match in pattern.finditer(line):
                    matches.append({
                        "path": str(path),
                        "line": number,
                        "column": match.start() + 1,
                        "text": line.strip()[:400],
                        "start": match.start(),
                        "end": match.end(),
                    })
                    if len(matches) >= self.limit:
                        truncated = True
                        break
                if len(matches) >= self.limit:
                    break
        self.results_ready.emit(matches, scanned, truncated)


class ProjectSearchDialog(QDialog):
    """Search (and replace) across every file in the project — Ctrl+Shift+F."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent or owner)
        self.owner = owner
        self.worker: ProjectSearchWorker | None = None
        self.matches: list[dict] = []
        self.setWindowTitle("Search in Project")
        self.resize(860, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search across the project…")
        self.query_edit.returnPressed.connect(self.start_search)
        row.addWidget(self.query_edit, 2)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("path filter, e.g. .py")
        row.addWidget(self.filter_edit, 1)
        self.case_check = QCheckBox("Aa")
        self.case_check.setToolTip("Match case")
        row.addWidget(self.case_check)
        self.regex_check = QCheckBox(".*")
        self.regex_check.setToolTip("Regular expression")
        row.addWidget(self.regex_check)
        search_button = QPushButton("Search")
        search_button.setObjectName("primary")
        search_button.clicked.connect(self.start_search)
        row.addWidget(search_button)
        layout.addLayout(row)

        replace_row = QHBoxLayout()
        replace_row.setSpacing(6)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace all matches with…")
        replace_row.addWidget(self.replace_edit, 2)
        replace_button = QPushButton("Replace All")
        replace_button.setToolTip("Replace every match in the listed files (asks first)")
        replace_button.clicked.connect(self.replace_all)
        replace_row.addWidget(replace_button)
        layout.addLayout(replace_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File / match", "Line"])
        self.tree.setColumnWidth(0, 620)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._open_match)
        layout.addWidget(self.tree, 1)

        self.status = QLabel("Enter a search term and press Enter.")
        self.status.setObjectName("hint")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.query_edit.setFocus()
        selected = owner.active_editor_tab()
        if selected is not None:
            text = selected.editor.textCursor().selectedText()
            if text and "\n" not in text:
                self.query_edit.setText(text)

    # ------------------------------------------------------------------ search
    def start_search(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            self.status.setText("Type something to search for.")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        root = self.owner.explorer.project_root or self.owner.current_working_directory()
        self.status.setText(f"Searching {root}…")
        self.tree.clear()
        self.worker = ProjectSearchWorker(
            root, query, self.filter_edit.text(),
            self.case_check.isChecked(), self.regex_check.isChecked(),
        )
        self.worker.results_ready.connect(self._on_results)
        self.worker.start()

    def _on_results(self, matches: list, scanned: int, truncated: bool) -> None:
        if matches and "error" in matches[0]:
            self.status.setText(matches[0]["error"])
            return
        self.matches = matches
        grouped: dict[str, list[dict]] = {}
        for match in matches:
            grouped.setdefault(match["path"], []).append(match)

        for path, rows in grouped.items():
            root_item = QTreeWidgetItem([f"{Path(path).name}", ""])
            root_item.setToolTip(0, path)
            root_item.setForeground(0, QColor("#9cdcfe"))
            self.tree.addTopLevelItem(root_item)
            for row in rows:
                child = QTreeWidgetItem([f"   {row['line']}: {row['text']}", str(row["line"])])
                child.setData(0, Qt.ItemDataRole.UserRole, row)
                root_item.addChild(child)
            root_item.setExpanded(True)
        suffix = " (truncated)" if truncated else ""
        self.status.setText(
            f"{len(matches)} matches in {len(grouped)} files · {scanned} files scanned{suffix}"
        )

    def _open_match(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        row = item.data(0, Qt.ItemDataRole.UserRole)
        if not row:
            return
        tab = self.owner.open_file(Path(row["path"]))
        if tab is not None and getattr(tab, "KIND", "") == "text":
            tab.goto_line(row["line"])
            cursor = tab.editor.textCursor()
            cursor.setPosition(cursor.block().position() + row["start"])
            cursor.setPosition(
                cursor.position() + max(1, row["end"] - row["start"]),
                QTextCursor.MoveMode.KeepAnchor,
            )
            tab.editor.setTextCursor(cursor)

    # ------------------------------------------------------------------ replace
    def replace_all(self) -> None:
        replacement = self.replace_edit.text()
        if not self.matches:
            self.status.setText("Run a search first.")
            return
        files = sorted({m["path"] for m in self.matches})
        if QMessageBox.question(
            self, "Replace All",
            f"Replace {len(self.matches)} matches across {len(files)} file(s)?\n\n"
            "This rewrites the files on disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        query = self.query_edit.text()
        flags = 0 if self.case_check.isChecked() else re.IGNORECASE
        pattern = re.compile(query if self.regex_check.isChecked() else re.escape(query), flags)
        changed = 0
        errors = 0
        for path_str in files:
            path = Path(path_str)
            try:
                text, _encoding = read_text_file(path)
                new_text, count = pattern.subn(replacement, text)
                if count:
                    path.write_text(new_text, encoding="utf-8", newline="\n")
                    changed += count
                    tab_index, tab = self.owner._find_tab_for_path(path)
                    if tab is not None and not tab.is_modified():
                        tab.reload_from_disk()
            except Exception:
                errors += 1
        self.status.setText(
            f"Replaced {changed} matches in {len(files)} files"
            + (f" · {errors} failed" if errors else "")
        )


class QuickOpenDialog(QDialog):
    """VS Code style fuzzy file palette (Ctrl+P)."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent or owner)
        self.owner = owner
        self.setWindowTitle("Quick Open")
        self.resize(720, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type part of a file name — ↑/↓ to move, Enter to open")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _item: self._accept_current())
        layout.addWidget(self.list, 1)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)

        self.files: list[Path] = []
        root = owner.explorer.project_root
        if root:
            self.files = list(iter_project_files(root, limit=8000))
        recent = [Path(p) for p in owner.config.get("recent_files", []) if Path(p).exists()]
        seen = {str(f) for f in self.files}
        for path in recent:
            if str(path) not in seen:
                self.files.insert(0, path)
        self.hint.setText(f"{len(self.files)} files indexed from {root or 'nowhere'}")
        self._filter("")
        self.search.setFocus()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8,
                    Qt.Key.Key_PageUp: -8}.get(event.key())
            if step is not None and self.list.count():
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _score(needle: str, haystack: str) -> int:
        """Cheap subsequence score; -1 means no match."""
        needle = needle.lower()
        haystack = haystack.lower()
        if not needle:
            return 0
        position = haystack.find(needle)
        if position >= 0:
            return 100 - position
        index = 0
        for char in haystack:
            if index < len(needle) and char == needle[index]:
                index += 1
        return 10 if index == len(needle) else -1

    def _filter(self, text: str) -> None:
        self.list.clear()
        query = text.strip()
        scored = []
        for path in self.files:
            score = self._score(query, path.name) if query else 0
            if score < 0 and query:
                score = max(-1, self._score(query, str(path)) // 2)
            if score < 0:
                continue
            scored.append((score, str(path), path))
        scored.sort(key=lambda item: (-item[0], len(item[1])))
        for _score_value, _full, path in scored[:400]:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self.owner.open_file(Path(path))


# --------------------------------------------------------------------------------------
# Pro tooling: palette, diff viewer, background helpers
# --------------------------------------------------------------------------------------


def fuzzy_score(needle: str, haystack: str) -> int:
    """Subsequence match score (higher is better); -1 means no match."""
    needle = needle.lower().strip()
    haystack = haystack.lower()
    if not needle:
        return 0
    position = haystack.find(needle)
    if position >= 0:
        bonus = 40 if position == 0 else (15 if haystack[position - 1] in " /\\._-:" else 0)
        return 200 - min(position, 100) + bonus
    index = 0
    streak = best = 0
    for char in haystack:
        if index < len(needle) and char == needle[index]:
            index += 1
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return 10 + best * 3 if index == len(needle) else -1


class FuncWorker(QThread):
    """Run any callable off the UI thread; emits its return value (or the exception)."""

    result = pyqtSignal(object)

    def __init__(self, function, parent=None) -> None:
        super().__init__(parent)
        self.function = function

    def run(self) -> None:
        try:
            self.result.emit(self.function())
        except Exception as exc:  # delivered to the UI thread, never lost
            self.result.emit(exc)


class _PickerDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:  # noqa: N802
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, QColor("#04395e"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#2a2d2e"))
        rect = option.rect.adjusted(12, 0, -12, 0)
        detail = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        metrics = painter.fontMetrics()
        detail_w = metrics.horizontalAdvance(detail) if detail else 0
        label = metrics.elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                                   Qt.TextElideMode.ElideRight, max(40, rect.width() - detail_w - 16))
        painter.setPen(QColor("#ffffff" if selected else "#cccccc"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        if detail:
            painter.setPen(QColor("#9d9d9d" if selected else "#7a7a7a"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, detail)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 28)


class PickerDialog(QDialog):
    """Fuzzy quick-pick used for the command palette, symbols, branches, interpreters…

    ``items`` is a list of ``(label, detail, payload)``; the chosen payload ends up in
    ``self.choice`` (None when cancelled).
    """

    def __init__(self, parent, title: str, placeholder: str, items: list,
                 initial: str = "", max_rows: int = 300) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setStyleSheet(
            "QDialog { background: #252526; border: 1px solid #454545; }"
            "QLineEdit { background: #3c3c3c; border: 1px solid #007acc; padding: 6px 8px;"
            " font-size: 13px; }"
            "QListWidget { background: #252526; border: none; }"
        )
        self.resize(640, 420)
        self.items = items
        self.max_rows = max_rows
        self.choice = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setItemDelegate(_PickerDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.itemClicked.connect(lambda _item: self._accept_current())
        layout.addWidget(self.list, 1)
        self.empty = QLabel("No matches")
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)
        self.search.setText(initial)
        self._filter(initial)
        self.search.setFocus()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8,
                    Qt.Key.Key_PageUp: -8}.get(key)
            if step is not None and self.list.count():
                row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
                self.list.setCurrentRow(row)
                return True
        return super().eventFilter(obj, event)

    def _filter(self, text: str) -> None:
        self.list.clear()
        query = text.strip()
        scored = []
        for order, (label, detail, payload) in enumerate(self.items):
            score = fuzzy_score(query, label)
            if score < 0 and detail:
                score = fuzzy_score(query, detail) // 3 if fuzzy_score(query, detail) >= 0 else -1
            if score >= 0:
                scored.append((-score, order, label, detail, payload))
        scored.sort(key=lambda row: (row[0], row[1]))
        for _score, _order, label, detail, payload in scored[:self.max_rows]:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, payload)
            item.setData(Qt.ItemDataRole.UserRole + 1, detail)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.empty.setVisible(self.list.count() == 0)

    def _accept_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.choice = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    @classmethod
    def pick(cls, parent, title: str, placeholder: str, items: list, initial: str = ""):
        dialog = cls(parent, title, placeholder, items, initial)
        if parent is not None:
            geometry = parent.geometry()
            dialog.move(geometry.center().x() - dialog.width() // 2, geometry.top() + 70)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.choice
        return None


class DiffHighlighter(QSyntaxHighlighter):
    """Colours unified-diff text."""

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if text.startswith(("+++", "---")):
            self.setFormat(0, len(text), _fmt("#9cdcfe", bold=True))
        elif text.startswith("@@"):
            self.setFormat(0, len(text), _fmt("#c586c0"))
        elif text.startswith("+"):
            fmt = _fmt("#b5e8a8")
            fmt.setBackground(QColor("#16341c"))
            self.setFormat(0, len(text), fmt)
        elif text.startswith("-"):
            fmt = _fmt("#f2a7a7")
            fmt.setBackground(QColor("#3a1a1a"))
            self.setFormat(0, len(text), fmt)
        elif text.startswith(("diff ", "index ", "new file", "deleted file", "commit ", "Author:", "Date:")):
            self.setFormat(0, len(text), _fmt("#8b8b8b"))


class DiffDialog(QDialog):
    """Read-only unified-diff viewer."""

    def __init__(self, parent, title: str, diff_text: str, open_path: Path | None = None,
                 owner=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        header.addWidget(label, 1)
        added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
        stats = QLabel(f"<span style='color:#4ec9b0'>+{added}</span>  "
                       f"<span style='color:#f14c4c'>−{removed}</span>")
        header.addWidget(stats)
        layout.addLayout(header)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(monospace_font(10))
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setPlainText(diff_text if diff_text.strip() else "No differences.")
        self.highlighter = DiffHighlighter(self.view.document())
        layout.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if open_path is not None and owner is not None and Path(open_path).exists():
            open_button = QPushButton("Open File")
            open_button.clicked.connect(lambda: (owner.open_file(open_path), self.accept()))
            buttons.addWidget(open_button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


def unified_diff_text(old: str, new: str, old_name: str, new_name: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=old_name, tofile=new_name, n=3,
    ))


def section_header(title: str, *widgets) -> QFrame:
    """Panel header strip matching the existing panels (title on the left, tools on the right)."""
    header = QFrame()
    header.setStyleSheet("QFrame { background: #252526; border-bottom: 1px solid #2b2b2b; }")
    row = QHBoxLayout(header)
    row.setContentsMargins(10, 4, 6, 4)
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    row.addWidget(label)
    row.addStretch(1)
    for widget in widgets:
        row.addWidget(widget)
    return header


def tool_button(text: str, tip: str, slot) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda _checked=False: slot())
    return button


class PanelHub(QTabWidget):
    """A dock body made of several panels, shown as tabs (keeps the saved dock layout valid)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setTabPosition(QTabWidget.TabPosition.North)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabBar().setExpanding(False)
        self.tabBar().setStyleSheet(
            "QTabBar::tab { padding: 5px 10px; font-size: 11px; background: #181818; color: #9d9d9d;"
            " border: none; border-bottom: 2px solid transparent; }"
            "QTabBar::tab:selected { color: #ffffff; background: #1e1e1e; border-bottom: 2px solid #007acc; }"
            "QTabBar::tab:hover { color: #ffffff; }"
        )

    def set_badge(self, widget: QWidget, text: str) -> None:
        index = self.indexOf(widget)
        if index >= 0:
            base = widget.property("hub_title") or self.tabText(index).split("  ")[0]
            self.setTabText(index, f"{base}  {text}" if text else base)


class ProjectLintWorker(QThread):
    """Checks every Python/JSON file in the project for syntax errors and lint warnings."""

    file_done = pyqtSignal(str, object)
    finished_scan = pyqtSignal(int, int)

    def __init__(self, root: Path, parent=None) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        scanned = problems = 0
        for path in iter_project_files(self.root, limit=6000):
            if self._stop:
                break
            suffix = path.suffix.lower()
            if suffix not in PYTHON_SUFFIXES and suffix != ".json":
                continue
            try:
                if path.stat().st_size > 800_000:
                    continue
                text, _encoding = read_text_file(path)
            except Exception:
                continue
            scanned += 1
            diagnostics = (analyze_python(text, path, collect_warnings=False)
                           if suffix in PYTHON_SUFFIXES else analyze_json(text))
            if diagnostics:
                problems += len(diagnostics)
                self.file_done.emit(str(path), diagnostics)
        self.finished_scan.emit(scanned, problems)


class PyflakesWorker(QThread):
    """Optional deep lint: runs ``python -m pyflakes`` from the configured interpreter."""

    done = pyqtSignal(object, int, object)    # tab, revision, diagnostics | None (unavailable)

    def __init__(self, tab, revision: int, interpreter: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.tab = tab
        self.revision = revision
        self.interpreter = interpreter
        self.text = text

    def run(self) -> None:
        rc, out, err = run_hidden([self.interpreter, "-m", "pyflakes"], self.text, timeout=15)
        if "No module named" in err and "pyflakes" in err:
            self.done.emit(self.tab, self.revision, None)
            return
        self.done.emit(self.tab, self.revision, parse_pyflakes_output(out + "\n" + err))


class ProblemsPanel(QWidget):
    """VS Code-style Problems view: errors/warnings per file, click to jump."""

    counts_changed = pyqtSignal(int, int, int)

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setProperty("hub_title", "Problems")
        self.open_files: dict[str, tuple[str, Path | None, list]] = {}
        self.scan_files: dict[str, list] = {}
        self.scan_worker: ProjectLintWorker | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.rebuild)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.summary = QLabel("No problems")
        self.summary.setObjectName("hint")
        self.only_current = QCheckBox("Current file")
        self.only_current.setToolTip("Show only the active editor's problems")
        self.only_current.toggled.connect(lambda _on: self.schedule_rebuild())
        scan = tool_button("Scan project", "Check every .py / .json file in the project", self.scan_project)
        clear = tool_button("✕", "Forget project scan results", self.clear_scan)
        layout.addWidget(section_header("PROBLEMS", self.summary, self.only_current, scan, clear))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget { background: #1e1e1e; border: none; }")
        self.tree.itemActivated.connect(self._open_item)
        self.tree.itemClicked.connect(self._open_item)
        layout.addWidget(self.tree, 1)
        self.empty = QLabel("✔  No problems detected in the open files.\n"
                            "Use “Scan project” to check every Python and JSON file.")
        self.empty.setObjectName("hint")
        self.empty.setContentsMargins(14, 10, 14, 10)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

    # ------------------------------------------------------------------ data
    def set_file(self, key: str, label: str, path: Path | None, diagnostics: list) -> None:
        if diagnostics:
            self.open_files[key] = (label, path, list(diagnostics))
        else:
            self.open_files.pop(key, None)
        self.schedule_rebuild()

    def forget_file(self, key: str) -> None:
        if self.open_files.pop(key, None) is not None:
            self.schedule_rebuild()

    def schedule_rebuild(self) -> None:
        self._timer.start()

    def _merged(self) -> list[tuple[str, str, Path | None, list]]:
        rows = [(key, label, path, diags) for key, (label, path, diags) in self.open_files.items()]
        open_keys = set(self.open_files)
        for key, diags in self.scan_files.items():
            if key not in open_keys and not self._is_open_clean(key):
                rows.append((key, Path(key).name, Path(key), diags))
        current = self.owner.active_editor_tab() if hasattr(self.owner, "tabs") else None
        if self.only_current.isChecked():
            current_key = str(current.path) if current is not None and current.path else None
            rows = [row for row in rows if row[0] == current_key]
        return rows

    def _is_open_clean(self, key: str) -> bool:
        """A file that is open in an editor and currently clean must not show stale scan results."""
        try:
            index, _tab = self.owner._find_tab_for_path(Path(key))
        except Exception:
            return False
        return index >= 0

    def totals(self) -> tuple[int, int, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for _key, _label, _path, diags in self._merged():
            for diag in diags:
                counts[diag.severity] = counts.get(diag.severity, 0) + 1
        return counts["error"], counts["warning"], counts["info"]

    def rebuild(self) -> None:
        self.tree.clear()
        rows = sorted(self._merged(), key=lambda row: row[1].lower())
        for _key, label, path, diags in rows:
            top = QTreeWidgetItem([f"{label}   ({len(diags)})"])
            top.setToolTip(0, str(path) if path else label)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for diag in sorted(diags, key=lambda d: (SEVERITY_ORDER[d.severity], d.line, d.col)):
                child = QTreeWidgetItem([f"{SEVERITY_ICON[diag.severity]}  {diag.message}   "
                                         f"[Ln {diag.line + 1}, Col {diag.col + 1}]"])
                child.setForeground(0, QColor(SEVERITY_COLOR[diag.severity]))
                child.setToolTip(0, f"{diag.message}\n{diag.source} {diag.code}".strip())
                child.setData(0, Qt.ItemDataRole.UserRole, (str(path) if path else "", diag.line, diag.col))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(len(rows) <= 6 or any(d.severity == "error" for d in diags))
        errors, warnings_, infos = self.totals()
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings_:
            parts.append(f"{warnings_} warning{'s' if warnings_ != 1 else ''}")
        if infos:
            parts.append(f"{infos} hint{'s' if infos != 1 else ''}")
        self.summary.setText(", ".join(parts) if parts else "No problems")
        self.empty.setVisible(not rows)
        self.counts_changed.emit(errors, warnings_, infos)

    # ------------------------------------------------------------------ actions
    def _open_item(self, item, _column: int = 0) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            item.setExpanded(not item.isExpanded())
            return
        path, line, col = data
        if path:
            tab = self.owner.open_file(Path(path))
            if tab is not None and getattr(tab, "KIND", "") == "text":
                tab.goto_line(line + 1, col)

    def scan_project(self) -> None:
        root = self.owner.explorer.project_root
        if not root:
            QMessageBox.information(self, APP_NAME, "Open a project folder first.")
            return
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.scan_worker.wait(1500)
        self.scan_files = {}
        self.summary.setText("Scanning…")
        worker = ProjectLintWorker(Path(root), self)
        worker.file_done.connect(self._scan_file)
        worker.finished_scan.connect(self._scan_finished)
        self.scan_worker = worker
        worker.start()

    def _scan_file(self, path: str, diagnostics) -> None:
        self.scan_files[path] = diagnostics
        self.schedule_rebuild()

    def _scan_finished(self, scanned: int, problems: int) -> None:
        self.rebuild()
        self.owner.flash(f"Project scan: {scanned} files checked, {problems} problem(s) found.")

    def clear_scan(self) -> None:
        self.scan_files = {}
        self.rebuild()

    def shutdown(self) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.scan_worker.wait(1500)


TODO_PATTERN = re.compile(
    r"(?:#|//|/\*|<!--|--|;|%|\*)\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|OPTIMIZE)\b\s*[:\-(]?\s*(.*)")
TODO_COLORS = {"TODO": "#4fc1ff", "FIXME": "#f14c4c", "BUG": "#f14c4c", "HACK": "#ce9178",
               "XXX": "#ce9178", "NOTE": "#9cdcfe", "OPTIMIZE": "#dcdcaa"}


class TodoScanWorker(QThread):
    found = pyqtSignal(str, int, str, str)
    finished_scan = pyqtSignal(int)

    def __init__(self, root: Path, parent=None) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        total = 0
        for path in iter_project_files(self.root, limit=12000):
            if self._stop or total >= 3000:
                break
            if not is_probably_text_path(path):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                text, _enc = read_text_file(path)
            except Exception:
                continue
            if "TODO" not in text and "FIXME" not in text and "HACK" not in text and "XXX" not in text \
                    and "BUG" not in text and "NOTE" not in text and "OPTIMIZE" not in text:
                continue
            for number, line in enumerate(text.splitlines()):
                match = TODO_PATTERN.search(line)
                if match:
                    total += 1
                    self.found.emit(str(path), number, match.group(1), match.group(2).strip()[:200])
        self.finished_scan.emit(total)


class TodoPanel(QWidget):
    """TODO / FIXME / HACK tracker for the whole project."""

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setProperty("hub_title", "TODO")
        self.worker: TodoScanWorker | None = None
        self.entries: dict[str, list[tuple[int, str, str]]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        self.filter = QComboBox()
        self.filter.addItems(["All", "TODO", "FIXME", "BUG", "HACK", "XXX", "NOTE", "OPTIMIZE"])
        self.filter.currentTextChanged.connect(lambda _t: self.rebuild())
        refresh = tool_button("⟳", "Scan the project for TODO / FIXME comments", self.scan)
        layout.addWidget(section_header("TODO", self.summary, self.filter, refresh))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget { background: #1e1e1e; border: none; }")
        self.tree.itemActivated.connect(self._open_item)
        self.tree.itemClicked.connect(self._open_item)
        layout.addWidget(self.tree, 1)
        self.empty = QLabel("Press ⟳ to find TODO, FIXME, HACK and BUG comments across the project.")
        self.empty.setObjectName("hint")
        self.empty.setContentsMargins(14, 10, 14, 10)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

    def scan(self) -> None:
        root = self.owner.explorer.project_root
        if not root:
            QMessageBox.information(self, APP_NAME, "Open a project folder first.")
            return
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        self.entries = {}
        self.summary.setText("Scanning…")
        worker = TodoScanWorker(Path(root), self)
        worker.found.connect(self._found)
        worker.finished_scan.connect(self._finished)
        self.worker = worker
        worker.start()

    def _found(self, path: str, line: int, tag: str, text: str) -> None:
        self.entries.setdefault(path, []).append((line, tag, text))

    def _finished(self, total: int) -> None:
        self.rebuild()
        self.empty.setText("🎉  Nothing to do — no TODO/FIXME comments found." if not total else "")

    def rebuild(self) -> None:
        self.tree.clear()
        wanted = self.filter.currentText()
        shown = 0
        root = Path(self.owner.explorer.project_root) if self.owner.explorer.project_root else None
        for path, rows in sorted(self.entries.items()):
            rows = [row for row in rows if wanted == "All" or row[1] == wanted]
            if not rows:
                continue
            try:
                label = str(Path(path).relative_to(root)) if root else Path(path).name
            except ValueError:
                label = Path(path).name
            top = QTreeWidgetItem([f"{label}   ({len(rows)})"])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for line, tag, text in rows:
                child = QTreeWidgetItem([f"{tag}  {text}   [Ln {line + 1}]"])
                child.setForeground(0, QColor(TODO_COLORS.get(tag, "#cccccc")))
                child.setData(0, Qt.ItemDataRole.UserRole, (path, line))
                top.addChild(child)
                shown += 1
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.summary.setText(f"{shown} item{'s' if shown != 1 else ''}" if self.entries else "")
        self.empty.setVisible(shown == 0)
        if shown == 0 and self.entries:
            self.empty.setText("No items match this filter.")

    def _open_item(self, item, _column: int = 0) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            item.setExpanded(not item.isExpanded())
            return
        path, line = data
        tab = self.owner.open_file(Path(path))
        if tab is not None and getattr(tab, "KIND", "") == "text":
            tab.goto_line(line + 1)

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)


GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GCM_INTERACTIVE": "never",
           "GIT_EDITOR": "true", "GIT_MERGE_AUTOEDIT": "no"}
GIT_STATUS_COLORS = {"M": "#e2c08d", "A": "#73c991", "D": "#c74e39", "R": "#73c991", "C": "#73c991",
                     "U": "#73c991", "!": "#e51400", "T": "#e2c08d"}


class GitWorker(QThread):
    """Runs one git command off the UI thread."""

    done = pyqtSignal(str, int, str, str, object)

    def __init__(self, tag: str, args: list, cwd: str, extra=None, timeout: float = 60.0,
                 parent=None) -> None:
        super().__init__(parent)
        self.tag = tag
        self.args = args
        self.cwd = cwd
        self.extra = extra
        self.timeout = timeout

    def run(self) -> None:
        rc, out, err = run_hidden(["git", "-c", "core.quotepath=off", *self.args], None,
                                  self.cwd, self.timeout, GIT_ENV)
        self.done.emit(self.tag, rc, out, err, self.extra)


def parse_git_status(raw: str) -> tuple[dict, list]:
    """Parse ``git status --porcelain=v1 -b -z`` into (branch info, [(x, y, path, orig)])."""
    branch = {"name": "", "upstream": "", "ahead": 0, "behind": 0, "detached": False, "unborn": False}
    entries: list[tuple[str, str, str, str | None]] = []
    records = raw.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("## "):
            text = record[3:]
            if text.startswith("No commits yet on "):
                branch["name"] = text[len("No commits yet on "):]
                branch["unborn"] = True
            elif text.startswith("HEAD (no branch)"):
                branch["name"] = "HEAD"
                branch["detached"] = True
            else:
                head, _sep, rest = text.partition("...")
                if not _sep:
                    head = text.split(" [")[0]
                branch["name"] = head
                if rest:
                    branch["upstream"] = rest.split(" [")[0]
                    ahead = re.search(r"ahead (\d+)", rest)
                    behind = re.search(r"behind (\d+)", rest)
                    branch["ahead"] = int(ahead.group(1)) if ahead else 0
                    branch["behind"] = int(behind.group(1)) if behind else 0
            continue
        if len(record) < 4:
            continue
        x, y, path = record[0], record[1], record[3:]
        orig = None
        if x in "RC" or y in "RC":
            orig = records[index] if index < len(records) else None
            index += 1
        entries.append((x, y, path, orig))
    return branch, entries


def parse_diff_marks(diff_text: str) -> dict:
    """Turn ``git diff -U0`` hunks into {zero-based line: 'add'|'mod'|'del'}."""
    marks: dict[int, str] = {}
    for match in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff_text, re.M):
        old_len = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_len = int(match.group(4)) if match.group(4) is not None else 1
        if new_len == 0:
            marks.setdefault(max(0, new_start - 1), "del")
        else:
            kind = "add" if old_len == 0 else "mod"
            for line in range(new_start - 1, new_start - 1 + new_len):
                marks[line] = kind
    return marks


class _MessageEdit(QPlainTextEdit):
    submit = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.submit.emit()
            return
        super().keyPressEvent(event)


class GitPanel(QWidget):
    """Source Control: branch, stage/unstage, commit, pull/push, history and diffs."""

    branch_changed = pyqtSignal(str, int)       # status-bar text, number of changed files

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setProperty("hub_title", "Source Control")
        self.git_exe = shutil.which("git")
        self.repo_root: Path | None = None
        self.state = "none"                    # none | nogit | norepo | repo
        self.branch: dict = {}
        self.branches: list[str] = []
        self.untracked: set[str] = set()
        self.workers: set[GitWorker] = set()
        self.has_commits = True
        self.busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.branch_button = QToolButton()
        self.branch_button.setText("⎇ —")
        self.branch_button.setToolTip("Switch branch")
        self.branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.branch_button.clicked.connect(self.show_branch_menu)
        refresh = tool_button("⟳", "Refresh status", self.refresh)
        layout.addWidget(section_header("SOURCE CONTROL", self.branch_button, refresh))

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # ---- page 0: informational state ----------------------------------------
        info_page = QWidget()
        info_layout = QVBoxLayout(info_page)
        info_layout.setContentsMargins(14, 14, 14, 14)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("hint")
        info_layout.addWidget(self.info_label)
        self.init_button = QPushButton("Initialize Repository")
        self.init_button.clicked.connect(self.init_repo)
        info_layout.addWidget(self.init_button)
        info_layout.addStretch(1)
        self.stack.addWidget(info_page)

        # ---- page 1: repository ------------------------------------------------------
        repo_page = QWidget()
        repo_layout = QVBoxLayout(repo_page)
        repo_layout.setContentsMargins(8, 8, 8, 8)
        repo_layout.setSpacing(6)
        self.message = _MessageEdit()
        self.message.setPlaceholderText("Commit message  (Ctrl+Enter to commit)")
        self.message.setFixedHeight(64)
        self.message.submit.connect(self.commit)
        repo_layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.commit_button = QPushButton("✓ Commit")
        self.commit_button.setToolTip("Commit the staged changes")
        self.commit_button.clicked.connect(self.commit)
        buttons.addWidget(self.commit_button, 1)
        for text, tip, slot in (("↓", "Pull", self.pull), ("↑", "Push", self.push)):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, s=slot: s())
            buttons.addWidget(button)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("More git actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Fetch", self.fetch)
        menu.addAction("New Branch…", self.new_branch)
        menu.addSeparator()
        menu.addAction("Stash Changes", self.stash)
        menu.addAction("Pop Latest Stash", self.stash_pop)
        menu.addSeparator()
        menu.addAction("Amend Last Commit (keep message)", self.amend)
        menu.addAction("Stage All", self.stage_all)
        menu.addAction("Unstage All", self.unstage_all)
        more.setMenu(menu)
        buttons.addWidget(more)
        repo_layout.addLayout(buttons)

        actions = QHBoxLayout()
        for text, tip, slot in (("＋ Stage", "Stage the selected files", self.stage_selected),
                                ("－ Unstage", "Unstage the selected files", self.unstage_selected),
                                ("↶ Discard", "Discard changes in the selected files", self.discard_selected)):
            actions.addWidget(tool_button(text, tip, slot))
        actions.addStretch(1)
        repo_layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemDoubleClicked.connect(self._open_diff_for_item)
        self.tree.setStyleSheet("QTreeWidget { background: #1e1e1e; border: 1px solid #2b2b2b; }")
        splitter.addWidget(self.tree)
        self.history = QListWidget()
        self.history.setStyleSheet("QListWidget { background: #1e1e1e; border: 1px solid #2b2b2b; }")
        self.history.itemDoubleClicked.connect(self._open_commit)
        splitter.addWidget(self.history)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        repo_layout.addWidget(splitter, 1)
        self.stack.addWidget(repo_page)

        self._poll = QTimer(self)
        self._poll.setInterval(20000)
        self._poll.timeout.connect(self._auto_refresh)
        self._poll.start()
        self._show_info("Open a project folder to use Source Control.", init=False)

    # ------------------------------------------------------------------ plumbing
    def _project_root(self) -> Path | None:
        root = self.owner.explorer.project_root if hasattr(self.owner, "explorer") else None
        return Path(root) if root else None

    def _show_info(self, text: str, init: bool) -> None:
        self.info_label.setText(text)
        self.init_button.setVisible(init)
        self.stack.setCurrentIndex(0)

    def _git(self, tag: str, args: list, extra=None, timeout: float = 60.0, cwd: Path | None = None) -> None:
        directory = cwd or self.repo_root or self._project_root()
        if directory is None or not self.git_exe:
            return
        worker = GitWorker(tag, args, str(directory), extra, timeout, self)
        worker.done.connect(self._on_done)
        worker.finished.connect(lambda w=worker: self.workers.discard(w))
        self.workers.add(worker)
        worker.start()

    def _auto_refresh(self) -> None:
        if self.isVisible() and self.state == "repo" and not self.busy:
            self.refresh(quiet=True)

    def refresh(self, quiet: bool = False) -> None:
        root = self._project_root()
        if root is None:
            self.state = "none"
            self._show_info("Open a project folder to use Source Control.", init=False)
            self.branch_button.setText("⎇ —")
            self.branch_changed.emit("", 0)
            return
        if not self.git_exe:
            self.state = "nogit"
            self._show_info("Git was not found on this computer.\nInstall it from git-scm.com and "
                            "restart PyForge IDE.", init=False)
            self.branch_changed.emit("", 0)
            return
        self._git("toplevel", ["rev-parse", "--show-toplevel"], extra=quiet, cwd=root)

    # ------------------------------------------------------------------ result dispatch
    def _on_done(self, tag: str, rc: int, out: str, err: str, extra) -> None:
        if tag == "toplevel":
            if rc == 0 and out.strip():
                self.repo_root = Path(out.strip())
                self.state = "repo"
                self._git("status", ["status", "--porcelain=v1", "-b", "-z", "-uall"])
                self._git("log", ["log", "-n", "40", "--pretty=format:%h%x1f%s%x1f%an%x1f%ar%x1f%d"])
                self._git("branches", ["branch", "--format=%(refname:short)"])
            else:
                self.repo_root = None
                self.state = "norepo"
                self.branch_button.setText("⎇ —")
                self._show_info("This folder is not a git repository yet.", init=True)
                self.branch_changed.emit("", 0)
                self._clear_marks()
        elif tag == "status" and rc == 0:
            self._apply_status(out)
        elif tag == "log":
            self._apply_log(out if rc == 0 else "")
        elif tag == "branches" and rc == 0:
            self.branches = [line.strip() for line in out.splitlines() if line.strip()]
        elif tag in ("marks", "marks-unborn"):
            tab = extra
            try:
                if self.owner.tabs.indexOf(tab) < 0:
                    return
            except RuntimeError:
                return
            if rc != 0 and tag == "marks" and ("HEAD" in err or "revision" in err):
                self._git("marks-unborn", ["diff", "-U0", "--no-color", "--", extra.path_rel], extra=tab)
                return
            tab.editor.set_git_marks(parse_diff_marks(out) if rc == 0 else {})
        elif tag == "diff":
            title, path = extra
            DiffDialog(self.owner, title, out if rc == 0 else err, path, self.owner).exec()
        elif tag == "show":
            DiffDialog(self.owner, extra, out if rc == 0 else err).exec()
        elif tag.startswith("op:"):
            self.busy = False
            label = tag[3:]
            if rc == 0:
                summary = (out.strip().splitlines() or err.strip().splitlines() or [""])[-1]
                self.owner.flash(f"git {label}: {summary}"[:160] if summary else f"git {label} done.")
                if label == "commit":
                    self.message.clear()
            else:
                detail = (err.strip() or out.strip() or "unknown error")
                if label == "push" and "no upstream branch" in detail:
                    self._offer_upstream()
                else:
                    QMessageBox.warning(self.owner, f"git {label} failed", detail[:1500])
            self.refresh(quiet=True)

    # ------------------------------------------------------------------ status / history views
    def _apply_status(self, raw: str) -> None:
        branch, entries = parse_git_status(raw)
        self.branch = branch
        self.has_commits = not branch.get("unborn", False)
        self.untracked = {path for x, _y, path, _o in entries if x == "?"}
        self.tree.clear()
        groups = {"conflict": [], "staged": [], "changes": [], "untracked": []}
        for x, y, path, orig in entries:
            if x == "?":
                groups["untracked"].append(("U", path, orig))
            elif x == "U" or y == "U" or (x == y and x in "AD"):
                groups["conflict"].append(("!", path, orig))
            else:
                if x not in " ?!":
                    groups["staged"].append((x, path, orig))
                if y not in " ?!":
                    groups["changes"].append((y, path, orig))
        titles = {"conflict": "Merge Conflicts", "staged": "Staged Changes",
                  "changes": "Changes", "untracked": "Untracked Files"}
        for key in ("conflict", "staged", "changes", "untracked"):
            rows = groups[key]
            if not rows:
                continue
            top = QTreeWidgetItem([f"{titles[key]}   ({len(rows)})"])
            top.setData(0, Qt.ItemDataRole.UserRole, ("group", key))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for code, path, orig in sorted(rows, key=lambda row: row[1].lower()):
                name = Path(path).name
                folder = str(Path(path).parent)
                text = f"{code}   {name}" + (f"   ← {orig}" if orig else "") + \
                       (f"    {folder}" if folder != "." else "")
                child = QTreeWidgetItem([text])
                child.setForeground(0, QColor(GIT_STATUS_COLORS.get(code, "#cccccc")))
                child.setToolTip(0, path)
                child.setData(0, Qt.ItemDataRole.UserRole, ("file", key, path))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        total = sum(len(rows) for rows in groups.values())
        name = branch.get("name") or "HEAD"
        arrows = ""
        if branch.get("ahead"):
            arrows += f" ↑{branch['ahead']}"
        if branch.get("behind"):
            arrows += f" ↓{branch['behind']}"
        self.branch_button.setText(f"⎇ {name}{arrows}")
        self.branch_button.setToolTip(
            f"Branch: {name}" + (f"\nTracking: {branch['upstream']}" if branch.get("upstream") else
                                  "\nNo upstream branch") + "\nClick to switch branch")
        self.stack.setCurrentIndex(1)
        self.commit_button.setText(f"✓ Commit ({len(groups['staged'])})" if groups["staged"] else "✓ Commit")
        self.branch_changed.emit(f"⎇ {name}{arrows}" + (f"  ●{total}" if total else ""), total)
        self.owner.refresh_git_marks()

    def _apply_log(self, raw: str) -> None:
        self.history.clear()
        for line in raw.splitlines():
            parts = line.split("\x1f")
            if len(parts) < 4:
                continue
            short, subject, author, when = parts[:4]
            decorations = parts[4].strip() if len(parts) > 4 else ""
            item = QListWidgetItem(f"{short}  {subject}" + (f"  {decorations}" if decorations else ""))
            item.setToolTip(f"{subject}\n{author} · {when}")
            item.setData(Qt.ItemDataRole.UserRole, short)
            self.history.addItem(item)

    # ------------------------------------------------------------------ editor gutter marks
    def _clear_marks(self) -> None:
        for index in range(self.owner.tabs.count()):
            widget = self.owner.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                widget.editor.set_git_marks({})

    def update_marks(self, tab) -> None:
        if self.state != "repo" or tab is None or getattr(tab, "KIND", "") != "text" or not tab.path \
                or self.repo_root is None:
            if tab is not None and getattr(tab, "KIND", "") == "text":
                tab.editor.set_git_marks({})
            return
        try:
            relative = Path(tab.path).resolve().relative_to(self.repo_root.resolve()).as_posix()
        except (ValueError, OSError):
            tab.editor.set_git_marks({})
            return
        tab.path_rel = relative
        if relative in self.untracked:
            tab.editor.set_git_marks({n: "add" for n in range(tab.editor.blockCount())})
            return
        self._git("marks", ["diff", "HEAD", "-U0", "--no-color", "--", relative], extra=tab, timeout=20)

    # ------------------------------------------------------------------ selection helpers
    def _selected(self, kinds: tuple = ("staged", "changes", "untracked", "conflict")) -> list:
        rows = []
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue
            if data[0] == "file" and data[1] in kinds:
                rows.append((data[1], data[2]))
            elif data[0] == "group" and data[1] in kinds:
                for index in range(item.childCount()):
                    child = item.child(index).data(0, Qt.ItemDataRole.UserRole)
                    rows.append((child[1], child[2]))
        seen, unique = set(), []
        for row in rows:
            if row not in seen:
                seen.add(row)
                unique.append(row)
        return unique

    def _run_op(self, label: str, args: list, timeout: float = 120.0) -> None:
        self.busy = True
        self._git(f"op:{label}", args, timeout=timeout)

    # ------------------------------------------------------------------ operations
    def stage_selected(self) -> None:
        paths = [p for kind, p in self._selected(("changes", "untracked", "conflict"))]
        if paths:
            self._run_op("add", ["add", "--", *paths])

    def stage_all(self) -> None:
        self._run_op("add", ["add", "-A"])

    def unstage_selected(self) -> None:
        paths = [p for _k, p in self._selected(("staged",))]
        if paths:
            self._run_op("unstage", ["restore", "--staged", "--", *paths] if self.has_commits
                         else ["rm", "--cached", "-r", "--", *paths])

    def unstage_all(self) -> None:
        self._run_op("unstage", ["restore", "--staged", "."] if self.has_commits
                     else ["rm", "--cached", "-r", "."])

    def discard_selected(self) -> None:
        rows = self._selected(("changes", "untracked"))
        if not rows:
            return
        names = ", ".join(Path(p).name for _k, p in rows[:4]) + (" …" if len(rows) > 4 else "")
        answer = QMessageBox.question(
            self.owner, "Discard changes",
            f"Discard changes in {len(rows)} file(s)?\n\n{names}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        tracked = [p for kind, p in rows if kind == "changes"]
        for kind, path in rows:
            if kind == "untracked" and self.repo_root is not None:
                target = self.repo_root / path
                try:
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
                except OSError as exc:
                    QMessageBox.warning(self.owner, APP_NAME, f"Could not delete {path}:\n{exc}")
        if tracked:
            self._run_op("discard", ["checkout", "--", *tracked])
        else:
            self.refresh(quiet=True)
            self.owner.explorer.refresh()

    def commit(self) -> None:
        message = self.message.toPlainText().strip()
        if not message:
            self.message.setFocus()
            self.owner.flash("Write a commit message first.")
            return
        staged = any(data and data[0] == "group" and data[1] == "staged"
                     for data in (self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                                  for i in range(self.tree.topLevelItemCount())))
        args = ["commit", "-m", message]
        if not staged:
            answer = QMessageBox.question(
                self.owner, "Nothing staged",
                "There are no staged changes.\n\nStage all changes and commit them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.busy = True
            self._git("op:add", ["add", "-A"], timeout=60)
            QTimer.singleShot(900, lambda: self._run_op("commit", args))
            return
        self.owner.save_all()
        self._run_op("commit", args)

    def amend(self) -> None:
        message = self.message.toPlainText().strip()
        self._run_op("amend", ["commit", "--amend", *(["-m", message] if message else ["--no-edit"])])

    def pull(self) -> None:
        self._run_op("pull", ["pull", "--no-edit"], timeout=180)

    def push(self) -> None:
        self._run_op("push", ["push"], timeout=180)

    def _offer_upstream(self) -> None:
        name = self.branch.get("name") or "HEAD"
        answer = QMessageBox.question(
            self.owner, "No upstream branch",
            f"Branch “{name}” has no upstream yet.\n\nPublish it to 'origin' and track it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            self._run_op("push", ["push", "--set-upstream", "origin", name], timeout=180)

    def fetch(self) -> None:
        self._run_op("fetch", ["fetch", "--all", "--prune"], timeout=180)

    def stash(self) -> None:
        self._run_op("stash", ["stash", "push", "-u", "-m", "PyForge IDE stash"])

    def stash_pop(self) -> None:
        self._run_op("stash pop", ["stash", "pop"])

    def init_repo(self) -> None:
        root = self._project_root()
        if root is None:
            return
        self._git("op:init", ["init"], cwd=root)

    def new_branch(self) -> None:
        name, ok = QInputDialog.getText(self.owner, "New Branch", "Name of the new branch:")
        if ok and name.strip():
            self._run_op("branch", ["checkout", "-b", name.strip()])

    def checkout(self, name: str) -> None:
        self._run_op("checkout", ["checkout", name])

    def show_branch_menu(self) -> None:
        if self.state != "repo":
            self.owner.flash("Open a git repository to switch branches.")
            return
        menu = QMenu(self)
        current = self.branch.get("name")
        for name in self.branches or [current or "HEAD"]:
            action = menu.addAction(("✓  " if name == current else "     ") + name)
            action.triggered.connect(lambda _c=False, n=name: self.checkout(n) if n != current else None)
        menu.addSeparator()
        menu.addAction("＋ New Branch…", self.new_branch)
        menu.exec(self.branch_button.mapToGlobal(self.branch_button.rect().bottomLeft()))

    # ------------------------------------------------------------------ diffs / menus
    def _diff_for(self, kind: str, path: str) -> None:
        title = f"{path}  ({'staged' if kind == 'staged' else 'working tree'})"
        absolute = (self.repo_root / path) if self.repo_root else None
        if kind == "untracked":
            try:
                content = Path(absolute).read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            text = unified_diff_text("", content, "/dev/null", path)
            DiffDialog(self.owner, title + " — new file", text, absolute, self.owner).exec()
            return
        args = ["diff", "--no-color", *(["--cached"] if kind == "staged" else []), "--", path]
        self._git("diff", args, extra=(title, absolute))

    def _open_diff_for_item(self, item, _column: int = 0) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            self._diff_for(data[1], data[2])

    def _open_commit(self, item) -> None:
        short = item.data(0, Qt.ItemDataRole.UserRole)
        if short:
            self._git("show", ["show", "--stat", "--patch", "--no-color", short],
                      extra=f"Commit {short}")

    def _tree_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if data and data[0] == "file":
            kind, path = data[1], data[2]
            menu.addAction("Open File", lambda: self.owner.open_file(self.repo_root / path))
            menu.addAction("Show Diff", lambda: self._diff_for(kind, path))
            menu.addSeparator()
            if kind == "staged":
                menu.addAction("Unstage", self.unstage_selected)
            else:
                menu.addAction("Stage", self.stage_selected)
            if kind in ("changes", "untracked"):
                menu.addAction("Discard Changes", self.discard_selected)
        elif data and data[0] == "group":
            if data[1] == "staged":
                menu.addAction("Unstage All", self.unstage_all)
            else:
                menu.addAction("Stage All", self.stage_all)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def show_file_history_diff(self, path: Path | None) -> None:
        """Diff of the whole active file against HEAD (used by the menu)."""
        if self.state != "repo" or path is None or self.repo_root is None:
            self.owner.flash("Not inside a git repository.")
            return
        try:
            relative = Path(path).resolve().relative_to(self.repo_root.resolve()).as_posix()
        except ValueError:
            self.owner.flash("This file is outside the repository.")
            return
        self._git("diff", ["diff", "HEAD", "--no-color", "--", relative],
                  extra=(f"{relative}  (vs HEAD)", Path(path)))

    def shutdown(self) -> None:
        self._poll.stop()
        for worker in list(self.workers):
            worker.wait(1500)


class TestStreamWorker(QThread):
    """Runs a test command and streams its output line by line."""

    line = pyqtSignal(str)
    finished_run = pyqtSignal(int)

    def __init__(self, args: list, cwd: str, parent=None) -> None:
        super().__init__(parent)
        self.args = args
        self.cwd = cwd
        self.proc = None
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self.proc = subprocess.Popen(
                self.args, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.line.emit(f"Could not start the test run: {exc}")
            self.finished_run.emit(127)
            return
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            if self._stop:
                break
            self.line.emit(raw.rstrip("\n"))
        try:
            code = self.proc.wait(timeout=5)
        except Exception:
            code = -1
        self.finished_run.emit(code)


TEST_RESULT_LINE = re.compile(
    r"^(?:\[gw\d+\]\s+)?(?P<id>\S.*?::\S.*?)\s+(?P<res>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
TEST_SUMMARY_LINE = re.compile(r"^(FAILED|ERROR)\s+(?P<id>[^\s:]+\.py(?:::\S.*?)?)(?:\s+-\s+.*)?$")
UNITTEST_LINE = re.compile(r"^(?P<name>\w+) \((?P<where>[\w\.]+)\)(?:.*)? \.\.\. (?P<res>ok|FAIL|ERROR|skipped.*)$")
TEST_ICONS = {"PASSED": ("✔", "#4ec9b0"), "FAILED": ("✖", "#f14c4c"), "ERROR": ("✖", "#f14c4c"),
              "SKIPPED": ("⊘", "#cca700"), "XFAIL": ("⊘", "#cca700"), "XPASS": ("✔", "#cca700"),
              "RUNNING": ("●", "#3794ff"), "IDLE": ("○", "#8b8b8b")}


class TestsPanel(QWidget):
    """Test explorer: discover with pytest, run all / selected / failed, jump to failures."""

    __test__ = False          # keep pytest from collecting this class by name

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setProperty("hub_title", "Tests")
        self.items: dict[str, QTreeWidgetItem] = {}
        self.results: dict[str, str] = {}
        self.stream: TestStreamWorker | None = None
        self.discovery: FuncWorker | None = None
        self.started_at = 0.0
        self.pytest_missing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        tools = [
            tool_button("▶ All", "Run every test", self.run_all),
            tool_button("▶ Selected", "Run the selected tests", self.run_selected),
            tool_button("↻ Failed", "Re-run the tests that failed", self.run_failed),
            tool_button("■", "Stop the running tests", self.stop),
            tool_button("⟳", "Discover tests", self.discover),
        ]
        layout.addWidget(section_header("TESTS", self.summary, *tools))
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setObjectName("hint")
        self.message.setContentsMargins(12, 6, 12, 6)
        self.message.hide()
        layout.addWidget(self.message)
        self.install_button = QPushButton("Install pytest in the selected interpreter")
        self.install_button.clicked.connect(self.install_pytest)
        self.install_button.hide()
        layout.addWidget(self.install_button)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setStyleSheet("QTreeWidget { background: #1e1e1e; border: none; }")
        self.tree.itemActivated.connect(self._open_test)
        splitter.addWidget(self.tree)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(monospace_font(9))
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setPlaceholderText("Test output appears here.")
        splitter.addWidget(self.output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------ helpers
    def _root(self) -> Path | None:
        root = self.owner.explorer.project_root
        return Path(root) if root else None

    def _need_root(self) -> Path | None:
        root = self._root()
        if root is None:
            QMessageBox.information(self, APP_NAME, "Open a project folder first.")
        return root

    def _running(self) -> bool:
        return self.stream is not None and self.stream.isRunning()

    def _set_status(self, node_id: str, status: str) -> None:
        item = self.items.get(node_id)
        if item is None:
            return
        icon, color = TEST_ICONS.get(status, TEST_ICONS["IDLE"])
        name = item.data(0, Qt.ItemDataRole.UserRole + 1) or node_id
        item.setText(0, f"{icon}  {name}")
        item.setForeground(0, QColor(color))
        self.results[node_id] = status
        parent = item.parent()
        while parent is not None:                      # roll the worst child status up
            states = [self.results.get(parent.child(i).data(0, Qt.ItemDataRole.UserRole), "IDLE")
                      for i in range(parent.childCount())]
            worst = ("FAILED" if any(s in ("FAILED", "ERROR") for s in states) else
                     "RUNNING" if "RUNNING" in states else
                     "PASSED" if states and all(s in ("PASSED", "SKIPPED", "XFAIL", "XPASS") for s in states)
                     else "IDLE")
            icon, color = TEST_ICONS[worst]
            label = parent.data(0, Qt.ItemDataRole.UserRole + 1)
            parent.setText(0, f"{icon}  {label}")
            parent.setForeground(0, QColor(color))
            self.results[parent.data(0, Qt.ItemDataRole.UserRole)] = worst
            parent = parent.parent()

    def _ensure_item(self, node_id: str) -> QTreeWidgetItem:
        if node_id in self.items:
            return self.items[node_id]
        parts = node_id.split("::")
        parent_item = None
        built = ""
        for index, part in enumerate(parts):
            built = part if not built else f"{built}::{part}"
            item = self.items.get(built)
            if item is None:
                item = QTreeWidgetItem([f"○  {part}"])
                item.setData(0, Qt.ItemDataRole.UserRole, built)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, part)
                item.setForeground(0, QColor("#8b8b8b"))
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                item.setExpanded(index < len(parts) - 1 and index == 0)
                self.items[built] = item
            parent_item = item
        return parent_item

    def _show_message(self, text: str, install: bool = False) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.install_button.setVisible(install)

    # ------------------------------------------------------------------ discovery
    def discover(self) -> None:
        root = self._need_root()
        if root is None:
            return
        interpreter = self.owner._interpreter()
        self.summary.setText("Discovering…")
        self._show_message("")

        def work():
            return run_hidden([interpreter, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                               "--color=no"], None, str(root), timeout=90)

        self.discovery = FuncWorker(work, self)
        self.discovery.result.connect(self._discovered)
        self.discovery.start()

    def _discovered(self, outcome) -> None:
        if isinstance(outcome, Exception):
            self.summary.setText("")
            self._show_message(f"Test discovery failed: {outcome}")
            return
        rc, out, err = outcome
        combined = out + "\n" + err
        if "No module named pytest" in combined:
            self.pytest_missing = True
            self.summary.setText("pytest missing")
            self._show_message("pytest is not installed in the selected interpreter.\n"
                               "You can still use Run All — it falls back to unittest.", install=True)
            return
        self.pytest_missing = False
        self.tree.clear()
        self.items.clear()
        self.results.clear()
        count = 0
        for line in out.splitlines():
            line = line.strip()
            if "::" in line and not line.startswith(("=", "-", " ")) and " " not in line.split("::")[0]:
                self._ensure_item(line)
                count += 1
        self.summary.setText(f"{count} test{'s' if count != 1 else ''}")
        if count == 0:
            tail = [ln for ln in combined.splitlines() if ln.strip()][-3:]
            self._show_message("No tests were found.\n" + "\n".join(tail))
        else:
            self._show_message("")

    def install_pytest(self) -> None:
        interpreter = self.owner._interpreter()
        self.owner.show_terminal()
        self.owner.terminal.run_command(
            build_command(interpreter, "-m pip install pytest", self.owner.terminal_shell_path()))
        self.owner.flash("Installing pytest… press ⟳ in the Tests panel when it finishes.")

    # ------------------------------------------------------------------ running
    def run_all(self) -> None:
        self._run([])

    def run_selected(self) -> None:
        ids = []
        for item in self.tree.selectedItems():
            ids.append(item.data(0, Qt.ItemDataRole.UserRole))
        if not ids:
            self.owner.flash("Select one or more tests first.")
            return
        self._run(ids)

    def run_failed(self) -> None:
        ids = [node for node, status in self.results.items()
               if status in ("FAILED", "ERROR") and "::" in node and not self.items[node].childCount()]
        if not ids:
            self.owner.flash("No failed tests to re-run.")
            return
        self._run(ids)

    def run_file(self, path: Path) -> None:
        root = self._root()
        if root is None:
            return
        try:
            node = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            node = str(path)
        self._run([node])

    def stop(self) -> None:
        if self._running():
            self.stream.stop()
            self.owner.flash("Stopping the test run…")

    def _run(self, targets: list) -> None:
        root = self._need_root()
        if root is None or self._running():
            return
        self.owner.save_all()
        interpreter = self.owner._interpreter()
        self.output.clear()
        for node in (targets or list(self.items)):
            if node in self.items:
                self._set_status(node, "RUNNING")
        if self.pytest_missing:
            args = [interpreter, "-m", "unittest", "discover", "-v"]
        else:
            args = [interpreter, "-m", "pytest", "-v", "--color=no", "-p", "no:cacheprovider",
                    "--tb=short", "-rfE", *targets]
        self.output.appendPlainText("$ " + " ".join(args) + "\n")
        self.started_at = time.monotonic()
        self.summary.setText("Running…")
        worker = TestStreamWorker(args, str(root), self)
        worker.line.connect(self._on_line)
        worker.finished_run.connect(self._on_finished)
        self.stream = worker
        worker.start()

    def _on_line(self, line: str) -> None:
        self.output.appendPlainText(line)
        match = TEST_RESULT_LINE.match(line)
        if match:
            node = match.group("id")
            self._ensure_item(node)
            self._set_status(node, match.group("res"))
            return
        summary = TEST_SUMMARY_LINE.match(line)
        if summary:
            node = summary.group("id")
            self._ensure_item(node)
            self._set_status(node, "FAILED")

    def _on_finished(self, code: int) -> None:
        elapsed = time.monotonic() - self.started_at
        leaves = [n for n, i in self.items.items() if not i.childCount()]
        for node in leaves:                              # nothing may stay "running"
            if self.results.get(node) == "RUNNING":
                self._set_status(node, "IDLE")
        passed = sum(1 for n in leaves if self.results.get(n) in ("PASSED", "XPASS"))
        failed = sum(1 for n in leaves if self.results.get(n) in ("FAILED", "ERROR"))
        skipped = sum(1 for n in leaves if self.results.get(n) in ("SKIPPED", "XFAIL"))
        if self.pytest_missing:
            tail = [ln for ln in self.output.toPlainText().splitlines() if ln.strip()][-1:] or [""]
            self.summary.setText(f"unittest: {tail[0][:40]}")
        else:
            bits = [f"{passed} passed"] + ([f"{failed} failed"] if failed else []) + \
                   ([f"{skipped} skipped"] if skipped else [])
            self.summary.setText(", ".join(bits) + f" · {elapsed:.1f}s")
        self.owner.flash("Tests finished: " + self.summary.text())

    # ------------------------------------------------------------------ navigation
    def _open_test(self, item, _column: int = 0) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole) or ""
        root = self._root()
        if not node or root is None:
            return
        file_part, _sep, rest = node.partition("::")
        path = root / file_part
        if not path.exists():
            return
        tab = self.owner.open_file(path)
        if tab is None or getattr(tab, "KIND", "") != "text" or not rest:
            return
        name = re.split(r"[\[\s]", rest.split("::")[-1])[0]
        kind = "class" if "::" not in rest and name[:1].isupper() else "def"
        for number, text in enumerate(tab.text().splitlines()):
            if re.match(rf"\s*(async\s+)?{kind}\s+{re.escape(name)}\b", text):
                tab.goto_line(number + 1)
                return

    def shutdown(self) -> None:
        if self._running():
            self.stream.stop()
            self.stream.wait(2000)


# --------------------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """The IDE shell: docks, tabs, menus, status bar and all wiring."""

    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._untitled_counter = 0
        self._force_close = False
        self._pyflakes_state: dict = {}
        self._workers: set = set()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._build_app_icon())
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.setDockNestingEnabled(True)
        self.setUnifiedTitleAndToolBarOnMac(True)
        # Let the bottom panel own the corners so it spans the full width instead of
        # being split into narrow sub-areas beside the explorer / AI panels.
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

        self._build_central()
        self._build_docks()
        self._build_activity_bar()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_layout()

        self.act_whitespace.setChecked(bool(self.config.get("show_whitespace", False)))
        self.act_scroll_past_end.setChecked(bool(self.config.get("scroll_past_end", False)))
        self.act_autosave.setChecked(bool(self.config.get("auto_save", False)))
        QTimer.singleShot(150, self._restore_project)
        QTimer.singleShot(400, lambda: self.terminal.start(
            self.config.get("terminal_shell") or default_shell(),
            str(self.current_working_directory()),
        ))

    # ------------------------------------------------------------------ chrome
    def _build_app_icon(self):
        from PyQt6.QtGui import QIcon

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#007acc"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont(monospace_family(), 26, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PF")
        painter.end()
        return QIcon(pixmap)

    def _build_central(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(False)   # replaced by explicit, themed close buttons
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border-top: 1px solid #2b2b2b; }"
        )
        self.setCentralWidget(self.tabs)
        self._show_welcome()

    def _build_activity_bar(self) -> None:
        """Thin VS Code style strip with a button per panel."""
        bar = QToolBar("Activity", self)
        bar.setObjectName("activity_bar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setStyleSheet(
            "QToolBar#activity_bar { background: #181818; border-right: 1px solid #2b2b2b;"
            " spacing: 2px; padding: 4px 2px; }"
        )
        icon_color = "#cccccc"
        self.activity_buttons: list[tuple[object, str]] = []
        for kind, tip, slot in (
            ("explorer", "Explorer (Ctrl+Shift+E)", self.show_explorer),
            ("search", "Search in project (Ctrl+Shift+F)", self.project_search),
            ("quickopen", "Quick open (Ctrl+P)", self.quick_open),
            ("palette", "Command palette (Ctrl+Shift+P)", self.command_palette),
            ("outline", "Outline (Ctrl+Shift+O)", self.show_outline),
            ("problems", "Problems (Ctrl+Shift+M)", self.show_problems),
            ("git", "Source control (Ctrl+Shift+G)", self.show_git),
            ("tests", "Tests (Ctrl+Alt+T)", self.show_tests),
            ("terminal", "Terminal (Ctrl+`)", self.show_terminal),
            ("packages", "Packages (Ctrl+Alt+P)", self.show_packages),
            ("build", "Build & Package (Ctrl+Shift+B)", self.show_build),
            ("ai", "AI assistant (Ctrl+Alt+A)", self.show_ai),
        ):
            button = QToolButton()
            button.setIcon(make_icon(kind, icon_color, 20))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tip)
            button.setFixedSize(32, 32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            button.setStyleSheet(
                "QToolButton { border: none; border-radius: 4px; padding: 5px; }"
                "QToolButton:hover { background: rgba(128, 128, 128, 0.22); }"
            )
            bar.addWidget(button)
            self.activity_buttons.append((button, kind))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        bar.addWidget(spacer)
        reset = QToolButton()
        reset.setIcon(make_icon("settings", icon_color, 18))
        reset.setToolTip("Reset layout (Ctrl+Alt+R)")
        reset.setFixedSize(32, 32)
        reset.setStyleSheet(
            "QToolButton { border: none; border-radius: 4px; padding: 7px; }"
            "QToolButton:hover { background: rgba(128, 128, 128, 0.22); }"
        )
        reset.clicked.connect(self.reset_layout)
        bar.addWidget(reset)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)
        self.activity_bar = bar

    def _build_docks(self) -> None:
        # ---- Explorer ----------------------------------------------------------
        self.explorer = ExplorerPanel(self)
        self.git_panel = GitPanel(self)
        self.tests_panel = TestsPanel(self)
        self.left_hub = PanelHub()
        self.left_hub.addTab(self.explorer, "Explorer")
        self.left_hub.addTab(self.git_panel, "Source Control")
        self.left_hub.addTab(self.tests_panel, "Tests")
        self.explorer_dock = self._make_dock("Explorer", "dock_explorer", self.left_hub,
                                             Qt.DockWidgetArea.LeftDockWidgetArea)

        # ---- Outline / Problems / TODO (right, stacked with AI) ---------------------
        self.outline = OutlinePanel(self)
        self.problems = ProblemsPanel(self)
        self.todo_panel = TodoPanel(self)
        self.right_hub = PanelHub()
        self.right_hub.addTab(self.outline, "Outline")
        self.right_hub.addTab(self.problems, "Problems")
        self.right_hub.addTab(self.todo_panel, "TODO")
        self.outline_dock = self._make_dock("Outline", "dock_outline", self.right_hub,
                                            Qt.DockWidgetArea.RightDockWidgetArea)

        # ---- AI ----------------------------------------------------------------
        self.ai_panel = AIPanel(self)
        self.ai_dock = self._make_dock("AI Assistant", "dock_ai", self.ai_panel,
                                       Qt.DockWidgetArea.RightDockWidgetArea)

        # ---- Terminal, packages and build (tabbed at the bottom) ----------------
        self.terminal = TerminalPanel(self)
        self.terminal_dock = self._make_dock("Terminal", "dock_terminal", self.terminal,
                                             Qt.DockWidgetArea.BottomDockWidgetArea)
        self.packages = PackagesPanel(self)
        self.packages_dock = self._make_dock("Packages", "dock_packages", self.packages,
                                             Qt.DockWidgetArea.BottomDockWidgetArea)
        self.build_panel = BuildPanel(self)
        self.build_dock = self._make_dock("Build", "dock_build", self.build_panel,
                                          Qt.DockWidgetArea.BottomDockWidgetArea)
        # Tabbing and sizing happen in _restore_layout()/reset_layout(): Qt duplicates
        # dock tab groups if restoreState() runs on an already-tabified window.

    DOCK_SPEC = (
        ("dock_explorer", "Explorer", "explorer_dock", "left_hub",
         Qt.DockWidgetArea.LeftDockWidgetArea),
        ("dock_outline", "Outline", "outline_dock", "right_hub",
         Qt.DockWidgetArea.RightDockWidgetArea),
        ("dock_ai", "AI Assistant", "ai_dock", "ai_panel",
         Qt.DockWidgetArea.RightDockWidgetArea),
        ("dock_terminal", "Terminal", "terminal_dock", "terminal",
         Qt.DockWidgetArea.BottomDockWidgetArea),
        ("dock_packages", "Packages", "packages_dock", "packages",
         Qt.DockWidgetArea.BottomDockWidgetArea),
        ("dock_build", "Build", "build_dock", "build_panel",
         Qt.DockWidgetArea.BottomDockWidgetArea),
    )

    def rebuild_docks(self) -> None:
        """Throw the dock widgets away and recreate them, then restore the default layout.

        Qt cannot reliably re-tabify dock groups on a window that is already visible
        (it allocates duplicate tab bars), so Reset Layout starts from fresh docks -
        the same code path used at startup. Panel widgets themselves are preserved,
        so no editor/terminal/AI state is lost.
        """
        panels = {
            "left_hub": self.left_hub,
            "right_hub": self.right_hub,
            "ai_panel": self.ai_panel,
            "terminal": self.terminal,
            "packages": self.packages,
            "build_panel": self.build_panel,
        }
        for panel in panels.values():
            panel.setParent(None)
        for dock in self.findChildren(QDockWidget):
            dock.setParent(None)
            dock.deleteLater()
        QApplication.processEvents()

        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        for object_name, title, attr, panel_key, area in self.DOCK_SPEC:
            dock = self._make_dock(title, object_name, panels[panel_key], area)
            setattr(self, attr, dock)
        self.apply_default_layout(rebuild=True)
        self.panels_menu.clear()
        self._populate_panels_menu()
        self.flash("Layout reset to defaults.")

    def _make_dock(self, title: str, object_name: str, widget: QWidget,
                   area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    # ------------------------------------------------------------------ actions
    def _action(self, text: str, shortcut=None, slot=None, tip: str = "",
                icon=None, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if icon is not None:
            action.setIcon(icon)
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.act_new = self._action("New File", "Ctrl+N", self.new_file, "Create a new file")
        self.act_open = self._action("Open File…", "Ctrl+O", self.open_file_dialog, "Open a file")
        self.act_open_folder = self._action(
            "Open Folder…", "Ctrl+K, Ctrl+O", self.open_folder_dialog, "Open a project folder"
        )
        self.act_save = self._action("Save", "Ctrl+S", self.save_active, "Save the active file")
        self.act_save_as = self._action("Save As…", "Ctrl+Shift+S", self.save_active_as,
                                        "Save the active file under a new name")
        self.act_close_tab = self._action("Close Tab", "Ctrl+W", self.close_current_tab,
                                          "Close the active tab")
        self.act_close_all = self._action("Close All Tabs", "Ctrl+Shift+W", self.close_all_tabs,
                                          "Close every tab")
        self.act_exit = self._action("Exit", "Ctrl+Q", self.close, "Quit PyForge IDE")

        self.act_undo = self._action("Undo", "Ctrl+Z", self._editor_undo)
        self.act_redo = self._action("Redo", "Ctrl+Y", self._editor_redo)
        self.act_cut = self._action("Cut", "Ctrl+X", self._editor_cut)
        self.act_copy = self._action("Copy", "Ctrl+C", self._editor_copy)
        self.act_paste = self._action("Paste", "Ctrl+V", self._editor_paste)
        self.act_select_all = self._action("Select All", "Ctrl+A", self._editor_select_all)
        self.act_zoom_in = self._action("Zoom In", "Ctrl+=", lambda: self._zoom(1))
        self.act_zoom_out = self._action("Zoom Out", "Ctrl+-", lambda: self._zoom(-1))
        self.act_zoom_reset = self._action("Reset Zoom", "Ctrl+0", self._zoom_reset)
        self.act_wrap = self._action("Toggle Word Wrap", "Alt+Z", self._toggle_wrap, checkable=True)
        self.act_wrap.setChecked(bool(self.config.get("wrap_lines", False)))

        self.act_run = self._action("Run Active File", "F5", self.run_active_file,
                                    "Save and run the active script in the real terminal")
        self.act_run_terminal = self._action(
            "Run in Terminal (Ctrl+F5)", "Ctrl+F5", self.run_in_terminal,
            "Run a shell command in the project directory"
        )
        self.act_stop = self._action("Stop / Interrupt", "Ctrl+.", self.stop_process,
                                     "Send Ctrl+C to the running process")
        self.act_settings = self._action("Settings…", "Ctrl+,", self.open_settings,
                                         "Configure interpreter, AI provider and editor")
        self.act_focus_packages = self._action("PyPI Package Manager", "Ctrl+Alt+P",
                                               self.show_packages,
                                               "Search PyPI and manage installed packages")
        self.act_focus_ai = self._action("AI Assistant", "Ctrl+Alt+A", self.show_ai,
                                         "Focus the AI assistant")
        self.act_focus_terminal = self._action("Terminal", "Ctrl+`", self.show_terminal,
                                               "Focus the terminal")
        self.act_focus_explorer = self._action("Explorer", "Ctrl+Shift+E", self.show_explorer,
                                               "Focus the project explorer")
        self.act_reset_layout = self._action("Reset Layout", "Ctrl+Alt+R", self.reset_layout,
                                             "Restore the default panel layout")
        self.act_fullscreen = self._action("Toggle Full Screen", "F11", self._toggle_fullscreen)
        self.act_open_config = self._action("Open Settings Folder", None, self._open_config_folder)
        self.act_shortcuts = self._action("Keyboard Shortcuts", "F1", self.show_shortcuts)
        self.act_about = self._action("About PyForge IDE", None, self.show_about)

        # ---- editing / navigation (v2) -----------------------------------------
        self.act_find = self._action("Find…", "Ctrl+F", lambda: self.show_find(False),
                                     "Find in the active file")
        self.act_replace = self._action("Replace…", "Ctrl+H", lambda: self.show_find(True),
                                        "Find and replace in the active file")
        self.act_find_next = self._action("Find Next", "F3", self.find_next,
                                          "Jump to the next match")
        self.act_find_prev = self._action("Find Previous", "Shift+F3", self.find_previous,
                                          "Jump to the previous match")
        self.act_goto_line = self._action("Go to Line…", "Ctrl+G", self.goto_line_dialog,
                                          "Jump to a line number")
        self.act_quick_open = self._action("Quick Open File…", "Ctrl+P", self.quick_open,
                                           "Fuzzy-search every file in the project")
        self.act_project_search = self._action("Search in Project…", "Ctrl+Shift+F",
                                               self.project_search,
                                               "Search (and replace) across all project files")
        self.act_comment = self._action("Toggle Comment", "Ctrl+/", self.toggle_comment,
                                        "Comment or uncomment the selected lines")
        self.act_duplicate_line = self._action("Duplicate Line", "Ctrl+D", self.duplicate_line,
                                               "Duplicate the current line")
        self.act_delete_line = self._action("Delete Line", "Ctrl+Shift+K", self.delete_line,
                                            "Delete the current line")
        self.act_move_up = self._action("Move Line Up", "Alt+Up", lambda: self.move_line(-1),
                                        "Move the current line up")
        self.act_move_down = self._action("Move Line Down", "Alt+Down", lambda: self.move_line(1),
                                          "Move the current line down")
        self.act_format_json = self._action("Format JSON", "Ctrl+Alt+F", self.format_json,
                                            "Pretty-print the JSON in the active file")
        self.act_sort_lines = self._action("Sort Lines", None, self.sort_lines,
                                           "Sort the selected lines alphabetically")
        self.act_save_all = self._action("Save All", "Ctrl+Alt+S", self.save_all,
                                         "Save every modified file")
        self.act_reopen_tab = self._action("Reopen Closed Tab", "Ctrl+Shift+T",
                                           self.reopen_closed_tab,
                                           "Reopen the most recently closed tab")

        # ---- view / workspace (v2) ---------------------------------------------
        self.act_toggle_preview = self._action("Toggle Live Preview", "Ctrl+Shift+V",
                                               self.toggle_preview, checkable=True)
        self.act_refresh_preview = self._action("Refresh Preview", "Ctrl+Alt+Shift+R",
                                                self.refresh_preview)
        self.act_zen = self._action("Zen Mode (hide all panels)", "Ctrl+Alt+Z",
                                    self.toggle_zen, "Toggle distraction-free mode")
        self.act_whitespace = self._action("Show Whitespace", "Ctrl+Alt+W",
                                           self.toggle_whitespace, checkable=True)
        self.act_scroll_past_end = self._action(
            "Scroll Past End", None, self.toggle_scroll_past_end, checkable=True
        )
        self.act_autosave = self._action("Auto Save", "Ctrl+Shift+Alt+S",
                                         self.toggle_autosave, checkable=True)
        self.act_show_outline = self._action("Outline", "Ctrl+Shift+O", self.show_outline,
                                             "Focus the symbol outline")
        self.act_show_build = self._action("Build && Package", "Ctrl+Shift+B", self.show_build,
                                           "Compile the active script into an .exe or binary")
        self.act_change_explorer = self._action("Change Explorer Folder…", "Ctrl+Alt+O",
                                                self.change_explorer_folder,
                                                "Point the explorer at any folder")
        self.act_run_file = self._action("Run File", None, lambda: self.run_active_file())
        self.act_open_terminal_here = self._action("Open Terminal in Project Folder", None,
                                                   lambda: self.open_terminal_at(
                                                       self.current_working_directory()))
        self._build_pro_actions()

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addActions([self.act_new, self.act_open, self.act_open_folder])
        self.recent_files_menu = file_menu.addMenu("Open Recent File")
        self.recent_projects_menu = file_menu.addMenu("Recent Projects")
        self._populate_recent_menus()
        file_menu.addSeparator()
        file_menu.addActions([self.act_save, self.act_save_as, self.act_save_all])
        file_menu.addAction(self.act_autosave)
        file_menu.addSeparator()
        file_menu.addActions([self.act_close_tab, self.act_reopen_tab, self.act_close_all])
        file_menu.addSeparator()
        file_menu.addAction(self.act_change_explorer)
        file_menu.addAction(self.act_open_terminal_here)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        edit_menu = self.edit_menu = menubar.addMenu("&Edit")
        edit_menu.addActions([self.act_undo, self.act_redo])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_cut, self.act_copy, self.act_paste, self.act_select_all])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_find, self.act_replace, self.act_find_next,
                              self.act_find_prev, self.act_goto_line])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_comment, self.act_duplicate_line, self.act_delete_line,
                              self.act_move_up, self.act_move_down])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_format_json, self.act_sort_lines])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_wrap, self.act_whitespace, self.act_scroll_past_end])

        go_menu = self.go_menu = menubar.addMenu("&Go")
        go_menu.addActions([self.act_quick_open, self.act_project_search, self.act_goto_line])
        go_menu.addSeparator()
        go_menu.addActions([self.act_focus_explorer, self.act_show_outline])

        view_menu = self.view_menu = menubar.addMenu("&View")
        self.panels_menu = view_menu.addMenu("Panels")
        self._populate_panels_menu()
        view_menu.addSeparator()
        view_menu.addActions([self.act_toggle_preview, self.act_refresh_preview])
        view_menu.addSeparator()
        view_menu.addActions([self.act_zen, self.act_fullscreen])
        view_menu.addSeparator()
        view_menu.addAction(self.act_reset_layout)

        run_menu = self.run_menu = menubar.addMenu("&Run")
        run_menu.addActions([self.act_run, self.act_run_terminal, self.act_stop])
        run_menu.addSeparator()
        run_menu.addAction(self.act_show_build)

        tools_menu = self.tools_menu = menubar.addMenu("&Tools")
        tools_menu.addActions([self.act_focus_packages, self.act_focus_ai])
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_settings)
        tools_menu.addAction(self.act_open_config)

        self._extend_menus(menubar)
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.act_shortcuts)
        help_menu.addAction(self.act_about)

    def _populate_recent_menus(self) -> None:
        self.recent_files_menu.clear()
        files = self.config.get("recent_files", []) or []
        if not files:
            self.recent_files_menu.addAction("(empty)").setEnabled(False)
        for path in files[:12]:
            action = self.recent_files_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(lambda _c=False, p=path: self.open_file(Path(p)))
        if files:
            self.recent_files_menu.addSeparator()
            self.recent_files_menu.addAction("Clear Recent Files", self._clear_recent_files)

        self.recent_projects_menu.clear()
        projects = self.config.get("recent_projects", []) or []
        if not projects:
            self.recent_projects_menu.addAction("(empty)").setEnabled(False)
        for path in projects[:12]:
            action = self.recent_projects_menu.addAction(Path(path).name or path)
            action.setToolTip(path)
            action.triggered.connect(
                lambda _c=False, p=path: self.explorer.set_project(Path(p))
            )
        if projects:
            self.recent_projects_menu.addSeparator()
            self.recent_projects_menu.addAction("Clear Recent Projects",
                                                self._clear_recent_projects)

    def _clear_recent_files(self) -> None:
        self.config.set("recent_files", [])
        self.config.save()
        self._populate_recent_menus()

    def _clear_recent_projects(self) -> None:
        self.config.set("recent_projects", [])
        self.config.save()
        self._populate_recent_menus()

    def _populate_panels_menu(self) -> None:
        self.panels_menu.clear()
        for dock in self.findChildren(QDockWidget):
            action = dock.toggleViewAction()
            action.setText(dock.windowTitle())
            self.panels_menu.addAction(action)
        self.panels_menu.addSeparator()
        self.panels_menu.addAction(self.act_reset_layout)
        self.panels_menu.addAction(self.act_change_explorer)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(True)
        toolbar.setFloatable(True)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet(
            "QToolBar { background: #181818; border-bottom: 1px solid #2b2b2b; spacing: 4px;"
            " padding: 3px; } QToolBar::separator { background: #3c3c3c; width: 1px; margin: 4px 6px; }"
        )
        for action, label in (
            (self.act_new, "New"),
            (self.act_open, "Open"),
            (self.act_open_folder, "Folder"),
            (self.act_save, "Save"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(f"{action.text()}  ({action.shortcut().toString()})")
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(button)
        toolbar.addSeparator()
        run_button = QToolButton()
        run_button.setDefaultAction(self.act_run)
        run_button.setText("▶ Run")
        run_button.setStyleSheet(
            "QToolButton { color: #ffffff; background: #16825d; border: 1px solid #1f9d70;"
            " border-radius: 3px; padding: 3px 10px; font-weight: 600; }"
            "QToolButton:hover { background: #1f9d70; }"
        )
        run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        toolbar.addWidget(run_button)
        toolbar.addSeparator()
        for action, label in (
            (self.act_focus_terminal, "Terminal"),
            (self.act_focus_packages, "Packages"),
            (self.act_focus_ai, "AI"),
            (self.act_reset_layout, "Reset Layout"),
            (self.act_settings, "Settings"),
        ):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(button)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.status_file = QLabel("No file")
        self.status_position = QLabel("Ln 1, Col 1")
        self.status_language = QLabel("Plain Text")
        self.status_interpreter = QLabel("")
        self.status_interpreter.setToolTip("Configured Python interpreter")
        for label in (self.status_file, self.status_position, self.status_language,
                      self.status_interpreter):
            label.setStyleSheet("color: #9d9d9d; padding: 0 8px;")
        bar.addWidget(self.status_file, 1)
        self.status_branch = QToolButton()
        self.status_branch.setText("⎇ —")
        self.status_branch.setToolTip("Git branch — click to switch")
        self.status_branch.setStyleSheet("QToolButton { color: #9d9d9d; border: none; padding: 0 8px; }"
                                         "QToolButton:hover { background: rgba(128,128,128,0.2); }")
        self.status_branch.clicked.connect(self.git_panel.show_branch_menu)
        self.status_problems = QToolButton()
        self.status_problems.setText("✖ 0   ▲ 0")
        self.status_problems.setToolTip("Errors and warnings in the open files — click for the Problems panel")
        self.status_problems.setStyleSheet("QToolButton { color: #9d9d9d; border: none; padding: 0 8px; }")
        self.status_problems.clicked.connect(self.show_problems)
        bar.addPermanentWidget(self.status_branch)
        bar.addPermanentWidget(self.status_problems)
        self.git_panel.branch_changed.connect(self._on_branch_changed)
        self.problems.counts_changed.connect(self._on_problem_counts)
        bar.addPermanentWidget(self.status_language)
        bar.addPermanentWidget(self.status_position)
        bar.addPermanentWidget(self.status_interpreter)
        self._refresh_interpreter_label()

    def _refresh_interpreter_label(self) -> None:
        interpreter = self.config.get("python_path") or detect_python_interpreter()
        exists = Path(interpreter).exists() if os.path.sep in interpreter else bool(
            shutil.which(interpreter)
        )
        self.status_interpreter.setText(
            f"Python: {Path(interpreter).name if interpreter else 'not set'}"
        )
        self.status_interpreter.setToolTip(
            f"{interpreter}\n{'found' if exists else 'NOT FOUND — set it in Settings (Ctrl+,)'}"
        )
        self.status_interpreter.setStyleSheet(
            f"color: {'#9d9d9d' if exists else '#f14c4b'}; padding: 0 8px;"
        )

    # ------------------------------------------------------------------ layout
    def _restore_layout(self) -> None:
        geometry = self.settings.value("v2/window/geometry")
        state = self.settings.value("v2/window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        restored = False
        if state is not None:
            restored = bool(self.restoreState(state))
            if restored:
                self.show()
                QApplication.processEvents()
                if self._layout_is_sane():
                    self._apply_default_sizes()
                else:
                    self.settings.remove("v2/window/state")
                    restored = False
        if not restored:
            self.apply_default_layout()

    def _layout_is_sane(self) -> bool:
        """Guard against corrupt/foreign saved layouts (all panels on screen?)."""
        screen = self.screen().availableGeometry() if self.screen() else None
        for dock in self.findChildren(QDockWidget):
            if dock.isFloating():
                rect = dock.frameGeometry()
                if screen is not None and not screen.intersects(rect):
                    return False
            elif dock.isHidden() and dock.isVisible():
                return False
        return True

    def apply_default_layout(self, rebuild: bool = False) -> None:
        """Restore the built-in arrangement: explorer | editor | outline/AI, panels below."""
        import base64

        layout = (
            (self.explorer_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.outline_dock, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.ai_dock, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.terminal_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
            (self.packages_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
            (self.build_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
        )
        for dock, area in layout:
            dock.setFloating(False)
            # Re-adding pulls the dock out of any previous tab group; restoreState()
            # below then rebuilds the groups cleanly in one shot.
            self.addDockWidget(area, dock)
        # Qt allocates duplicate dock tab bars if state is restored onto a *visible*
        # window, so the window is hidden for the duration of the rebuild.
        was_visible = self.isVisible()
        if rebuild and was_visible:
            self.setUpdatesEnabled(False)
            self.hide()
        restored = self.restoreState(base64.b64decode(DEFAULT_LAYOUT_B64))
        if rebuild and was_visible:
            self.show()
            self.setUpdatesEnabled(True)
        if not restored:                      # extremely unlikely: fall back to splitters
            for dock, _area in layout:
                dock.setVisible(True)
        if rebuild:
            QTimer.singleShot(0, self._reveal_hidden_docks)

    def _reveal_hidden_docks(self) -> None:
        """Re-open panels the user had closed, once the rebuilt layout has settled."""
        if not self.isVisible():
            return
        for dock in (self.explorer_dock, self.outline_dock, self.ai_dock,
                     self.terminal_dock, self.packages_dock, self.build_dock):
            if dock.isHidden():
                dock.setVisible(True)

    def _apply_default_sizes(self) -> None:
        """Give each dock a sensible size.

        Deliberately called *before* the window is shown (and after re-detaching the
        docks when the layout is rebuilt): resizing tabbed dock groups while they are
        visible makes Qt create duplicate dock tab bars.
        """
        width = max(900, self.width())
        left = max(240, min(340, int(width * 0.19)))
        right = max(280, min(420, int(width * 0.24)))
        bottom = max(170, min(290, int(self.height() * 0.24)))
        self.resizeDocks([self.explorer_dock], [left], Qt.Orientation.Horizontal)
        self.resizeDocks([self.ai_dock, self.outline_dock], [right, right],
                         Qt.Orientation.Horizontal)
        self.resizeDocks([self.terminal_dock], [bottom], Qt.Orientation.Vertical)

    def reset_layout(self) -> None:
        """Forget any saved layout and rebuild the default arrangement from scratch."""
        self.settings.remove("v2/window/state")
        self.settings.sync()
        self.rebuild_docks()

    # ------------------------------------------------------------------ docks
    def show_explorer(self) -> None:
        self.explorer_dock.show()
        self.explorer_dock.raise_()
        self.left_hub.setCurrentWidget(self.explorer)
        self.explorer.tree.setFocus()

    def show_terminal(self) -> None:
        self.terminal_dock.show()
        self.terminal_dock.raise_()
        self.terminal.input.setFocus()

    def show_packages(self) -> None:
        self.packages_dock.show()
        self.packages_dock.raise_()
        self.packages.search_input.setFocus()
        self.packages.search_input.selectAll()

    def show_ai(self) -> None:
        self.ai_dock.show()
        self.ai_dock.raise_()
        self.ai_panel.prompt.setFocus()

    def flash(self, message: str, timeout: int = 5000) -> None:
        self.statusBar().showMessage(message, timeout)

    # ------------------------------------------------------------------ tabs
    def _add_tab(self, widget, label: str) -> int:
        """Insert a tab with a themed close button (welcome tab stays close-proof)."""
        index = self.tabs.addTab(widget, label)
        self.tabs.setTabToolTip(index, widget.tooltip())
        if getattr(widget, "KIND", "") != "welcome":
            button = QToolButton()
            button.setText("✕")
            button.setToolTip("Close tab (Ctrl+W)")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QToolButton { border: none; background: transparent; color: #9d9d9d;"
                " font-size: 11px; padding: 1px 4px; border-radius: 3px; }"
                "QToolButton:hover { background: #4b4b4b; color: #ffffff; }"
            )
            button.clicked.connect(
                lambda _checked=False, w=widget: self.close_tab_at(self.tabs.indexOf(w))
            )
            self.tabs.tabBar().setTabButton(
                index, QTabBar.ButtonPosition.RightSide, button
            )
        return index

    def _show_welcome(self) -> None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "welcome":
                self.tabs.setCurrentIndex(index)
                return
        welcome = WelcomeTab(self)
        index = self._add_tab(welcome, "Welcome")
        self.tabs.setCurrentIndex(index)

    def active_editor_tab(self):
        widget = self.tabs.currentWidget()
        if widget is not None and getattr(widget, "KIND", "") == "text":
            return widget
        return None

    def _find_tab_for_path(self, path: Path):
        target = Path(path).resolve()
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            widget_path = getattr(widget, "path", None)
            if widget_path is not None:
                try:
                    if Path(widget_path).resolve() == target:
                        return index, widget
                except OSError:
                    continue
        return -1, None

    def _wire_tab(self, widget) -> None:
        """Keep the tab caption in sync, looking the tab up by widget (never a stale index)."""
        if getattr(widget, "KIND", "") == "text":
            widget.editor.textChanged.connect(
                lambda *_args, w=widget: self._update_tab_title(self.tabs.indexOf(w))
            )
            widget.editor.modification_changed.connect(
                lambda *_args, w=widget: self._update_tab_title(self.tabs.indexOf(w))
            )
            widget.editor.cursor_info_changed.connect(self._on_cursor_moved)
            self._setup_editor_features(widget)

    def _update_tab_title(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None:
            return
        name = widget.display_name()
        if hasattr(widget, "is_modified") and widget.is_modified():
            name = "● " + name
        self.tabs.setTabText(index, name)
        self.tabs.setTabToolTip(index, widget.tooltip())

    def _on_tab_changed(self, index: int) -> None:
        if not hasattr(self, "status_file"):
            return          # fired while the window is still being assembled
        widget = self.tabs.widget(index)
        if widget is None:
            self.status_file.setText("No file")
            self.status_language.setText("Plain Text")
            self.status_position.setText("Ln 1, Col 1")
            return
        tooltip = widget.tooltip()
        self.status_file.setText(tooltip)
        self.status_file.setToolTip(tooltip)
        self.status_language.setText(language_for_path(getattr(widget, "path", None)))
        if getattr(widget, "KIND", "") == "text":
            cursor = widget.editor.textCursor()
            self.status_position.setText(
                f"Ln {cursor.blockNumber() + 1}, Col {cursor.columnNumber() + 1}"
            )
            widget.editor.setFocus()
        else:
            self.status_position.setText("—")
        if hasattr(self, "ai_panel"):
            self.ai_panel._update_context_label()
        if hasattr(self, "outline"):
            self.outline.rebuild()
        if hasattr(self, "build_panel"):
            self.build_panel.refresh()
        self._update_tab_title(index)
        if hasattr(self, "problems"):
            self.problems.schedule_rebuild()
            if getattr(widget, "KIND", "") == "text":
                self.git_panel.update_marks(widget)

    def _on_cursor_moved(self, line: int, column: int) -> None:
        self.status_position.setText(f"Ln {line}, Col {column}")

    def open_file(self, path):
        """Open any file type in the central tab area and return its tab widget."""
        if path is None:
            return None
        path = Path(path)
        if not path.exists():
            QMessageBox.warning(self, APP_NAME, f"File not found:\n{path}")
            return None
        if path.is_dir():
            self.explorer.set_project(path)
            return None

        index, existing = self._find_tab_for_path(path)
        if existing is not None:
            self.tabs.setCurrentIndex(index)
            return existing

        widget = self._create_tab_for_path(path)
        if widget is None:
            return None
        tab_index = self._add_tab(widget, widget.display_name())
        self.tabs.setCurrentIndex(tab_index)
        self._wire_tab(widget)
        if getattr(widget, "KIND", "") == "text":
            widget.editor.set_whitespace_visible(bool(self.config.get("show_whitespace", False)))
            widget.editor.set_scroll_past_end(bool(self.config.get("scroll_past_end", False)))
            widget.editor.textChanged.connect(
                lambda *_a, w=widget: self._maybe_autosave(w)
            )
        self._update_tab_title(tab_index)
        self._remember_file(path)
        if getattr(widget, "KIND", "") == "text":
            widget.editor.textChanged.connect(self.outline.schedule_rebuild)
            if widget.has_preview():
                widget.set_preview_visible(bool(self.config.get("live_preview", True)))
                self.act_toggle_preview.setChecked(widget.preview_visible())
        self.outline.rebuild()
        self.statusBar().showMessage(f"Opened {path.name}", 3000)
        return widget

    def _create_tab_for_path(self, path: Path):
        font_size = int(self.config.get("font_size", 11) or 11)
        wrap = bool(self.config.get("wrap_lines", False))
        if is_image_path(path):
            return ImageTab(path, self)
        if path.suffix.lower() in MEDIA_EXTENSIONS:
            return MediaTab(path, self)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > MAX_TEXT_BYTES:
            return BinaryTab(
                path,
                reason=f"Large file ({human_size(size)}) — too big for the text editor.",
                parent=self,
            )
        text_like = is_probably_text_path(path) or looks_like_text(path)
        if not text_like:
            return BinaryTab(path, reason="Binary or non-UTF8 file — no text preview available.",
                             parent=self)
        try:
            text, encoding = read_text_file(path)
        except Exception as exc:
            return BinaryTab(path, reason=f"Unreadable file: {exc}", parent=self)
        tab = EditorTab(path, text, self, font_size=font_size, wrap=wrap)
        tab.encoding = encoding
        return tab

    def new_file(self) -> None:
        self._untitled_counter += 1
        font_size = int(self.config.get("font_size", 11) or 11)
        wrap = bool(self.config.get("wrap_lines", False))
        tab = EditorTab(None, "", self, font_size=font_size, wrap=wrap)
        tab.untitled_name = f"Untitled-{self._untitled_counter}"
        index = self._add_tab(tab, tab.untitled_name)
        self._wire_tab(tab)
        self.tabs.setCurrentIndex(index)
        tab.editor.textChanged.connect(self.outline.schedule_rebuild)
        tab.editor.setFocus()

    def open_file_dialog(self) -> None:
        start = str(self.current_working_directory())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", start,
            "All files (*);;Python (*.py);;Text (*.txt *.md *.json *.csv);;Images (*.png *.jpg *.jpeg *.gif *.bmp *.ico *.webp)",
        )
        if path:
            self.open_file(Path(path))

    def open_folder_dialog(self) -> None:
        start = str(self.config.get("last_project") or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open Project Folder", start)
        if folder:
            self.explorer.set_project(folder)

    def on_project_opened(self, path: Path) -> None:
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self._remember_project(path)
        self.outline.rebuild()
        self.flash(f"Project opened: {path}")
        self._refresh_interpreter_label()
        if self.terminal.worker is not None:
            self.terminal.worker.cd(str(path))
        self.explorer.reveal(path)
        self.ai_panel._update_context_label()
        self.build_panel.refresh()
        self.git_panel.refresh()
        self.problems.clear_scan()
        self.tests_panel.tree.clear()
        self.tests_panel.items.clear()
        self.tests_panel.results.clear()
        self.tests_panel.summary.setText("")
        self.todo_panel.entries = {}
        self.todo_panel.rebuild()
        if not getattr(self, "_restoring_project", False):
            self._restoring_project = True
            QTimer.singleShot(250, lambda: self.restore_project_state(path))
            QTimer.singleShot(600, lambda: setattr(self, "_restoring_project", False))

    def _restore_project(self) -> None:
        last = self.config.get("last_project")
        if last and Path(last).is_dir():
            self.explorer.set_project(last)
        else:
            cwd = Path.cwd()
            if any(cwd.iterdir()) and cwd != Path.home():
                self.explorer.set_project(cwd)
            else:
                self.explorer.set_project(Path.home())

    def project_state_path(self, folder: Path | None = None) -> Path | None:
        root = folder or (self.explorer.project_root if hasattr(self, "explorer") else None)
        return Path(root) / PROJECT_STATE_FILENAME if root else None

    def save_project_state(self) -> None:
        """Persist the open tabs and UI bits that belong to this project folder."""
        path = self.project_state_path()
        if path is None:
            return
        open_files = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            widget_path = getattr(widget, "path", None)
            if widget_path:
                open_files.append(str(widget_path))
        state = {
            "open_files": open_files,
            "build_preset": self.build_panel.preset_combo.currentData(),
            "build_name": self.build_panel.name_edit.text(),
            "build_extra": self.build_panel.extra_edit.text(),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def restore_project_state(self, folder: Path) -> None:
        """Reopen the files that were open last time this folder was used."""
        path = self.project_state_path(folder)
        if path is None or not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for file_path in state.get("open_files", [])[:12]:
            candidate = Path(file_path)
            if candidate.exists():
                self.open_file(candidate)
        if state.get("build_preset"):
            index = self.build_panel.preset_combo.findData(state["build_preset"])
            if index >= 0:
                self.build_panel.preset_combo.setCurrentIndex(index)
        self.build_panel.name_edit.setText(state.get("build_name", "") or "")
        self.build_panel.extra_edit.setText(state.get("build_extra", "") or "")
        self.flash(f"Restored {len(state.get('open_files', []))} file(s) from the last session.")

    def current_working_directory(self) -> Path:
        tab = self.tabs.currentWidget()
        tab_path = getattr(tab, "path", None)
        if tab_path and Path(tab_path).parent.is_dir():
            return Path(tab_path).parent
        if self.explorer.project_root:
            return self.explorer.project_root
        return Path.home()

    # ------------------------------------------------------------------ saving
    def save_tab(self, tab, save_as: bool = False) -> bool:
        if tab is None or getattr(tab, "KIND", "") != "text":
            return False
        target = None
        if save_as or tab.path is None:
            suggestion = str(tab.path) if tab.path else str(
                self.current_working_directory() / f"{tab.display_name()}.py"
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "Save File", suggestion,
                "Python (*.py);;Text (*.txt);;JSON (*.json);;All files (*)",
            )
            if not path:
                return False
            target = Path(path)
        suffix_after = (target or tab.path).suffix.lower() if (target or tab.path) else ""
        if self.config.get("format_on_save", False) and suffix_after in PYTHON_SUFFIXES:
            self._format_tab(tab, silent=True)
        if not tab.save(target):
            QMessageBox.critical(self, APP_NAME, "Could not save the file. Check permissions.")
            return False
        self._run_lint(tab)
        self.git_panel.refresh(quiet=True)
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self._update_tab_title(index)
        self.explorer.refresh()
        self.flash(f"Saved {tab.path}")
        self._on_tab_changed(self.tabs.currentIndex())
        return True

    def save_active(self) -> None:
        tab = self.tabs.currentWidget()
        if getattr(tab, "KIND", "") == "text":
            self.save_tab(tab)
        elif tab is not None:
            self.flash("This tab has nothing to save.")

    def save_active_as(self) -> None:
        tab = self.tabs.currentWidget()
        if getattr(tab, "KIND", "") == "text":
            self.save_tab(tab, save_as=True)

    def close_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None:
            return
        if getattr(widget, "KIND", "") == "text" and widget.is_modified():
            self.tabs.setCurrentIndex(index)
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {widget.display_name()} before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self.save_tab(widget):
                return
        closed_path = getattr(widget, "path", None)
        if closed_path is not None:
            stack = getattr(self, "_closed_tabs", [])
            stack.append(Path(closed_path))
            self._closed_tabs = stack[-15:]
        if getattr(widget, "KIND", "") == "text":
            self.problems.forget_file(self._lint_key(widget))
        self.tabs.removeTab(index)
        widget.deleteLater()
        if self.tabs.count() == 0:
            self._show_welcome()
        self.outline.rebuild()
        self.build_panel.refresh()

    def close_current_tab(self) -> None:
        self.close_tab_at(self.tabs.currentIndex())

    def close_all_tabs(self) -> None:
        for index in range(self.tabs.count() - 1, -1, -1):
            self.close_tab_at(index)

    def on_path_renamed(self, old: Path, new: Path) -> None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            widget_path = getattr(widget, "path", None)
            if widget_path is None:
                continue
            try:
                widget_path = Path(widget_path)
                if widget_path == old or old in widget_path.parents:
                    relative = widget_path.relative_to(old)
                    widget.path = new / relative
                    self._update_tab_title(index)
            except Exception:
                continue
        self.flash(f"Renamed to {new.name}")

    def on_path_deleted(self, path: Path) -> None:
        for index in range(self.tabs.count() - 1, -1, -1):
            widget = self.tabs.widget(index)
            widget_path = getattr(widget, "path", None)
            if widget_path is None:
                continue
            try:
                widget_path = Path(widget_path)
                if widget_path == path or path in widget_path.parents:
                    widget.editor.document().setModified(False)
                    self.tabs.removeTab(index)
                    widget.deleteLater()
            except Exception:
                continue
        if self.tabs.count() == 0:
            self._show_welcome()
        self.flash(f"Deleted {path.name}")

    # ------------------------------------------------------------------ editor commands
    def _current_editor(self):
        tab = self.tabs.currentWidget()
        if getattr(tab, "KIND", "") == "text":
            return tab.editor
        return None

    def _editor_undo(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.undo()

    def _editor_redo(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.redo()

    def _editor_cut(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.cut()

    def _editor_copy(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.copy()

    def _editor_paste(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.paste()

    def _editor_select_all(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.selectAll()

    def _zoom(self, delta: int) -> None:
        size = int(self.config.get("font_size", 11) or 11) + delta
        size = max(7, min(28, size))
        self.config.set("font_size", size)
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                widget.set_font_size(size)
        self.flash(f"Editor font size: {size}pt")

    def _zoom_reset(self) -> None:
        self.config.set("font_size", 11)
        self._zoom(0)

    def _toggle_wrap(self, checked: bool) -> None:
        self.config.set("wrap_lines", bool(checked))
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                widget.set_word_wrap(bool(checked))
        self.flash(f"Word wrap {'on' if checked else 'off'}")

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # ------------------------------------------------------------------ running
    def terminal_shell_path(self) -> str:
        """The shell actually driving the terminal (used for correct quoting)."""
        if self.terminal.worker is not None:
            return self.terminal.worker.shell_path
        return self.config.get("terminal_shell") or default_shell()

    def _interpreter(self) -> str:
        interpreter = (self.config.get("python_path") or "").strip()
        if not interpreter:
            interpreter = detect_python_interpreter()
        return interpreter

    def _interpreter_ok(self, interpreter: str) -> bool:
        if not interpreter:
            return False
        if os.path.sep in interpreter or "/" in interpreter:
            return Path(interpreter).exists()
        return shutil.which(interpreter) is not None

    def run_file(self, path: Path) -> None:
        """Run/preview a file of any supported type (used by the explorer menu)."""
        tab = self.open_file(path)
        if tab is not None:
            if getattr(tab, "KIND", "") == "text" and tab.has_preview():
                tab.set_preview_visible(True)
                self.refresh_preview()
            else:
                self.run_active_file()

    def _file_command(self, path: Path | None, interpreter: str) -> str:
        """Build the Run command for the active file, honouring per-type overrides."""
        shell = self.terminal_shell_path()
        suffix = path.suffix.lower() if path else ".py"
        overrides = self.config.get("run_overrides", {}) or {}
        target = overrides.get(suffix) or RUN_TARGETS.get(suffix, "")
        quoted_path = shell_quote(str(path), shell)

        if target == "python" or target == "":
            return build_command(interpreter, quoted_path, shell)
        if target == "browser":
            return build_command(interpreter, "-m webbrowser -t " + quoted_path, shell)
        if target == "shell":
            return build_command("bash", quoted_path, shell)
        if target == "powershell":
            return build_command("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File "
                                 + quoted_path, shell)
        if target == "cmd":
            return build_command("cmd.exe", "/c " + quoted_path, shell)
        return build_command(target, quoted_path, shell)

    def run_active_file(self) -> None:
        tab = self.tabs.currentWidget()
        if tab is None:
            QMessageBox.information(self, APP_NAME, "Open a file to run it.")
            return
        kind = getattr(tab, "KIND", "")
        if kind in ("image", "binary", "media", "welcome"):
            if kind == "media":
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(tab.path)))
            else:
                QMessageBox.information(
                    self, APP_NAME,
                    "This tab has nothing to execute. Open a .py, .html, .js, .md or .sh file.",
                )
            return
        if tab.path is None or tab.is_modified():
            if not self.save_tab(tab):
                return
        path = Path(tab.path)
        suffix = path.suffix.lower()

        # Markdown / HTML preview rather than execution
        if suffix in PREVIEW_KINDS and getattr(tab, "has_preview", lambda: False)():
            tab.set_preview_visible(True)
            tab.refresh_preview()
            self.act_toggle_preview.setChecked(True)
            self.flash(f"Previewing {path.name}")
            return

        interpreter = self._interpreter()
        needs_python = RUN_TARGETS.get(suffix, "python") == "python"
        if needs_python and not self._interpreter_ok(interpreter):
            answer = QMessageBox.question(
                self, "Python interpreter not found",
                f"The configured interpreter was not found:\n\n{interpreter}\n\n"
                "Open Settings now to point at your python.exe?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.open_settings()
            return

        command = self._file_command(path, interpreter)
        self.show_terminal()
        self.terminal.set_workdir(path.parent)
        self.terminal.write(f"\n— running {path.name} —\n")
        self.terminal.run_command(command)
        self.flash(f"Running {path.name}")

    def run_in_terminal(self) -> None:
        command, ok = QInputDialog.getText(
            self, "Run in Terminal", "Shell command to run in the project directory:"
        )
        if ok and command.strip():
            self.show_terminal()
            self.terminal.run_command(command.strip())

    def stop_process(self) -> None:
        self.terminal.interrupt()
        self.flash("Interrupt sent to the terminal.")

    # ------------------------------------------------------------------ v2: navigation
    def show_outline(self) -> None:
        self.outline_dock.show()
        self.outline_dock.raise_()
        self.right_hub.setCurrentWidget(self.outline)
        self.outline.rebuild()

    def show_build(self) -> None:
        self.build_dock.show()
        self.build_dock.raise_()
        self.build_panel.refresh()
        self.build_panel.build_button.setFocus()

    def change_explorer_folder(self) -> None:
        start = str(self.explorer.project_root or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose Explorer Folder", start)
        if folder:
            self.explorer.set_project(Path(folder))
            self.flash(f"Explorer now shows {folder}")

    def open_terminal_at(self, directory: Path) -> None:
        self.show_terminal()
        self.terminal.set_workdir(directory)

    def quick_open(self) -> None:
        dialog = QuickOpenDialog(self, self)
        dialog.exec()

    def project_search(self) -> None:
        dialog = ProjectSearchDialog(self, self)
        dialog.exec()

    def show_find(self, replace: bool = False) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            self.flash("Open a text file to search inside it.")
            return
        tab.show_find(replace=replace)

    def find_next(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.find_next()

    def find_previous(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.find_previous()

    def goto_line_dialog(self) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            self.flash("Open a text file first.")
            return
        current = tab.editor.textCursor().blockNumber() + 1
        line, ok = QInputDialog.getInt(
            self, "Go to Line", f"Line number (1 – {tab.editor.blockCount()}):",
            current, 1, max(1, tab.editor.blockCount()), 1,
        )
        if ok:
            tab.goto_line(line)

    # ------------------------------------------------------------------ v2: editing
    def toggle_comment(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.comment_toggle()
            self.flash("Toggled comment.")

    def duplicate_line(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.duplicate_line()

    def delete_line(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.delete_line()

    def move_line(self, direction: int) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.move_line(direction)

    def format_json(self) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            return
        if tab.format_json():
            self.flash("JSON formatted (2-space indent).")
        else:
            QMessageBox.warning(self, APP_NAME, "This file does not contain valid JSON.")

    def sort_lines(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.sort_lines()
            self.flash("Lines sorted.")

    def _maybe_autosave(self, widget) -> None:
        """Save automatically (debounced) when Auto Save is enabled."""
        if not self.config.get("auto_save") or getattr(widget, "path", None) is None:
            return
        if not widget.is_modified():
            return
        timer = getattr(widget, "_autosave_timer", None)
        if timer is None:
            timer = QTimer(widget)
            timer.setSingleShot(True)
            timer.setInterval(1200)
            timer.timeout.connect(lambda: self.save_tab(widget) if widget.is_modified() else None)
            widget._autosave_timer = timer
        timer.start()

    def save_all(self) -> None:
        saved = 0
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text" and widget.is_modified() and widget.path:
                if self.save_tab(widget):
                    saved += 1
        self.flash(f"Saved {saved} file(s)." if saved else "Nothing to save.")

    # ------------------------------------------------------------------ v2: view
    def toggle_preview(self, checked: bool) -> None:
        tab = self.active_editor_tab()
        if tab is None or not tab.has_preview():
            self.act_toggle_preview.setChecked(False)
            self.flash("Live preview is available for Markdown, HTML and HTM files.")
            return
        tab.set_preview_visible(bool(checked))
        self.flash(f"Preview {'shown' if checked else 'hidden'}.")

    def refresh_preview(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None and tab.has_preview():
            tab.refresh_preview()
            tab.set_preview_visible(True)
            self.act_toggle_preview.setChecked(True)
            self.flash("Preview refreshed.")
        else:
            self.flash("The active tab has no preview.")

    def toggle_whitespace(self, checked: bool) -> None:
        self.config.set("show_whitespace", bool(checked))
        self.config.save()
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                widget.editor.set_whitespace_visible(bool(checked))

    def toggle_scroll_past_end(self, checked: bool) -> None:
        self.config.set("scroll_past_end", bool(checked))
        self.config.save()

    def toggle_autosave(self, checked: bool) -> None:
        self.config.set("auto_save", bool(checked))
        self.config.save()
        self.flash(f"Auto save {'enabled' if checked else 'disabled'}.")

    def toggle_zen(self) -> None:
        """Hide every panel for distraction-free editing (Ctrl+Alt+Z)."""
        self._zen_state = not getattr(self, "_zen_state", False)
        for dock in self.findChildren(QDockWidget):
            dock.setVisible(not self._zen_state)
        self.statusBar().setVisible(not self._zen_state)
        for toolbar in self.findChildren(QToolBar):
            toolbar.setVisible(not self._zen_state)
        self.flash("Zen mode on — Ctrl+Alt+Z to exit." if self._zen_state else "Zen mode off.")

    # ------------------------------------------------------------------ v2: recents
    def _remember_file(self, path: Path) -> None:
        recent = remember(self.config.get("recent_files", []) or [], str(path))
        self.config.set("recent_files", recent)
        self.config.save()
        if hasattr(self, "recent_files_menu"):
            self._populate_recent_menus()

    def _remember_project(self, path: Path) -> None:
        recent = remember(self.config.get("recent_projects", []) or [], str(path))
        self.config.set("recent_projects", recent)
        self.config.save()
        if hasattr(self, "recent_projects_menu"):
            self._populate_recent_menus()

    def reopen_closed_tab(self) -> None:
        stack = getattr(self, "_closed_tabs", [])
        if not stack:
            self.flash("No recently closed tab.")
            return
        path = stack.pop()
        if path and Path(path).exists():
            self.open_file(Path(path))
            self.flash(f"Reopened {Path(path).name}")
        else:
            self.new_file()

    # ------------------------------------------------------------------ settings
    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            previous_shell = self.config.get("terminal_shell")
            self.config.update(values)
            self.config.save()
            self.ai_panel.update_provider_label()
            self._refresh_interpreter_label()
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if getattr(widget, "KIND", "") == "text":
                    widget.set_font_size(values["font_size"])
                    widget.set_word_wrap(values["wrap_lines"])
            self.act_wrap.setChecked(values["wrap_lines"])
            if values["terminal_shell"] != previous_shell:
                self.terminal.restart_shell()
            self.packages.refresh_installed_silently()
            self.flash("Settings saved to " + str(CONFIG_FILE))

    def _open_config_folder(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    # ------------------------------------------------------------------ help
    def show_shortcuts(self) -> None:
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "General\n"
            "  Ctrl+Shift+P  Command palette    Ctrl+P  Quick open file\n"
            "  Ctrl+R  Go to symbol              Ctrl+G  Go to line\n"
            "  Ctrl+Shift+F  Search in project   Ctrl+,  Settings\n\n"
            "File\n"
            "  Ctrl+N  New    Ctrl+O  Open    Ctrl+K Ctrl+O  Open folder\n"
            "  Ctrl+S  Save   Ctrl+Shift+S  Save as   Ctrl+W  Close tab\n\n"
            "Editing\n"
            "  Ctrl+Space  Suggestions    Tab  Expand snippet / next stop\n"
            "  Shift+Alt+F  Format document   Ctrl+/  Toggle comment\n"
            "  Ctrl+D  Duplicate line   Alt+Up/Down  Move line\n"
            "  Ctrl+K Ctrl+L  Fold   Ctrl+K Ctrl+0  Fold all   Ctrl+K Ctrl+J  Unfold all\n"
            "  F8 / Shift+F8  Next / previous problem\n\n"
            "Run\n"
            "  F5  Run file   Shift+F5  Debug with pdb   Ctrl+.  Interrupt\n\n"
            "Panels\n"
            "  Ctrl+Shift+E  Explorer   Ctrl+Shift+G  Source control   Ctrl+Alt+T  Tests\n"
            "  Ctrl+Shift+M  Problems   Ctrl+Shift+O  Outline   Ctrl+`  Terminal\n"
            "  Ctrl+Alt+P  Packages     Ctrl+Alt+A  AI assistant   Ctrl+Alt+R  Reset layout\n"
            "  Ctrl+Alt+I  Select Python interpreter",
        )

    def show_about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>A single-file PyQt6 desktop IDE: dockable panels, a real terminal, "
            "live PyPI package management and multi-provider AI assistance.</p>"
            f"<p style='color:#8b8b8b'>Python {platform.python_version()} · "
            f"PyQt6 · {platform.system()} {platform.release()}</p>"
            f"<p style='color:#8b8b8b'>Settings: {CONFIG_FILE}</p>",
        )

    # ------------------------------------------------------------------ v3 pro features
    def _build_pro_actions(self) -> None:
        a = self._action
        self.act_palette = a("Command Palette…", "Ctrl+Shift+P", self.command_palette,
                             "Search and run any command")
        self.act_goto_symbol = a("Go to Symbol in File…", "Ctrl+R", self.goto_symbol,
                                 "Jump to a function or class in the active file")
        self.act_suggest = a("Trigger Suggestions", None, self.trigger_suggestions,
                             "Open the completion list (Ctrl+Space)")
        self.act_format_doc = a("Format Document", "Shift+Alt+F", self.format_document,
                                "Format with black/ruff (or basic cleanup)")
        self.act_next_problem = a("Next Problem", "F8", lambda: self.step_problem(1),
                                  "Jump to the next error or warning in this file")
        self.act_prev_problem = a("Previous Problem", "Shift+F8", lambda: self.step_problem(-1),
                                  "Jump to the previous error or warning")
        self.act_fold = a("Fold / Unfold at Cursor", "Ctrl+K, Ctrl+L", self.fold_toggle)
        self.act_fold_all = a("Fold All", "Ctrl+K, Ctrl+0", self.fold_all)
        self.act_unfold_all = a("Unfold All", "Ctrl+K, Ctrl+J", self.unfold_all)
        self.act_show_problems = a("Problems", "Ctrl+Shift+M", self.show_problems)
        self.act_show_git = a("Source Control", "Ctrl+Shift+G", self.show_git)
        self.act_show_tests = a("Tests", "Ctrl+Alt+T", self.show_tests)
        self.act_show_todo = a("TODO List", None, self.show_todos)
        self.act_run_tests = a("Run All Tests", None, self.run_all_tests)
        self.act_run_file_tests = a("Run Tests in Active File", None, self.run_file_tests)
        self.act_debug = a("Debug Active File (pdb)", "Shift+F5", self.debug_active_file,
                           "Run the active script under the Python debugger in the terminal")
        self.act_select_interp = a("Select Python Interpreter…", "Ctrl+Alt+I", self.select_interpreter)
        self.act_create_venv = a("Create Virtual Environment…", None, self.create_venv)
        self.act_install_reqs = a("Install requirements.txt", None, self.install_requirements)
        self.act_freeze = a("Write requirements.txt (pip freeze)", None, self.freeze_requirements)
        self.act_compare_saved = a("Compare Active File with Saved Version", None, self.compare_with_saved)
        self.act_compare_file = a("Compare Active File with Another File…", None, self.compare_with_file)
        self.act_git_refresh = a("Git: Refresh Status", None, lambda: self.git_panel.refresh())
        self.act_git_commit = a("Git: Commit…", None, self.git_focus_commit)
        self.act_git_stage_all = a("Git: Stage All Changes", None, lambda: self.git_panel.stage_all())
        self.act_git_pull = a("Git: Pull", None, lambda: self.git_panel.pull())
        self.act_git_push = a("Git: Push", None, lambda: self.git_panel.push())
        self.act_git_fetch = a("Git: Fetch", None, lambda: self.git_panel.fetch())
        self.act_git_branch = a("Git: Switch Branch…", None, lambda: self.git_panel.show_branch_menu())
        self.act_git_new_branch = a("Git: New Branch…", None, lambda: self.git_panel.new_branch())
        self.act_git_stash = a("Git: Stash Changes", None, lambda: self.git_panel.stash())
        self.act_git_stash_pop = a("Git: Pop Stash", None, lambda: self.git_panel.stash_pop())
        self.act_git_diff_file = a("Git: Show Changes in Active File", None, self.git_diff_active)
        self.act_live_lint = a("Live Problem Checking", None,
                               lambda on: self._toggle_feature("live_lint", on), checkable=True)
        self.act_completion = a("Auto-Completion", None,
                                lambda on: self._toggle_feature("completion", on), checkable=True)
        self.act_auto_close = a("Auto-Close Brackets and Quotes", None,
                                lambda on: self._toggle_feature("auto_close", on), checkable=True)
        self.act_format_save = a("Format Python on Save", None,
                                 lambda on: self._toggle_feature("format_on_save", on), checkable=True)
        self.act_live_lint.setChecked(bool(self.config.get("live_lint", True)))
        self.act_completion.setChecked(bool(self.config.get("completion", True)))
        self.act_auto_close.setChecked(bool(self.config.get("auto_close", True)))
        self.act_format_save.setChecked(bool(self.config.get("format_on_save", False)))

    def _extend_menus(self, menubar) -> None:
        self.edit_menu.addSeparator()
        self.edit_menu.addActions([self.act_format_doc, self.act_suggest])
        fold_menu = self.edit_menu.addMenu("Folding")
        fold_menu.addActions([self.act_fold, self.act_fold_all, self.act_unfold_all])
        self.go_menu.addSeparator()
        self.go_menu.addActions([self.act_palette, self.act_goto_symbol,
                                 self.act_next_problem, self.act_prev_problem])
        self.view_menu.addSeparator()
        self.view_menu.addActions([self.act_show_problems, self.act_show_git,
                                   self.act_show_tests, self.act_show_todo])
        self.run_menu.addSeparator()
        self.run_menu.addActions([self.act_debug, self.act_run_tests, self.act_run_file_tests])
        self.tools_menu.addSeparator()
        self.tools_menu.addActions([self.act_select_interp, self.act_create_venv,
                                    self.act_install_reqs, self.act_freeze])
        self.tools_menu.addSeparator()
        self.tools_menu.addActions([self.act_compare_saved, self.act_compare_file])
        features = self.tools_menu.addMenu("Editor Intelligence")
        features.addActions([self.act_live_lint, self.act_completion, self.act_auto_close,
                             self.act_format_save])
        git_menu = menubar.addMenu("&Git")
        git_menu.addActions([self.act_show_git, self.act_git_refresh, self.act_git_commit,
                             self.act_git_stage_all])
        git_menu.addSeparator()
        git_menu.addActions([self.act_git_pull, self.act_git_push, self.act_git_fetch])
        git_menu.addSeparator()
        git_menu.addActions([self.act_git_branch, self.act_git_new_branch])
        git_menu.addSeparator()
        git_menu.addActions([self.act_git_diff_file, self.act_git_stash, self.act_git_stash_pop])

    # ---- panels ------------------------------------------------------------------
    def show_git(self) -> None:
        self.explorer_dock.show()
        self.explorer_dock.raise_()
        self.left_hub.setCurrentWidget(self.git_panel)
        self.git_panel.refresh(quiet=True)

    def show_tests(self) -> None:
        self.explorer_dock.show()
        self.explorer_dock.raise_()
        self.left_hub.setCurrentWidget(self.tests_panel)
        if not self.tests_panel.items and self.explorer.project_root:
            self.tests_panel.discover()

    def show_problems(self) -> None:
        self.outline_dock.show()
        self.outline_dock.raise_()
        self.right_hub.setCurrentWidget(self.problems)

    def show_todos(self) -> None:
        self.outline_dock.show()
        self.outline_dock.raise_()
        self.right_hub.setCurrentWidget(self.todo_panel)
        if not self.todo_panel.entries and self.explorer.project_root:
            self.todo_panel.scan()

    def git_focus_commit(self) -> None:
        self.show_git()
        self.git_panel.message.setFocus()

    def git_diff_active(self) -> None:
        tab = self.active_editor_tab()
        self.git_panel.show_file_history_diff(tab.path if tab else None)

    def refresh_git_marks(self) -> None:
        count = 0
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                self.git_panel.update_marks(widget)
                count += 1
                if count >= 15:
                    break

    def _on_branch_changed(self, text: str, total: int) -> None:
        self.status_branch.setText(text or "⎇ no repository")
        self.left_hub.set_badge(self.git_panel, str(total) if total else "")

    def _on_problem_counts(self, errors: int, warnings_: int, infos: int) -> None:
        self.status_problems.setText(f"✖ {errors}   ▲ {warnings_}")
        color = "#f14c4c" if errors else ("#cca700" if warnings_ else "#9d9d9d")
        self.status_problems.setStyleSheet(
            f"QToolButton {{ color: {color}; border: none; padding: 0 8px; }}"
            "QToolButton:hover { background: rgba(128,128,128,0.2); }")
        self.right_hub.set_badge(self.problems, str(errors + warnings_) if errors + warnings_ else "")

    # ---- command palette / symbols -----------------------------------------------
    def _collect_commands(self) -> list:
        items, seen = [], set()

        def label_of(action) -> str:
            return action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")

        def walk(menu, trail: list) -> None:
            for action in menu.actions():
                sub = action.menu()
                if sub is not None:
                    title = label_of(action)
                    if title.startswith(("Open Recent", "Recent Projects")):
                        continue
                    walk(sub, trail + [title])
                    continue
                if action.isSeparator() or not action.text() or not action.isEnabled() or id(action) in seen:
                    continue
                seen.add(id(action))
                name = label_of(action)
                if name.endswith("…"):
                    name = name[:-1]
                prefix = (trail[0] + ": ") if trail else ""
                if trail and name.startswith(trail[0] + ":"):
                    prefix = ""
                if trail and trail[0] == "Panels":
                    prefix = "View: Panel: "
                items.append((prefix + name, action.shortcut().toString(QKeySequence.SequenceFormat.NativeText),
                              action))

        for top in self.menuBar().actions():
            if top.menu() is not None:
                walk(top.menu(), [label_of(top)])
        for action in self.actions():
            if id(action) not in seen and action.text() and action.isEnabled():
                seen.add(id(action))
                items.append((label_of(action).rstrip("…"),
                              action.shortcut().toString(QKeySequence.SequenceFormat.NativeText), action))
        return items

    def command_palette(self) -> None:
        chosen = PickerDialog.pick(self, "Command Palette",
                                   "Type a command — e.g. “format”, “git push”, “fold all”…",
                                   self._collect_commands())
        if chosen is not None:
            QTimer.singleShot(0, chosen.trigger)

    def goto_symbol(self) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            self.flash("Open a code file first.")
            return
        suffix = tab.path.suffix.lower() if tab.path else ".py"
        symbols = find_symbols(tab.text(), suffix)
        if not symbols:
            self.flash("No functions or classes found in this file.")
            return
        items = [(f"{'◆' if kind == 'class' else 'ƒ'}  {name}", f"{kind} · line {line + 1}", line)
                 for kind, name, line in symbols]
        line = PickerDialog.pick(self, "Go to Symbol", "Type a function or class name…", items)
        if line is not None:
            tab.goto_line(line + 1)

    def trigger_suggestions(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.editor.setFocus()
            tab.editor.update_completions(forced=True)

    # ---- folding -------------------------------------------------------------------
    def fold_toggle(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.editor.fold_at_cursor()

    def fold_all(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.editor.fold_all()

    def unfold_all(self) -> None:
        tab = self.active_editor_tab()
        if tab is not None:
            tab.editor.unfold_all()

    # ---- diagnostics -----------------------------------------------------------------
    @staticmethod
    def _lint_key(tab) -> str:
        return str(tab.path) if tab.path else f"untitled:{id(tab)}"

    def _tab_alive(self, tab) -> bool:
        try:
            return self.tabs.indexOf(tab) >= 0
        except RuntimeError:
            return False

    def _setup_editor_features(self, tab) -> None:
        tab.configure_editor(auto_close=self.config.get("auto_close", True),
                             completion=self.config.get("completion", True),
                             jedi=self.config.get("jedi", True))
        tab.editor.extra_words_provider = lambda t=tab: self._project_words(t)
        timer = QTimer(tab)
        timer.setSingleShot(True)
        timer.setInterval(650)
        timer.timeout.connect(lambda t=tab: self._run_lint(t))
        tab._lint_timer = timer
        tab._diag_internal = []
        tab._diag_external = None
        tab.editor.textChanged.connect(timer.start)
        QTimer.singleShot(350, lambda t=tab: self._run_lint(t))
        QTimer.singleShot(600, lambda t=tab: self._alive_call(t, self.git_panel.update_marks))

    def _alive_call(self, tab, function) -> None:
        if self._tab_alive(tab):
            function(tab)

    def _project_words(self, current) -> list:
        words: list = []
        pattern = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)
        for index in range(min(self.tabs.count(), 14)):
            widget = self.tabs.widget(index)
            if widget is current or getattr(widget, "KIND", "") != "text":
                continue
            words.extend(pattern.findall(widget.text()[:200000]))
        return words

    def _run_lint(self, tab) -> None:
        if not self._tab_alive(tab) or getattr(tab, "KIND", "") != "text":
            return
        key = self._lint_key(tab)
        if not self.config.get("live_lint", True):
            tab.editor.set_diagnostics([])
            self.problems.forget_file(key)
            return
        suffix = tab.path.suffix.lower() if tab.path else ""
        text = tab.text()
        if len(text) > 1_500_000:
            return
        if suffix in PYTHON_SUFFIXES:
            diagnostics = analyze_python(text, tab.path)
        elif suffix == ".json":
            diagnostics = analyze_json(text)
        else:
            diagnostics = []
        tab._diag_internal = diagnostics
        if suffix not in PYTHON_SUFFIXES or any(d.code == "syntax-error" for d in diagnostics):
            tab._diag_external = None
        self._publish_diagnostics(tab)
        if suffix in PYTHON_SUFFIXES and not any(d.code == "syntax-error" for d in diagnostics):
            self._schedule_pyflakes(tab)

    def _publish_diagnostics(self, tab) -> None:
        if not self._tab_alive(tab):
            return
        diagnostics = list(getattr(tab, "_diag_internal", []))
        external = getattr(tab, "_diag_external", None)
        if external is not None:
            diagnostics = [d for d in diagnostics if d.code != "unused-import"] + list(external)
        diagnostics.sort(key=lambda d: (d.line, d.col))
        tab.editor.set_diagnostics(diagnostics)
        self.problems.set_file(self._lint_key(tab), tab.display_name(), tab.path, diagnostics)

    def _schedule_pyflakes(self, tab) -> None:
        interpreter = self._interpreter()
        if self._pyflakes_state.get(interpreter) is False or not self._interpreter_ok(interpreter):
            return
        worker = getattr(tab, "_flakes_worker", None)
        if worker is not None and worker.isRunning():
            tab._flakes_pending = True
            return
        worker = PyflakesWorker(tab, tab.editor.document().revision(), interpreter, tab.text(), self)
        worker.done.connect(self._on_pyflakes_done)
        tab._flakes_worker = worker
        tab._flakes_pending = False
        worker.start()

    def _on_pyflakes_done(self, tab, revision: int, diagnostics) -> None:
        interpreter = self._interpreter()
        if not self._tab_alive(tab):
            return
        if diagnostics is None:
            self._pyflakes_state[interpreter] = False
            tab._diag_external = None
        else:
            self._pyflakes_state[interpreter] = True
            if revision == tab.editor.document().revision():
                tab._diag_external = diagnostics
        self._publish_diagnostics(tab)
        if getattr(tab, "_flakes_pending", False) or (
                diagnostics is not None and revision != tab.editor.document().revision()):
            tab._flakes_pending = False
            QTimer.singleShot(200, lambda t=tab: self._run_lint(t))

    def step_problem(self, direction: int) -> None:
        tab = self.active_editor_tab()
        if tab is None or not tab.editor.diagnostics:
            self.flash("No problems in this file.")
            return
        diagnostics = sorted(tab.editor.diagnostics, key=lambda d: (d.line, d.col))
        cursor = tab.editor.textCursor()
        here = (cursor.blockNumber(), cursor.positionInBlock())
        if direction > 0:
            target = next((d for d in diagnostics if (d.line, d.col) > here), diagnostics[0])
        else:
            target = next((d for d in reversed(diagnostics) if (d.line, d.col) < here), diagnostics[-1])
        tab.goto_line(target.line + 1, target.col)
        self.flash(f"{SEVERITY_ICON[target.severity]} {target.message}", 8000)

    def _toggle_feature(self, key: str, enabled: bool) -> None:
        self.config.set(key, bool(enabled))
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") != "text":
                continue
            widget.configure_editor(auto_close=self.config.get("auto_close", True),
                                    completion=self.config.get("completion", True),
                                    jedi=self.config.get("jedi", True))
            if key == "live_lint":
                self._run_lint(widget)
        names = {"live_lint": "Live problem checking", "completion": "Auto-completion",
                 "auto_close": "Auto-close brackets", "format_on_save": "Format on save"}
        self.flash(f"{names.get(key, key)} {'enabled' if enabled else 'disabled'}.")

    # ---- formatting ----------------------------------------------------------------------
    def format_document(self) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            self.flash("Open a file to format it.")
            return
        self._format_tab(tab, silent=False)

    def _format_tab(self, tab, silent: bool) -> bool:
        suffix = tab.path.suffix.lower() if tab.path else ""
        text = tab.text()
        if suffix == ".json":
            try:
                new_text = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
                message = "JSON formatted."
            except ValueError as exc:
                if not silent:
                    self.flash(f"Cannot format invalid JSON: {exc}")
                return False
        elif suffix in PYTHON_SUFFIXES:
            interpreter = self._interpreter()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                cwd = str(tab.path.parent) if tab.path else None
                new_text, message = format_python_source(
                    text, interpreter if self._interpreter_ok(interpreter) else "", cwd)
            finally:
                QApplication.restoreOverrideCursor()
            if new_text is None:
                if not silent:
                    self.flash(f"Format failed: {message}", 9000)
                return False
            if silent and message.startswith("Applied basic cleanup"):
                return False             # never rewrite files on save without a real formatter
        else:
            new_text, message = basic_cleanup(text), "Applied basic cleanup."
        if new_text == text:
            if not silent:
                self.flash("Already formatted.")
            return True
        apply_text_minimally(tab.editor, new_text)
        if not silent:
            self.flash(message, 7000)
        return True

    # ---- interpreters, venvs, requirements -------------------------------------------------
    def find_interpreters(self) -> list:
        found: dict[str, str] = {}
        root = self.explorer.project_root
        relative = (("bin", "python"), ("Scripts", "python.exe"), ("bin", "python3"))
        if root:
            for name in (".venv", "venv", "env", ".env"):
                for parts in relative:
                    candidate = Path(root) / name / Path(*parts)
                    if candidate.exists():
                        found.setdefault(str(candidate), f"{name} · this project")
        home = Path.home()
        patterns = [home / ".pyenv" / "versions", home / "anaconda3" / "envs", home / "miniconda3" / "envs",
                    home / ".conda" / "envs", home / "AppData" / "Local" / "Programs" / "Python"]
        for base in patterns:
            if base.is_dir():
                try:
                    for child in sorted(base.iterdir()):
                        for parts in relative:
                            candidate = child / Path(*parts)
                            if candidate.exists():
                                found.setdefault(str(candidate), f"{base.name} · {child.name}")
                        direct = child / "python.exe"
                        if direct.exists():
                            found.setdefault(str(direct), f"{child.name}")
                except OSError:
                    continue
        for name in ("python3", "python"):
            path = shutil.which(name)
            if path:
                found.setdefault(path, "on PATH")
        found.setdefault(detect_python_interpreter(), "auto-detected")
        if not getattr(sys, "frozen", False):
            found.setdefault(sys.executable, "running PyForge")
        current = self.config.get("python_path")
        if current:
            found.setdefault(current, "current")
        return [(path, note + (" · selected" if path == current else ""), path)
                for path, note in found.items()]

    def select_interpreter(self) -> None:
        items = self.find_interpreters()
        items.append(("Enter interpreter path…", "browse for python.exe / python3", "__custom__"))
        choice = PickerDialog.pick(self, "Select Python Interpreter", "Choose an interpreter…", items)
        if choice is None:
            return
        if choice == "__custom__":
            choice, _ = QFileDialog.getOpenFileName(self, "Select Python interpreter", str(Path.home()))
            if not choice:
                return
        self.config.set("python_path", choice)
        self.config.save()
        self._pyflakes_state.clear()
        self._refresh_interpreter_label()
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "KIND", "") == "text":
                self._run_lint(widget)
        self.flash(f"Interpreter set to {choice}")
        if self.tests_panel.items:
            self.tests_panel.discover()

    def create_venv(self) -> None:
        root = self.explorer.project_root
        if not root:
            QMessageBox.information(self, APP_NAME, "Open a project folder first.")
            return
        target = Path(root) / ".venv"
        if target.exists():
            QMessageBox.information(self, APP_NAME, f"{target} already exists.\n"
                                    "Use “Select Python Interpreter” to switch to it.")
            return
        interpreter = self._interpreter()
        if not self._interpreter_ok(interpreter):
            QMessageBox.warning(self, APP_NAME, "Configure a base Python interpreter first (Ctrl+,).")
            return
        self.flash("Creating virtual environment…", 20000)
        worker = FuncWorker(lambda: run_hidden([interpreter, "-m", "venv", str(target)], timeout=300), self)
        worker.result.connect(lambda outcome, w=worker: self._venv_created(outcome, target, w))
        self._workers.add(worker)
        worker.start()

    def _venv_created(self, outcome, target: Path, worker) -> None:
        self._workers.discard(worker)
        if isinstance(outcome, Exception) or outcome[0] != 0:
            detail = str(outcome) if isinstance(outcome, Exception) else (outcome[2] or outcome[1])
            QMessageBox.warning(self, "Virtual environment failed", detail[:1200])
            return
        python = target / ("Scripts/python.exe" if is_windows() else "bin/python")
        self.config.set("python_path", str(python))
        self.config.save()
        self._pyflakes_state.clear()
        self._refresh_interpreter_label()
        self.explorer.refresh()
        self.flash(f"Created {target.name} and selected it as the interpreter.")
        if (target.parent / "requirements.txt").exists():
            answer = QMessageBox.question(self, "requirements.txt found",
                                          "Install the packages from requirements.txt now?")
            if answer == QMessageBox.StandardButton.Yes:
                self.install_requirements()

    def install_requirements(self) -> None:
        root = self.explorer.project_root
        requirements = Path(root) / "requirements.txt" if root else None
        if requirements is None or not requirements.exists():
            QMessageBox.information(self, APP_NAME, "There is no requirements.txt in the project folder.")
            return
        shell = self.terminal_shell_path()
        self.show_terminal()
        self.terminal.set_workdir(Path(root))
        self.terminal.run_command(build_command(
            self._interpreter(), "-m pip install -r " + shell_quote(str(requirements), shell), shell))

    def freeze_requirements(self) -> None:
        root = self.explorer.project_root
        if not root:
            QMessageBox.information(self, APP_NAME, "Open a project folder first.")
            return
        interpreter = self._interpreter()
        target = Path(root) / "requirements.txt"
        if target.exists() and QMessageBox.question(
                self, APP_NAME, "requirements.txt already exists. Overwrite it?") != QMessageBox.StandardButton.Yes:
            return
        worker = FuncWorker(lambda: run_hidden([interpreter, "-m", "pip", "freeze"], timeout=60), self)

        def done(outcome, w=worker) -> None:
            self._workers.discard(w)
            if isinstance(outcome, Exception) or outcome[0] != 0:
                QMessageBox.warning(self, APP_NAME, "pip freeze failed:\n" + (
                    str(outcome) if isinstance(outcome, Exception) else outcome[2][:800]))
                return
            target.write_text(outcome[1], encoding="utf-8")
            self.explorer.refresh()
            self.flash(f"Wrote {target.name} ({len(outcome[1].splitlines())} packages).")

        worker.result.connect(done)
        self._workers.add(worker)
        worker.start()

    # ---- debugging, tests, compare ----------------------------------------------------------
    def debug_active_file(self) -> None:
        tab = self.active_editor_tab()
        if tab is None or (tab.path is not None and tab.path.suffix.lower() not in PYTHON_SUFFIXES):
            QMessageBox.information(self, APP_NAME, "Open a Python file to debug it.")
            return
        if tab.path is None or tab.is_modified():
            if not self.save_tab(tab):
                return
        interpreter = self._interpreter()
        if not self._interpreter_ok(interpreter):
            self.open_settings()
            return
        shell = self.terminal_shell_path()
        self.show_terminal()
        self.terminal.set_workdir(Path(tab.path).parent)
        self.terminal.write("\n— debugging with pdb:  n next · s step · c continue · p <expr> · "
                            "l list · b <line> breakpoint · q quit —\n")
        self.terminal.run_command(build_command(interpreter, "-m pdb " + shell_quote(str(tab.path), shell), shell))

    def run_all_tests(self) -> None:
        self.show_tests()
        self.tests_panel.run_all()

    def run_file_tests(self) -> None:
        tab = self.active_editor_tab()
        if tab is None or tab.path is None:
            self.flash("Open a test file first.")
            return
        self.show_tests()
        self.tests_panel.run_file(tab.path)

    def compare_with_saved(self) -> None:
        tab = self.active_editor_tab()
        if tab is None or tab.path is None or not Path(tab.path).exists():
            self.flash("Save the file once before comparing it with the saved version.")
            return
        try:
            saved, _enc = read_text_file(Path(tab.path))
        except Exception as exc:
            self.flash(f"Cannot read the saved file: {exc}")
            return
        DiffDialog(self, f"{tab.path.name}: saved ↔ editor",
                   unified_diff_text(saved, tab.text(), "saved on disk", "editor"), tab.path, self).exec()

    def compare_with_file(self) -> None:
        tab = self.active_editor_tab()
        if tab is None:
            self.flash("Open a file to compare.")
            return
        start = str(tab.path.parent) if tab.path else str(self.current_working_directory())
        other, _ = QFileDialog.getOpenFileName(self, "Compare with…", start)
        if not other:
            return
        try:
            text, _enc = read_text_file(Path(other))
        except Exception as exc:
            self.flash(f"Cannot read {other}: {exc}")
            return
        DiffDialog(self, f"{Path(other).name} ↔ {tab.display_name()}",
                   unified_diff_text(text, tab.text(), Path(other).name, tab.display_name())).exec()

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._force_close:
            modified = [
                self.tabs.widget(i) for i in range(self.tabs.count())
                if getattr(self.tabs.widget(i), "KIND", "") == "text"
                and self.tabs.widget(i).is_modified()
            ]
            if modified:
                answer = QMessageBox.question(
                    self, "Unsaved changes",
                    f"{len(modified)} file(s) have unsaved changes. Quit anyway?",
                    QMessageBox.StandardButton.SaveAll | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if answer == QMessageBox.StandardButton.SaveAll:
                    for tab in modified:
                        if not self.save_tab(tab):
                            event.ignore()
                            return
            self._force_close = True

        self.save_project_state()
        self.settings.setValue("v2/window/geometry", self.saveGeometry())
        self.settings.setValue("v2/window/state", self.saveState())
        self.settings.setValue("v2/window/maximized", self.isMaximized())
        self.settings.sync()
        self.config.save()
        self.terminal.shutdown()
        self.packages.shutdown()
        self.ai_panel.shutdown()
        for panel in (self.git_panel, self.tests_panel, self.problems, self.todo_panel):
            try:
                panel.shutdown()
            except Exception:
                pass
        for worker in list(self._workers):
            worker.wait(1500)
        event.accept()


# --------------------------------------------------------------------------------------
# Application entry point
# --------------------------------------------------------------------------------------


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR["bg_alt"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR["bg_alt"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3d41"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(COLOR["red"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(COLOR["accent"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR["selection"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLOR["text_dim"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b6b6b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6b6b6b"))
    app.setPalette(palette)
    app.setStyleSheet(THEME_QSS)

    font = QFont()
    for family in ("Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Sans Serif"):
        if family in set(QFontDatabase.families()):
            font.setFamily(family)
            break
    font.setPointSize(9)
    app.setFont(font)


def install_exception_hook() -> None:
    """Show a dialog instead of dying silently — important in a windowed .exe."""

    def hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        if QApplication.instance() is None:
            return
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(f"{APP_NAME} — unexpected error")
        box.setText("Something went wrong, but the IDE is still running.")
        box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = hook


def main() -> int:
    if is_windows():
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PyForge.IDE.1")
        except Exception:
            pass

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setDesktopFileName("pyforge-ide")
    apply_theme(app)
    install_exception_hook()

    window = MainWindow()
    window.show()
    if window.settings.value("v2/window/maximized", False, type=bool):
        window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
