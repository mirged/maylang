# Native Maylang UI

`import "ui" as ui` gives a typed widget tree, responsive row/column layout,
buttons, checkboxes, Unicode single-line entries, keyboard focus, scroll viewports
and fixed-height virtual lists. Widgets and interaction logic are Maylang. The
small `native/` adapter supplies an X11 window, clipboard/input, CPU drawing,
trusted TrueType font metrics and PNG output. It has no widget or application
state. Its X11 presentation/input code follows the existing maybrowser adapter;
vendored stb headers retain their embedded MIT/public-domain license notices.

Uses the direct `x86_64-linux` native backend and full runtime. The experimental
LLVM backend currently has no C `extern` support. Requires a C compiler, X11 development headers and
a readable TrueType font. Interactive windows need X11 or XWayland. Debian/Ubuntu:
`sudo apt-get install build-essential libx11-dev fonts-dejavu-core`.
`MAYUI_FONT` selects a trusted local font; DejaVu Sans is the default.

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
`poll` waits up to 50 ms; skip repaints for `idle` events.

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
bridge, IME composition overlay, rich text, image widgets or GPU rendering.

For deterministic rendering, use `open(..., true)` without a display, then
`present` and `snapshot`. `dispatch` exercises input transitions without X11.
The [complete Mayboard app](../../example_projects/apps/mayboard/README.md) shows
separate model/store/view modules, persistence, search and editing.

Run `python3 toolchain/mayui/tests/run.py --require-x11` with Xvfb and xdotool to
check rendering/model behavior and real desktop input. Without those dependencies,
the default command reports the real-input skip explicitly.
