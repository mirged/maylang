MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/sdl_test

build/sdl_test: main.may
	mkdir -p build
	$(MAYC) main.may -o $@
