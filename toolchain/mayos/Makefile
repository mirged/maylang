MAYC ?= ../mayc/mayc_new
MAYPKG ?= build/maypkg
QEMU ?= qemu-system-x86_64
AS ?= as
LD ?= ld
DISK ?= data/disk.img
QEMU_FLAGS = -machine pc,accel=tcg -m 64M -cdrom build/mayos.iso -drive file=$(DISK),format=raw,if=ide,index=0 -boot d -no-reboot -device isa-debug-exit,iobase=0xf4,iosize=0x04

.PHONY: build run gui test check clean
build: build/mayos.iso

build/kernel.elf: main.may $(wildcard src/*.may) $(MAYC) tools/mayc Makefile mayproj.json $(MAYPKG)
	mkdir -p build
	chmod +x tools/mayc
	PWD="$(CURDIR)" $(MAYPKG) build --force --script
	MAYOS_COMPILER="$(abspath $(MAYC))" PATH="$(CURDIR)/tools:$$PATH" sh build/maypkg.build.sh
	PWD="$(CURDIR)" $(MAYPKG) lock

build/maypkg: ../maypkg/main.may ../maypkg/src/*.may
	mkdir -p build
	$(MAYC) ../maypkg/main.may -o $@

build/boot.o: boot/boot.S
	mkdir -p build
	$(AS) --64 $< -o $@

build/loader.elf: build/boot.o boot/boot.ld
	$(LD) -m elf_x86_64 -T boot/boot.ld build/boot.o -o $@
	grub-file --is-x86-multiboot2 $@

build/mayos.iso: build/kernel.elf build/loader.elf boot/grub.cfg
	mkdir -p build/iso/boot/grub
	cp build/kernel.elf build/loader.elf build/iso/boot/
	cp boot/grub.cfg build/iso/boot/grub/grub.cfg
	grub-mkrescue -o $@ build/iso > build/grub.log 2>&1

$(DISK): tools/create_disk.py
	python3 tools/create_disk.py "$@"

run: build $(DISK)
	@$(QEMU) $(QEMU_FLAGS) -display none -serial stdio -monitor none; code=$$?; test $$code -eq 33

gui: build $(DISK)
	@$(QEMU) $(QEMU_FLAGS) -serial stdio -monitor none; code=$$?; test $$code -eq 33

test: build
	python3 tests/test_boot.py --qemu "$(QEMU)" --iso build/mayos.iso

check: build
	PWD="$(CURDIR)" $(MAYPKG) check
	PWD="$(CURDIR)" $(MAYPKG) verify

clean:
	python3 -c "import shutil; shutil.rmtree('build', ignore_errors=True)"
