# Native UI dependencies

Sokol is from [floooh/sokol](https://github.com/floooh/sokol), pinned to commit
`5e94d1291fea504ed911090338cf35bd9ef49a06`. The following files are unmodified
upstream copies, with their embedded zlib/libpng license notices intact:

- `sokol_app.h`: window, OpenGL context, events and clipboard.
- `sokol_gfx.h`: graphics resources and render passes.
- `sokol_glue.h`: application/graphics environment and swapchain bridge.

`../sokol.c` defines the implementations once, using `SOKOL_NO_ENTRY` to keep
Maylang's entry point and the `SOKOL_GLCORE` backend. Its polling bridge currently
targets Linux x86-64; vendoring Sokol does not extend Maylang's runtime targets.

The stb font and PNG headers retain their embedded MIT/public-domain notices.

`../gpu.h` supplies Maylang's own signed-distance shape and glyph-atlas shader,
with one Sokol graphics pipeline and an alpha-blended draw batch. It does not
use sokol-gl or an immediate-mode widget library.
