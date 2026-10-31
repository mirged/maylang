# Native UI dependencies

Every third-party file here is listed in [vendor.json](vendor.json) with its
upstream repository, pinned revision, upstream path, SPDX license, SHA-256
checksum and local modifications (currently none: all files are byte-identical
upstream copies with their embedded license notices intact).

Sokol is from [floooh/sokol](https://github.com/floooh/sokol), pinned to commit
`5e94d1291fea504ed911090338cf35bd9ef49a06` (zlib/libpng license):

- `sokol_app.h`: window, OpenGL context, events and clipboard.
- `sokol_gfx.h`: graphics resources and render passes.
- `sokol_glue.h`: application/graphics environment and swapchain bridge.

`../sokol.c` defines the implementations once, using `SOKOL_NO_ENTRY` to keep
Maylang's entry point and the `SOKOL_GLCORE` backend. Its polling bridge currently
targets Linux x86-64; vendoring Sokol does not extend Maylang's runtime targets.

`stb_truetype.h` (v1.26) and `stb_image_write.h` (v1.16) are from
[nothings/stb](https://github.com/nothings/stb), pinned to commit
`6e9f34d5429cf16790ec43c9bac3f1ee4ad1f760`, under its MIT or public-domain
(Unlicense) alternative.

This directory is the only maintained copy. `frozen/platform/maybrowser` keeps
older duplicates of the stb headers, which are not built or updated
([frozen/README.md](../../../../frozen/README.md)). The release bundle ships
this directory unchanged, so UI sources stay self-contained.

Checking and updating:

- `make check` runs `python3 scripts/vendor.py check`, which fails when a file
  differs from its recorded checksum or is not listed in `vendor.json`. The
  package test runs the same check on the extracted bundle.
- `python3 scripts/vendor.py upstream` downloads each pinned revision and
  confirms that unmodified files still match it.
- `python3 scripts/vendor.py update stdlib/ui/native/vendor FILE REVISION`
  replaces a file with the upstream copy at `REVISION` and records the new
  revision and checksum. Review the diff and the license, restore the
  `version` field, then run `make test-ui` and `make package`. If a file must
  be patched locally, describe the change in its `modifications` field.

`../gpu.h` supplies Maylang's own signed-distance shape and glyph-atlas shader,
with one Sokol graphics pipeline and an alpha-blended draw batch. It does not
use sokol-gl or an immediate-mode widget library.
