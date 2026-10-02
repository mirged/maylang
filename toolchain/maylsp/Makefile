MAYC ?= ../mayc/mayc_new

.PHONY: all build test
all: build

build:
	mkdir -p build
	$(MAYC) main.may -o build/maylsp

test: build
	python3 tests/test_lsp.py --binary "$(CURDIR)/build/maylsp"
