/* GRUB enters this ELF image in 32-bit protected mode. Only CPU setup and port/IRQ
 * primitives live here; the monitor, console and allocator are raw Maylang. */
.section .multiboot,"a"
.balign 8
mb_header:
    .long 0xe85250d6, 0, mb_header_end - mb_header
    .long -(0xe85250d6 + (mb_header_end - mb_header))
    /* Request a VGA text console, optional if unsupported. */
    .short 4, 1
    .long 12
    .long 2
    .balign 8
    .short 0, 0
    .long 8
mb_header_end:

.section .text
.code32
.global _start
_start:
    cli
    cld
    mov $stack_top, %esp
    cmp $0x36d76289, %eax
    jne fail32
    mov %eax, mailbox + 8
    mov %ebx, mailbox + 16
    /* Find the first GRUB module: the mayc --raw ELF64 image. */
    lea 8(%ebx), %esi
    mov (%ebx), %edi
    add %ebx, %edi
find_module:
    cmp %edi, %esi
    jae fail32
    cmpl $0, (%esi)
    je fail32
    cmpl $3, (%esi)
    je got_module
    mov 4(%esi), %ecx
    cmp $8, %ecx
    jb fail32
    add $7, %ecx
    and $-8, %ecx
    add %ecx, %esi
    jmp find_module
got_module:
    mov 8(%esi), %eax
    mov %eax, mailbox + 24
    mov 12(%esi), %ecx
    sub %eax, %ecx
    mov %ecx, mailbox + 32
    cmpl $0x400000, 12(%esi)
    ja fail32
    /* Identity-map the first GiB with 512 two-MiB pages. */
    mov $pdpt, %eax
    or $3, %eax
    mov %eax, pml4
    mov $page_directory, %eax
    or $3, %eax
    mov %eax, pdpt
    xor %ecx, %ecx
map_pages:
    mov %ecx, %eax
    shl $21, %eax
    or $0x83, %eax
    mov %eax, page_directory(,%ecx,8)
    inc %ecx
    cmp $512, %ecx
    jne map_pages
    lgdt gdt_pointer
    mov %cr4, %eax
    or $0x20, %eax
    mov %eax, %cr4
    mov $pml4, %eax
    mov %eax, %cr3
    mov $0xc0000080, %ecx
    rdmsr
    or $0x100, %eax
    wrmsr
    mov %cr0, %eax
    or $0x80000000, %eax
    mov %eax, %cr0
    ljmp $8, $long_mode
fail32:
    mov $0xe9, %dx
    mov $'!', %al
    out %al, %dx
    mov $0xf4, %dx
    mov $0x7e, %eax
    out %eax, %dx
1:  hlt
    jmp 1b

.code64
long_mode:
    mov $16, %ax
    mov %ax, %ds
    mov %ax, %es
    mov %ax, %ss
    xor %eax, %eax
    mov %ax, %fs
    mov %ax, %gs
    mov $stack_top, %esp
    /* Initialise COM1 at 115200, 8N1 before any failure can occur. */
    mov $0x3f9, %dx
    out %al, %dx
    mov $0x3fb, %dx
    mov $0x80, %al
    out %al, %dx
    mov $0x3f8, %dx
    mov $1, %al
    out %al, %dx
    mov $0x3f9, %dx
    xor %eax, %eax
    out %al, %dx
    mov $0x3fb, %dx
    mov $3, %al
    out %al, %dx
    mov $0x3fa, %dx
    mov $0xc7, %al
    out %al, %dx
    mov $0x3fc, %dx
    mov $0x0b, %al
    out %al, %dx
    /* Load PT_LOAD segments at the addresses fixed by mayc. */
    mov mailbox + 24, %ebx
    cmpl $0x464c457f, (%rbx)
    jne fault
    cmpb $2, 4(%rbx)
    jne fault
    cmpb $1, 5(%rbx)
    jne fault
    cmpw $62, 18(%rbx)
    jne fault
    cmpw $56, 54(%rbx)
    jne fault
    mov 24(%rbx), %r12
    cmp $0x401000, %r12
    jne fault
    mov 32(%rbx), %r13
    movzwl 56(%rbx), %r14d
    mov %r14, %rax
    imul $56, %rax
    add %r13, %rax
    cmp mailbox + 32, %rax
    ja fault
    add %rbx, %r13
load_segment:
    test %r14, %r14
    jz segments_done
    cmpl $1, (%r13)
    jne next_segment
    mov 32(%r13), %rcx
    cmp 40(%r13), %rcx
    ja fault
    mov 8(%r13), %rsi
    mov %rsi, %rax
    add %rcx, %rax
    jc fault
    cmp mailbox + 32, %rax
    ja fault
    add %rbx, %rsi
    mov 24(%r13), %rdi
    cmp 16(%r13), %rdi
    jne fault
    cmp $0x400000, %rdi
    jb fault
    mov %rdi, %rax
    add 40(%r13), %rax
    jc fault
    cmp $0x800000, %rax
    ja fault
    rep movsb
    mov 40(%r13), %rcx
    sub 32(%r13), %rcx
    xor %eax, %eax
    rep stosb
next_segment:
    add $56, %r13
    dec %r14
    jmp load_segment
segments_done:
    /* Fixed mailbox ABI: tick counter, boot metadata and three primitives. */
    movq $port_in, mailbox + 64
    movq $port_out, mailbox + 72
    movq $cpu_idle, mailbox + 80
    movq $port_out32, mailbox + 88
    movq $port_out16, mailbox + 96
    movq $port_in16, mailbox + 104
    /* A fault gate for all vectors; override IRQ0 with the PIT handler. */
    mov $idt, %edi
    mov $256, %ecx
    mov $fault, %rax
make_gate:
    mov %ax, (%rdi)
    movw $8, 2(%rdi)
    movb $0, 4(%rdi)
    movb $0x8e, 5(%rdi)
    mov %rax, %rdx
    shr $16, %rdx
    mov %dx, 6(%rdi)
    movl $0, 8(%rdi)
    movl $0, 12(%rdi)
    add $16, %rdi
    loop make_gate
    mov $timer_irq, %rax
    mov %ax, idt + 32 * 16
    shr $16, %rax
    mov %ax, idt + 32 * 16 + 6
    lidt idt_pointer
    /* Remap the legacy PIC to vectors 32/40; unmask only PIT IRQ0. */
    mov $0x11, %al
    out %al, $0x20
    out %al, $0xa0
    mov $0x20, %al
    out %al, $0x21
    mov $0x28, %al
    out %al, $0xa1
    mov $4, %al
    out %al, $0x21
    mov $2, %al
    out %al, $0xa1
    mov $1, %al
    out %al, $0x21
    out %al, $0xa1
    mov $0xfe, %al
    out %al, $0x21
    mov $0xff, %al
    out %al, $0xa1
    /* PIT channel 0, square wave, divisor 11932 (~100 Hz). */
    mov $0x36, %al
    out %al, $0x43
    mov $0x9c, %al
    out %al, $0x40
    mov $0x2e, %al
    out %al, $0x40
    sti
    jmp *%r12

/* SysV ABI primitives. Maylang's __ccall6 intrinsic provides the bridge. */
port_in:
    mov %edi, %edx
    xor %eax, %eax
    in %dx, %al
    ret
port_out:
    mov %edi, %edx
    mov %esi, %eax
    out %al, %dx
    xor %eax, %eax
    ret
port_out32:
    mov %edi, %edx
    mov %esi, %eax
    out %eax, %dx
    xor %eax, %eax
    ret
port_out16:
    mov %edi, %edx
    mov %esi, %eax
    out %ax, %dx
    xor %eax, %eax
    ret
port_in16:
    mov %edi, %edx
    xor %eax, %eax
    in %dx, %ax
    ret
cpu_idle:
    hlt
    xor %eax, %eax
    ret
timer_irq:
    push %rax
    incq mailbox
    mov $0x20, %al
    out %al, $0x20
    pop %rax
    iretq
fault:
    cli
    mov $fault_message, %esi
fault_print:
    lodsb
    test %al, %al
    jz fault_exit
    mov $0x3f8, %dx
    out %al, %dx
    mov $0xe9, %dx
    out %al, %dx
    jmp fault_print
fault_exit:
    mov $0xf4, %dx
    mov $0x7e, %eax
    out %eax, %dx
2:  hlt
    jmp 2b

.section .rodata
.balign 8
gdt:
    .quad 0, 0x00af9a000000ffff, 0x00cf92000000ffff
gdt_end:
gdt_pointer:
    .word gdt_end - gdt - 1
    .long gdt
idt_pointer:
    .word 4095
    .quad idt
fault_message:
    .asciz "\r\nMAYOS CPU/BOOT FAULT: halted\r\n"

.section .bss
.balign 4096
pml4: .skip 4096
pdpt: .skip 4096
page_directory: .skip 4096
idt: .skip 4096
.balign 16
stack_bottom: .skip 65536
stack_top:

.section .mailbox,"aw",@nobits
.balign 4096
mailbox: .skip 4096

/* Dedicated filesystem buffers, independent of the interactive heap. */
.section .storage,"aw",@nobits
.balign 4096
.skip 32768

.section .note.GNU-stack,"",@progbits
