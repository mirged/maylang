MAYC ?= ../../../toolchain/mayc/mayc_new
MAYPKG ?= build/maypkg
MAYLANG_STDLIB ?= $(abspath ../../../stdlib)
export MAYLANG_STDLIB

.PHONY: build demo test check
build: $(MAYPKG)
	mkdir -p build
	PWD="$(CURDIR)" PATH="$(abspath ../../../toolchain/mayc):$$PATH" $(MAYPKG) build --force --script
	PATH="$(abspath ../../../toolchain/mayc):$$PATH" sh build/maypkg.build.sh
	PWD="$(CURDIR)" $(MAYPKG) lock

build/maypkg: ../../../toolchain/maypkg/main.may ../../../toolchain/maypkg/src/*.may
	mkdir -p build
	$(MAYC) ../../../toolchain/maypkg/main.may -o $@

demo: build
	python3 tools/demo.py ./build/rivet

check: build
	PWD="$(CURDIR)" $(MAYPKG) check
	PWD="$(CURDIR)" $(MAYPKG) verify

test: build
	python3 tests/test_storage.py ./build/rivet
