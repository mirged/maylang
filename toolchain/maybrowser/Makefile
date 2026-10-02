MAYC ?= ../mayc/mayc_new
CC ?= cc
PYTHON ?= python3
CFLAGS ?= -O2 -Wall -Wextra
CURL_LIBS ?= -l:libcurl.so.4

SOURCES := main.may $(wildcard src/*.may)
VENDOR := $(wildcard native/vendor/*.h)

.PHONY: all build embed check test examples clean
all: build
build: build/maybrowser build/libmaybrowser.so

build:
	mkdir -p $@

src/js_prelude.may: native/dom_bridge.js tools/embed_js.py
	$(PYTHON) tools/embed_js.py

embed:
	$(PYTHON) tools/embed_js.py

build/maybrowser: $(SOURCES) $(MAYC) ../mayc/build/bin/mayc_new ../mayc/runtime.may ../mayc/native.may ../../stdlib/prelude.may | build
	$(MAYC) main.may -o $@.next
	mv $@.next $@

build/libmaybrowser.so: native/maybrowser.c $(VENDOR) | build
	$(CC) $(CFLAGS) -fPIC -shared native/maybrowser.c -o $@.next $(CURL_LIBS) -lm
	mv $@.next $@

check: src/js_prelude.may
	$(PYTHON) tools/embed_js.py --check
	$(MAYC) --check main.may

test: build
	$(PYTHON) tests/run.py --compiler $(MAYC)

examples: build
	./maybrowser examples/hello.html --width 800 --height 900 -o build/hello.png
	./maybrowser examples/dynamic.html --width 800 --height 700 -o build/dynamic.png

clean:
	$(PYTHON) -c 'import shutil; shutil.rmtree("build", ignore_errors=True)'
