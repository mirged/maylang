# Rivet log format, version 1

All integers are unsigned 32-bit little-endian. Lengths and offsets count bytes,
not Unicode characters. No padding occurs between fields or records.

## File header

| Offset | Bytes | Meaning |
| ---: | ---: | --- |
| 0 | 8 | ASCII `RIVET01` followed by LF |
| 8 | 4 | Version: 1 |
| 12 | 4 | Reserved: 0 |

An empty database consists only of these 16 bytes. Replay requires the whole
header to match; header corruption is never treated as a recoverable suffix.

## Frame

| Relative offset | Bytes | Meaning |
| ---: | ---: | --- |
| 0 | 4 | ASCII `RVF1` |
| 4 | 4 | Total frame size: `28 + key length + value length` |
| 8 | 4 | Transaction ID |
| 12 | 4 | Type: BEGIN=1, PUT=2, DELETE=3, COMMIT=4 |
| 16 | 4 | Key byte length |
| 20 | 4 | Value byte length |
| 24 | key length | Key bytes |
| 24 + key length | value length | Value bytes |
| total size − 4 | 4 | Adler-32 of all preceding bytes in this frame |

Adler-32 starts with `a=1, b=0`. For each byte: `a=(a+byte)%65521`,
`b=(b+a)%65521`. The checksum is `b*65536+a`, stored little-endian.
It is compatible with Python's `zlib.adler32`.

BEGIN and COMMIT have empty keys and values and are each 28 bytes. PUT requires
a nonempty key and permits an empty value. DELETE requires a nonempty key and
an empty value. Keys contain no NUL; the CLI supplies UTF-8 keys. Values are
opaque byte strings and may contain NUL and every other byte value.

## Transaction state machine

```text
Idle(last ID = n)
    BEGIN(n+1) -> Pending(n+1)
Pending(n+1)
    PUT/DELETE(n+1) -> stage operation, stay Pending
    COMMIT(n+1)    -> apply staged operations in order, return Idle
```

At least one PUT/DELETE must occur before COMMIT. Nested BEGIN, skipped IDs,
mismatched IDs and operations outside a transaction are corruption. A frame's
checksum covers its ID, type, lengths and payload, so accidental edits to those
fields are detected along with payload edits. Replay also checks record,
transaction, frame-count and live-key bounds.

The committed boundary advances only after a valid COMMIT. Index entries point
to the most recent committed PUT's value bytes inside the mapped file. DELETE
removes the entry. Pending operations never change the committed index.

## Tail handling

| End condition | Result |
| --- | --- |
| EOF immediately after COMMIT or file header | Clean log |
| Fewer than 28 bytes remain | Incomplete frame header/trailer; recoverable tail |
| Valid frame header declares a payload beyond EOF | Incomplete frame; recoverable tail |
| EOF with a valid BEGIN and operations but no COMMIT | Uncommitted transaction; recoverable tail |
| Complete frame has wrong checksum, magic, lengths or transaction structure | Corruption; abort without modifying the file |

A short trailing fragment cannot be fully verified. Rivet treats it as an
incomplete write and allows explicit recovery to discard it. For complete
records, it does not attempt to distinguish physical corruption from a failed
write that produced bad bytes.

`recover` truncates to the last committed boundary under the exclusive lock,
then `fsync`s the database. It never commits a partial transaction. Repeating
recovery on a clean log removes zero bytes.

## Commit and replacement protocol

Normal mutation:

1. Lock the stable sidecar exclusively; replay and require a clean log.
2. Validate all operations, resulting live-key count and resource limits.
3. Append BEGIN, operations and COMMIT with a complete-write loop.
4. `fsync` the database; acknowledge the transaction; release the lock.

Compaction:

1. Hold the exclusive sidecar lock and require a clean source.
2. Create `DB.compact.PID` exclusively in the same directory.
3. Write the header and bounded transactions containing sorted live PUTs.
4. `fsync` and validate the completed replacement log.
5. Atomically rename it over DB and `fsync` the containing directory.
6. Release the sidecar lock. It is the same inode before and after replacement.

A killed compactor before rename leaves the original database and may leave a
temporary file. Compaction creates a new PID-specific file on later attempts.
The old temporary file can be removed once that process has exited. A failure
after rename can leave the new database installed even though the command reports
an error; callers should inspect before retrying. Compaction resets physical
transaction IDs and removes historical updates and tombstones.
