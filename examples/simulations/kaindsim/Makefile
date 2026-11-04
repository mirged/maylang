MAYC ?= ../../../compiler/mayc/mayc_new

.PHONY: build demo test check
build: build/kaindsim

build/kaindsim: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@

demo: build
	./build/kaindsim demo --out demo

check:
	$(MAYC) --check main.may

test: build
	python3 tests/test_simulation.py ./build/kaindsim
