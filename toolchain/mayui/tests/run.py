#!/usr/bin/env python3
"""Exercise Maylang layout/editing, the complete app, and real X11 interaction."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "example_projects/apps/mayboard"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, default=ROOT / "toolchain/mayc/mayc_new")
    parser.add_argument("--require-x11", action="store_true")
    parser.add_argument("--display", help="use an existing test display instead of starting Xvfb")
    options = parser.parse_args()
    environment = dict(os.environ, MAYLANG_STDLIB=str(ROOT / "stdlib"), MAYC=str(options.compiler.resolve()), MAYUI_RENDERER="gpu")
    if options.display:
        environment["DISPLAY"] = options.display
    with tempfile.TemporaryDirectory(prefix="may-ui-") as temporary:
        directory = Path(temporary)
        environment["LD_LIBRARY_PATH"] = str(directory) + ":" + environment.get("LD_LIBRARY_PATH", "")

        def run(command, cwd=ROOT, timeout=90):
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=environment,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"{command}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        def compile(source, output):
            run([options.compiler, source, "-o", output])

        native = ROOT / "stdlib/ui/native"
        run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", native / "draw.c", native / "sokol.c", "-o", directory / "libmayui.so", "-lX11", "-lXi", "-lXcursor", "-lGL", "-ldl", "-pthread", "-lm"])
        print(run([sys.executable, Path(__file__).with_name('native.py'), directory / 'libmayui.so']).strip(), flush=True)
        print(run([sys.executable, Path(__file__).with_name('raster.py'), directory / 'libmayui.so']).strip(), flush=True)
        compile(ROOT / "examples/ui_showcase.may", directory / "showcase")
        run([directory / "showcase", "--snapshot", directory / "light.png"])
        run([directory / "showcase", "--dark", "--snapshot", directory / "dark.png"])
        assert (directory / "light.png").read_bytes() != (directory / "dark.png").read_bytes()
        compile(ROOT / "toolchain/mayui/tests/widgets.may", directory / "widgets")
        print(run([directory / "widgets"]).strip())
        compile(ROOT / "toolchain/may/main.may", directory / "may")
        print(run([directory / "may", "test"], APP).strip())
        run([directory / "may", "run", "--", "--demo", "--snapshot", directory / "snapshot.png"], APP)
        assert (directory / "snapshot.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        scaffold = directory / "desktop project λ"
        run([directory / "may", "new", scaffold, "--ui"])
        run([directory / "may", "check"], scaffold)
        run([directory / "may", "build"], scaffold)
        run([directory / "may", "test"], scaffold)
        print("PASS native raster/widgets, app models, headless PNG and may new --ui/build/test")

        xdotool = shutil.which("xdotool")
        xvfb = shutil.which("Xvfb")
        if not xdotool or (not xvfb and not environment.get("DISPLAY")):
            if options.require_x11:
                raise RuntimeError("X11 regression needs Xvfb and xdotool (or an existing DISPLAY)")
            print("SKIP real X11 input (install Xvfb and xdotool, then use --require-x11)")
            return
        server = None
        try:
            if xvfb and not options.display:
                # -displayfd lets the server choose a free display without a port race.
                read_fd, write_fd = os.pipe()
                server = subprocess.Popen([xvfb, "-displayfd", str(write_fd), "-screen", "0", "1280x1024x24", "-nolisten", "tcp", "-ac"],
                                          env=environment, pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                os.close(write_fd)
                import select
                assert select.select([read_fd], [], [], 10)[0], "Xvfb did not start"
                display = os.read(read_fd, 32).decode().strip(); os.close(read_fd)
                assert display, server.stderr.read().decode()
                environment["DISPLAY"] = ":" + display
            print(run([sys.executable, Path(__file__).with_name('native.py'), directory / 'libmayui.so', '--window']).strip(), flush=True)
            software = subprocess.run([sys.executable, str(Path(__file__).with_name('native.py')),
                                       str(directory / 'libmayui.so'), '--window'],
                                      env=dict(environment, MAYUI_RENDERER='cpu'), capture_output=True,
                                      text=True, timeout=90)
            assert software.returncode == 0, (software.stdout, software.stderr)
            print('PASS forced CPU reference in a native Sokol window', flush=True)
            compile(APP / "src/main.may", directory / "mayboard")
            data = directory / "data/tasks.json"

            def wait(predicate, label):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    try:
                        if predicate():
                            return
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                    time.sleep(.08)
                raise AssertionError(label)

            def records():
                return json.loads(data.read_text())["tasks"]

            def start():
                child = subprocess.Popen([directory / "mayboard", "--data", data], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    window = run([xdotool, "search", "--sync", "--onlyvisible", "--pid", child.pid, "--name", "Mayboard"], timeout=10).strip().splitlines()[0]
                    run([xdotool, "windowfocus", "--sync", window])
                    return child, window
                except BaseException:
                    child.kill(); child.wait(); raise

            def key(window, keys):
                run([xdotool, "key", "--clearmodifiers", keys])
                time.sleep(.08)

            def click(window, x, y):
                run([xdotool, "mousemove", "--window", window, x, y, "click", "1"])
                time.sleep(.08)

            child, window = start()
            try:
                competing = subprocess.run([directory / "mayboard", "--data", data], env=environment,
                                           capture_output=True, text=True, timeout=5)
                assert competing.returncode == 1 and "Another Mayboard instance" in competing.stdout
                # xdotool temporarily remaps Unicode keysyms; keep the mapping
                # until the app consumes the key before xdotool restores it.
                run([xdotool, "type", "--window", window, "--clearmodifiers", "--delay", "150", "First café λ"])
                key(window, "Return")
                wait(lambda: len(records()) == 1, "Enter did not persist task")
                assert records()[0]["title"] == "First café λ", records()
                assert data.stat().st_mode & 0o777 == 0o600
                run([xdotool, "type", "--window", window, "Second task"]); key(window, "Return")
                wait(lambda: len(records()) == 2, "second task not saved")
                click(window, 50, 397)
                wait(lambda: records()[0]["done"], "checkbox did not complete task")
                click(window, 735, 397)
                key(window, "ctrl+a")
                run([xdotool, "type", "--window", window, "--delay", "150", "Renamed λ"]); key(window, "Return")
                wait(lambda: records()[0]["title"] == "Renamed λ", "edit did not persist")
                # Search reduces visible rows. Delete must target the matching second task.
                click(window, 405, 330)
                run([xdotool, "type", "--window", window, "Second"])
                key(window, "ctrl+a"); key(window, "ctrl+c"); key(window, "BackSpace"); key(window, "ctrl+v")
                time.sleep(.25); click(window, 815, 397)
                wait(lambda: len(records()) == 1, "filtered Delete did not persist")
                assert records()[0]["title"] == "Renamed λ"
                run([xdotool, "windowsize", window, "560", "580"])
                time.sleep(.2); key(window, "ctrl+q")
                child.communicate(timeout=5); assert child.returncode == 0
            finally:
                if child.poll() is None:
                    child.kill(); child.communicate()
            child, window = start()
            try:
                # Reopened persisted data; Clear done removes the completed row.
                click(window, 815, 712)
                wait(lambda: records() == [], "restart/clear did not load persisted completion")
                key(window, "ctrl+q"); child.communicate(timeout=5); assert child.returncode == 0
            finally:
                if child.poll() is None:
                    child.kill(); child.communicate()
            broken = '{"schema":2,"tasks":[]}'; data.write_text(broken)
            child, window = start()
            try:
                run([xdotool, "type", "--window", window, "Preserve data"]); key(window, "Return")
                time.sleep(.3); key(window, "ctrl+q"); child.communicate(timeout=5)
                assert child.returncode == 0 and data.read_text() == broken, "invalid source data was overwritten"
            finally:
                if child.poll() is None:
                    child.kill(); child.communicate()
            assert not list(data.parent.glob("*.tmp-*"))
            print("PASS real X11 Unicode typing, Enter/add, checkbox, edit, search/delete, resize, close/reopen, atomic persistence and corrupt-file preservation")
        finally:
            if server:
                server.terminate()
                server.communicate(timeout=5)


if __name__ == "__main__":
    main()
