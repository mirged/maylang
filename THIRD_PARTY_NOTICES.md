# Third-party notices

Maylang is released under the [MIT License](LICENSE). That license covers the
compiler, tools, standard library, examples and native adapters in this
repository, except for the third-party sources listed here, which stay under
their own licenses.

Every vendored file keeps its original text and embedded license notice. Do
not strip or rewrite those notices when copying files into a release bundle.
`python3 scripts/vendor.py check` (part of `make check`) verifies that the
maintained copies still match the pinned upstream bytes.

## Native UI headers

[Sokol](https://github.com/floooh/sokol) at commit
`5e94d1291fea504ed911090338cf35bd9ef49a06`, under the
[zlib/libpng license](#zliblibpng-license), copyright (c) 2018 Andre Weissflog:

- `stdlib/ui/native/vendor/sokol_app.h`
- `stdlib/ui/native/vendor/sokol_gfx.h`
- `stdlib/ui/native/vendor/sokol_glue.h`

[nothings/stb](https://github.com/nothings/stb) at commit
`6e9f34d5429cf16790ec43c9bac3f1ee4ad1f760`, dual-licensed under the
[MIT license](#mit-license) or the public-domain
[Unlicense](https://unlicense.org), copyright (c) 2017 Sean Barrett:

- `stdlib/ui/native/vendor/stb_image_write.h` (v1.16)
- `stdlib/ui/native/vendor/stb_truetype.h` (v1.26)

## May NES emulator core

[binji/binjnes](https://github.com/binji/binjnes) at commit
`e2f5871a28ff189daa82b70be9324a42e2aaf9fd`, under the
[MIT license](#mit-license), copyright 2021 Ben Smith. The sources and the
full notice are in `examples/apps/maynes/native/vendor/binjnes/`, including
`examples/apps/maynes/native/vendor/binjnes/LICENSE`. Local patches are
described in `examples/apps/maynes/native/vendor/README.md`.

The bundled homebrew ROM `examples/apps/maynes/roms/starfall.nes` is an
original work under the [MIT license](#mit-license), copyright 2026 May NES
contributors; the full notice is `examples/apps/maynes/roms/LICENSE`. No
commercial ROMs are bundled.

## Bundled distributions

The release archive built by `dist/package.py` contains the `stdlib/` tree and
the May NES application, so it includes the Sokol, stb and binjnes sources
above. The archive ships this file and the root `LICENSE` alongside them.

## Build-time dependencies

The Rust workspace crates in `Cargo.lock` and the VS Code extension's
`editors/vscode/package-lock.json` dependency tree are fetched from their
registries and are not vendored here or copied into the release archive. Each
dependency keeps its own license; run `cargo metadata` or `npm ls` for the
exact set when redistributing a build you made from them.

## zlib/libpng license

This software is provided 'as-is', without any express or implied warranty. In
no event will the authors be held liable for any damages arising from the use
of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim
   that you wrote the original software. If you use this software in a product,
   an acknowledgment in the product documentation would be appreciated but is
   not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.

## MIT license

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
