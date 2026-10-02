# Rivet

A small persistent key-value database with a binary transaction log you can
inspect byte by byte. Use it to store local configuration, small cached blobs,
or checkpoints, and to explore how a storage engine handles torn writes.

Rivet is written in strict Maylang and compiled to a freestanding native
executable with `mayc`. `maypkg` manages its dependency graph, incremental build
and source lock. The storage path uses Linux syscalls directly: `mmap`, `flock`,
partial-write loops, `fsync`, `ftruncate` and atomic `rename`.

## Try the crash laboratory

From the Maylang repository root:

```sh
make -C example_projects/tools/rivet demo
```

The demo commits a configuration batch, updates a port, deletes a feature flag,
and prints the binary frames. It then truncates a final COMMIT, shows that the
old port still reads correctly, recovers the incomplete transaction, and compacts
the database. It uses a temporary directory and removes it afterwards. Python
drives this demonstration; the native Maylang executable performs all database
operations.

## Use it as a local database

```sh
make -C example_projects/tools/rivet build
cd example_projects/tools/rivet
./build/rivet init settings.rvt
./build/rivet put settings.rvt service/host localhost
./build/rivet put settings.rvt service/port 8080
./build/rivet put settings.rvt feature/replay enabled
./build/rivet get settings.rvt service/port
./build/rivet list settings.rvt service/
./build/rivet delete settings.rvt feature/replay
./build/rivet stats settings.rvt
./build/rivet inspect settings.rvt
./build/rivet compact settings.rvt
```

`get` writes the exact value to stdout, with no added newline; errors go to
stderr. `put` accepts an empty string. Unicode keys and text values are preserved
as UTF-8 bytes. A missing key or another error exits with status 2.

Binary values work too:

```sh
./build/rivet put-file settings.rvt checkpoint checkpoint.bin
./build/rivet get settings.rvt checkpoint --out restored.bin
```

`--out` creates a new file and refuses to overwrite an existing one. `init`
also refuses to replace an existing database. Output parent directories must
already exist.

## Atomic batches

Save this as `changes.json`:

```json
[
  {"op": "put", "key": "service/host", "value": "127.0.0.1"},
  {"op": "put", "key": "service/port", "value": "9090"},
  {"op": "delete", "key": "feature/replay"}
]
```

```sh
./build/rivet batch settings.rvt changes.json
```

The complete batch is validated before writing. Replay stages its operations
until the matching COMMIT is present and checksummed; readers see all changes
or none. Operations run in array order, so repeated updates and deletes to one
key have predictable results. Deleting an absent key is a valid no-op tombstone.

## Recovery and compaction

Each record contains little-endian fields, explicit byte lengths and an Adler-32
checksum. Replay checks transaction ordering and framing as well as checksums.
See **[FORMAT.md](FORMAT.md)** for the exact layout and state machine.

If the log ends during a transaction, reads return the last committed state.
`stats` reports the uncommitted tail. Further writes and compaction stop until:

```sh
./build/rivet recover settings.rvt
```

Recovery truncates to the last committed boundary and syncs the file. It discards
the entire incomplete transaction, including any complete PUT records it already
contains. A complete record with a bad checksum or invalid structure is reported
as corruption, and recovery leaves that file untouched.

Compaction streams the live values into a new file in the same directory,
checks the replacement log, syncs it, atomically renames it over the old log,
then syncs the directory. Large live datasets are split across bounded
transactions. Physical transaction IDs restart at 1 after compaction; they are
log positions rather than permanent application IDs.

Readers take a shared lock and mutations take an exclusive lock on `DB.lock`.
The stable sidecar coordinates operations across replacement of the database
inode. Concurrent writers and compaction serialize. Keep the lock file beside
the database and use one consistent database path; hard-link aliases are not
supported. Database and output symlinks are rejected. Durability relies on the
filesystem honouring `fsync` and atomic rename. A failed write/sync does not
acknowledge success; inspect the database before retrying it.

## Standard library use

| Module | Used for |
| --- | --- |
| `io.may` | Binary-safe text reads, `/proc` arguments and JSON batch input |
| `path.may` | Parent directory selection for directory syncing |
| `algo.may` | Stable merge sorting for prefix listings and compaction |
| `format.may` | Storage sizes, aligned stats and frame tables |
| `csv.may` | Transitive dependency of `io.may` |

Imports name the repository stdlib paths explicitly so builds work both from
the project directory and from the repository root with the current compiler's
module resolver. `Any` is confined to the stdlib APIs and heterogeneous JSON
boundary; domain records, byte offsets and syscall contracts use concrete types.

## Bounds and implementation

| Limit | Value |
| --- | ---: |
| Log size | 16 MiB |
| Value size | 64 KiB, including arbitrary binary bytes |
| Key size | 1–1024 UTF-8 bytes, without NUL |
| Live keys | 8192 |
| Transaction size | 1 MiB, including BEGIN/COMMIT |
| Operations in a transaction | 1024 |
| Frames in a log | 65536; compact before reaching it |
| JSON batch input | 16 KiB |

The JSON bound keeps work manageable in the existing character-oriented stdlib
parser. Use `put-file` for larger values. Every invocation scans the mapped log
to build an in-memory index of value offsets; it does not load all values into
the Maylang heap. Reads and compaction stream values directly from that mapping.
This favours small local datasets rather than large database workloads.

Linux x86-64 and `/proc` are required. Rivet uses the current Maylang string
layout to distinguish byte lengths from Unicode character counts. Adler-32
detects accidental corruption; it is not an authentication mechanism.

| File | Responsibility |
| --- | --- |
| `src/os.may` | Checked syscalls, locks, mmap, byte strings and exact writes |
| `src/codec.may` | Binary encoding, checksums and transactional replay |
| `src/storage.may` | Mutation validation, recovery, direct reads and compaction |
| `src/report.may` | Stdlib batch input, sorted listings and escaped frame reports |
| `main.may` | Command parsing, dispatch and byte-clean error handling |

## Verify and manage

```sh
make -C example_projects/tools/rivet test
make -C example_projects/tools/rivet check
```

The tests use an independent Python `struct`/`zlib` decoder. They check exact
binary values, Unicode, empty strings, overwrite/delete semantics, batch
validation, every truncation point, checksum and structural corruption, locking,
concurrent compaction, sorted reports, randomized workloads and compaction across
transaction boundaries. These are process and file-format tests, not a simulated
database implementation.

`make build` bootstraps a local `maypkg` and provides it the selected compiler.
Override `MAYC` or `MAYPKG` if needed. You can also compile directly:

```sh
mayc example_projects/tools/rivet/main.may -o /tmp/rivet
```
