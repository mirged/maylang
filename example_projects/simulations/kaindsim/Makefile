MAYC ?= ../../../toolchain/mayc/mayc_new
MAYPKG ?= build/maypkg

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
	./build/kaindsim demo --out demo

check: $(MAYPKG)
	PWD="$(CURDIR)" $(MAYPKG) check
	PWD="$(CURDIR)" $(MAYPKG) verify

test: build
	python3 tests/test_simulation.py ./build/kaindsim
