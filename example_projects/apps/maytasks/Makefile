MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/maytasks

build/maytasks: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@
