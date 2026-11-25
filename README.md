# PyForge

A lightweight, customizable, single-file Python desktop IDE built with **PyQt6**.

## ✨ Features
* **Customizable Dockable Layout:** Drag, float, stack, or tab any panel (Explorer, Terminal, PyPI Manager, AI Assistant) anywhere in the window—your layout saves automatically.
* **Project File Explorer:** Browse folders, open any file type (code, text, images, and safe binary previews), and create, rename, or delete files directly in the sidebar.
* **Code Editor:** Multi-tab editor with line numbers, 4-space indentation, and Python syntax highlighting.
* **Real Interactive Terminal:** Embedded live shell (`PowerShell` on Windows / `bash` on Linux & macOS) for real script execution, interactive `input()` prompts, and shell commands.
* **Built-in PyPI Package Manager:** Search Python libraries directly on PyPI, view installed packages, and install or uninstall libraries with one click.
* **Optional Multi-Provider AI Assistant:** Connect a local **Ollama** instance or enter an **OpenAI** / **Anthropic** API key to ask questions about your code or apply direct edits (with one-click Undo).

---

## 🚀 Running from Source

1. **Clone the repository:**
   ```bash
   git clone https://github.com
   cd PyForge
   ```

2. **Install dependencies:**
   ```bash
   pip install PyQt6 requests
   ```

3. **Launch the IDE:**
   ```bash
   python pyforge_ide.py
   ```

---

## 🛠️ Building the Standalone `.exe` (Windows)

Follow these steps to compile `pyforge_ide.py` into a standalone Windows executable.

### Prerequisites
* **Python 3.10 – 3.13** installed on Windows (make sure **"Add python.exe to PATH"** was checked during installation).

### 1. Clone the Repository
```bash
git clone https://github.com
cd PyForge
```

### 2. Install Build Dependencies
Open a terminal (Command Prompt or PowerShell) inside the project folder and run:
```bash
pip install PyQt6 requests pyinstaller
```

### 3. Compile with PyInstaller
```bash
pyinstaller --onefile --windowed --name "PyForgeIDE" pyforge_ide.py
```

### 4. Run & Configure
1. Once the build finishes, open the newly created **`dist/`** folder and double-click **`PyForgeIDE.exe`**.
2. **First-time setup:** Open **Settings** inside the app and set the **Python Interpreter** path to your local `python.exe` (or `python`) so the IDE can run scripts and install packages via `pip`.
