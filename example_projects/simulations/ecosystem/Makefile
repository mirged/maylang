MAYC ?= ../../../toolchain/mayc/mayc_new

.PHONY: all build test demo experiment
all: build
build: build/ecosystem

build/ecosystem: main.may $(wildcard src/*.may)
	mkdir -p build
	$(MAYC) main.may -o $@

test: build
	$(MAYC) tests/domain.may -o /tmp/maylang-ecosystem-domain-tests
	/tmp/maylang-ecosystem-domain-tests
	python3 tests/test_simulation.py --binary "$(CURDIR)/build/ecosystem"

demo: build
	./build/ecosystem demo --out results/demo

experiment: build
	./build/ecosystem run --generations 100000 --out results/seed42-100000
