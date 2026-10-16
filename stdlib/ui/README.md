# Native Maylang UI

`import "ui" as ui` gives a typed widget tree, responsive row/column layout,
buttons, checkboxes, Unicode single-line entries, keyboard focus, scroll viewports
and fixed-height virtual lists. Widgets and interaction logic are Maylang. The
native adapter records clipped geometry and uses Sokol to render rounded
rectangles, concentric borders, soft shadows, lines and text in one alpha-blended
GPU draw batch. Rounded edges use analytical distance-field antialiasing. Text
uses fractional glyph positions and a cached, twice-oversampled Unicode atlas.
No full-window CPU rasterization or RGB texture upload is needed for native
widget rendering. Widgets, layout, focus and application state remain Maylang.

Sokol runs on a dedicated Linux thread. Immutable geometry/atlas packets cross a
synchronized bridge; only that thread calls graphics APIs. A matching software
renderer handles headless windows, snapshots and pixel inspection. Vendored
headers and their licenses are listed in [native/vendor/README.md](native/vendor/README.md).

Uses the direct `x86_64-linux` native backend and full runtime. The experimental
LLVM backend currently has no C `extern` support. Requires a C compiler, X11,
Xi, Xcursor and OpenGL development libraries, and a readable TrueType font.
Interactive windows need X11 or XWayland and OpenGL 4.3 (Mesa software rendering
also works). Debian/Ubuntu:
`sudo apt-get install build-essential libx11-dev libxi-dev libxcursor-dev libgl-dev fonts-dejavu-core`.
`MAYUI_FONT` selects a trusted local font; DejaVu Sans is the default.

The native target compiles `draw.c` and `sokol.c` into `libmayui.so` and links
`-lX11 -lXi -lXcursor -lGL -ldl -pthread -lm`. Sokol headers are pinned and
vendored, so builds do not download dependencies. Existing native targets that
compile `window.c` must switch to `sokol.c` and add these link flags.

```sh
may new my-desktop-app --ui
cd my-desktop-app
may run
may dev
```

The scaffold declares the native adapter as a prerequisite in `may.json`, builds
it into the artifact store and supplies the application's library search path.
For an existing workspace, copy the `ui` native target and application `depends`
from [Mayboard's workspace](../../example_projects/apps/mayboard/may.json).

```may
import "ui" as ui;
let window: ui.Window = ui.open("Counter", 640, 420, false);
mut count: Int = 0;
mut running: Bool = true;
while (running) {
    ui.present(window, ui.spacing(ui.column([
        ui.label("Clicks: " + str(count)),
        ui.button("count", "Count a click")
    ]), 24, 12));
    let event: ui.Event = ui.poll(window);
    if (event.kind == "close") { running = false; }
    if (event.kind == "click" and event.id == "count") { count += 1; }
}
ui.close(window);
```

Use stable, unique identifiers for interactive widgets and scrollers. Keep the
`Window` while rebuilding views from your model. `present` measures/layouts the
new tree and replaces hit regions; persistent focus/caret/scroll state belongs
to the window. Apply `edit` event text to your model before the next render.
Checkbox `toggle` events return `"true"`/`"false"`; the application owns the value.
`submit` comes from Enter in an entry, and `click` from mouse/Enter/Space actions.
`poll` waits up to 16 ms; skip repaints for `idle` events. `poll_for(window, ms)`
accepts 0..1000 ms; use zero when an application supplies its own frame pacing.
Polling also wakes when Sokol submits a frame, so animation loops can use the
remaining refresh interval instead of adding a fixed sleep after rendering.

Containers use content dimensions unless given a size. `flex` shares remaining
space along the parent axis; cross-axis space fills the parent. `spacing` sets
inset and gaps, `style` sets RGB colors/font size/radius, and `placeholder` adds
an empty-entry hint. Text stays on one line and clips to its widget. Scroll
viewports clip both drawing and hit tests. `virtual_list` builds the visible
fixed-height rows plus spacers, keeping long lists from constructing every row.

Tab/Shift+Tab traverse visible controls. Entries support codepoint-safe arrows,
Home/End, Backspace/Delete, Enter, Ctrl+A (select whole input), Ctrl+C/X/V (plain
text clipboard); Ctrl+Q closes the app. Entry values are limited to 2048
codepoints. Selection is currently whole-input, with no range drag selection.
Only one window/surface may be active. This first toolkit has no accessibility
bridge, IME composition overlay, rich text or a general image collection. Sokol currently
uses the Linux OpenGL backend; adding a graphics backend does not extend the
compiler/runtime host platforms.

Light and dark showcase previews, rendered through the native OpenGL pipeline:
[light](screenshots/light.png) · [dark](screenshots/dark.png).

## Dynamic framebuffers and game input

`upload_rgba(pointer, width, height)` copies packed RGBA8 pixels into the active
surface's single shared framebuffer (1..4096 pixels per axis). The caller may
reuse/free its source buffer after the call. `framebuffer(source_width,
source_height, integer_scale)` creates an aspect-fit widget with nearest pixel
sampling; `flex` makes it occupy available space. An integer scale is used when
at least 1× fits, otherwise it scales down to fit. Normal clipping and snapshots
work for framebuffers too. Multiple framebuffer widgets display the same image.
Upload after `open`; closing releases it. The texture is separate from the glyph
atlas, and its GPU storage/staging buffer persist across updates.

`key_down(window, key)` reports held keys. `key_pressed(window, key)` consumes one
press, retaining taps that happen between polls and excluding auto-repeat.
Both clear on focus loss and window close. Codes use Sokol's stable values:
uppercase ASCII letters (A=65, X=88, Z=90), Space=32, Enter=257, Right=262,
Left=263, Down=264, Up=265, F5=294, F8=297, right Shift=344.
`focused(window)` reports native keyboard focus. Applications should suppress
shortcuts and gameplay while text entries own their focus, and consume unused
presses to avoid replaying them later.

The [May NES app](../../example_projects/apps/maynes/README.md) demonstrates a
real emulator framebuffer, simultaneous controller keys, audio and cartridge
loading with the same native widget toolkit.

## Appearance and rendering

Default controls follow the window's light/dark palette, with fine borders,
quiet hover fills, a pressed state and a violet keyboard-focus ring. Checkmarks
use antialiased round-capped line segments. Disabled controls stay in layout but
are excluded from mouse actions and keyboard traversal. Explicit `style` colors
continue to take precedence over the palette.

```may
ui.set_theme(window, ui.dark_theme());
let content: ui.Widget = ui.card(ui.spacing(ui.column([
    ui.label("Your next idea"),
    ui.entry("name", "A smooth native surface"),
    ui.primary(ui.button("create", "Create workspace")),
    ui.enabled(ui.button("publish", "Publish"), false)
]), 24, 14));
ui.present(window, ui.spacing(ui.column([content]), 32, 16));
print(ui.renderer(window));
print(ui.render_stats(window));
```

`Theme` contains background, surface, soft, text, muted, accent, on-accent and
border RGB colors. `set_theme`, `light_theme` and `dark_theme` change defaults.
`primary` applies accent colors, `border(item, rgb, width)` adds a 0..8 px border,
`elevated(item, level)` adds a 0..3 elevation shadow, and `card` combines a themed
surface, a 1 px border, a 14 px radius and a light shadow. Normal containers allow
shadows to extend beyond their boxes; scroll viewports still clip drawing/hits.
Text widths are cached by content and font size. Layout is recalculated on
each presentation, so mutable widget trees and resizes stay correct. Plain
widgets share immutable decoration data; styling helpers replace that data
without changing other widgets.

`renderer` identifies the actual OpenGL driver, including Mesa software drivers.
`render_stats` reports recorded commands/vertices, cumulative glyph-cache hits
and misses, atlas bytes, and draw batches (zero in headless mode). The atlas grows
from 4 MiB to at most 16 MiB and the glyph/measurement caches are bounded. If a
single frame exhausts the atlas it uses an outlined fallback glyph, then resets
the cache at the next frame boundary. Unchanged geometry stays in a persistent
GPU vertex buffer, and the atlas is uploaded only when its content changes.
A resize changes geometry without
reallocating a fullscreen upload texture.

Set `MAYUI_RENDERER=cpu` to compare the software rasterizer in a native window;
Sokol then presents the resulting RGB image. Native windows still need OpenGL
in that mode. `MAYUI_FONT` selects a trusted local font, and changing it requires
closing/reopening the surface.

Run the [showcase](../../examples/ui_showcase.may) from the repository root:

```sh
python3 toolchain/mayui/demo.py
python3 toolchain/mayui/demo.py --dark
python3 toolchain/mayui/demo.py --snapshot /tmp/mayui-light.png
```

For deterministic rendering, use `open(..., true)` without a display, then
`present` and `snapshot`. This path renders the commands in software and starts no Sokol thread or graphics context.
Native `snapshot`/`pixel` materialize the same frame in software on demand; they
do not stall for GPU readback and do not measure GPU completion.
`dispatch` exercises input transitions without a display.
The [complete Mayboard app](../../example_projects/apps/mayboard/README.md) shows
separate model/store/view modules, persistence, search and editing.

Run `python3 toolchain/mayui/tests/run.py --require-x11` with Xvfb and xdotool to
check fractional edge coverage, alpha/clipping, Unicode cache reuse, malformed
UTF-8, GPU/software pixel agreement, light/dark previews, repeated window lifecycle,
window-manager close and real desktop input. Without those dependencies, the
default command reports the real-input skip explicitly.
