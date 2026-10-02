//! A conservative, non-moving mark-sweep garbage collector for the native
//! runtime.
//!
//! Every allocation carries a 32-byte header:
//!
//! ```text
//! [0]  size      : total block size in bytes (8-aligned, >= 32)
//! [8]  meta      : (MAGIC << 16) | (free << 9) | (mark << 8) | kind
//! [16] next_all  : intrusive list of live (allocated) blocks
//! [24] next_free : free-list link (address-ordered, coalesced)
//! ```
//!
//! The allocator is a first-fit free-list allocator that splits and coalesces
//! blocks; blocks are never moved, so tagged pointers stay valid. When the free
//! list cannot satisfy a request the bump pointer is used, and when the heap is
//! exhausted a collection runs. The collector is conservative about roots —
//! machine registers, the native stack and the data segment are scanned for
//! words that look like tagged heap pointers — but precise when tracing, because
//! each block's `kind` says where its children live.
//!
//! After marking, the sweep rebuilds the free list by walking the heap
//! physically, coalescing adjacent free runs, and rewinds the bump pointer past
//! the last live block, reclaiming the tail.
//!
//! Allocator entry points (all take the payload size in `RDI`):
//!
//! * `rt_alloc`         raw bytes, no traced children
//! * `rt_alloc_str`     string `{ len, bytes }`
//! * `rt_alloc_array`   array of tagged values
//! * `rt_alloc_list`    list/map header `{ count, cap, data }`
//! * `rt_alloc_float`   boxed `f64`
//! * `rt_alloc_closure` closure object `{ -1, code, nup, upvals... }`
//! * `rt_alloc_cell`    captured-variable cell `{ value }`

use crate::x86::*;
use crate::Target;

/// GC header size in bytes.
pub const HEADER: i32 = 32;
const MAGIC: i64 = 0x4D41_594C_414E; // "MAYLAN" (48 bits)
const MARK_BIT: i32 = 1 << 8;
const FREE_BIT: i32 = 1 << 9;
/// Promoted to the old generation (survived a minor collection).
const OLD_BIT: i32 = 1 << 10;
const KIND_MASK: i32 = 0xFF;

/// Object kinds understood by the tracer.
pub const KIND_RAW: i64 = 0;
const KIND_STR: i64 = 1;
const KIND_ARRAY: i64 = 2;
const KIND_LIST: i64 = 3;
const KIND_CELL: i64 = 4;
const KIND_CLOSURE: i64 = 5;
const KIND_FLOAT: i64 = 6;

/// Bytes reserved for the mark worklist (8 M pointers).
pub const MARK_STACK_BYTES: usize = 1 << 23;

/// Intrusive live-list link offset.
const NEXT_ALL: i32 = 16;
/// Free-list link offset.
const NEXT_FREE: i32 = 24;
/// Do not create free remainders smaller than this.
const MIN_SPLIT: i64 = 64;

/// Offsets of the collector's globals, resolved by the code generator.
#[derive(Clone)]
pub struct GcData {
    pub data_begin: usize,
    pub data_end: usize,
    pub heap_start: usize,
    pub heap_ptr: usize,
    pub all_head: usize,
    pub mark_sp: usize,
    pub gc_busy: usize,
    pub free_heads: usize,
    pub gc_regs: usize,
    /// `argc` captured at process entry.
    pub argc: usize,
    /// `argv` base pointer captured at process entry.
    pub argv: usize,
    /// Upper bound of the current stack (main stack top, or a fiber's top).
    pub cur_stack_hi: usize,
    /// Number of live fiber slots.
    pub fib_count: usize,
    /// 1 while running a minor (young-generation-only) collection.
    pub gc_minor: usize,
}

fn data_addr(asm: &mut Asm, reg: Reg, off: usize) {
    asm.mov_reg_abs(reg, AbsRef::Data(off));
}

fn mark_stack_addr(asm: &mut Asm, reg: Reg) {
    asm.mov_reg_abs(reg, AbsRef::DataSym("mark_stack".to_string()));
}

/// Emit the allocator and the collector.
pub fn emit(
    asm: &mut Asm,
    target: Target,
    gc: &GcData,
    heap_ptr_slot: usize,
    heap_end_slot: usize,
) {
    emit_allocator(asm, target, gc, heap_ptr_slot, heap_end_slot);
    emit_collector(asm, target, gc, heap_end_slot);
}

fn emit_allocator(
    asm: &mut Asm,
    target: Target,
    gc: &GcData,
    heap_ptr_slot: usize,
    heap_end_slot: usize,
) {
    // ----- typed entry points -------------------------------------------
    let wrappers: [(&str, i64); 5] = [
        ("rt_alloc_str", KIND_STR),
        ("rt_alloc_array", KIND_ARRAY),
        ("rt_alloc_list", KIND_LIST),
        ("rt_alloc_float", KIND_FLOAT),
        ("rt_alloc_closure", KIND_CLOSURE),
    ];
    for (name, kind) in wrappers {
        asm.bind_symbol(name);
        asm.mov_reg_imm64(RSI, kind);
        asm.jmp_sym("rt_alloc_core");
    }
    // `rt_alloc` keeps its old signature: raw, untraced bytes.
    asm.bind_symbol("rt_alloc");
    asm.xor_rr(RSI, RSI);
    asm.jmp_sym("rt_alloc_core");

    // `rt_alloc_cell`: rdi = value -> cell object containing it.
    asm.bind_symbol("rt_alloc_cell");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_imm64(RDI, 8);
    asm.mov_reg_imm64(RSI, KIND_CELL);
    asm.call_sym("rt_alloc_core");
    asm.mov_reg_mem(RCX, RBP, -8);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // ----- core allocator -------------------------------------------------
    // rdi = payload bytes, rsi = kind.
    asm.bind_symbol("rt_alloc_core");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_mem_reg(RBP, -8, RDI); // payload
    asm.mov_mem_reg(RBP, -16, RSI); // kind
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -56, RAX); // "already collected" flag
    // total = align8(payload + HEADER)
    asm.add_imm32(RDI, HEADER);
    asm.add_imm32(RDI, 7);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -24, RDI); // total

    let retry = asm.new_label();
    let search = asm.new_label();
    let found = asm.new_label();
    let nosplit = asm.new_label();
    let nosplit_head = asm.new_label();
    let nosplit_done = asm.new_label();
    let split_head = asm.new_label();
    let split_done = asm.new_label();
    let bump = asm.new_label();
    let need_gc = asm.new_label();
    let oom = asm.new_label();
    let link_live = asm.new_label();

    asm.bind(retry);
    data_addr(asm, R11, gc.free_heads);
    asm.mov_reg_mem(R8, R11, 0); // cur
    asm.xor_rr(R9, R9); // prev
    asm.bind(search);
    asm.test_rr(R8, R8);
    asm.jcc(CC_E, bump);
    asm.mov_reg_mem(RAX, R8, 0); // size
    asm.mov_reg_mem(RDX, RBP, -24); // total
    asm.cmp_rr(RAX, RDX);
    asm.jcc(CC_AE, found);
    asm.mov_reg_reg(R9, R8);
    asm.mov_reg_mem(R8, R8, NEXT_FREE);
    asm.jmp(search);

    asm.bind(found);
    // remainder = size - total
    asm.mov_reg_reg(RCX, RAX);
    asm.sub_rr(RCX, RDX);
    asm.mov_reg_imm64(R11, MIN_SPLIT);
    asm.cmp_rr(RCX, R11);
    asm.jcc(CC_B, nosplit);
    // split: carve `total` off the front, leave `remainder` free.
    asm.mov_reg_reg(R10, R8);
    asm.add_rr(R10, RDX); // remainder block
    asm.mov_mem_reg(R10, 0, RCX);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.shl_imm(R11, 16);
    asm.mov_reg_imm64(RAX, (FREE_BIT | KIND_RAW as i32) as i64);
    asm.or_rr(R11, RAX);
    asm.mov_mem_reg(R10, 8, R11);
    asm.mov_reg_mem(R11, R8, NEXT_FREE);
    asm.mov_mem_reg(R10, NEXT_FREE, R11);
    asm.test_rr(R9, R9);
    asm.jcc(CC_E, split_head);
    asm.mov_mem_reg(R9, NEXT_FREE, R10);
    asm.jmp(split_done);
    asm.bind(split_head);
    data_addr(asm, R11, gc.free_heads);
    asm.mov_mem_reg(R11, 0, R10);
    asm.bind(split_done);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.mov_mem_reg(R8, 0, RDX);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.shl_imm(R11, 16);
    asm.or_rr(RCX, R11);
    asm.mov_mem_reg(R8, 8, RCX);
    asm.mov_reg_imm64(R11, 0);
    asm.mov_mem_reg(R8, NEXT_FREE, R11);
    asm.mov_reg_reg(RAX, R8);
    asm.jmp(link_live);

    asm.bind(nosplit);
    asm.mov_reg_mem(R10, R8, NEXT_FREE);
    asm.test_rr(R9, R9);
    asm.jcc(CC_E, nosplit_head);
    asm.mov_mem_reg(R9, NEXT_FREE, R10);
    asm.jmp(nosplit_done);
    asm.bind(nosplit_head);
    data_addr(asm, R11, gc.free_heads);
    asm.mov_mem_reg(R11, 0, R10);
    asm.bind(nosplit_done);
    // Keep the block's full size: shrinking it would leave a gap that the
    // physical heap walk mistakes for part of the next block.
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.shl_imm(R11, 16);
    asm.or_rr(RCX, R11);
    asm.mov_mem_reg(R8, 8, RCX);
    asm.mov_reg_imm64(R11, 0);
    asm.mov_mem_reg(R8, NEXT_FREE, R11);
    asm.mov_reg_reg(RAX, R8);
    asm.jmp(link_live);

    asm.bind(bump);
    data_addr(asm, R11, heap_ptr_slot);
    asm.mov_reg_mem(RAX, R11, 0); // block
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.mov_reg_reg(R10, RAX);
    asm.add_rr(R10, RDX); // new heap_ptr
    data_addr(asm, R11, heap_end_slot);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.cmp_rr(R10, RCX);
    asm.jcc(CC_A, need_gc);
    data_addr(asm, R11, heap_ptr_slot);
    asm.mov_mem_reg(R11, 0, R10);
    asm.mov_mem_reg(RAX, 0, RDX);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.shl_imm(R11, 16);
    asm.or_rr(RCX, R11);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_reg_imm64(R11, 0);
    asm.mov_mem_reg(RAX, NEXT_FREE, R11);
    asm.jmp(link_live);

    asm.bind(need_gc);
    data_addr(asm, R11, gc.gc_busy);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, oom);
    // Collection phase: 0 -> try a minor (young-only) collection first, then
    // 1 -> a major (full) collection; 2 means the live set does not fit.
    asm.mov_reg_mem(RCX, RBP, -56);
    asm.cmp_imm32(RCX, 2);
    asm.jcc(CC_AE, oom);
    asm.add_imm32(RCX, 1);
    asm.mov_mem_reg(RBP, -56, RCX);
    // gc_minor = (phase == 1)
    asm.xor_rr(RAX, RAX);
    asm.cmp_imm32(RCX, 1);
    let not_minor = asm.new_label();
    asm.jcc(CC_NE, not_minor);
    asm.mov_reg_imm64(RAX, 1);
    asm.bind(not_minor);
    data_addr(asm, R11, gc.gc_minor);
    asm.mov_mem_reg(R11, 0, RAX);
    // gc_busy = 1; run the collector.
    data_addr(asm, R11, gc.gc_busy);
    asm.mov_reg_imm64(RCX, 1);
    asm.mov_mem_reg(R11, 0, RCX);
    asm.call_sym("gc");
    data_addr(asm, R11, gc.gc_busy);
    asm.mov_reg_imm64(RCX, 0);
    asm.mov_mem_reg(R11, 0, RCX);
    asm.jmp(retry);

    asm.bind(oom);
    asm.mov_reg_imm64(RAX, target.exit_nr());
    asm.mov_reg_imm64(RDI, 70);
    asm.syscall();

    asm.bind(link_live);
    data_addr(asm, R11, gc.all_head);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.mov_mem_reg(RAX, NEXT_ALL, RCX);
    asm.mov_mem_reg(R11, 0, RAX);
    asm.add_imm32(RAX, HEADER);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_collector(asm: &mut Asm, target: Target, gc: &GcData, heap_end_slot: usize) {
    // ----- gc -------------------------------------------------------------
    asm.bind_symbol("gc");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    // Save every GPR so conservative register scanning sees live pointers.
    data_addr(asm, R11, gc.gc_regs);
    let gprs: [Reg; 16] = [
        RAX, RBX, RCX, RDX, RSI, RDI, RBP, RSP, R8, R9, R10, R11, R12, R13, R14, R15,
    ];
    for (i, reg) in gprs.iter().enumerate() {
        asm.mov_mem_reg(R11, (i * 8) as i32, *reg);
    }
    // mark_sp = 0
    data_addr(asm, R11, gc.mark_sp);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(R11, 0, RAX);

    // roots: saved registers
    data_addr(asm, RBX, gc.gc_regs);
    asm.mov_reg_imm64(R12, 16);
    let reg_loop = asm.new_label();
    let reg_done = asm.new_label();
    asm.bind(reg_loop);
    asm.test_rr(R12, R12);
    asm.jcc(CC_E, reg_done);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.sub_imm32(R12, 1);
    asm.jmp(reg_loop);
    asm.bind(reg_done);

    // roots: the machine stack, from this frame to the current stack top (the
    // main stack, or the running fiber's stack).
    asm.mov_reg_reg(RBX, RBP);
    data_addr(asm, R12, gc.cur_stack_hi);
    asm.mov_reg_mem(R12, R12, 0);
    let stack_loop = asm.new_label();
    let stack_done = asm.new_label();
    asm.bind(stack_loop);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, stack_done);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.jmp(stack_loop);
    asm.bind(stack_done);

    // roots: the data segment (globals and inline string data).
    data_addr(asm, RBX, gc.data_begin);
    asm.mov_reg_mem(RBX, RBX, 0);
    data_addr(asm, R12, gc.data_end);
    asm.mov_reg_mem(R12, R12, 0);
    let data_loop = asm.new_label();
    let data_done = asm.new_label();
    asm.bind(data_loop);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, data_done);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.jmp(data_loop);
    asm.bind(data_done);

    // roots: suspended fiber stacks. The running fiber is covered by the
    // machine-stack scan above; ready (state 1) fibers are scanned here.
    data_addr(asm, R11, gc.fib_count);
    asm.mov_reg_mem(R13, R11, 0); // count (R13 survives maybe_mark_tagged)
    asm.mov_reg_imm64(R9, 1); // index
    let fib_loop = asm.new_label();
    let fib_next = asm.new_label();
    let fib_done = asm.new_label();
    let fib_inner = asm.new_label();
    asm.bind(fib_loop);
    asm.cmp_rr(R9, R13);
    asm.jcc(CC_AE, fib_done);
    asm.mov_reg_reg(RDX, R9);
    asm.shl_imm(RDX, 6);
    asm.mov_reg_abs(R11, AbsRef::DataSym("fib_table".to_string()));
    asm.add_rr(RDX, R11);
    asm.mov_reg_mem(RAX, RDX, 0);
    asm.cmp_imm32(RAX, 1);
    asm.jcc(CC_NE, fib_next);
    asm.mov_reg_mem(RBX, RDX, 8); // rsp
    asm.mov_reg_mem(R12, RDX, 24); // stack_hi
    asm.bind(fib_inner);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, fib_next);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.jmp(fib_inner);
    asm.bind(fib_next);
    asm.add_imm32(R9, 1);
    asm.jmp(fib_loop);
    asm.bind(fib_done);

    asm.call_sym("gc_trace");
    asm.call_sym("gc_sweep");

    // Restore callee-saved registers (RBX, R12-R15); rbp is restored by frame.
    data_addr(asm, R11, gc.gc_regs);
    asm.mov_reg_mem(RBX, R11, 8);
    asm.mov_reg_mem(R12, R11, 96);
    asm.mov_reg_mem(R13, R11, 104);
    asm.mov_reg_mem(R14, R11, 112);
    asm.mov_reg_mem(R15, R11, 120);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // ----- maybe_mark_tagged(rax = tagged word) ---------------------------
    asm.bind_symbol("maybe_mark_tagged");
    asm.mov_reg_reg(RCX, RAX);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RCX, R11);
    let mt_mark = asm.new_label();
    asm.cmp_imm32(RCX, 1);
    asm.jcc(CC_E, mt_mark);
    asm.cmp_imm32(RCX, 5);
    asm.jcc(CC_E, mt_mark);
    asm.cmp_imm32(RCX, 6);
    asm.jcc(CC_E, mt_mark);
    asm.cmp_imm32(RCX, 7);
    asm.jcc(CC_E, mt_mark);
    asm.ret();
    asm.bind(mt_mark);
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.jmp_sym("mark_ptr");

    // ----- mark_ptr(rdi = object pointer) ---------------------------------
    asm.bind_symbol("mark_ptr");
    asm.mov_reg_reg(RAX, RDI);
    asm.sub_imm32(RAX, HEADER); // block
    data_addr(asm, R11, gc.heap_start);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.cmp_rr(RAX, RCX);
    let mp_skip = asm.new_label();
    asm.jcc(CC_B, mp_skip);
    data_addr(asm, R11, heap_end_slot);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_AE, mp_skip);
    asm.mov_reg_mem(RDX, RAX, 8); // meta
    asm.mov_reg_reg(RCX, RDX);
    asm.shr_imm(RCX, 16);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.cmp_rr(RCX, R11);
    asm.jcc(CC_NE, mp_skip);
    asm.mov_reg_imm64(RCX, FREE_BIT as i64);
    asm.test_rr(RDX, RCX);
    asm.jcc(CC_NE, mp_skip);
    asm.mov_reg_imm64(RCX, MARK_BIT as i64);
    asm.test_rr(RDX, RCX);
    asm.jcc(CC_NE, mp_skip);
    asm.or_rr(RDX, RCX);
    asm.mov_mem_reg(RAX, 8, RDX);
    // push rdi onto the mark stack
    data_addr(asm, R11, gc.mark_sp);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.mov_reg_imm64(RDX, (MARK_STACK_BYTES - 8) as i64);
    asm.cmp_rr(RCX, RDX);
    let mp_ok = asm.new_label();
    asm.jcc(CC_B, mp_ok);
    asm.mov_reg_imm64(RAX, target.exit_nr());
    asm.mov_reg_imm64(RDI, 70);
    asm.syscall();
    asm.bind(mp_ok);
    mark_stack_addr(asm, R11);
    asm.add_rr(R11, RCX);
    asm.mov_mem_reg(R11, 0, RDI);
    data_addr(asm, R11, gc.mark_sp);
    asm.add_imm32(RCX, 8);
    asm.mov_mem_reg(R11, 0, RCX);
    asm.bind(mp_skip);
    asm.ret();

    // ----- gc_trace: drain the worklist -----------------------------------
    asm.bind_symbol("gc_trace");
    let tr_loop = asm.new_label();
    let tr_done = asm.new_label();
    asm.bind(tr_loop);
    data_addr(asm, R11, gc.mark_sp);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, tr_done);
    asm.sub_imm32(RCX, 8);
    asm.mov_mem_reg(R11, 0, RCX);
    mark_stack_addr(asm, R11);
    asm.add_rr(R11, RCX);
    asm.mov_reg_mem(RDI, R11, 0);
    asm.call_sym("trace_block");
    asm.jmp(tr_loop);
    asm.bind(tr_done);
    asm.ret();

    // ----- trace_block(rdi = object pointer) ------------------------------
    asm.bind_symbol("trace_block");
    asm.push(RBP);
    asm.push(RBX);
    asm.push(R12);
    asm.mov_reg_reg(RBP, RSP);
    asm.mov_reg_reg(RAX, RDI);
    asm.sub_imm32(RAX, HEADER);
    asm.mov_reg_mem(RCX, RAX, 8);
    asm.mov_reg_imm64(R11, KIND_MASK as i64);
    asm.and_rr(RCX, R11);
    let tb_array = asm.new_label();
    let tb_list = asm.new_label();
    let tb_cell = asm.new_label();
    let tb_closure = asm.new_label();
    let tb_done = asm.new_label();
    asm.cmp_imm32(RCX, KIND_ARRAY as i32);
    asm.jcc(CC_E, tb_array);
    asm.cmp_imm32(RCX, KIND_LIST as i32);
    asm.jcc(CC_E, tb_list);
    asm.cmp_imm32(RCX, KIND_CELL as i32);
    asm.jcc(CC_E, tb_cell);
    asm.cmp_imm32(RCX, KIND_CLOSURE as i32);
    asm.jcc(CC_E, tb_closure);
    asm.jmp(tb_done);

    // array: scan the whole payload conservatively (stale tail words are zero
    // or old tagged values, which mark_ptr validates before use).
    asm.bind(tb_array);
    asm.mov_reg_mem(RDX, RAX, 0); // block size
    asm.sub_imm32(RDX, HEADER); // payload bytes
    asm.mov_reg_reg(RBX, RDI);
    asm.mov_reg_reg(R12, RDI);
    asm.add_rr(R12, RDX);
    let arr_loop = asm.new_label();
    asm.bind(arr_loop);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, tb_done);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.jmp(arr_loop);

    // list / map header: keep the backing array alive but trace only its live
    // prefix (`count` entries). Scanning the whole payload would treat stale
    // values in unused capacity as roots and retain dead objects forever.
    asm.bind(tb_list);
    asm.mov_reg_mem(RCX, RDI, 0); // count (also 2*slots for maps)
    asm.mov_reg_mem(RDX, RDI, 16); // backing array payload pointer
    // Mark the backing array block without enqueuing it, so its own (whole
    // payload) array tracer never runs for a container.
    asm.mov_reg_reg(RAX, RDX);
    asm.sub_imm32(RAX, HEADER); // block address
    data_addr(asm, R11, gc.heap_start);
    asm.mov_reg_mem(R8, R11, 0);
    asm.cmp_rr(RAX, R8);
    asm.jcc(CC_B, tb_done);
    data_addr(asm, R11, heap_end_slot);
    asm.mov_reg_mem(R8, R11, 0);
    asm.cmp_rr(RAX, R8);
    asm.jcc(CC_AE, tb_done);
    asm.mov_reg_mem(R8, RAX, 8); // meta
    asm.mov_reg_reg(R9, R8);
    asm.shr_imm(R9, 16);
    asm.mov_reg_imm64(R11, MAGIC);
    asm.cmp_rr(R9, R11);
    asm.jcc(CC_NE, tb_done);
    asm.mov_reg_imm64(R11, FREE_BIT as i64);
    asm.test_rr(R8, R11);
    asm.jcc(CC_NE, tb_done);
    asm.mov_reg_imm64(R11, MARK_BIT as i64);
    asm.test_rr(R8, R11);
    let ld_marked = asm.new_label();
    asm.jcc(CC_NE, ld_marked);
    asm.or_rr(R8, R11);
    asm.mov_mem_reg(RAX, 8, R8);
    asm.bind(ld_marked);
    // Scan the first `count` tagged words.
    asm.mov_reg_reg(RBX, RDX);
    asm.mov_reg_reg(R12, RCX);
    asm.shl_imm(R12, 3);
    asm.add_rr(R12, RDX);
    let ld_loop = asm.new_label();
    asm.bind(ld_loop);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, tb_done);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.add_imm32(RBX, 8);
    asm.jmp(ld_loop);

    // cell: trace the captured value.
    asm.bind(tb_cell);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.call_sym("maybe_mark_tagged");
    asm.jmp(tb_done);

    // closure: trace each upvalue cell.
    asm.bind(tb_closure);
    asm.mov_reg_mem(RBX, RDI, 16); // nup
    asm.mov_reg_reg(R12, RDI);
    asm.add_imm32(R12, 24);
    let cl_loop = asm.new_label();
    asm.bind(cl_loop);
    asm.test_rr(RBX, RBX);
    asm.jcc(CC_E, tb_done);
    asm.mov_reg_mem(RDI, R12, 0);
    asm.call_sym("mark_ptr");
    asm.add_imm32(R12, 8);
    asm.sub_imm32(RBX, 1);
    asm.jmp(cl_loop);

    asm.bind(tb_done);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(R12);
    asm.pop(RBX);
    asm.pop(RBP);
    asm.ret();

    // ----- gc_sweep -------------------------------------------------------
    // Pass 1: keep marked blocks in the live list, mark the rest free, and
    // remember the highest live address. Pass 2: walk the heap physically,
    // coalesce adjacent free runs into a fresh (address-ordered) free list, and
    // rewind the bump pointer past the last live block.
    asm.bind_symbol("gc_sweep");
    data_addr(asm, R11, gc.gc_minor);
    asm.mov_reg_mem(R15, R11, 0); // minor flag (R15 is free during a GC)
    data_addr(asm, R11, gc.all_head);
    asm.mov_reg_mem(RBX, R11, 0);
    asm.xor_rr(R13, R13); // new live list head
    asm.xor_rr(R14, R14); // highest live end
    let sw_loop = asm.new_label();
    let sw_done = asm.new_label();
    let sw_keep = asm.new_label();
    let sw_free = asm.new_label();
    let sw_next = asm.new_label();
    let sw_noend = asm.new_label();
    let sw_hb_ok = asm.new_label();
    let sw_no_reset = asm.new_label();
    asm.bind(sw_loop);
    asm.test_rr(RBX, RBX);
    asm.jcc(CC_E, sw_done);
    asm.mov_reg_mem(R12, RBX, NEXT_ALL);
    asm.mov_reg_mem(RDX, RBX, 8); // meta
    asm.mov_reg_imm64(RCX, MARK_BIT as i64);
    asm.test_rr(RDX, RCX);
    asm.jcc(CC_NE, sw_keep);
    // Unmarked. During a minor collection the old generation is retained, so
    // an unmarked *old* block survives (only young garbage is reclaimed).
    asm.test_rr(R15, R15);
    asm.jcc(CC_E, sw_free);
    asm.mov_reg_imm64(RCX, OLD_BIT as i64);
    asm.test_rr(RDX, RCX);
    asm.jcc(CC_NE, sw_keep);
    asm.bind(sw_free);
    // free: clear kind/mark/free/old, set free + RAW kind
    asm.mov_reg_imm64(
        RCX,
        !((KIND_MASK | MARK_BIT | FREE_BIT | OLD_BIT) as i64),
    );
    asm.and_rr(RDX, RCX);
    asm.mov_reg_imm64(RCX, (FREE_BIT | KIND_RAW as i32) as i64);
    asm.or_rr(RDX, RCX);
    asm.mov_mem_reg(RBX, 8, RDX);
    asm.jmp(sw_next);
    asm.bind(sw_keep);
    // Survives: clear the mark and promote to the old generation.
    asm.mov_reg_imm64(RCX, MARK_BIT as i64);
    asm.not(RCX);
    asm.and_rr(RDX, RCX);
    asm.mov_reg_imm64(RCX, OLD_BIT as i64);
    asm.or_rr(RDX, RCX);
    asm.mov_mem_reg(RBX, 8, RDX);
    asm.mov_mem_reg(RBX, NEXT_ALL, R13);
    asm.mov_reg_reg(R13, RBX);
    asm.mov_reg_mem(RAX, RBX, 0); // size
    asm.add_rr(RAX, RBX);
    asm.cmp_rr(RAX, R14);
    asm.jcc(CC_BE, sw_noend);
    asm.mov_reg_reg(R14, RAX);
    asm.bind(sw_noend);
    asm.jmp(sw_next);
    asm.bind(sw_next);
    asm.mov_reg_reg(RBX, R12);
    asm.jmp(sw_loop);
    asm.bind(sw_done);
    data_addr(asm, R11, gc.all_head);
    asm.mov_mem_reg(R11, 0, R13);

    // heap_ptr = max(highest live end, heap_start)
    data_addr(asm, R11, gc.heap_start);
    asm.mov_reg_mem(RDX, R11, 0);
    asm.cmp_rr(R14, RDX);
    asm.jcc(CC_AE, sw_hb_ok);
    asm.mov_reg_reg(R14, RDX);
    asm.bind(sw_hb_ok);
    data_addr(asm, R11, gc.heap_ptr);
    asm.mov_reg_mem(RCX, R11, 0); // old heap_ptr
    asm.cmp_rr(R14, RCX);
    asm.jcc(CC_AE, sw_no_reset);
    asm.mov_mem_reg(R11, 0, R14);
    asm.bind(sw_no_reset);

    // pass 2: physical walk
    data_addr(asm, R11, gc.free_heads);
    asm.mov_reg_imm64(RCX, 0);
    asm.mov_mem_reg(R11, 0, RCX);
    asm.xor_rr(R9, R9); // run start
    asm.xor_rr(R10, R10); // run size
    data_addr(asm, R11, gc.heap_start);
    asm.mov_reg_mem(RBX, R11, 0); // p
    data_addr(asm, R11, gc.heap_ptr);
    asm.mov_reg_mem(R12, R11, 0); // heap_ptr
    let walk = asm.new_label();
    let walk_done = asm.new_label();
    let walk_free = asm.new_label();
    let walk_free_add = asm.new_label();
    let walk_live = asm.new_label();
    let walk_finish = asm.new_label();
    asm.bind(walk);
    asm.cmp_rr(RBX, R12);
    asm.jcc(CC_AE, walk_done);
    asm.mov_reg_mem(RAX, RBX, 0); // size
    asm.mov_reg_mem(RDX, RBX, 8); // meta
    asm.mov_reg_imm64(RCX, FREE_BIT as i64);
    asm.test_rr(RDX, RCX);
    asm.jcc(CC_NE, walk_free);
    // live block: flush any pending run first
    asm.test_rr(R9, R9);
    asm.jcc(CC_E, walk_live);
    asm.call_sym("gc_link_free");
    asm.xor_rr(R9, R9);
    asm.xor_rr(R10, R10);
    asm.mov_reg_mem(RAX, RBX, 0);
    asm.bind(walk_live);
    asm.add_rr(RBX, RAX);
    asm.jmp(walk);
    asm.bind(walk_free);
    asm.test_rr(R9, R9);
    asm.jcc(CC_NE, walk_free_add);
    asm.mov_reg_reg(R9, RBX);
    asm.bind(walk_free_add);
    asm.add_rr(R10, RAX);
    asm.add_rr(RBX, RAX);
    asm.jmp(walk);
    asm.bind(walk_done);
    asm.test_rr(R9, R9);
    asm.jcc(CC_E, walk_finish);
    asm.call_sym("gc_link_free");
    asm.bind(walk_finish);
    asm.ret();

    // gc_link_free: r9 = block, r10 = size. Pushes onto the free list.
    asm.bind_symbol("gc_link_free");
    asm.mov_mem_reg(R9, 0, R10);
    asm.mov_reg_imm64(RAX, MAGIC);
    asm.shl_imm(RAX, 16);
    asm.mov_reg_imm64(RCX, (FREE_BIT | KIND_RAW as i32) as i64);
    asm.or_rr(RAX, RCX);
    asm.mov_mem_reg(R9, 8, RAX);
    data_addr(asm, R11, gc.free_heads);
    asm.mov_reg_mem(RCX, R11, 0);
    asm.mov_mem_reg(R9, NEXT_FREE, RCX);
    asm.mov_mem_reg(R11, 0, R9);
    asm.ret();
}
