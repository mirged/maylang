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
