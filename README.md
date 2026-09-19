# GCAD — Git for CAD

A lightweight Windows GUI for managing CAD CAD files with Git and Git LFS.
Designed for users with no Git experience — just select a file, lock it, edit, and push.

## Features

- **Pull** — sync the latest files from the remote
- **Lock / Unlock** — prevent others from editing the same file (via Git LFS locking)
- **Push** — stage, commit, push, and auto-unlock in one click
- **File status grid** — see at a glance which files are Ready, Modified, Deleted, or Locked
- **Batch operations** — select multiple files to lock, unlock, or commit at once
- **Open File / Open in Containing Folder** — select one file to open it in its default application or browse its folder in Windows Explorer
- **Guided setup** — check/install tools, configure your identity, and download or select a repository
- **Live operation feedback** — follow each stage, Git transfer output, elapsed time, and per-file batch progress
- **Activity history** — review completion, warnings, and errors; expand or copy the last 250 session events
- **Repository overview** — see file/change/lock counts, your current branch, and selection totals
- **Appearance** — choose Light, Dark, or Follow system from the top-right selector. Your choice is saved across launches and repository changes. Follow system (the default) tracks the Windows app color setting while GCAD is open; other platforms use light mode as the system fallback.

## Operation feedback

The activity panel remains visible below your files while GCAD works. Pull, Push,
Refresh, Lock, Unlock, Restore, and Hard Reset report their current stage. Git
transfer percentages appear when Git supplies them; operations without a known
total use an animated bar and elapsed time. Batch actions show the number of files
processed in the current stage, rather than an estimated overall percentage.

Completion stays visible until the next operation. Warnings and failures open the
activity history automatically. **Show activity** reveals timestamped details and
**Copy activity** copies them for troubleshooting. History is kept in memory for
the current session only.

Unavailable lock checks are marked **Not verified**, and lock counts show a dash
instead of an assumed zero. If an operation fails after completing some steps,
use Refresh to check the current file state before retrying. Actions that change
the repository and closing GCAD are disabled while an operation is running.
Refresh preserves your selection and collapsed folders.

## First launch (Windows .exe)

Open `GCAD.exe` and follow the setup wizard. No Python or terminal commands are needed:

1. **Required tools** — GCAD detects Git and Git LFS. Click **Install missing tools** to install them with Windows Package Manager. This accepts the package/source agreements and may show a Windows administrator prompt. If automatic installation is unavailable, the wizard provides official download links and a **Check again** button.
2. **Your name and email** — confirm the identity shown beside your saved changes. Existing global Git settings are suggested; the wizard saves your choices only in the selected repository.
3. **Your CAD repository** — paste your team's HTTPS or SSH clone link and choose a new or empty folder, or select an existing repository folder. HTTPS uses Git's browser sign-in. For SSH, click **Set up SSH access** for guided key creation, account registration instructions, and connection testing. Your account must have access to the repository.
4. **Ready to work** — click **Open GCAD** to save setup and load your files.

Setup opens whenever `%USERPROFILE%\.gcad\config.json` is missing or unreadable, including when the `.gcad` folder has been deleted. It also opens if the configured repository folder no longer exists. Cancelling does not save an incomplete configuration; setup opens again on the next launch. A completed download remains on disk and can be selected with **Use an existing folder** on a later attempt.

GCAD disables SSL certificate verification for all Git and Git LFS operations, during setup and when working with existing repositories (including Pull, Push, Refresh, Lock, and Unlock). This applies automatically without rerunning setup. The override is limited to processes launched by GCAD; it does not change repository or global Git settings.

Git operations and installation run in the background with progress feedback. Wait for the operation to finish before closing setup. Setup errors leave the wizard open so you can correct the details and retry. Use **File > New Repository** to run the wizard for another repository later.

Git and Git LFS remain required at runtime. For manual installation, use [Git for Windows](https://git-scm.com/download/win) with its default command-line and Credential Manager options, and [Git LFS](https://git-lfs.com/). The wizard initializes LFS for the repository automatically. [Git Credential Manager](https://git-scm.com/doc/credential-helpers) supports browser sign-in; automatic installation uses [WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/install).

## SSH setup

On the repository page, paste an SSH clone link such as `git@github.com:team/cad.git` and click **Set up SSH access**. For an existing folder, GCAD reads its `origin` URL; it must already be an SSH URL. Existing SSH configurations can also be used directly without opening this helper.

1. **Your key** — create an Ed25519 key or browse to an existing private key (the file without `.pub`). New keys are stored directly in `%USERPROFILE%\.ssh` as `id_ed25519` and `id_ed25519.pub`. If either file already exists, GCAD asks for confirmation before replacing the pair; choosing **No** keeps the existing files. The automatic option explicitly creates a key **without a passphrase** so desktop Git operations can run unattended. Keep that private file secure. If your host requires another key algorithm or your team requires a passphrase, create the required key in a terminal and select it in GCAD. The dialog includes encrypted-key and SSH-agent instructions; GCAD does not store passphrases.
2. **Add to account** — copy the displayed **public** key and add it to your Git account. GCAD opens the SSH settings page for GitHub.com or GitLab.com and shows instructions; for other hosts, ask your team for its account settings page. You must sign in, save the key, accept repository invitations, and complete any organization SSO authorization yourself. GCAD cannot grant account or repository permissions.
3. **Verify and test** — fetch the server fingerprint and compare it with the linked official fingerprint list, or a fingerprint supplied separately by your administrator. Confirm only if it matches, then click **Trust server and test repository access**. A successful test confirms read access to that repository; Push and Lock also need permissions from your team. Git LFS can require a separate HTTPS sign-in.
4. Click **Use SSH for this repository**, then finish the main setup wizard. GCAD saves the selected SSH command in this repository's Git configuration so subsequent launches use the same key. Changing the repository link requires running SSH setup again for that link.

Trusted server keys are saved separately in `%USERPROFILE%\.ssh\gcad_known_hosts`. GCAD keeps strict host-key checking enabled and refuses to silently replace a previously trusted server key. If a fingerprint differs or access fails, the dialog provides recovery guidance for account keys, SSO, invitations, encrypted keys, VPNs, and firewalls. Cancelling SSH setup leaves any generated keys and explicitly trusted server keys on disk so they remain available for reuse; it does not select them for a repository.

Guided setup supports hostname-based SSH clone links and custom ports (`ssh://git@host:2222/team/cad.git`). For SSH aliases, jump hosts, or other advanced configurations, use your team's existing SSH setup. GCAD prefers Windows OpenSSH when available and otherwise uses Git's bundled OpenSSH tools. Encrypted keys must be loaded into the matching agent: Windows OpenSSH uses the Windows agent service, while Git's OpenSSH requires launching GCAD from the Git Bash session running its agent.

If fingerprint fetching encounters the Windows `ssh-keyscan` “unsupported KEX method” bug, GCAD retries with another installed scanner, including Git's bundled OpenSSH. This only changes fingerprint fetching; authentication still uses the selected SSH client and agent, and you must compare and confirm the fingerprint. If no compatible scanner is available, update Windows OpenSSH or Git for Windows and retry.

Account instructions: [GitHub SSH keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account), [GitHub SSO authorization](https://docs.github.com/en/enterprise-cloud%40latest/authentication/authenticating-with-single-sign-on/authorizing-an-ssh-key-for-use-with-single-sign-on), [GitLab SSH keys](https://docs.gitlab.com/user/ssh/), and [Windows SSH agent setup](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

## Running from source

```
py -m pip install -r requirements.txt
py main.py
```

The same setup wizard runs when launching from source.

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

The MMR logo is embedded in the executable for Explorer and desktop shortcuts,
and used by the taskbar, window titles, dialogs, and About screen. Desktop
shortcuts should target `GCAD.exe` and use its embedded icon.

To regenerate icons after replacing `assets/logo.png` and `assets/logo-icon.png`:

```
py -m pip install Pillow
py assets/build_icons.py
py -m PyInstaller build.spec
```

The Windows icon includes sizes from 16 to 256 pixels for different display scales.

Run the setup regression tests with `python -m unittest discover -s tests -v`.
The UI smoke tests require a desktop with Tcl/Tk available; the other tests use
temporary local repositories and simulate installers without installing system tools.

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
├── setup_ops.py         prerequisite installation and repository setup
├── ssh_setup.py         SSH key creation, host verification and access tests
├── dpi.py               high-DPI display scaling
├── ui/
│   ├── file_table.py    file status treeview
│   ├── toolbar.py       action buttons
│   ├── dialogs.py       commit dialog and error popups
│   ├── setup_wizard.py  guided first-launch and repository setup
│   └── ssh_dialog.py    SSH setup and account guidance
└── build.spec           PyInstaller packaging config
```

## Tech Stack

- Python 3 + tkinter + ttkbootstrap
- Git / Git LFS via subprocess
- Threading for non-blocking UI during git operations
