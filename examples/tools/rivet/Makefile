MAYC ?= ../../../compiler/mayc/mayc_new
MAYLANG_STDLIB ?= $(abspath ../../../stdlib)
export MAYLANG_STDLIB

.PHONY: build demo test check
build: build/rivet

build/rivet: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@

demo: build
	python3 tools/demo.py ./build/rivet

check:
	$(MAYC) --check main.may

test: build
	python3 tests/test_storage.py ./build/rivet
