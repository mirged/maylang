OUTPUT_FORMAT(elf64-x86-64)
ENTRY(_start)
SECTIONS {
    . = 0x100000;
    .multiboot : { KEEP(*(.multiboot)) }
    .text ALIGN(4096) : { *(.text*) }
    .rodata ALIGN(4096) : { *(.rodata*) }
    .bss ALIGN(4096) (NOLOAD) : { *(.bss*) *(COMMON) }
    . = 0x200000;
    .mailbox (NOLOAD) : { *(.mailbox) }
    . = 0x210000;
    .storage (NOLOAD) : { *(.storage) }
    /DISCARD/ : { *(.eh_frame) *(.note*) *(.comment) }
}
