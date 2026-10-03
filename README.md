# Fakturama Image-to-Cash

Takes an order document (image or PDF), extracts and validates it, then creates and verifies the
matching **Order + linked Invoice** inside a running Fakturama desktop application.

This file covers **installation and running only**. The architecture is documented separately in
[docs/DESIGN.md](docs/DESIGN.md).

---

## 1. Requirements

| Requirement | Details |
|---|---|
| OS | **Windows 10 or 11 only.** The project uses the Windows OCR API and Windows UI Automation. It does not run on Linux or macOS. |
| Python | 3.11 – 3.13 (tested on 3.13.7), 64-bit. |
| Windows OCR language pack | English OCR must be installed: Settings → Time & language → Language & region → English → Language options → Basic typing / OCR. |
| Fakturama | Version 2.2, already installed, **already running**, with an open workspace. Needed only for the `run` command — not for the tests. |

Check your Python:

```bash
python --version
python -m pip --version
```

If `python` is not recognized, use the Windows launcher `py` instead of `python` in every command
below.

---

## 2. Get the code

```bash
git clone https://github.com/Mahmoud135200/Fakturama_I2C.git
cd Fakturama_I2C
```

All commands in this file are run from the repository root.

---

## 3. Install the dependencies

Pick **one** of the methods below. Method A is recommended.

### A. Virtual environment + pip (recommended)

Create the environment:

```bash
python -m venv .venv
```

Activate it:

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

```cmd
:: cmd.exe
.\.venv\Scripts\activate.bat
```

```bash
# Git Bash
source .venv/Scripts/activate
```

Install:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Leave the environment later with `deactivate`.

> If PowerShell blocks the activation script with an execution-policy error, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and activate again.

### B. No virtual environment (per-user install)

```bash
python -m pip install --user -r requirements.txt
```

### C. Pin a specific Python version with the `py` launcher

Useful when several Pythons are installed, or when you want `rapidocr` (see the note in section 4):

```bash
py -3.12 -m venv .venv
.\.venv\Scripts\activate.bat
py -3.12 -m pip install -r requirements.txt
```

List the versions you have with `py --list`.

### D. Install the packages one by one

Equivalent to `requirements.txt`, if you prefer explicit control:

```bash
python -m pip install "uiautomation>=2.0.20"
python -m pip install "pywin32>=306"
python -m pip install "winocr>=0.0.13"
python -m pip install numpy
python -m pip install "pillow>=10"
python -m pip install "pypdfium2>=4"
python -m pip install "pytest>=8"
python -m pip install "rapidocr_onnxruntime>=1.3"
```

The last one is optional and only installs on Python < 3.13.

### E. conda / miniconda

```bash
conda create -n fakturama python=3.12 -y
conda activate fakturama
python -m pip install -r requirements.txt
```

Install with `pip` inside the conda environment — these packages are not all available on
conda-forge.

### F. uv (fast pip replacement)

```bash
uv venv
.\.venv\Scripts\activate.bat
uv pip install -r requirements.txt
```

### G. Offline / air-gapped machine

On a machine with internet access, download the wheels:

```bash
python -m pip download -r requirements.txt -d wheels --platform win_amd64 --only-binary=:all:
```

Copy the `wheels` folder to the target machine, then:

```bash
python -m pip install --no-index --find-links=wheels -r requirements.txt
```

### H. Behind a proxy or a private mirror

```bash
python -m pip install -r requirements.txt --proxy http://user:pass@proxy.host:port
python -m pip install -r requirements.txt --index-url https://your.mirror/simple --trusted-host your.mirror
```

---

## 4. What is in `requirements.txt`

| Package | Used for |
|---|---|
| `uiautomation>=2.0.20` | Walking the UIA tree, control patterns, clicks |
| `pywin32>=306` | `win32gui` / `win32process` — window lifecycle and foreground checks |
| `winocr>=0.0.13` | Windows OCR: the full-page pass and the multi-variant cell pass |
| `rapidocr_onnxruntime>=1.3` | Optional second OCR engine, better on short tokens |
| `numpy` | Image arrays for the cell-level re-read |
| `pillow>=10` | Image loading, grid screenshots, mock rendering |
| `pypdfium2>=4` | PDF rendering (self-contained wheel, no Poppler needed) |
| `pytest>=8` | Test suite |

**Note on `rapidocr_onnxruntime`:** it is marked `python_version < "3.13"` because no 3.13 wheel is
published yet. On Python 3.13 pip skips it and everything still works — Windows OCR is the primary
engine. If you want it, use Python 3.12 (method C or E above).

---

## 5. Make the package importable

The code lives under `src/` and the project has no `pyproject.toml`, so `src` must be on
`PYTHONPATH` before you run the program:

```powershell
# PowerShell
$env:PYTHONPATH = "src"
```

```cmd
:: cmd.exe
set PYTHONPATH=src
```

```bash
# Git Bash
export PYTHONPATH=src
```

This lasts for the current terminal session only — set it again in each new terminal.

To do it per-command instead, without setting a variable:

```bash
PYTHONPATH=src python -m fakturama_i2c --help
```

The tests do **not** need this: `tests/conftest.py` adds `src/` to `sys.path` automatically.

---

## 6. Verify the installation

Check that every dependency imports:

```bash
python -c "import uiautomation, win32gui, winocr, numpy, PIL, pypdfium2; print('all deps OK')"
```

Check that the CLI is reachable:

```bash
python -m fakturama_i2c --help
```

Expected output:

```text
usage: fakturama_i2c [-h] {run} ...

Order image -> saved, verified Order + linked Invoice in Fakturama.
```

Run the test suite — no Fakturama needed, takes about a minute:

```bash
python -m pytest
```

Expected result: `186 passed, 1 xfailed`.

Useful variants:

```bash
python -m pytest -v                                 # verbose
python -m pytest tests/unit/test_validation.py      # a single file
python -m pytest -k calculations                    # match by name
```

---

## 7. Run it

### Before you start

1. Fakturama 2.2 is **open** with a workspace loaded.
2. `PYTHONPATH` is set (section 5).
3. Do not use the mouse or keyboard during the run — the automation needs Fakturama in the
   foreground and aborts if another window steals focus.

### Command

```bash
python -m fakturama_i2c run <DOCUMENT>
```

Example using the included sample:

```bash
python -m fakturama_i2c run samples/order_WEB-2026-0714-A17.png
```

PDF input works the same way:

```bash
python -m fakturama_i2c run samples/pdf/order_WEB-2026-0714-A17.pdf
```

### Options

| Option | Meaning |
|---|---|
| `DOCUMENT` | Order image (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.gif`, `.webp`) or `.pdf` |
| `--out-dir DIR` | Where to write `report.json` and screenshots. Default: `runs/<timestamp>` |
| `--no-seed-payments` | Skip the up-front terms-of-payment seeding and create the payment method on demand instead |
| `-h`, `--help` | Show usage |

Example with an explicit output folder:

```bash
python -m fakturama_i2c run samples/mock/order_01_new_debtor_paid.png --out-dir runs/demo
```

### What you will see

```text
attaching to Fakturama...
running flow, writing evidence to runs/20261004-021500
{ ... report JSON printed to stdout ... }
```

### Output files

```text
runs/<timestamp>/
├── screenshots/      PNG evidence per step
├── events.jsonl      step-by-step event log
└── report.json       final result
```

The `runs/` folder is git-ignored.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Run finished successfully |
| `1` | Run stopped — manual review required, or verification failed (see `report.json`) |
| `2` | The document could not be extracted or validated; Fakturama was never touched |

---

## 8. Sample documents

| Path | Contents |
|---|---|
| `samples/` | The main reference order (PNG + expected JSON) |
| `samples/pdf/` | The same order as a PDF |
| `samples/mock/` | 6 valid orders covering the different create/reuse paths — see `SCENARIOS.md` |
| `samples/edge/` | 13 documents that are **expected** to stop for manual review — see `EDGE_CASES.md` |

Every sample has a matching `.expected.json` file next to it.

---

## 9. Troubleshooting

**`No module named fakturama_i2c`**
`PYTHONPATH` is not set. See section 5.

**`ModuleNotFoundError` for `winocr`, `win32gui`, `pypdfium2`, …**
The dependencies went into a different interpreter than the one you are running. Activate the
virtual environment, then confirm with `python -m pip list`.

**OCR returns nothing, or `winocr` raises an error**
The Windows English OCR language pack is missing. Install it (section 1) and reboot.

**`rapidocr_onnxruntime` is not installed**
Expected on Python 3.13 — it is optional and the run continues without it. Use Python 3.12 if you
need it.

**`could not bring Fakturama to the foreground`**
Another window is stealing focus. Close notification popups, screen recorders and auto-focusing
apps, then rerun and leave the desktop alone.

**Timeout waiting for `a running Fakturama window`**
Fakturama is not running, or no workspace is open. Start it, open the workspace, then rerun.

**`pywin32` installed but `win32gui` still fails to import**
Run the post-install step once:

```bash
python .venv/Scripts/pywin32_postinstall.py -install
```

**PowerShell refuses to activate the virtual environment**
Execution policy. Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate.

---

## 10. Quick reference

```bash
git clone https://github.com/Mahmoud135200/Fakturama_I2C.git
cd Fakturama_I2C
python -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pytest
set PYTHONPATH=src
python -m fakturama_i2c run samples/order_WEB-2026-0714-A17.png
```
