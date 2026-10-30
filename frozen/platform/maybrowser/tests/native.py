"""Observable resource-boundary tests for the browser's native adapter."""
import base64
import ctypes
import gzip
import struct
import zlib


MAX_BYTES = 16 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_PIXELS = 16 * 1024 * 1024


def adapter(path):
    library = ctypes.CDLL(str(path))
    for name, arguments, result in (
        ('mb_image_load', [ctypes.c_char_p], ctypes.c_void_p),
        ('mb_image_load_mem', [ctypes.c_void_p, ctypes.c_int], ctypes.c_void_p),
        ('mb_image_load_b64', [ctypes.c_char_p], ctypes.c_void_p),
        ('mb_fetch_file', [ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
        ('mb_last_error', [], ctypes.c_char_p),
        ('mb_free', [ctypes.c_void_p], None),
    ):
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    return library


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def image_header(width, height):
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))


def image_metadata(width, height):
    return image_header(width, height) + chunk(b'IDAT', b'')


def image(width, height):
    # Compress row by row so the test fixture itself needs little memory.
    compressor = zlib.compressobj()
    row = b'\0' + bytes((17, 34, 51, 255)) * width
    body = b''.join(compressor.compress(row) for _ in range(height)) + compressor.flush()
    return image_header(width, height) + chunk(b'IDAT', body) + chunk(b'IEND', b'')


def test_images(library_path, directory):
    library = adapter(library_path)
    path = directory / 'bounded-image.png'
    good = image(1, 1)

    def check_image(data, width, height):
        pointer = library.mb_image_load_mem(data, len(data))
        assert pointer, library.mb_last_error()
        try:
            assert struct.unpack('4i', ctypes.string_at(pointer, 16)) == (width, height, 4, 0)
            assert ctypes.string_at(pointer + 16, 4) == bytes((17, 34, 51, 255))
            assert library.mb_last_error() == b''
        finally:
            library.mb_free(pointer)

    check_image(good, 1, 1)
    check_image(image(MAX_DIMENSION, 1), MAX_DIMENSION, 1)
    check_image(image(1, MAX_DIMENSION), 1, MAX_DIMENSION)
    check_image(image(4096, 4096), 4096, 4096)  # Exactly the decoded-pixel budget.
    # Encoded-byte boundary (PNG permits trailing bytes).
    check_image(good + b'\0' * (MAX_BYTES - len(good)), 1, 1)
    assert not library.mb_image_load_mem(good, MAX_BYTES + 1)
    assert b'16 MiB' in library.mb_last_error()
    assert not library.mb_image_load_mem(None, -1)
    assert not library.mb_image_load_mem(None, 0)

    for data, message in (
        (image_metadata(MAX_DIMENSION + 1, 1), b'8192'),
        (image_metadata(1, MAX_DIMENSION + 1), b'8192'),
        (image_metadata(4097, 4096), b'16777216'),
        (image_metadata(MAX_DIMENSION, MAX_DIMENSION), b'16777216'),
        (image_metadata(0, 1), b'header'),
        (image_metadata(1, 1), b'data'),  # Valid metadata, truncated pixel data.
        (b'not an image', b'header'),
    ):
        path.write_bytes(data)
        for load in (
            lambda: library.mb_image_load_mem(data, len(data)),
            lambda: library.mb_image_load(str(path).encode()),
            lambda: library.mb_image_load_b64(base64.b64encode(data)),
        ):
            assert not load()
            assert message in library.mb_last_error(), library.mb_last_error()
            check_image(good, 1, 1)  # A failure must not poison later loads.
    with path.open('wb') as output:
        output.truncate(MAX_BYTES + 1)
    assert not library.mb_image_load(str(path).encode())
    assert b'16 MiB' in library.mb_last_error()
    assert not library.mb_image_load_b64(base64.b64encode(b'x' * (MAX_BYTES + 1)))
    assert b'16 MiB' in library.mb_last_error()
    # A sufficiently long base64 value also catches signed accumulator overflow.
    pointer = library.mb_image_load_b64(base64.b64encode(good))
    assert pointer, library.mb_last_error()
    library.mb_free(pointer)


def respond(handler):
    """Serve fixed-length, chunked, EOF-delimited and gzip budget boundaries."""
    if not handler.path.startswith('/budget/'):
        return False
    mode, count = handler.path.removeprefix('/budget/').split('/')
    count = int(count)
    handler.send_response(200)
    if mode == 'gzip':
        payload = gzip.compress(b'x' * count)
        handler.send_header('Content-Encoding', 'gzip')
        handler.send_header('Content-Length', str(len(payload)))
    elif mode == 'fixed':
        handler.send_header('Content-Length', str(count))
    elif mode == 'chunked':
        handler.send_header('Transfer-Encoding', 'chunked')
    else:
        assert mode == 'eof'
        handler.send_header('Connection', 'close')
    handler.end_headers()
    try:
        if mode == 'gzip':
            handler.wfile.write(payload)
        else:
            while count:
                data = b'x' * min(count, 65536)
                if mode == 'chunked':
                    handler.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')
                else:
                    handler.wfile.write(data)
                count -= len(data)
            if mode == 'chunked':
                handler.wfile.write(b'0\r\n\r\n')
    except (BrokenPipeError, ConnectionResetError):
        pass  # The client must abort over-budget transfers.
    return True


def test_responses(library_path, directory, origin, browser):
    library = adapter(library_path)
    output = directory / 'bounded-download'

    def fetch(url):
        return library.mb_fetch_file(url.encode(), str(output).encode())

    for mode in ('fixed', 'chunked', 'eof', 'gzip'):
        for count in (0, MAX_BYTES - 1, MAX_BYTES, MAX_BYTES + 1):
            output.write_bytes(b'preserved')
            code = fetch(f'{origin}/budget/{mode}/{count}')
            if count <= MAX_BYTES:
                assert code == 0, library.mb_last_error()
                assert output.stat().st_size == count
                if count:
                    assert output.read_bytes() == b'x' * count
                assert library.mb_last_error() == b''
            else:
                assert code != 0
                assert b'16 MiB' in library.mb_last_error(), library.mb_last_error()
                assert output.read_bytes() == b'preserved'
                assert fetch(f'{origin}/budget/fixed/2') == 0, library.mb_last_error()
                assert output.read_bytes() == b'xx'
                assert library.mb_last_error() == b''
    # The browser must surface the limit instead of only a generic read error.
    result = browser(f'{origin}/budget/gzip/{MAX_BYTES + 1}', '-o', directory/'oversized.png', success=False)
    assert '16 MiB' in result, result
    assert not (directory/'oversized.png').exists()
    browser(origin+'/nested/index.html', '-o', directory/'recovered.png')
    url = f'{origin}/budget/gzip/{MAX_BYTES + 1}'
    html = f'<html><head><link rel="stylesheet" href="{url}"></head><body><img src="{url}"><script src="{url}"></script><p>Still renders</p></body></html>'
    result = browser('--html', html, '-o', directory/'skipped-assets.png')
    assert result.count('16 MiB') == 1, result  # Failed resources are cached once.
    bad_image = directory/'large-dimensions.png'
    bad_image.write_bytes(image_metadata(MAX_DIMENSION + 1, 1))
    good_image = directory/'good-image.png'
    good_image.write_bytes(image(1, 1))
    result = browser('--html', f'<html><body><img src="{bad_image}"><img src="{good_image}"></body></html>',
                     '-o', directory/'skipped-image.png')
    assert '8192' in result, result
    for prefix, payload in (
        ('data:text/plain,', 'x' * (MAX_BYTES + 1)),
        ('data:;base64,', base64.b64encode(b'x' * (MAX_BYTES + 1)).decode()),
    ):
        assert fetch(prefix + payload) != 0
        assert b'16 MiB' in library.mb_last_error()
    assert fetch('data:text/plain,%41%00%42') == 0
    assert output.read_bytes() == b'A\0B'
    assert fetch('data:;base64,QQBC') == 0
    assert output.read_bytes() == b'A\0B'
