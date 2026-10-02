//! Cooperative fibers: user-space green threads with their own stacks, a
//! round-robin scheduler and a machine-code context switch.
//!
//! A fixed table of fiber records lives in BSS. Each record is 64 bytes:
//!
//! ```text
//! [0]  state     : 0 free, 1 ready, 2 done, 3 running
//! [8]  rsp       : saved stack pointer
//! [16] stack_lo  : mmap base
//! [24] stack_hi  : mmap end (exclusive); also the stack-scan upper bound
//! [32] fn        : tagged first-class function value
//! ```
//!
//! Slot 0 is reserved for the scheduler (the main stack). `spawn(f)` maps a
//! fresh stack, `run()` drains ready fibers, and `yield()` returns control to
//! the scheduler. The collector scans every suspended fiber's stack.

use crate::x86::*;
use crate::Target;

const MAX_SLOTS: i32 = 65;
const STACK_SIZE: i64 = 1 << 18; // 256 KiB per fiber

/// Offsets of the scheduler's globals (allocated by the code generator).
#[derive(Clone)]
pub struct FibData {
    pub count: usize,
    pub current: usize,
    pub cur_stack_hi: usize,
    pub rr: usize,
}

fn global(asm: &mut Asm, off: usize, reg: Reg, value: Reg) {
    asm.mov_reg_abs(reg, AbsRef::Data(off));
    asm.mov_mem_reg(reg, 0, value);
}

fn load_global(asm: &mut Asm, off: usize, dst: Reg) {
    asm.mov_reg_abs(dst, AbsRef::Data(off));
    asm.mov_reg_mem(dst, dst, 0);
}

/// rcx = table + rdx * 64, using `tmp` as scratch.
fn rec_ptr(asm: &mut Asm, index: Reg, out: Reg, tmp: Reg) {
    asm.mov_reg_reg(out, index);
    asm.shl_imm(out, 6);
    asm.mov_reg_abs(tmp, AbsRef::DataSym("fib_table".to_string()));
    asm.add_rr(out, tmp);
}

pub fn emit(asm: &mut Asm, target: Target, f: &FibData) {
    emit_switch(asm, f);
    emit_trampoline(asm, f);
    emit_spawn(asm, target, f);
    emit_yield(asm, f);
    emit_run(asm, f);
}

/// `fib_switch(rdi = from rec, rsi = to rec, rdx = to index)`.
fn emit_switch(asm: &mut Asm, f: &FibData) {
    asm.bind_symbol("fib_switch");
    global(asm, f.current, R11, RDX);
    asm.mov_reg_mem(RAX, RSI, 24);
    global(asm, f.cur_stack_hi, R11, RAX);
    asm.push(RBP);
    asm.push(RBX);
    asm.push(R12);
    asm.push(R13);
    asm.push(R14);
    asm.push(R15);
    asm.mov_mem_reg(RDI, 8, RSP);
    asm.mov_reg_mem(RSP, RSI, 8);
    asm.pop(R15);
    asm.pop(R14);
    asm.pop(R13);
    asm.pop(R12);
    asm.pop(RBX);
    asm.pop(RBP);
    asm.ret();
}

/// First instructions run on a fresh fiber stack: call the function, mark the
/// fiber done, and hand control back to the scheduler.
fn emit_trampoline(asm: &mut Asm, f: &FibData) {
    asm.bind_symbol("fib_trampoline");
    load_global(asm, f.current, RCX);
    rec_ptr(asm, RCX, RCX, R11);
    asm.mov_reg_mem(R11, RCX, 32); // fn
    asm.call_sym("rt_call");
    load_global(asm, f.current, RCX);
    rec_ptr(asm, RCX, RCX, R11);
    asm.mov_reg_imm64(RAX, 2); // done
    asm.mov_mem_reg(RCX, 0, RAX);
    asm.mov_reg_reg(RDI, RCX);
    asm.mov_reg_abs(RSI, AbsRef::DataSym("fib_table".to_string()));
    asm.xor_rr(RDX, RDX);
    asm.call_sym("fib_switch");
    asm.ret();
}

/// `rt_spawn(rdi = tagged function value) -> tagged fiber index or -1`.
fn emit_spawn(asm: &mut Asm, target: Target, f: &FibData) {
    asm.bind_symbol("rt_spawn");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_mem_reg(RBP, -8, RDI); // fn
    let scan = asm.new_label();
    let found = asm.new_label();
    let full = asm.new_label();
    asm.mov_reg_imm64(RCX, 1);
    asm.bind(scan);
    asm.cmp_imm32(RCX, MAX_SLOTS);
    asm.jcc(CC_GE, full);
    rec_ptr(asm, RCX, RDX, R11);
    asm.mov_reg_mem(RAX, RDX, 0);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_E, found);
    asm.add_imm32(RCX, 1);
    asm.jmp(scan);
    asm.bind(found);
    asm.mov_mem_reg(RBP, -16, RCX); // index
    asm.mov_mem_reg(RBP, -24, RDX); // rec

    // mmap the stack.
    asm.xor_rr(RDI, RDI);
    asm.mov_reg_imm64(RSI, STACK_SIZE);
    asm.mov_reg_imm64(RDX, 3);
    asm.mov_reg_imm64(R10, target.mmap_anon_flags());
    asm.mov_reg_imm64(R8, -1);
    asm.xor_rr(R9, R9);
    asm.mov_reg_imm64(RAX, target.mmap_nr());
    asm.syscall();
    // A result in the top page (-4095..-1) is an error.
    asm.mov_reg_imm64(R11, -4095);
    asm.cmp_rr(RAX, R11);
    asm.jcc(CC_AE, full);

    asm.mov_reg_mem(RDX, RBP, -24); // rec
    asm.mov_mem_reg(RDX, 16, RAX); // stack_lo
    asm.mov_reg_reg(RCX, RAX);
    asm.mov_reg_imm64(R11, STACK_SIZE);
    asm.add_rr(RCX, R11);
    asm.mov_mem_reg(RDX, 24, RCX); // stack_hi
    asm.mov_reg_mem(R11, RBP, -8);
    asm.mov_mem_reg(RDX, 32, R11); // fn
    // Initial context sits at the top of the stack: 6 saved registers (zero,
    // from demand-zero mmap) followed by the trampoline address.
    asm.sub_imm32(RCX, 56); // rcx = stack_hi - 56
    asm.mov_reg_abs(R11, AbsRef::CodeSym("fib_trampoline".to_string()));
    asm.mov_mem_reg(RCX, 48, R11); // return address above the 6 saved regs
    asm.mov_mem_reg(RDX, 8, RCX); // rsp
    asm.mov_reg_imm64(RAX, 1);
    asm.mov_mem_reg(RDX, 0, RAX); // ready

    // count = max(count, i + 1)
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.add_imm32(RCX, 1);
    load_global(asm, f.count, RAX);
    asm.cmp_rr(RCX, RAX);
    let no_update = asm.new_label();
    asm.jcc(CC_BE, no_update);
    global(asm, f.count, R11, RCX);
    asm.bind(no_update);

    asm.mov_reg_mem(RAX, RBP, -16);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    asm.bind(full);
    asm.mov_reg_imm64(RAX, -8); // tagged -1
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `rt_yield()`: mark the current fiber ready and return to the scheduler.
fn emit_yield(asm: &mut Asm, f: &FibData) {
    asm.bind_symbol("rt_yield");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    load_global(asm, f.current, RCX);
    rec_ptr(asm, RCX, RDX, R11);
    asm.mov_reg_mem(RAX, RDX, 0);
    let skip = asm.new_label();
    asm.cmp_imm32(RAX, 2);
    asm.jcc(CC_E, skip);
    asm.mov_reg_imm64(RAX, 1);
    asm.mov_mem_reg(RDX, 0, RAX);
    asm.bind(skip);
    asm.mov_reg_reg(RDI, RDX);
    asm.mov_reg_abs(RSI, AbsRef::DataSym("fib_table".to_string()));
    asm.xor_rr(RDX, RDX);
    asm.call_sym("fib_switch");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `rt_run()`: round-robin through ready fibers until none remain.
fn emit_run(asm: &mut Asm, f: &FibData) {
    asm.bind_symbol("rt_run");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    let loop_l = asm.new_label();
    let find = asm.new_label();
    let no_wrap = asm.new_label();
    let picked = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_l);
    load_global(asm, f.count, RAX);
    asm.cmp_imm32(RAX, 1);
    asm.jcc(CC_LE, done);
    asm.mov_reg_reg(R8, RAX); // count
    load_global(asm, f.rr, RCX); // start index
    asm.xor_rr(R9, R9); // tries
    asm.bind(find);
    asm.add_imm32(RCX, 1);
    asm.cmp_rr(RCX, R8);
    asm.jcc(CC_B, no_wrap);
    asm.mov_reg_imm64(RCX, 1);
    asm.bind(no_wrap);
    rec_ptr(asm, RCX, RDX, R11);
    asm.mov_reg_mem(RAX, RDX, 0);
    asm.cmp_imm32(RAX, 1);
    asm.jcc(CC_E, picked);
    asm.add_imm32(R9, 1);
    asm.cmp_rr(R9, R8);
    asm.jcc(CC_B, find);
    asm.jmp(done);
    asm.bind(picked);
    global(asm, f.rr, R11, RCX);
    asm.mov_reg_imm64(RAX, 3); // running
    asm.mov_mem_reg(RDX, 0, RAX);
    asm.mov_reg_abs(RDI, AbsRef::DataSym("fib_table".to_string()));
    asm.mov_reg_reg(RSI, RDX);
    asm.mov_reg_reg(RDX, RCX);
    asm.call_sym("fib_switch");
    asm.jmp(loop_l);
    asm.bind(done);
    asm.mov_reg_imm64(RAX, 0);
    global(asm, f.rr, R11, RAX);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}
