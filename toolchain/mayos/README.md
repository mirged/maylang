# MayOS

A small bootable x86-64 teaching OS whose console, shell, memory-map reader,
allocator, ATA driver and filesystem are written in **strict raw Maylang**.
GRUB loads a short assembly boot shim, the shim enters long mode and loads the
`mayc --raw` ELF64 kernel, and Maylang takes over at ring 0.

The kernel has a VGA text display, COM1 serial console, PS/2 keyboard input,
PIC/IDT interrupt setup, a PIT timer, a zeroing bump allocator, and persistent
files on a dedicated IDE disk. There is no Linux process underneath it and no
Maylang hosted runtime in the kernel.

Kernel modules live in `src/`, the GRUB entry and linker script live in
`boot/`, and generated kernel, ISO and disk artifacts stay under `build/`.
QEMU tests are in `tests/`; disk tooling and the raw compiler adapter are in
`tools/`.

## Build and boot

From the repository root:

```sh
make -C toolchain/mayos build
make -C toolchain/mayos run
```

`run` starts QEMU with software emulation, 64 MiB of RAM and the serial console
in your terminal. At the `mayos>` prompt, try:

```text
help
info
mmap
uptime
selftest
alloc 32
fill 0x800000 16 65
dump 0x800000 16
checksum 0x800000 16
mem
shutdown
```

The allocation address in this example assumes a fresh boot. `alloc` prints the
actual address. The checksum of sixteen `A` bytes is `0x22980411`.
`shutdown` exits QEMU and the Makefile treats its debug-exit status as success.

For a VGA window with keyboard input:

```sh
make -C toolchain/mayos gui
```

The serial console remains available in the launching terminal. The keyboard
uses a US layout with shifted letters/punctuation, Enter, Space and Backspace.
Commands are lowercase; serial input accepts decimal numbers or `0x` hexadecimal.
The GUI target needs a desktop/display available on the host.

The bootable image is **`build/mayos.iso`**. Dependencies are the repository's
strict-capable `mayc`, GNU `as`/`ld`, `grub-file`, `grub-mkrescue`, `xorriso`,
Make, Python 3 for tests, and `qemu-system-x86_64`. They were already available
in this workspace. Override `MAYC`, `MAYPKG` or `QEMU` in Make when needed.

## Persistent files

`run` and `gui` create a blank 4 MiB disk at `data/disk.img` on first use and
attach it as the primary IDE master. The image is preserved across rebuilds,
QEMU restarts and `make clean`. Initialise a **new** disk once in the shell:

```text
disk
format yes
write note "Hello from MayOS"
write lines "first line\nsecond line"
ls
cat note
shutdown
```

Start QEMU again and `cat note` still prints the saved text. `format yes`
erases existing MayFS files; it is never run automatically. Choose a separate
image with `make -C toolchain/mayos run DISK=data/other.img`.

You can also save binary data from an allocated memory range:

```text
alloc 32
fill 0x800000 32 65
save sample 0x800000 32
load sample
```

`load` allocates a new buffer and prints its address and size. Use that address
with `dump` or `checksum`. `cat` renders non-printable binary bytes as dots.
`rm sample` deletes the file. Quoted text supports `\n`, `\t`, `\"` and `\\`;
unmatched quotes or unsupported escapes reject the command. Empty quoted text
creates an empty file, and loading it does not allocate memory.

MayFS is a deliberately small flat filesystem: 16 files, up to 480 bytes each,
and names of 1–23 characters from letters, digits, dot, underscore and hyphen.
Names are case-sensitive. Text entered at the shell still has the 127-byte line
limit; `save` can write the full 480 bytes. The driver supports a primary IDE
master with 512-byte sectors and 28-bit LBA, with bounded polling timeouts.
Missing, undersized, blank or invalid disks leave the shell usable.

Each filesystem update writes the inactive snapshot's 16 data sectors, flushes
the ATA cache, publishes a checksummed header, then flushes again. The two banks
occupy sectors 1–17 and 18–34; sector 0 and all later sectors are untouched.
At boot, header, snapshot and file checksums plus names/lengths are validated,
and the valid snapshot with the highest generation is loaded. If the newest
snapshot is damaged or incomplete, the previous valid generation is recovered.
This provides a small teaching example of ordered persistent updates, assuming
the virtual disk honours cache flushes; it is not a general-purpose disk format.
No valid snapshot is automatically overwritten. A failed commit remounts the
last valid disk state and reports an error.

## Commands

| Command | Behaviour |
| --- | --- |
| `help` | Show all commands |
| `info` | Kernel, boot magic, load address and device setup |
| `mmap` | Print the physical memory map supplied by GRUB |
| `uptime` | Interrupt ticks and approximate elapsed seconds |
| `mem` | Arena bounds, used/free bytes and allocation count |
| `alloc N` | Allocate and zero N bytes, rounded up to 16-byte alignment |
| `fill ADDR N BYTE` | Fill an allocated range with byte 0–255; N ≤ 4096 |
| `dump ADDR N` | Hex dump an allocated range; N ≤ 256 |
| `checksum ADDR N` | Adler-32 of an allocated range; N ≤ 4096 |
| `selftest` | Check allocation, zeroing, bytes, checksums, arithmetic and PIT |
| `disk` | ATA capacity, filesystem state and snapshot generation |
| `format yes` | Erase files and initialise MayFS on the attached disk |
| `ls` | List files and sizes |
| `write NAME TEXT` | Create or replace a text file; quote text containing spaces |
| `cat NAME` | Print file contents, showing binary bytes as dots |
| `rm NAME` | Delete a file |
| `save NAME ADDR N` | Save 1–480 bytes from allocated memory |
| `load NAME` | Load a file into a new allocation |
| `clear` | Clear VGA and emit serial terminal clear sequences |
| `shutdown` | Exit QEMU through its debug-exit device; ACPI fallback |

The line editor handles Backspace and CR/LF input, rejects lines over 127 ASCII
bytes, and accepts up to four tokens, including double-quoted arguments. Memory
commands operate only inside the arena's allocated prefix, including alignment padding.
They cannot write to the kernel, loader, stack or page tables. The allocator is
monotonic: there is no `free`; reboot starts a fresh arena. `selftest` restores
its allocation bookkeeping and needs at least 272 bytes free.

## How the boot works

```text
GRUB / Multiboot2
  → boot.S: 32-bit entry, page tables and long-mode transition
  → copy mayc ELF64 PT_LOAD segments to their fixed physical addresses
  → install IDT, remap PIC, program PIT, initialise COM1
  → jump to the kernel's ELF entry at 0x401000
  → main.may: check RAM, mount disk, draw banner, run the Maylang shell
```

`mayc --raw` means **untagged values and no hosted runtime**. It still writes
an ELF64 file with code, data and string segments; it does not write a BIOS boot
sector or a flat disk image. The assembly loader preserves those fixed addresses
instead of relocating or extracting only `.text`. GRUB supplies the kernel ELF
as a Multiboot module. The loader checks module/segment bounds and keeps kernel
copies inside the reserved 4–8 MiB region.

| Physical range | Purpose |
| --- | --- |
| Around 1 MiB | Boot code, GDT, IDT, page tables and 64 KiB stack |
| 2 MiB–2 MiB + 4 KiB | Reserved mailbox, boot metadata and shell buffers |
| 0x210000–0x218000 | Reserved disk and filesystem buffers |
| Below 4 MiB | GRUB's kernel module source |
| 4–8 MiB | Kernel ELF load segments |
| 8–16 MiB | Allocation arena, checked against usable RAM in GRUB's map |
| First 1 GiB | Identity-mapped by 2 MiB page entries |

The PIT runs at approximately 100 Hz. Its assembly interrupt handler only
increments the mailbox counter and acknowledges IRQ0, preserving the register
it uses. The kernel sleeps with `hlt` when neither serial nor keyboard input is
ready and wakes on the next timer interrupt. CPU faults halt with a distinct
failure exit status in the configured QEMU environment.

`hardware.may` wraps a few assembly primitives through `__ccall6`. The current
compiler's intrinsic still shifts arguments/results as tagged values even in
raw mode; the wrapper compensates for that at this one ABI boundary. Raw mode
also does not recognise `true`/`false` as literal values, so flags use integers
and boolean results use comparisons. Raw strings are NUL-terminated pointers;
the kernel uses explicit byte loads rather than hosted strings, collections,
garbage collection, syscalls or stdlib routines.

The compiler emits a Linux exit fallback after its top-level entry function.
MayOS never returns from its shell or shutdown loop, so that instruction is
unreachable. All hardware interaction uses port I/O and physical memory.

## Build management

`maypkg` generates the build script and locks the seven Maylang modules. Make
runs that script with the project-local `tools/mayc` adapter, which adds `--raw`,
then builds the assembly loader and packages both ELF files into the ISO. This
also preserves the compiler environment: the current hosted `system` primitive
used by ordinary `maypkg build` drops environment variables in its child shell.
Use **Make** for the complete boot image. To inspect the project from this directory:

```sh
.tools/maypkg info
.tools/maypkg tree
make check
```

The manifest's `linux` target denotes the current compiler's ELF output format;
the resulting kernel is freestanding. Do not invoke ordinary `maypkg run` for
this project: it launches a host executable rather than booting QEMU. The
Makefile's `run` and `gui` targets boot the ISO.

For a direct kernel compilation from the repository root:

```sh
mayc --raw toolchain/mayos/main.may -o /tmp/mayos-kernel.elf
```

## Verify

```sh
make -C toolchain/mayos test
make -C toolchain/mayos check
```

The tests boot the actual ISO using QEMU TCG and exercise serial commands,
input editing, memory bounds, exhaustion, binary checksums, allocator zeroing,
timer progress, insufficient RAM, clean shutdown, persistent files across
reboots, binary save/load, directory limits, snapshot recovery, injected write
errors with retry, and invalid
disks. Each guest uses a temporary disk rather than the user's `data/disk.img`.
They inject PS/2 keys
through QMP and capture the VGA framebuffer. Static checks verify the kernel's
load addresses, lack of a hosted interpreter/runtime, and the loader's Multiboot2
header. No mock kernel is used.

Artifacts include `build/serial-test.log` and `build/mayos-screen.ppm`.
QMP uses a local Unix socket; restricted execution environments may require
permission to create it. Headless `make run` does not need QMP.

This version has one kernel address space and one interactive monitor.
It does not implement user processes, a scheduler, directories, networking or
large files. Allocated RAM disappears when QEMU exits; saved files persist.

| File | Responsibility |
| --- | --- |
| `boot/boot.S`, `boot/boot.ld` | Multiboot entry, ELF loading, CPU setup and hardware primitives |
| `src/hardware.may` | Raw ABI wrappers, timer access and shutdown |
| `src/console.may` | Serial/VGA output, formatting and polled PS/2 keyboard |
| `src/memory.may` | Boot memory map, bounded arena, dump/checksum and self-test |
| `src/disk.may` | ATA IDENTIFY, sector reads/writes and cache flushing |
| `src/filesystem.may` | Checksummed snapshots, mounting and file operations |
| `src/shell.may` | Line editing, token/number parsing and commands |
| `main.may` | Kernel entry, arena validation and disk mounting |
| `tests/test_boot.py` | Actual QEMU and ELF verification |

Boot references: [GNU Multiboot2 specification](https://www.gnu.org/software/grub/manual/multiboot2/multiboot.html)
and [QEMU invocation documentation](https://qemu-project.gitlab.io/qemu/system/invocation.html).
Storage reference: [T13 ATA command specification](https://www.seagate.com/support/disc/manuals/ata/d1153r17.pdf).
