# Networking

`import "net" as net;` provides synchronous IPv4 TCP and UDP sockets, written
entirely in Maylang. It supports the full Linux x86-64 runtime on both `mayc`'s
native and direct `clang-llvm` backends. Addresses are dotted-decimal IPv4 or
`localhost`; DNS, IPv6, TLS and HTTP are outside this module's current scope.

## TCP example

Start [the echo server](../examples/network/echo_server.may), then run
[the client](../examples/network/echo_client.may) in another terminal:

```sh
mayc --strict examples/network/echo_server.may -o /tmp/echo-server
mayc --strict examples/network/echo_client.may -o /tmp/echo-client
/tmp/echo-server 9000
# In another terminal:
/tmp/echo-client 9000 "Hello, Maylang!"
```

Add `--target clang-llvm` to either compilation command to use LLVM.

```may
import "net" as net;

net.with_socket(net.tcp_connect("localhost", 9000), fun(s: net.Socket) -> Any {
    let message: Str = "Hello, Maylang!";
    net.tcp_send(s, message);
    net.tcp_shutdown(s, "write");
    return print(net.tcp_receive_exact(s, net.byte_length(message)));
});
```

TCP is a byte stream: one receive can return fewer bytes than a send supplied.
`tcp_send` sends the entire string, handling partial writes.
`tcp_receive_exact` reads the requested byte count or raises on early EOF.
`tcp_receive` returns an empty string at EOF; its maximum must be positive.
`tcp_receive_exact(s, 0)` returns an empty string without reading.

## API

| Function | Result / behavior |
|---|---|
| `ipv4(host: Str)` | Canonical IPv4 string; `localhost` becomes `127.0.0.1` |
| `address(host: Str, port: Int)` | `Address { host: Str, port: Int }`; ports 0–65535 |
| `tcp_connect(host: Str, port: Int)` | Connected `Socket`, with a 30-second connect timeout |
| `tcp_connect_timeout(host: Str, port: Int, ms: Int)` | Connect with an explicit timeout |
| `tcp_listen(host: Str, port: Int)` | Listener; port 0 requests an ephemeral port |
| `tcp_accept(listener: Socket)` | Connected `Socket`, inheriting the listener's timeout |
| `tcp_send(s: Socket, data: Str)` | Total bytes sent as `Int` |
| `tcp_receive(s: Socket, max_bytes: Int)` | Up to `max_bytes` as `Str`, or empty on EOF |
| `tcp_receive_exact(s: Socket, count: Int)` | Exactly `count` bytes as `Str` |
| `tcp_shutdown(s: Socket, how: Str)` | Half/full shutdown: `"read"`, `"write"`, `"both"` |
| `udp_bind(host: Str, port: Int)` | UDP `Socket`; port 0 requests an ephemeral port |
| `udp_send_to(s: Socket, data: Str, destination: Address)` | Datagram byte count as `Int` |
| `udp_receive_from(s: Socket, max_bytes: Int)` | `Datagram { data: Str, sender: Address }` |
| `socket_local_address(s: Socket)` | Bound/local `Address`, including the assigned port |
| `socket_peer_address(s: Socket)` | Connected peer `Address` |
| `socket_set_timeout(s: Socket, ms: Int)` | Change subsequent operation timeouts |
| `socket_wait(s: Socket, writing: Bool, ms: Int)` | `Bool` readiness; false on timeout |
| `socket_close(s: Socket)` | Close; repeated calls are harmless |
| `with_socket(s: Socket, action: (Socket) -> Any)` | Call `action`, close on success or error, return its result |
| `byte_length(data: Str)` | Byte count, including embedded NULs |
| `bytes(data: Str)` | `List<Int>` of raw bytes in 0–255 |
| `from_bytes(values: List<Int>)` | Raw byte string, without UTF-8 re-encoding |

Operations returning no value return `Nil`. Constructors and accept return
`Socket { fd: Int, kind: Str, timeout_ms: Int }`; kinds are `"tcp"`,
`"listener"`, and `"udp"`. Treat these fields as read-only except through
the helpers. A `Socket` owns its descriptor: close it explicitly or use
`with_socket`. Copies reference the same socket, so closing one closes all
aliases and sets `fd` to -1. There is no automatic finalizer.

## UDP example

```may
import "net" as net;

net.with_socket(net.udp_bind("127.0.0.1", 9001), fun(s: net.Socket) -> Any {
    let packet: net.Datagram = net.udp_receive_from(s, 65535);
    return net.udp_send_to(s, packet.data, packet.sender);
});
```

UDP preserves message boundaries and sender addresses. Empty datagrams are
valid. The maximum outgoing payload is 65,507 bytes. If a received packet
exceeds `max_bytes`, it is consumed and raises an error with `errno == 90`,
rather than returning truncated data. `max_bytes` must be 1–65,535.
Destination port 0 is rejected for TCP connections and UDP sends.

## Bytes, waiting and errors

Payloads are `Str` values containing arbitrary bytes, including NULs and
invalid UTF-8. Use `byte_length` and `bytes` for binary data; `len(Str)` counts
Unicode codepoints. TCP receive allocations are limited to 16 MiB per call;
larger streams can be processed in successive calls.

Sockets are nonblocking and close on exec. Public operations wait using
`poll`; their default timeout is 30,000 milliseconds. Set -1 for unlimited
waiting or 0 for an immediate readiness check. Valid finite values are
0–2,147,483,647. Each operation uses one monotonic deadline across partial
I/O and interrupted syscalls. `socket_wait` uses its explicit timeout and
does not change the socket's setting. Readiness can also indicate EOF or an
error; the subsequent I/O determines which. Sending on a disconnected peer
raises a Maylang error instead of terminating the process with SIGPIPE.

Errors integrate with `may ... otherwise` and contain `kind == "network"`,
`message`, `operation` and positive Linux `errno`. Validation errors use 22,
closed sockets 9, timeouts 110, oversized UDP packets 90, and unexpected
TCP EOF 0. Other system errors preserve their Linux number. Socket creation,
connect, bind and listen failures clean up descriptors before raising.
`with_socket` preserves the original callback error when cleaning up.

```may
let result: Any = may {
    net.with_socket(net.tcp_connect_timeout("localhost", 9000, 1000),
        fun(s: net.Socket) -> Any { return net.tcp_receive(s, 4096); });
} otherwise {
    print(err.kind, err.operation, err.errno, err.message);
    nil
};
```

## Verification

```sh
python3 toolchain/mayc/tests/network.py --llvm
```

The suite checks address validation, byte round trips, TCP/UDP loopback,
timeouts, partial transfers against a Python peer, EOF, half-close, SIGPIPE,
descriptor flags and cleanup, and private module visibility on both backends.
In sandboxes that deny socket creation, live tests are skipped while all
fixtures still compile and validation tests execute. CI uses
`--require-sockets --llvm` to require real loopback execution.
