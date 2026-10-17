# Install Maylang

On **Linux x86-64**, including **x86-64 WSL 2**, paste this into your terminal:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/mirged/maylang/releases/latest/download/maylang-init.sh | sh
```

The small downloader checks your platform, fetches and verifies the prebuilt
native installer, and opens the interactive Maylang setup. You need `curl` and
standard Linux utilities; no checkout, compiler, Rust, Python or build command
is required. No administrator password is needed for the default user install.

## Choose your setup

Press **Enter** on **Install Maylang** to accept the recommended settings.
The default installs all five tools and their standard library into
`~/.maylang`, then configures the shell profile shown on screen.

Choose **Customize setup** to change:

- **Installation folder:** choose an independent user prefix.
- **Included tools:** install the complete toolkit, compiler only, or toggle
  individual tools with Space. The compiler is always included.
- **Shell integration:** configure PATH automatically, select a different
  shell profile, or use the activation command yourself.

Use **↑ ↓** or **j/k** to move, **Enter** to choose, and **Esc** to go back.
Number shortcuts work too. The final review shows the folder, tools and shell
profile before anything is installed. Cancellation leaves the existing setup
unchanged. Progress follows file copying, compiler verification and shell setup.

Bash uses `~/.bashrc`, Zsh uses `~/.zshrc`, and other POSIX shells use
`~/.profile`, unless you choose a different profile. The installer manages only
its own block, so repeat installs do not duplicate PATH entries.

## Start using Maylang

Open a new terminal, or run the activation command printed by the installer:

```sh
. "$HOME/.maylang/env.sh"
may new hello
cd hello
may run
```

To compile a single source file:

```sh
mayc hello.may -o hello
./hello
```

The compiler, project runner, formatter, package manager and language server
are `mayc`, `may`, `mayfmt`, `maypkg` and `maylsp`. Native UI builds need a C
compiler, X11/Xi/Xcursor/OpenGL development libraries and a TrueType font;
ordinary native compilation needs none of those. The project runner uses `sha256sum` from
coreutils for its build cache.

## Unattended setup and accessibility

Pass installer options after `sh -s --`:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/mirged/maylang/releases/latest/download/maylang-init.sh | sh -s -- --yes --no-modify-path
```

| Option | Effect |
| --- | --- |
| `-y`, `--yes` | Accept the selected settings without prompts |
| `--prefix DIR` | Choose a user prefix |
| `--components=compiler` | Install the compiler and standard library only |
| `--components=may,mayfmt,maylsp` | Choose individual tools; `mayc` is included |
| `--profile FILE` | Choose a Bash/Zsh/POSIX startup file |
| `--no-modify-path` | Leave shell startup files untouched |
| `--plain` | Use numbered menus and a scrolling transcript |
| `--no-color` | Disable colors |
| `--help` | Show options without downloading the native installer |

`NO_COLOR` disables colors. `TERM=dumb` and narrow terminals use simple menus.
Piping the script does not take input away from the menus: setup reads from
`/dev/tty`. In a headless session use `--yes`. Fish and PowerShell users should
run the command inside a POSIX shell and choose manual PATH setup, or use WSL.

## Update or uninstall

Run the same one-line command again to install the latest release. Each
complete installation is copied into a generation under your chosen prefix;
older generations remain available. The active tools and standard library
resolve entirely inside that prefix. Moving, cleaning or deleting a source
checkout does not affect them.

### Automatic stable-release updates (Linux with systemd)

The optional Python updater checks GitHub for a newer stable release, verifies
both the installer checksum and GitHub's asset digest when available, and runs
the native installer unattended. It preserves your selected components and
shell-profile configuration, retains older generations, and never downgrades a
newer installation. It requires Python 3.9 or newer and a prefix managed by the
native installer.

From a source checkout, enable hourly checks for the default `~/.maylang` prefix:

```sh
mkdir -p "$HOME/.local/share/maylang" "$HOME/.config/systemd/user"
cp dist/auto_update.py "$HOME/.local/share/maylang/"
cp dist/systemd/maylang-update.* "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now maylang-update.timer
systemctl --user start maylang-update.service
```

The timer checks hourly with up to five minutes of randomized delay and catches
up after downtime. User services normally run while you are logged in; use
`loginctl enable-linger "$USER"` if you want them to continue after logout.
The computer must be running and online to download updates. For a custom
installation prefix, edit the service's `--prefix` and `ConditionPathExists`.

Check availability or inspect the scheduled job:

```sh
python3 "$HOME/.local/share/maylang/auto_update.py" --check
systemctl --user list-timers maylang-update.timer
journalctl --user -u maylang-update.service
```

To stop automatic updates, run
`systemctl --user disable --now maylang-update.timer`.
The updater and timer are separate from the toolchain prefix; disable the timer
before uninstalling. VS Code extension updates remain managed by the editor.

To uninstall the default installation:

```sh
"$HOME/.maylang/bin/may-uninstall"
```

Uninstall removes owned toolchains and this prefix's managed shell blocks,
while preserving unrelated files and settings. It is safe to repeat through a
saved installer with `--uninstall --yes --prefix DIR`. Prefixes made by the
older shell installer can stay alongside a new independent installation;
choose an empty prefix or one already managed by the Maylang installer.

## Download first or install offline

The [release page](https://github.com/mirged/maylang/releases) provides the
native `maylang-init-x86_64-linux` asset and its adjacent checksum. Download both
and verify them before running the installer:

```sh
sha256sum -c maylang-init-x86_64-linux.sha256
chmod +x maylang-init-x86_64-linux
./maylang-init-x86_64-linux
```

The native asset includes the complete toolchain and works offline. Archives
remain available for existing workflows. The legacy `dist/install.sh`
accepts an archive plus checksum or an extracted bundle and copies it into an
independent prefix. `maylang-bootstrap.c` and `maylang-install.sh` are optional
host-C bootstrap artifacts for developers; ordinary installation uses the
prebuilt native asset.

Set `MAYLANG_VERSION=v0.12.1` on the downloaded script to choose a particular
release. `MAYLANG_DIST_ROOT` can select an HTTPS distribution mirror. Public
releases before 0.12.0 do not include the native interactive installer.

## Editor and platform support

Install the released VSIX in VS Code. It finds `maylsp` through PATH; restart
the editor after installing, or set `maylang.serverPath` to the installed
binary. See [editor setup](DEVELOPMENT.md#editor-setup).

The compiler host currently requires Linux x86-64. On Windows, install WSL 2
and run the command inside an x86-64 Linux distribution. Native macOS, Windows
and ARM64 compiler-host releases are not available. Cross-compilation targets
and runtime limits are documented in [the target guide](../internals/NATIVE_TARGETS.md).

Contributors: see [source development](DEVELOPMENT.md),
[distribution internals](../../dist/README.md) and
[release preparation](RELEASING.md).
