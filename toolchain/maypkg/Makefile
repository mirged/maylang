MAYC ?= ../mayc/mayc_new

.PHONY: build
build: build/maypkg

build/maypkg: main.may $(wildcard src/*.may) $(MAYC)
	mkdir -p build
	$(MAYC) main.may -o $@
