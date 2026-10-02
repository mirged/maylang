MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: build
build: build/textstats

build/textstats: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@
