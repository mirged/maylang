PYTHON ?= python3
MAYC ?= toolchain/mayc/mayc_new
BUNDLE ?= /tmp/maylang-linux-x86_64.tar.gz

.DEFAULT_GOAL := help
.PHONY: help doctor setup build tools check test test-rust test-compiler test-bootstrap test-compliance test-tools test-docs test-distribution test-ui test-browser test-llvm test-limits test-all package editor

help:
	@echo 'Maylang development (Linux x86-64)'
	@echo '  make doctor             Check source build prerequisites'
	@echo '  make setup              Build all five tools and print shell setup'
	@echo '  make build              Rebuild the compiler and developer tools'
	@echo '  make tools              Rebuild tools with the selected MAYC'
	@echo '  make check              Check repository structure and reference freshness'
	@echo '  make test               Rust, compiler, compliance, docs and distribution checks'
	@echo '  make test-tools         Workspace runner, formatter, package manager and LSP'
	@echo '  make test-bootstrap     Verify compiler generation convergence'
	@echo '  make test-ui            UI checks, including X11 when available'
	@echo '  make test-browser       Browser checks (native dependencies required)'
	@echo '  make test-llvm          Experimental LLVM backend checks'
	@echo '  make test-limits        GC pressure/capacity checks and codegen reports'
	@echo '  make test-all           All local suites (optional dependencies required)'
	@echo '  make package            Build a bundle; override BUNDLE=/path/to/archive'
	@echo '  make editor             Install locked npm dependencies and compile the extension'
	@echo 'See CONTRIBUTING.md for targeted checks and docs/INSTALL.md for releases.'

doctor:
	$(PYTHON) scripts/doctor.py

setup: build
	@echo 'Enable this checkout in your current shell:'
	@echo '. "$(CURDIR)/build/dev/env.sh"'
	@echo 'Then try: may new /tmp/hello-maylang && cd /tmp/hello-maylang && may run'

build: doctor
	sh toolchain/rust/build.sh
	$(PYTHON) scripts/build_tools.py --compiler "$(MAYC)"

tools:
	$(PYTHON) scripts/build_tools.py --compiler "$(MAYC)"

check:
	$(PYTHON) scripts/check_repository.py
	$(PYTHON) reference/generate.py --check
	$(PYTHON) toolchain/maylsp/docs/generate.py --check

test: check test-rust test-compiler test-compliance test-docs test-distribution

test-rust:
	cargo test --offline --locked --workspace

test-compiler:
	$(PYTHON) toolchain/mayc/tests/verify.py --compiler "$(MAYC)"

test-bootstrap:
	$(PYTHON) toolchain/rust/test.py

test-compliance:
	MAYC="$(abspath $(MAYC))" $(PYTHON) tests/compliance/run.py

test-tools:
	MAYC="$(abspath $(MAYC))" $(PYTHON) toolchain/may/tests/run.py
	MAYC="$(abspath $(MAYC))" $(PYTHON) toolchain/mayfmt/tests/run.py
	mkdir -p build/tests
	"$(MAYC)" toolchain/maypkg/main.may -o build/tests/maypkg
	$(PYTHON) toolchain/maypkg/tests/test_workflows.py --binary build/tests/maypkg
	$(PYTHON) toolchain/maylsp/tests/test_lsp.py --compiler "$(MAYC)"

test-docs:
	$(PYTHON) toolchain/tests/documentation.py --compiler "$(MAYC)"

test-distribution:
	$(PYTHON) scripts/tests/test_developer.py
	$(PYTHON) toolchain/tests/test_release.py
	$(PYTHON) toolchain/tests/test_update.py
	sh toolchain/tests/install.sh

test-ui:
	$(PYTHON) toolchain/mayui/tests/run.py --compiler "$(MAYC)"

test-browser:
	$(MAKE) -C toolchain/maybrowser check test MAYC="$(abspath $(MAYC))"

test-llvm:
	$(PYTHON) toolchain/mayc/tests/llvm.py --compiler "$(MAYC)"
	$(PYTHON) toolchain/mayc/tests/reachability.py --compiler "$(MAYC)" --llvm

test-limits:
	$(PYTHON) toolchain/mayc/tests/test_limits.py
	$(PYTHON) toolchain/mayc/tests/limits.py --compiler "$(MAYC)" --self-test

test-all: test test-bootstrap test-tools test-ui test-browser test-llvm

package:
	$(PYTHON) scripts/doctor.py --profile package
	$(MAKE) build
	$(PYTHON) toolchain/distribution/package.py --compiler "$(MAYC)" --output "$(BUNDLE)"
	$(PYTHON) toolchain/tests/test_package.py "$(BUNDLE)"

editor:
	cd editors/vscode && npm ci && npm run compile
