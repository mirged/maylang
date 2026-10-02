MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/study

build/study: main.may
	mkdir -p build
	$(MAYC) main.may -o $@
