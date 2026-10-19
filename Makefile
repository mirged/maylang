PYTHON ?= python3
MAYC ?= compiler/mayc/mayc_new
BUNDLE ?= /tmp/maylang-linux-x86_64.tar.gz
INSTALL_ARGS ?=
INSTALLER_OUTPUT ?= build/installer

.DEFAULT_GOAL := help
.PHONY: help doctor setup install build tools check test test-rust test-compiler test-bootstrap test-compliance test-tools test-docs test-distribution test-installer test-ui test-browser test-llvm test-limits test-all package editor

help:
	@echo 'Maylang development (Linux x86-64)'
	@echo '  make doctor             Check source build prerequisites'
	@echo '  make setup / install    Build and install a standalone user toolchain'
	@echo '    INSTALL_ARGS="--yes --prefix=/path --no-modify-path" for unattended setup'
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
	@echo '  make package            Build a bundle and standalone C/shell installers'
	@echo '  make editor             Install locked npm dependencies and compile the extension'
	@echo 'See CONTRIBUTING.md for targeted checks and docs/guide/INSTALL.md for releases.'

doctor:
	$(PYTHON) scripts/doctor.py

setup: build
	build/dev/bin/may-installer --bundle "$(CURDIR)/build/dev" $(INSTALL_ARGS)

install: setup

build: doctor
	sh compiler/rust/build.sh
	$(PYTHON) scripts/build_tools.py --compiler "$(MAYC)"

tools:
	$(PYTHON) scripts/build_tools.py --compiler "$(MAYC)"

check:
	$(PYTHON) scripts/check_repository.py
	$(PYTHON) docs/reference/generate.py --check
	$(PYTHON) tools/maylsp/docs/generate.py --check

test: check test-rust test-compiler test-compliance test-docs test-distribution

test-rust:
	cargo test --offline --locked --workspace

test-compiler:
	$(PYTHON) compiler/mayc/tests/verify.py --compiler "$(MAYC)"

test-bootstrap:
	$(PYTHON) compiler/rust/test.py

test-compliance:
	MAYC="$(abspath $(MAYC))" $(PYTHON) tests/compliance/run.py

test-tools:
	MAYC="$(abspath $(MAYC))" $(PYTHON) tools/may/tests/run.py
	MAYC="$(abspath $(MAYC))" $(PYTHON) tools/mayfmt/tests/run.py
	mkdir -p build/tests
	"$(MAYC)" tools/maypkg/main.may -o build/tests/maypkg
	$(PYTHON) tools/maypkg/tests/test_workflows.py --binary build/tests/maypkg
	$(PYTHON) tools/maylsp/tests/test_lsp.py --compiler "$(MAYC)"

test-docs:
	$(PYTHON) tests/docs/run.py --compiler "$(MAYC)"

test-distribution:
	$(PYTHON) scripts/tests/test_developer.py
	$(PYTHON) dist/tests/test_release.py
	$(PYTHON) dist/tests/test_update.py
	$(PYTHON) dist/tests/test_auto_update.py
	sh dist/tests/install.sh

test-installer: tools
	$(PYTHON) dist/tests/test_installer.py --bundle build/dev

test-ui:
	$(PYTHON) tests/ui/run.py --compiler "$(MAYC)"

test-browser:
	$(MAKE) -C platform/maybrowser check test MAYC="$(abspath $(MAYC))"

test-llvm:
	$(PYTHON) compiler/mayc/tests/llvm.py --compiler "$(MAYC)"
	$(PYTHON) compiler/mayc/tests/externs.py --compiler "$(MAYC)" --llvm
	$(PYTHON) compiler/mayc/tests/fibers.py --compiler "$(MAYC)" --llvm
	$(PYTHON) compiler/mayc/tests/debug_traces.py --compiler "$(MAYC)" --llvm
	$(PYTHON) compiler/mayc/tests/reachability.py --compiler "$(MAYC)" --llvm

test-limits:
	$(PYTHON) compiler/mayc/tests/test_limits.py
	$(PYTHON) compiler/mayc/tests/limits.py --compiler "$(MAYC)" --self-test

test-all: test test-bootstrap test-tools test-ui test-browser test-llvm

package:
	$(PYTHON) scripts/doctor.py --profile package
	$(MAKE) build
	$(PYTHON) dist/package.py --compiler "$(MAYC)" --output "$(BUNDLE)" --installer-output "$(INSTALLER_OUTPUT)"
	$(PYTHON) dist/tests/test_package.py "$(BUNDLE)"
	$(PYTHON) dist/tests/test_installer.py --archive "$(BUNDLE)" --artifacts "$(INSTALLER_OUTPUT)"

editor:
	cd editors/vscode && npm ci && npm run compile
