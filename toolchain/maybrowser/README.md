# MayBrowser

MayBrowser is an experimental desktop browser written in Maylang. It has a
graphical start page, an editable address bar, page history, clickable links,
scrolling, live JavaScript button interactions, and PNG export. The browser
chrome, HTML/CSS engine, layout, drawing, and navigation run in Maylang. A small
native library provides X11 input/presentation, fonts, images, HTTP, and PNGs;
Duktape executes page scripts.

## Build and launch

The current build targets Linux x86-64 with X11 or XWayland. It needs a native
Maylang compiler, a C compiler, Python 3, X11 development headers, libcurl,
`libduktape.so.207`, and DejaVu fonts. On Ubuntu 24.04:

```sh
sudo apt-get install build-essential libx11-dev libcurl4-openssl-dev libduktape207 fonts-dejavu-core python3
# From the repository root; Rust stable is needed for the source bootstrap.
sh toolchain/rust/build.sh
make -C toolchain/maybrowser build
toolchain/maybrowser/maybrowser
```

Without an input, the browser opens its start page. Enter a file path or web
address, or open the built-in playground to try interactive JavaScript.

```sh
toolchain/maybrowser/maybrowser toolchain/maybrowser/examples/hello.html
toolchain/maybrowser/maybrowser https://example.com
toolchain/maybrowser/maybrowser about:demo --gui -o playground.png
```

HTTP and HTTPS documents can load relative stylesheets, scripts, and images.
Failed navigation shows a recovery page with retry and home controls.

| Control | Action |
| --- | --- |
| Ctrl+L | Focus and select the address |
| Enter / Escape | Open the edited address / cancel editing |
| Ctrl+A/C/V/X | Select, copy, paste, or cut the address |
| Alt+Left / Alt+Right | Previous / next page |
| Ctrl+R or F5 | Reload and reset page scripts |
| Ctrl+H | Start page |
| Wheel, arrows, Page Up/Down, Space | Scroll |
| Home / End | Top / bottom of the page |
| Ctrl+S or Save PNG | Save the current browser view |
| Ctrl+Q | Quit |

The window also has back, forward, reload, and home buttons, a clickable
scrollbar, link previews, and cursor feedback. Save PNG writes `maybrowser.png`
unless `--gui -o PATH` sets another path.

## Headless output

Passing `-o` without `--gui` preserves the page-to-PNG workflow. `--snapshot`
includes the browser interface and needs no graphical display.

```sh
toolchain/maybrowser/maybrowser toolchain/maybrowser/examples/hello.html -o page.png --width 800 --height 900
toolchain/maybrowser/maybrowser about:demo --snapshot -o browser.png
toolchain/maybrowser/maybrowser --snapshot -o start.png
printf '<h1>Hello</h1>' | toolchain/maybrowser/maybrowser - -o stdin.png
```

Use `--html` for inline HTML and `--no-js` to disable script execution.
Local files, `file://` paths, HTTP(S), and text/base64 `data:` documents work in
headless mode. Page viewports range from 1 to 4096 pixels per axis; graphical
and interface snapshot viewports start at 640×400.

## Checks

```sh
make -C toolchain/maybrowser check test
# Also exercise real HTTP and window input in a virtual X server:
sudo apt-get install xvfb xauth xdotool
xvfb-run -a make -C toolchain/maybrowser test TESTFLAGS='--require-network --gui'
```

Tests cover navigation/history, URL resolution, Unicode address editing,
load errors, JavaScript state and click handlers, stylesheet preservation,
scrolling, clipping, resizing, PNG pixels, HTTP assets, clipboard input, and
window shutdown. Socket checks explicitly skip when a sandbox blocks local
servers; `--require-network` makes that a failure. Live window checks require
`--gui`. Reports and screenshots are written to `build/` and uploaded by CI.

## Current scope

This is a small document browser, with basic block/inline CSS and Duktape
JavaScript. It does not yet implement modern browser features such as flex/grid
layout, JavaScript modules, timers, complete forms, or a full web platform.
HTTP loading is synchronous, so the window can pause during a request. The
playground and simple HTML documents demonstrate the supported interactions.
