MAYC ?= ../../../compiler/mayc/mayc_new
MAYPKG ?= build/maypkg

.PHONY: build demo test check
build: $(MAYPKG)
	mkdir -p build
	PWD="$(CURDIR)" PATH="$(abspath ../../../compiler/mayc):$$PATH" $(MAYPKG) build --force --script
	PATH="$(abspath ../../../compiler/mayc):$$PATH" sh build/maypkg.build.sh
	PWD="$(CURDIR)" $(MAYPKG) lock

build/maypkg: ../../../tools/maypkg/main.may ../../../tools/maypkg/src/*.may ../../../tools/shared/*.may
	mkdir -p build
	$(MAYC) ../../../tools/maypkg/main.may -o $@

demo: build
	./build/kaindsim demo --out demo

check: $(MAYPKG)
	PWD="$(CURDIR)" $(MAYPKG) check
	PWD="$(CURDIR)" $(MAYPKG) verify

test: build
	python3 tests/test_simulation.py ./build/kaindsim
