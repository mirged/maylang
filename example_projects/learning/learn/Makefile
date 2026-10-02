MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/learn

build/learn: main.may
	mkdir -p build
	$(MAYC) main.may -o $@
