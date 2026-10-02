MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/starfall

build/starfall: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@
