MAYC ?= ../mayc/mayc_new
CC ?= cc
PYTHON ?= python3
TESTFLAGS ?=
CFLAGS ?= -O2 -Wall -Wextra
CURL_LIBS ?= -l:libcurl.so.4
WINDOW_LIBS ?= -lX11

SOURCES := main.may $(wildcard src/*.may)
VENDOR := $(wildcard native/vendor/*.h)

.PHONY: all build embed check test examples clean
all: build
build: build/maybrowser build/libmaybrowser.so

build/.dir:
	mkdir -p build
	touch $@

src/js_prelude.may: native/dom_bridge.js tools/embed_js.py
	$(PYTHON) tools/embed_js.py

embed:
	$(PYTHON) tools/embed_js.py

build/maybrowser: $(SOURCES) $(MAYC) ../mayc/runtime.may ../mayc/native.may ../../stdlib/prelude.may | build/.dir
	$(MAYC) main.may -o $@.next
	mv $@.next $@

build/libmaybrowser.so: native/maybrowser.c native/window.c $(VENDOR) | build/.dir
	$(CC) $(CFLAGS) -fPIC -shared native/maybrowser.c native/window.c -o $@.next $(CURL_LIBS) $(WINDOW_LIBS) -lm
	mv $@.next $@

check: src/js_prelude.may
	$(PYTHON) tools/embed_js.py --check
	$(MAYC) --check main.may

test: build
	$(PYTHON) tests/run.py --compiler $(MAYC) $(TESTFLAGS)

examples: build
	./maybrowser examples/hello.html --width 800 --height 900 -o build/hello.png
	./maybrowser examples/dynamic.html --width 800 --height 700 -o build/dynamic.png

clean:
	$(PYTHON) -c 'import shutil; shutil.rmtree("build", ignore_errors=True)'
