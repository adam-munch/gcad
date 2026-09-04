# GCAD — Git for CAD

A lightweight Windows GUI for managing CAD CAD files with Git and Git LFS.
Designed for users with no Git experience — just select a file, lock it, edit, and push.

## Features

- **Pull** — sync the latest files from the remote
- **Lock / Unlock** — prevent others from editing the same file (via Git LFS locking)
- **Push** — stage, commit, push, and auto-unlock in one click
- **File status grid** — see at a glance which files are Ready, Modified, Deleted, or Locked
- **Batch operations** — select multiple files to lock, unlock, or commit at once

## Requirements

- [Git for Windows](https://git-scm.com/download/win) (with "Git from the command line" selected)
- [Git LFS](https://git-lfs.com/) (included with recent Git for Windows; run `git lfs install` once)
- SSH keys configured with your Git host (GitHub, GitLab, etc.)

## Quick Start

```
py -m pip install -r requirements.txt
py main.py
```

On first launch you'll be prompted for:
1. **Repository URL** — SSH URL of your Git repo
2. **Local folder** — where to clone it

After that the main window opens showing all LFS-tracked files and their status.

## Workflow

```
1. Click Pull         → get latest from remote
2. Select a file      → click Lock
3. Edit in CAD → save
4. Select the file    → click Push → enter commit message → done
```

The file is automatically unlocked after a successful push.

## Building a Standalone .exe

```
py -m pip install -r requirements.txt
py -m pip install PyInstaller
py -m PyInstaller build.spec
```

The `.exe` will be at `dist/GCAD.exe`. No Python install needed on target machines.

## File Status Legend

| Status | Meaning |
|---|---|
| Ready | Committed, not locked |
| Modified | Changed since last commit |
| Deleted | Removed from working tree |
| Locked (You) | Locked by you |
| Locked | Locked by another user |

## Project Structure

```
gcad/
├── main.py              entry point
├── app.py               main window, threading, workflow
├── config.py            config load/save (~/.gcad/config.json)
├── git_ops.py           all git/lfs subprocess operations
├── dpi.py               high-DPI display scaling
├── ui/
│   ├── file_table.py    file status treeview
│   ├── toolbar.py       action buttons
│   └── dialogs.py       setup wizard, commit dialog, error popups
└── build.spec           PyInstaller packaging config
```

## Tech Stack

- Python 3 + tkinter (stdlib only — no external dependencies)
- Git / Git LFS via subprocess
- Threading for non-blocking UI during git operations
