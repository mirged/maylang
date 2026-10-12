# Native core target verification

The [Native core targets workflow](../.github/workflows/native-targets.yml)
builds the compiler from source on Linux x86-64 and cross-emits checksummed
ARM64 Mach-O and x86-64 PE fixtures. Separate jobs execute them with the real
loaders on Apple Silicon macOS 14/15 and Windows Server 2022/2025. The compiler
itself is still hosted on Linux x86-64; these jobs verify emitted core programs.

The fixture suite checks UTF-8 output, strings/lists, multi-chunk allocation,
memory copies, nested/eight-argument calls, integer bounds, arithmetic failure
and status-70 heap exhaustion with a reduced capacity. PE core programs call
kernel32's GetStdHandle, WriteFile, VirtualAlloc and ExitProcess; a raw program
also returns through the loader. macOS fixtures are ad-hoc signed with
`codesign --force --sign -`, verified, and inspected with `otool -l` before
execution. Reports record actual OS versions, architecture, stdout, stderr and
exit status. A signing or loader failure fails the job; emulation is not a
substitute for this gate.

To emit from Linux and verify the Linux control fixtures:

```sh
python3 toolchain/mayc/tests/native_targets.py --emit --directory /tmp/native-targets
python3 toolchain/mayc/tests/native_targets.py --run x86_64-linux --directory /tmp/native-targets
```

Transfer `manifest.json` and the relevant target subdirectory to the target
host, keeping their layout. Then run one of:

```sh
python3 toolchain/mayc/tests/native_targets.py --run arm64-macos --directory native-targets
python toolchain/mayc/tests/native_targets.py --run x86_64-windows --directory native-targets
```

The runner rejects the wrong OS/architecture and checks fixture hashes before
signing/execution. Python 3.10 or later is required. GitHub job logs and uploaded
JSON reports provide the tested OS patch versions; support claims must follow
successful execution results, not merely the presence of this workflow.

## Recorded native validation

[Run 38255666274](https://github.com/mirged/maylang/actions/runs/38255666274)
passed on 2026-10-12: macOS 14.8.9 and 15.7.9 on ARM64, Windows Server 2022
10.0.20348 and Server 2025 10.0.26100 on AMD64. All core/arena/error/limit
fixtures passed; both Windows hosts also accepted the raw entry-return fixture.
The reports include exact byte output and exit statuses.

Native validation found and corrected defects absent from the emulator's loader:
an empty trailing PE section, missing Mach-O signature storage, insufficient
page-zero protection, static ARM64 output rejected by production kernels, and
missing platform/dyld/entry metadata. Mach-O now declares macOS 11+, a 4 GiB
page-zero region, dyld/libSystem loading, empty binding/rebase streams and
`LC_MAIN`. ARM64 data references use ADRP/ADD and pass a relocated-image test.
The generated program still exits through target syscalls; libSystem supplies
the initialization that the native dynamic loader expects.
