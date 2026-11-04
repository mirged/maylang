# Security policy

Maylang is experimental and not production-ready. It has no security
guarantees: the compiler, runtime and tools have not been audited, and programs
it builds should not handle untrusted input in production.

## Supported versions

Only the latest release and `main` receive fixes.

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub:
[Security → Report a vulnerability](https://github.com/mirged/maylang/security/advisories/new).
Please do not open a public issue for them.

Include the Maylang version (`mayc --version`), the host, a minimal program or
command that reproduces the problem, and what you expected. Reports about the
installer, release archives, the language server's handling of workspace files
and memory safety of the runtime are especially useful.

This is a small project maintained in spare time, so there is no response-time
commitment; reports are acknowledged and handled as soon as practical.
