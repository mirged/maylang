//! Native runtime routines emitted as machine code.
//!
//! Values are tagged 64-bit words:
//!
//! | low 3 bits | meaning                                          |
//! |------------|--------------------------------------------------|
//! | `000`      | integer, `value << 3`                            |
//! | `001`      | pointer to `{ len: u64, bytes }` (string)        |
//! | `010`      | nil                                              |
//! | `011`      | false                                            |
//! | `100`      | true                                             |
//! | `101`      | pointer to a list `{ len, cap, data }`           |
//! | `111`      | pointer to a map (flat `[k0, v0, k1, v1, ...]`)  |
//!
//! Printing uses the `write` syscall directly, so the produced executables are
//! freestanding. Lists and strings are allocated from a static bump heap.

use crate::x86::*;
use crate::Target;

const STR_TAG: i32 = 0b001;
const NIL_TAG: i32 = 0b010;
const FALSE_TAG: i32 = 0b011;
const TRUE_TAG: i32 = 0b100;
const LIST_TAG: i32 = 0b101;
const MAP_TAG: i32 = 0b111;

/// Offsets of runtime string data and syscall numbers.
#[derive(Clone)]
pub struct RuntimeData {
    pub newline: usize,
    pub space: usize,
    pub nil: usize,
    pub true_: usize,
    pub false_: usize,
    pub lbracket: usize,
    pub rbracket: usize,
    pub lbrace: usize,
    pub rbrace: usize,
    pub comma: usize,
    pub colon: usize,
    pub quote: usize,
    pub err_key: usize,
    pub msg_key: usize,
    pub not_callable: usize,
    pub fun_repr: usize,
    pub sym_sub: usize,
    pub sym_mul: usize,
    pub sym_div: usize,
    pub sym_mod: usize,
}

pub fn emit_data(asm: &mut Asm) -> RuntimeData {
    RuntimeData {
        newline: asm.intern(b"\n"),
        space: asm.intern(b" "),
        nil: asm.intern(b"nil"),
        true_: asm.intern(b"true"),
        false_: asm.intern(b"false"),
        lbracket: asm.intern(b"["),
        rbracket: asm.intern(b"]"),
        lbrace: asm.intern(b"{"),
        rbrace: asm.intern(b"}"),
        comma: asm.intern(b", "),
        colon: asm.intern(b": "),
        quote: asm.intern(b"\""),
        err_key: asm.intern(b"__error__"),
        msg_key: asm.intern(b"message"),
        not_callable: asm.intern(b"not callable"),
        fun_repr: asm.intern(b"<fun>"),
        sym_sub: asm.intern(b"-"),
        sym_mul: asm.intern(b"*"),
        sym_div: asm.intern(b"/"),
        sym_mod: asm.intern(b"%"),
    }
}

pub fn emit_runtime(
    asm: &mut Asm,
    target: Target,
    data: &RuntimeData,
    gc: &crate::gc::GcData,
    heap_ptr_slot: usize,
    heap_end_slot: usize,
    handler_depth_slot: usize,
    handler_stack_off: usize,
) {
    asm.bind_symbol("rt_write");
    asm.mov_reg_imm64(RAX, target.write_nr());
    asm.mov_reg_imm64(RDI, 1);
    asm.syscall();
    asm.ret();

    emit_single(asm, "rt_newline", data.newline);
    emit_single(asm, "rt_space", data.space);
    emit_single(asm, "rt_lbracket", data.lbracket);
    emit_single(asm, "rt_rbracket", data.rbracket);
    emit_single(asm, "rt_lbrace", data.lbrace);
    emit_single(asm, "rt_rbrace", data.rbrace);
    emit_single(asm, "rt_comma", data.comma);
    emit_single(asm, "rt_colon", data.colon);

    asm.bind_symbol("rt_print_cstr");
    asm.mov_reg_mem(RDX, RDI, 0);
    asm.lea(RSI, RDI, 8);
    asm.call_sym("rt_write");
    asm.ret();

    asm.bind_symbol("rt_print_str");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RDX, RDI, 0);
    asm.lea(RSI, RDI, 8);
    asm.call_sym("rt_write");
    asm.ret();

    emit_print_int(asm);
    emit_memcpy(asm);
    crate::gc::emit(asm, target, gc, heap_ptr_slot, heap_end_slot);
    emit_len(asm);
    emit_str_cat(asm);
    emit_char_at(asm);
    emit_char_from(asm);
    emit_int_to_str(asm);
    emit_str_of(asm, data);
    emit_value_eq(asm);
    emit_str_cmp(asm);
    emit_map_get(asm);
    emit_map_set(asm);
    emit_map_keys(asm, "rt_map_keys", 0);
    emit_map_keys(asm, "rt_map_values", 8);
    emit_map_has(asm);
    emit_to_map(asm);
    emit_value_tag(asm);
    emit_syscall(asm);
    emit_index(asm);
    emit_iter_get(asm);
    emit_set_index(asm);
    emit_push(asm);
    emit_pop(asm);
    emit_print_list(asm, data);
    emit_print_map(asm, data);
    emit_print_repr(asm, data);
    emit_print_value(asm, data);
    emit_num_helpers(asm);
    emit_binops(asm, data);
    emit_powf(asm);
    emit_math_unary(asm);
    emit_clock_time(asm, target);
    emit_io(asm, target);
    emit_process(asm, target, gc);
    emit_read_dir(asm, target);
    emit_ffi(asm);
    emit_exit(asm, target);
    emit_raise(asm, target, handler_depth_slot, handler_stack_off);
    emit_call(asm, data);
    emit_add(asm);
    emit_cmp(asm);
    emit_range(asm);
    emit_read_stdin(asm, target);
    emit_args(asm, gc);
}

const XMM0: u8 = 0;
const XMM1: u8 = 1;
const XMM2: u8 = 2;
const FLOAT_TAG: i32 = 0b110;

/// rt_num_f64: rdi = int or boxed float; loads the value into xmm0 as f64.
fn emit_num_f64(asm: &mut Asm) {
    asm.bind_symbol("rt_num_f64");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float = asm.new_label();
    asm.jcc(CC_E, float);
    asm.sar_imm(RDI, 3);
    asm.cvtsi2sd(XMM0, RDI);
    asm.ret();
    asm.bind(float);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.ret();
}

/// rt_box_float: xmm0 -> boxed float in rax.
fn emit_box_float(asm: &mut Asm) {
    asm.bind_symbol("rt_box_float");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.movsd_store(RBP, -8, XMM0);
    asm.mov_reg_imm64(RDI, 8);
    asm.call_sym("rt_alloc_float");
    asm.movsd_load(XMM0, RBP, -8);
    asm.movsd_store(RAX, 0, XMM0);
    asm.mov_reg_imm64(R11, FLOAT_TAG as i64);
    asm.or_rr(RAX, R11);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// rt_to_float: tagged int -> boxed float.
fn emit_to_float(asm: &mut Asm) {
    asm.bind_symbol("rt_to_float");
    asm.sar_imm(RDI, 3);
    asm.cvtsi2sd(XMM0, RDI);
    asm.jmp_sym("rt_box_float");
}

fn emit_num_helpers(asm: &mut Asm) {
    emit_num_f64(asm);
    emit_box_float(asm);
    emit_to_float(asm);

    // rt_float_floor
    asm.bind_symbol("rt_float_floor");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.cvttsd2si(RAX, XMM0);
    asm.cvtsi2sd(XMM1, RAX);
    asm.comisd(XMM0, XMM1);
    let floor_done = asm.new_label();
    asm.jcc(CC_AE, floor_done);
    asm.sub_imm32(RAX, 1);
    asm.bind(floor_done);
    asm.shl_imm(RAX, 3);
    asm.ret();

    // rt_float_ceil
    asm.bind_symbol("rt_float_ceil");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.cvttsd2si(RAX, XMM0);
    asm.cvtsi2sd(XMM1, RAX);
    asm.comisd(XMM0, XMM1);
    let ceil_done = asm.new_label();
    asm.jcc(CC_BE, ceil_done);
    asm.add_imm32(RAX, 1);
    asm.bind(ceil_done);
    asm.shl_imm(RAX, 3);
    asm.ret();

    // rt_float_trunc
    asm.bind_symbol("rt_float_trunc");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.cvttsd2si(RAX, XMM0);
    asm.shl_imm(RAX, 3);
    asm.ret();

    // rt_float_sqrt
    asm.bind_symbol("rt_float_sqrt");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.sqrtsd(XMM0, XMM0);
    asm.jmp_sym("rt_box_float");
}

/// Emit a unary float function: `RDI` (int or boxed float) in, boxed float out.
/// `body` runs with `st(0)` holding the argument and must leave the result in
/// `st(0)` (the x87 stack must otherwise be empty).
fn emit_x87_unary<F>(asm: &mut Asm, name: &str, body: F)
where
    F: FnOnce(&mut Asm),
{
    asm.bind_symbol(name);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -16, XMM0);
    asm.fldl(RBP, -16);
    body(asm);
    asm.fstpl(RBP, -16);
    asm.movsd_load(XMM0, RBP, -16);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// The x87 stack setup for `2 ** t` given `t = st(0)`; leaves the result in
/// `st(0)` and pops the rounding scratch value.
fn x87_exp2(asm: &mut Asm) {
    asm.fld_st(0); // t, t
    asm.frndint(); // n, t
    asm.fxch_st(1); // t, n
    asm.fsub_st0_st(1); // f = t - n
    asm.f2xm1(); // 2^f - 1
    asm.fld1(); // 1, 2^f - 1, n
    asm.faddp_st0_st(1); // 2^f, n
    asm.fscale(); // 2^t, n
    asm.fstp_st(1); // result
}

/// rt_powf: `rdi` = base, `rsi` = exponent (either numeric); `base ** exponent`
/// as a boxed float, using x87 (`fyl2x` + `f2xm1` + `fscale`).
fn emit_powf(asm: &mut Asm) {
    asm.bind_symbol("rt_powf");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -32, XMM0);
    asm.fldl(RBP, -32); // st0 = exponent
    asm.fldl(RBP, -24); // st0 = base, st1 = exponent
    asm.fyl2x(); // t = exponent * log2(base)
    x87_exp2(asm);
    asm.fstpl(RBP, -24);
    asm.movsd_load(XMM0, RBP, -24);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// The transcendental math built-ins, computed with the x87 unit.
fn emit_math_unary(asm: &mut Asm) {
    emit_x87_unary(asm, "rt_sin", |a| {
        a.fsin();
    });
    emit_x87_unary(asm, "rt_cos", |a| {
        a.fcos();
    });
    emit_x87_unary(asm, "rt_tan", |a| {
        a.fptan();
        a.fstp_st(0); // discard the pushed 1.0
    });
    emit_x87_unary(asm, "rt_asin", |a| {
        a.fld_st(0);
        a.fmul_st0_st(0); // x^2
        a.fld1();
        a.fsubrp_st0_st(1); // 1 - x^2
        a.fsqrt();
        a.fpatan(); // atan2(x, sqrt(1 - x^2))
    });
    emit_x87_unary(asm, "rt_acos", |a| {
        a.fld_st(0);
        a.fmul_st0_st(0);
        a.fld1();
        a.fsubrp_st0_st(1);
        a.fsqrt();
        a.fxch_st(1);
        a.fpatan(); // atan2(sqrt(1 - x^2), x)
    });
    emit_x87_unary(asm, "rt_atan", |a| {
        a.fld1();
        a.fpatan();
    });
    emit_x87_unary(asm, "rt_ln", |a| {
        a.fldln2();
        a.fxch_st(1);
        a.fyl2x();
    });
    emit_x87_unary(asm, "rt_log2", |a| {
        a.fld1();
        a.fxch_st(1);
        a.fyl2x();
    });
    emit_x87_unary(asm, "rt_log10", |a| {
        a.fldlg2();
        a.fxch_st(1);
        a.fyl2x();
    });
    emit_x87_unary(asm, "rt_exp", |a| {
        a.fldl2e();
        a.fmulp_st0_st(1); // t = x * log2(e)
        x87_exp2(a);
    });

    // rt_atan2: rdi = y, rsi = x.
    asm.bind_symbol("rt_atan2");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -32, XMM0);
    asm.fldl(RBP, -24); // x
    asm.fldl(RBP, -32); // y, x
    asm.fpatan();
    asm.fstpl(RBP, -24);
    asm.movsd_load(XMM0, RBP, -24);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// Wall-clock time: `rt_clock` (epoch seconds as a float) and `rt_time`
/// (epoch milliseconds as an integer), via `clock_gettime`/`gettimeofday`.
fn emit_clock_time(asm: &mut Asm, target: Target) {
    // rt_clock: 0 args -> seconds since the epoch as a boxed float.
    asm.bind_symbol("rt_clock");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    let ts = -16i32;
    if target == Target::MacOS {
        // gettimeofday(timeval*, NULL): { sec, usec }
        asm.mov_reg_imm64(RAX, target.gettimeofday_nr());
        asm.lea(RDI, RBP, ts);
        asm.xor_rr(RSI, RSI);
        asm.syscall();
    } else {
        // clock_gettime(CLOCK_REALTIME, timespec*): { sec, nsec }
        asm.mov_reg_imm64(RAX, target.clock_gettime_nr());
        asm.xor_rr(RDI, RDI);
        asm.lea(RSI, RBP, ts);
        asm.syscall();
    }
    asm.mov_reg_mem(RAX, RBP, ts); // seconds
    asm.cvtsi2sd(XMM0, RAX);
    asm.mov_reg_mem(RAX, RBP, ts + 8); // nanoseconds / microseconds
    asm.cvtsi2sd(XMM1, RAX);
    asm.mov_reg_imm64(RAX, if target == Target::MacOS { 1_000_000 } else { 1_000_000_000 });
    asm.cvtsi2sd(XMM2, RAX);
    asm.divsd(XMM1, XMM2);
    asm.addsd(XMM0, XMM1);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_time: 0 args -> milliseconds since the epoch as a tagged int.
    asm.bind_symbol("rt_time");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    if target == Target::MacOS {
        asm.mov_reg_imm64(RAX, target.gettimeofday_nr());
        asm.lea(RDI, RBP, ts);
        asm.xor_rr(RSI, RSI);
        asm.syscall();
    } else {
        asm.mov_reg_imm64(RAX, target.clock_gettime_nr());
        asm.xor_rr(RDI, RDI);
        asm.lea(RSI, RBP, ts);
        asm.syscall();
    }
    asm.mov_reg_mem(RAX, RBP, ts);
    asm.mov_reg_imm64(R11, 1000);
    asm.imul_rr(RAX, R11);
    asm.mov_reg_reg(R8, RAX);
    asm.mov_reg_mem(RAX, RBP, ts + 8);
    asm.mov_reg_imm64(RCX, if target == Target::MacOS { 1_000 } else { 1_000_000 });
    asm.cqo();
    asm.idiv(RCX);
    asm.add_rr(RAX, R8);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `exit(status)` — terminate the process with the given integer status.
fn emit_exit(asm: &mut Asm, target: Target) {
    asm.bind_symbol("rt_exit");
    asm.sar_imm(RDI, 3);
    asm.mov_reg_imm64(RAX, target.exit_nr());
    asm.syscall();
    asm.ret();
}

/// File I/O: `rt_read_file`, `rt_write_file` and `rt_file_exists`, built on the
/// open/read/write/close/access syscalls. Paths are copied to NUL-terminated
/// scratch buffers because Maylang strings are not NUL-terminated.
fn emit_io(asm: &mut Asm, target: Target) {
    // rt_cpath: rdi = tagged string -> rax = NUL-terminated copy (raw pointer).
    asm.bind_symbol("rt_cpath");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_mem(RCX, RDI, 0);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.mov_reg_reg(RDI, RCX);
    asm.add_imm32(RDI, 1);
    asm.call_sym("rt_alloc");
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_mem(RSI, RBP, -8);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDX, RBP, -16);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.add_rr(RAX, RCX);
    asm.mov_byte_mem_imm(RAX, 0, 0);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    let io_err = asm.intern(b"io error");

    // rt_read_file: rdi = path -> tagged string (or an `io` fault).
    asm.bind_symbol("rt_read_file");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.call_sym("rt_cpath");
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_imm64(RAX, target.open_nr());
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.xor_rr(RSI, RSI); // O_RDONLY
    asm.xor_rr(RDX, RDX);
    asm.syscall();
    asm.mov_mem_reg(RBP, -16, RAX);
    let rd_err = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_S, rd_err);
    // Buffer: 8-byte length header followed by data.
    asm.mov_reg_imm64(RDI, 65_544);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.mov_mem_reg(RBP, -32, RAX); // total
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -40, RAX);
    let read_loop = asm.new_label();
    let read_done = asm.new_label();
    asm.bind(read_loop);
    asm.mov_reg_imm64(RAX, target.read_nr());
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_mem(RSI, RBP, -24);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.add_rr(RSI, RCX);
    asm.mov_reg_imm64(RDX, 65_536);
    asm.sub_rr(RDX, RCX);
    asm.syscall();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_LE, read_done);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.add_rr(RCX, RAX);
    asm.mov_mem_reg(RBP, -40, RCX);
    asm.jmp(read_loop);
    asm.bind(read_done);
    asm.mov_reg_imm64(RAX, target.close_nr());
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.syscall();
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(rd_err);
    asm.mov_reg_abs(RDI, AbsRef::Data(io_err));
    asm.add_imm32(RDI, 1);
    asm.call_sym("raise_io_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_write_file: rdi = path, rsi = content -> nil.
    asm.bind_symbol("rt_write_file");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RSI, R11);
    asm.mov_mem_reg(RBP, -24, RSI); // content header ptr
    asm.mov_mem_reg(RBP, -8, RSI);
    asm.call_sym("rt_cpath");
    asm.mov_mem_reg(RBP, -16, RAX);
    asm.mov_reg_imm64(RAX, target.open_nr());
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_imm64(RSI, 577); // O_WRONLY | O_CREAT | O_TRUNC
    asm.mov_reg_imm64(RDX, 0o644);
    asm.syscall();
    asm.mov_mem_reg(RBP, -32, RAX);
    let wr_err = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_S, wr_err);
    asm.mov_reg_imm64(RAX, target.write_nr());
    asm.mov_reg_mem(RDI, RBP, -32);
    asm.mov_reg_mem(RSI, RBP, -24);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.mov_reg_mem(RDX, RDX, 0);
    asm.syscall();
    asm.mov_reg_imm64(RAX, target.close_nr());
    asm.mov_reg_mem(RDI, RBP, -32);
    asm.syscall();
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(wr_err);
    asm.mov_reg_abs(RDI, AbsRef::Data(io_err));
    asm.add_imm32(RDI, 1);
    asm.call_sym("raise_io_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_file_exists: rdi = path -> bool.
    asm.bind_symbol("rt_file_exists");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.call_sym("rt_cpath");
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_imm64(RAX, target.access_nr());
    asm.xor_rr(RSI, RSI); // F_OK
    asm.syscall();
    asm.test_rr(RAX, RAX);
    asm.setcc(CC_E, RAX);
    asm.movzx_byte(RAX, RAX);
    asm.add_imm32(RAX, FALSE_TAG as i32); // 0 -> false, 1 -> true
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_input: read one line from stdin -> tagged string (or nil at EOF).
    asm.bind_symbol("rt_input");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_reg_imm64(RDI, 4104);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -16, RAX);
    let in_loop = asm.new_label();
    let in_finish = asm.new_label();
    let in_eof = asm.new_label();
    asm.bind(in_loop);
    asm.mov_reg_imm64(RAX, target.read_nr());
    asm.xor_rr(RDI, RDI);
    asm.mov_reg_mem(RSI, RBP, -8);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.add_rr(RSI, RCX);
    asm.mov_reg_imm64(RDX, 1);
    asm.syscall();
    asm.cmp_imm32(RAX, 0);
    asm.jcc(CC_LE, in_eof);
    // stop at newline or when the 4096-byte buffer is full
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.add_imm32(RDX, 8);
    asm.add_rr(RDX, RCX);
    asm.movzx_byte_mem(R8, RDX, 0);
    asm.cmp_imm32(R8, 10);
    asm.jcc(CC_E, in_finish);
    asm.add_imm32(RCX, 1);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.cmp_imm32(RCX, 4096);
    asm.jcc(CC_GE, in_finish);
    asm.jmp(in_loop);
    asm.bind(in_eof);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, in_finish);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(in_finish);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `mkdir(path)` — create a directory (mode 0755). Raises an `io` fault on
/// failure so it composes with `may { } otherwise { }`.
fn emit_mkdir(asm: &mut Asm, target: Target) {
    let io_err = asm.intern(b"mkdir failed");
    asm.bind_symbol("rt_mkdir");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.call_sym("rt_cpath");
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_imm64(RSI, 0o755);
    asm.mov_reg_imm64(RAX, target.mkdir_nr());
    asm.syscall();
    asm.test_rr(RAX, RAX);
    let ok = asm.new_label();
    asm.jcc(CC_NS, ok);
    asm.mov_reg_abs(RDI, AbsRef::Data(io_err));
    asm.add_imm32(RDI, 1);
    asm.call_sym("raise_io_error");
    asm.bind(ok);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// Copy a tagged Maylang string into `rsi` as a NUL-terminated C string and
/// return the first byte after it in `rax`. Truncated at `SCRATCH_STR_CAP`.
fn emit_scratch_cstr(asm: &mut Asm, cap: usize) {
    asm.bind_symbol("rt_scratch_cstr");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RSI); // dst
    asm.mov_reg_reg(R11, RDI);
    asm.mov_reg_imm64(RCX, -8);
    asm.and_rr(R11, RCX);
    asm.mov_reg_mem(RCX, R11, 0); // len
    // clamp len to the remaining scratch capacity
    asm.mov_reg_imm64(RAX, cap as i64);
    asm.cmp_rr(RCX, RAX);
    let fits = asm.new_label();
    asm.jcc(CC_BE, fits);
    asm.mov_reg_reg(RCX, RAX);
    asm.bind(fits);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.mov_reg_reg(RSI, R11);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_reg(RDX, RCX);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_reg(RAX, RDI);
    asm.add_rr(RAX, RCX);
    asm.mov_byte_mem_imm(RAX, 0, 0);
    asm.add_imm32(RAX, 1);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `exec(argv)` — `fork` + `execve(argv[0], argv, envp)`, returning the child
/// pid. `argv` is a list of strings; `argv[0]` is the program path. The child
/// inherits the environment captured at `_start`. Raises nothing; a fork
/// failure yields `-1`.
fn emit_exec(asm: &mut Asm, target: Target, gc: &crate::gc::GcData) {
    asm.bind_symbol("rt_exec");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 96);
    asm.mov_mem_reg(RBP, -8, RDI); // tagged list
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RAX, R11);
    asm.mov_mem_reg(RBP, -16, RAX); // header
    asm.mov_reg_mem(RCX, RAX, 0); // len
    asm.mov_mem_reg(RBP, -24, RCX);
    let ret = asm.new_label();
    asm.cmp_imm32(RCX, 1024);
    let ok = asm.new_label();
    asm.jcc(CC_LE, ok);
    asm.mov_reg_imm64(RAX, -8); // tagged -1
    asm.jmp(ret);
    asm.bind(ok);
    asm.mov_reg_abs(R11, AbsRef::DataSym("proc_argv".to_string()));
    asm.mov_mem_reg(RBP, -32, R11); // argv base
    asm.mov_reg_abs(R11, AbsRef::DataSym("proc_str".to_string()));
    asm.mov_mem_reg(RBP, -40, R11); // str cursor
    asm.xor_rr(RAX, RAX);
    asm.mov_mem_reg(RBP, -48, RAX); // i
    let loop_l = asm.new_label();
    let built = asm.new_label();
    asm.bind(loop_l);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, built);
    // elem = list_data[i]
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_mem(RCX, RCX, 16);
    asm.mov_reg_mem(RDX, RBP, -48);
    asm.shl_imm(RDX, 3);
    asm.add_rr(RCX, RDX);
    asm.mov_reg_mem(RDI, RCX, 0);
    asm.mov_reg_mem(RSI, RBP, -40);
    asm.mov_mem_reg(RBP, -56, RSI); // dst start
    asm.call_sym("rt_scratch_cstr");
    asm.mov_mem_reg(RBP, -40, RAX); // advance cursor
    // argv[i] = dst start
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_reg_mem(RDX, RBP, -48);
    asm.shl_imm(RDX, 3);
    asm.add_rr(RCX, RDX);
    asm.mov_reg_mem(RAX, RBP, -56);
    asm.mov_mem_reg(RCX, 0, RAX);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -48, RAX);
    asm.jmp(loop_l);
    asm.bind(built);
    // argv[len] = NULL
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.shl_imm(RDX, 3);
    asm.add_rr(RCX, RDX);
    asm.xor_rr(RAX, RAX);
    asm.mov_mem_reg(RCX, 0, RAX);
    // envp = original argv + (argc + 1) * 8
    asm.mov_reg_abs(R11, AbsRef::Data(gc.argv));
    asm.mov_reg_mem(RAX, R11, 0);
    asm.mov_reg_abs(R11, AbsRef::Data(gc.argc));
    asm.mov_reg_mem(RCX, R11, 0);
    asm.add_imm32(RCX, 1);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RAX, RCX);
    asm.mov_mem_reg(RBP, -64, RAX); // envp
    asm.mov_reg_imm64(RAX, target.fork_nr());
    asm.syscall();
    asm.test_rr(RAX, RAX);
    let child = asm.new_label();
    let fork_err = asm.new_label();
    asm.jcc(CC_S, fork_err);
    asm.jcc(CC_E, child);
    asm.shl_imm(RAX, 3); // parent: tag the pid
    asm.jmp(ret);
    asm.bind(child);
    asm.mov_reg_mem(RDI, RBP, -32); // argv array
    asm.mov_reg_mem(RDI, RDI, 0); // path = argv[0]
    asm.mov_reg_mem(RSI, RBP, -32); // argv
    asm.mov_reg_mem(RDX, RBP, -64); // envp
    asm.mov_reg_imm64(RAX, target.execve_nr());
    asm.syscall();
    asm.mov_reg_imm64(RAX, target.exit_nr());
    asm.mov_reg_imm64(RDI, 127);
    asm.syscall();
    asm.bind(fork_err);
    asm.mov_reg_imm64(RAX, -8); // tagged -1
    asm.bind(ret);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `wait(pid)` — block until the child exits and return its status code
/// (`0..=255`), or `-1` on error.
fn emit_wait(asm: &mut Asm, target: Target) {
    asm.bind_symbol("rt_wait");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.sar_imm(RDI, 3); // untag pid
    asm.lea(RSI, RBP, -16);
    asm.xor_rr(RDX, RDX);
    asm.xor_rr(R10, R10);
    asm.mov_reg_imm64(RAX, target.wait4_nr());
    asm.syscall();
    let err = asm.new_label();
    let done = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_LE, err);
    asm.mov_reg_mem(RAX, RBP, -16); // status
    asm.sar_imm(RAX, 8);
    asm.mov_reg_imm64(RCX, 255);
    asm.and_rr(RAX, RCX);
    asm.shl_imm(RAX, 3);
    asm.jmp(done);
    asm.bind(err);
    asm.mov_reg_imm64(RAX, -8); // tagged -1
    asm.bind(done);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `system(command)` — run a shell command (`/bin/sh -c`) and return its exit
/// status. Uses the exec/wait machinery above.
fn emit_system(asm: &mut Asm) {
    let sh = asm.intern(b"/bin/sh");
    let dash_c = asm.intern(b"-c");
    asm.bind_symbol("rt_system");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_mem_reg(RBP, -8, RDI); // command
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc_list");
    asm.mov_mem_reg(RBP, -16, RAX);
    asm.xor_rr(RCX, RCX);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_mem_reg(RAX, 16, RCX);
    // push "/bin/sh"
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.add_imm32(RDI, LIST_TAG);
    asm.mov_reg_abs(RSI, AbsRef::Data(sh));
    asm.add_imm32(RSI, 1);
    asm.call_sym("rt_push");
    // push "-c"
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.add_imm32(RDI, LIST_TAG);
    asm.mov_reg_abs(RSI, AbsRef::Data(dash_c));
    asm.add_imm32(RSI, 1);
    asm.call_sym("rt_push");
    // push command
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.add_imm32(RDI, LIST_TAG);
    asm.mov_reg_mem(RSI, RBP, -8);
    asm.call_sym("rt_push");
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.add_imm32(RDI, LIST_TAG);
    asm.call_sym("rt_exec");
    let fail = asm.new_label();
    let done = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_LE, fail);
    asm.mov_reg_reg(RDI, RAX); // tagged pid
    asm.call_sym("rt_wait");
    asm.jmp(done);
    asm.bind(fail);
    asm.mov_reg_imm64(RAX, -8);
    asm.bind(done);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `read_dir(path)` — a list of entry names in `path`, excluding `.` and `..`.
/// Linux uses `getdents64`; on macOS this raises (no such syscall).
fn emit_read_dir(asm: &mut Asm, target: Target) {
    let io_err = asm.intern(b"read_dir failed");
    asm.bind_symbol("rt_read_dir");
    if target == Target::MacOS {
        asm.mov_reg_abs(RDI, AbsRef::Data(io_err));
        asm.add_imm32(RDI, 1);
        asm.call_sym("raise_io_error");
        asm.mov_reg_imm64(RAX, NIL_TAG as i64);
        asm.ret();
        return;
    }
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 128);
    asm.call_sym("rt_cpath");
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_imm64(RSI, target.o_directory());
    asm.xor_rr(RDX, RDX);
    asm.mov_reg_imm64(RAX, target.open_nr());
    asm.syscall();
    asm.test_rr(RAX, RAX);
    let opened = asm.new_label();
    asm.jcc(CC_NS, opened);
    asm.mov_reg_abs(RDI, AbsRef::Data(io_err));
    asm.add_imm32(RDI, 1);
    asm.call_sym("raise_io_error");
    asm.bind(opened);
    asm.mov_mem_reg(RBP, -16, RAX); // fd
    // result list
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc_list");
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.xor_rr(RCX, RCX);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_mem_reg(RAX, 16, RCX);
    // getdents buffer (32 KiB, raw/untraced)
    asm.mov_reg_imm64(RDI, 32768);
    asm.call_sym("rt_alloc");
    asm.mov_mem_reg(RBP, -32, RAX);
    let read_loop = asm.new_label();
    let drained = asm.new_label();
    asm.bind(read_loop);
    asm.mov_reg_imm64(RAX, target.getdents_nr());
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_mem(RSI, RBP, -32);
    asm.mov_reg_imm64(RDX, 32768);
    asm.syscall();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_LE, drained);
    asm.mov_mem_reg(RBP, -40, RAX); // bytes
    asm.xor_rr(RAX, RAX);
    asm.mov_mem_reg(RBP, -48, RAX); // offset
    let entry_loop = asm.new_label();
    let next_entry = asm.new_label();
    asm.bind(entry_loop);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, read_loop);
    asm.mov_reg_mem(R9, RBP, -32);
    asm.add_rr(R9, RAX); // entry ptr
    // reclen = u16 at [r9 + 16]
    asm.movzx_byte_mem(RAX, R9, 16);
    asm.movzx_byte_mem(RCX, R9, 17);
    asm.shl_imm(RCX, 8);
    asm.or_rr(RAX, RCX);
    asm.mov_mem_reg(RBP, -56, RAX); // reclen
    // name at r9 + 19
    asm.lea(R10, R9, 19);
    asm.mov_mem_reg(RBP, -64, R10); // name ptr
    // name length = scan to NUL
    asm.xor_rr(RCX, RCX);
    let scan = asm.new_label();
    let scanned = asm.new_label();
    asm.bind(scan);
    asm.mov_reg_mem(R10, RBP, -64);
    asm.add_rr(R10, RCX);
    asm.movzx_byte_mem(RAX, R10, 0);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_E, scanned);
    asm.add_imm32(RCX, 1);
    asm.jmp(scan);
    asm.bind(scanned);
    // skip "." and ".."
    asm.cmp_imm32(RCX, 1);
    let not_one = asm.new_label();
    asm.jcc(CC_NE, not_one);
    asm.mov_reg_mem(R10, RBP, -64);
    asm.movzx_byte_mem(RAX, R10, 0);
    asm.cmp_imm32(RAX, '.' as i32);
    asm.jcc(CC_E, next_entry);
    asm.bind(not_one);
    asm.cmp_imm32(RCX, 2);
    let include = asm.new_label();
    asm.jcc(CC_NE, include);
    asm.mov_reg_mem(R10, RBP, -64);
    asm.movzx_byte_mem(RAX, R10, 0);
    asm.cmp_imm32(RAX, '.' as i32);
    asm.jcc(CC_NE, include);
    asm.movzx_byte_mem(RAX, R10, 1);
    asm.cmp_imm32(RAX, '.' as i32);
    asm.jcc(CC_E, next_entry);
    asm.bind(include);
    // allocate the name string
    asm.mov_reg_mem(R10, RBP, -64);
    asm.mov_mem_reg(RBP, -72, R10); // name ptr
    asm.mov_mem_reg(RBP, -80, RCX); // name len
    asm.mov_reg_reg(RDI, RCX);
    asm.add_imm32(RDI, 8);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -88, RAX);
    asm.mov_reg_mem(RCX, RBP, -80);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_reg_reg(RDI, RAX);
    asm.add_imm32(RDI, 8);
    asm.mov_reg_mem(RSI, RBP, -72);
    asm.mov_reg_reg(RDX, RCX);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RAX, RBP, -88);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSI, RAX);
    asm.mov_reg_mem(RDI, RBP, -24);
    asm.add_imm32(RDI, LIST_TAG);
    asm.call_sym("rt_push");
    asm.bind(next_entry);
    asm.mov_reg_mem(RAX, RBP, -56);
    asm.mov_reg_mem(RCX, RBP, -48);
    asm.add_rr(RCX, RAX);
    asm.mov_mem_reg(RBP, -48, RCX);
    asm.jmp(entry_loop);
    asm.bind(drained);
    asm.mov_reg_imm64(RAX, target.close_nr());
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.syscall();
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `sleep(ms)` — block the process for `ms` milliseconds via `nanosleep`.
fn emit_sleep(asm: &mut Asm, target: Target) {
    asm.bind_symbol("rt_sleep");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.sar_imm(RDI, 3); // untag ms
    asm.mov_reg_reg(RAX, RDI);
    asm.xor_rr(RDX, RDX);
    asm.mov_reg_imm64(RCX, 1000);
    asm.div(RCX); // rax = seconds, rdx = remainder ms
    asm.mov_mem_reg(RBP, -16, RAX); // tv_sec
    asm.mov_reg_imm64(RCX, 1_000_000);
    asm.imul_rr(RDX, RCX);
    asm.mov_mem_reg(RBP, -8, RDX); // tv_nsec
    asm.lea(RDI, RBP, -16);
    asm.xor_rr(RSI, RSI);
    asm.mov_reg_imm64(RAX, target.nanosleep_nr());
    asm.syscall();
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// Emit the process/filesystem runtime: scratch copies, `mkdir`, `exec`,
/// `wait`, `system`, `sleep` and the getdents buffer.
fn emit_process(asm: &mut Asm, target: Target, gc: &crate::gc::GcData) {
    emit_scratch_cstr(asm, crate::PROC_SCRATCH_STR_CAP);
    emit_mkdir(asm, target);
    emit_exec(asm, target, gc);
    emit_wait(asm, target);
    emit_system(asm);
    emit_sleep(asm, target);
}

/// The "sovereign" layer: raw pointers and memory, and C-ABI calls.
///
/// Pointers are ordinary Maylang integers whose numeric value is a machine
/// address. `addr(x)` exposes a heap object's address, `load*`/`store*` read
/// and write raw memory, `ccall` invokes an address with the SysV C ABI, and
/// `extern_c` wraps an address as a value you can call like a function.
fn emit_ffi(asm: &mut Asm) {
    // rt_addr: rdi = value -> rax = payload address (tagged int), or 0.
    asm.bind_symbol("rt_addr");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    let a_str = asm.new_label();
    let a_base = asm.new_label();
    asm.cmp_imm32(RAX, STR_TAG);
    asm.jcc(CC_E, a_str);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    asm.jcc(CC_E, a_base);
    asm.cmp_imm32(RAX, LIST_TAG);
    asm.jcc(CC_E, a_base);
    asm.cmp_imm32(RAX, MAP_TAG);
    asm.jcc(CC_E, a_base);
    asm.xor_rr(RAX, RAX);
    asm.ret();
    asm.bind(a_str);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.add_imm32(RDI, 8);
    asm.mov_reg_reg(RAX, RDI);
    asm.shl_imm(RAX, 3);
    asm.ret();
    asm.bind(a_base);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_reg(RAX, RDI);
    asm.shl_imm(RAX, 3);
    asm.ret();

    // rt_load8 / rt_load16 / rt_load32 / rt_load64: rdi = address -> value.
    for (name, width) in [("rt_load8", 1usize), ("rt_load16", 2), ("rt_load32", 4), ("rt_load64", 8)] {
        asm.bind_symbol(name);
        asm.mov_reg_reg(RAX, RDI);
        asm.sar_imm(RAX, 3);
        match width {
            1 => asm.movzx_byte_mem(RAX, RAX, 0),
            2 => asm.movzx_word_mem(RAX, RAX, 0),
            4 => asm.mov32_reg_mem(RAX, RAX, 0),
            _ => asm.mov_reg_mem(RAX, RAX, 0),
        }
        asm.shl_imm(RAX, 3);
        asm.ret();
    }

    // rt_store8 / rt_store16 / rt_store32 / rt_store64: rdi = address, rsi = value.
    for (name, width) in [("rt_store8", 1usize), ("rt_store16", 2), ("rt_store32", 4), ("rt_store64", 8)] {
        asm.bind_symbol(name);
        asm.sar_imm(RDI, 3);
        asm.sar_imm(RSI, 3);
        match width {
            1 => asm.mov_byte_mem_reg(RDI, 0, RSI),
            2 => asm.mov_mem16_reg(RDI, 0, RSI),
            4 => asm.mov_mem32_reg(RDI, 0, RSI),
            _ => asm.mov_mem_reg(RDI, 0, RSI),
        }
        asm.mov_reg_imm64(RAX, NIL_TAG as i64);
        asm.ret();
    }

    // rt_cstr: rdi = string -> rax = address of a NUL-terminated copy.
    asm.bind_symbol("rt_cstr");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RCX, RDI, 0);
    asm.mov_mem_reg(RBP, -8, RCX); // len
    asm.mov_mem_reg(RBP, -16, RDI); // source base
    asm.mov_reg_reg(RDI, RCX);
    asm.add_imm32(RDI, 1);
    asm.call_sym("rt_alloc");
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.mov_reg_reg(RDI, RAX);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RCX, RBP, -8);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.mov_reg_reg(RAX, RDX);
    asm.add_rr(RAX, RCX);
    asm.mov_byte_mem_imm(RAX, 0, 0);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_ccall: rdi = fn address, rsi = argument list -> rax = result.
    asm.bind_symbol("rt_ccall");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 128);
    asm.sar_imm(RDI, 3);
    asm.mov_mem_reg(RBP, -8, RDI); // fn
    asm.mov_reg_reg(RAX, RSI);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RAX, R11);
    asm.mov_reg_mem(RCX, RAX, 0);
    asm.mov_mem_reg(RBP, -24, RCX); // len
    asm.mov_reg_mem(RCX, RAX, 16);
    asm.mov_mem_reg(RBP, -32, RCX); // data
    asm.xor_rr(RAX, RAX);
    for off in [-40, -48, -56, -64, -72, -80] {
        asm.mov_mem_reg(RBP, off, RAX);
    }
    asm.mov_mem_reg(RBP, -88, RAX); // i
    let cc_loop = asm.new_label();
    let cc_done = asm.new_label();
    asm.bind(cc_loop);
    asm.mov_reg_mem(RAX, RBP, -88);
    asm.cmp_imm32(RAX, 6);
    asm.jcc(CC_GE, cc_done);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, cc_done);
    asm.mov_reg_mem(RDX, RBP, -32);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RDX, RCX);
    asm.mov_reg_mem(RDX, RDX, 0);
    asm.sar_imm(RDX, 3);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 3);
    asm.mov_reg_reg(RSI, RBP);
    asm.sub_imm32(RSI, 40);
    asm.sub_rr(RSI, RCX);
    asm.mov_mem_reg(RSI, 0, RDX);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -88, RAX);
    asm.jmp(cc_loop);
    asm.bind(cc_done);
    asm.mov_reg_mem(RDI, RBP, -40);
    asm.mov_reg_mem(RSI, RBP, -48);
    asm.mov_reg_mem(RDX, RBP, -56);
    asm.mov_reg_mem(RCX, RBP, -64);
    asm.mov_reg_mem(R8, RBP, -72);
    asm.mov_reg_mem(R9, RBP, -80);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.call_reg(RAX);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_extern_c: rdi = fn address -> rax = callable foreign-function value.
    asm.bind_symbol("rt_extern_c");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.sar_imm(RDI, 3);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc");
    asm.mov_reg_imm64(RCX, -1);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_reg_abs(R11, AbsRef::CodeSym("rt_c_trampoline".to_string()));
    asm.mov_mem_reg(RAX, 8, R11);
    asm.mov_reg_mem(RCX, RBP, -8);
    asm.mov_mem_reg(RAX, 16, RCX);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_c_trampoline: entered with r11 = foreign object, args already in the
    // C-ABI registers. Calls the target and tags the return value.
    // The six integer argument registers are Maylang tagged values; the C ABI
    // wants raw words, so untag them (unused ones are ignored by the callee).
    asm.bind_symbol("rt_c_trampoline");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    for reg in [RDI, RSI, RDX, RCX, R8, R9] {
        asm.sar_imm(reg, 3);
    }
    asm.mov_reg_mem(RAX, R11, 16);
    asm.call_reg(RAX);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

#[derive(Clone, Copy)]
enum FlOp {
    Sub,
    Mul,
    Div,
}

/// Emit a numeric binary op that dispatches int vs boxed float with runtime
/// type checking.
fn emit_numeric_binop(asm: &mut Asm, name: &str, op: FlOp, symbol: usize, method: &str) {
    asm.bind_symbol(name);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_l = asm.new_label();
    asm.jcc(CC_E, float_l);
    asm.cmp_imm32(RCX, FLOAT_TAG);
    asm.jcc(CC_E, float_l);
    // Type check: both operands must be tagged integers.
    let type_err = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, type_err);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, type_err);
    // int path
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    match op {
        FlOp::Sub => {
            asm.sub_rr(RDI, RSI);
            let sub_ok = asm.new_label();
            asm.jcc(CC_NO, sub_ok);
            asm.call_sym("raise_overflow");
            asm.bind(sub_ok);
            asm.mov_reg_reg(RAX, RDI);
        }
        FlOp::Mul => {
            // Multiply in the untagged domain, then check that the product fits
            // in the 61-bit immediate range before re-tagging.
            asm.mov_reg_reg(RAX, RDI);
            asm.sar_imm(RAX, 3);
            asm.mov_reg_reg(RCX, RSI);
            asm.sar_imm(RCX, 3);
            asm.imul_rr(RAX, RCX);
            let mul_ok = asm.new_label();
            asm.jcc(CC_NO, mul_ok);
            asm.call_sym("raise_overflow");
            asm.bind(mul_ok);
            asm.mov_reg_imm64(R11, 1);
            asm.shl_imm(R11, 60); // 2^60
            asm.mov_reg_reg(RDX, R11);
            asm.neg(RDX); // -2^60
            asm.cmp_rr(RAX, RDX);
            let mul_ovf = asm.new_label();
            asm.jcc(CC_L, mul_ovf);
            asm.cmp_rr(RAX, R11);
            asm.jcc(CC_GE, mul_ovf);
            let mul_done = asm.new_label();
            asm.jmp(mul_done);
            asm.bind(mul_ovf);
            asm.call_sym("raise_overflow");
            asm.bind(mul_done);
            asm.shl_imm(RAX, 3);
        }
        FlOp::Div => {
            asm.sar_imm(RDI, 3);
            asm.sar_imm(RSI, 3);
            let nonzero = asm.new_label();
            asm.test_rr(RSI, RSI);
            asm.jcc(CC_NE, nonzero);
            asm.call_sym("raise_div_zero");
            asm.bind(nonzero);
            asm.mov_reg_reg(RAX, RDI);
            asm.mov_reg_reg(RCX, RSI);
            asm.cqo();
            asm.idiv(RCX);
            asm.shl_imm(RAX, 3);
        }
    }
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    // type error: raise a structured `type` fault (unless operator-overloaded).
    asm.bind(type_err);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let no_overload = asm.new_label();
    asm.jcc(CC_NE, no_overload);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym(method);
    asm.cmp_imm32(RAX, NIL_TAG as i32);
    asm.jcc(CC_E, no_overload);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(no_overload);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.mov_reg_abs(RDX, AbsRef::Data(symbol));
    asm.add_imm32(RDX, 1);
    asm.call_sym("raise_binop_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    // float path
    asm.bind(float_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_rr(XMM1, XMM0);
    asm.movsd_load(XMM0, RBP, -24);
    if let FlOp::Div = op {
        asm.xorps(XMM2, XMM2);
        asm.comisd(XMM1, XMM2);
        let ok = asm.new_label();
        asm.jcc(CC_NE, ok);
        asm.call_sym("raise_div_zero");
        asm.bind(ok);
    }
    match op {
        FlOp::Sub => asm.subsd(XMM0, XMM1),
        FlOp::Mul => asm.mulsd(XMM0, XMM1),
        FlOp::Div => asm.divsd(XMM0, XMM1),
    }
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_binops(asm: &mut Asm, data: &RuntimeData) {
    emit_numeric_binop(asm, "rt_sub", FlOp::Sub, data.sym_sub, "__op_sub");
    emit_numeric_binop(asm, "rt_mul", FlOp::Mul, data.sym_mul, "__op_mul");
    emit_numeric_binop(asm, "rt_div", FlOp::Div, data.sym_div, "__op_div");

    // rt_mod: ints `%` ints, or float remainder.
    asm.bind_symbol("rt_mod");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let mod_float = asm.new_label();
    asm.jcc(CC_E, mod_float);
    asm.cmp_imm32(RCX, FLOAT_TAG);
    asm.jcc(CC_E, mod_float);
    let mod_type = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, mod_type);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, mod_type);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.sar_imm(RDI, 3);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.sar_imm(RSI, 3);
    let mod_nonzero = asm.new_label();
    asm.test_rr(RSI, RSI);
    asm.jcc(CC_NE, mod_nonzero);
    asm.call_sym("raise_div_zero");
    asm.bind(mod_nonzero);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_reg(RCX, RSI);
    asm.cqo();
    asm.idiv(RCX);
    asm.mov_reg_reg(RAX, RDX);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(mod_float);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_rr(XMM1, XMM0);
    asm.xorps(XMM2, XMM2);
    asm.comisd(XMM1, XMM2);
    let mod_ok = asm.new_label();
    asm.jcc(CC_NE, mod_ok);
    asm.call_sym("raise_div_zero");
    asm.bind(mod_ok);
    asm.movsd_load(XMM0, RBP, -24);
    asm.movsd_rr(XMM2, XMM0);
    asm.divsd(XMM2, XMM1);
    asm.cvttsd2si(RAX, XMM2);
    asm.cvtsi2sd(XMM2, RAX);
    asm.mulsd(XMM2, XMM1);
    asm.subsd(XMM0, XMM2);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(mod_type);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.mov_reg_abs(RDX, AbsRef::Data(data.sym_mod));
    asm.add_imm32(RDX, 1);
    asm.call_sym("raise_binop_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();

    // rt_neg
    asm.bind_symbol("rt_neg");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_l = asm.new_label();
    asm.jcc(CC_E, float_l);
    asm.neg(RDI);
    asm.mov_reg_reg(RAX, RDI);
    asm.ret();
    asm.bind(float_l);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.movsd_load(XMM0, RDI, 0);
    asm.xorps(XMM1, XMM1);
    asm.subsd(XMM1, XMM0);
    asm.movsd_rr(XMM0, XMM1);
    asm.jmp_sym("rt_box_float");

    // rt_pow: int^int (non-negative exponent) fast path; everything else is
    // routed through `rt_powf` (x87), matching the VM's `powf` fallback.
    asm.bind_symbol("rt_pow");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    let powf = asm.new_label();
    // float exponent -> powf
    asm.cmp_imm32(RCX, FLOAT_TAG);
    asm.jcc(CC_E, powf);
    // negative integer exponent -> powf
    asm.mov_reg_reg(RDX, RSI);
    asm.sar_imm(RDX, 3);
    asm.test_rr(RDX, RDX);
    asm.jcc(CC_S, powf);
    // integer exponent: base must be int or float
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_pow = asm.new_label();
    asm.jcc(CC_E, float_pow);
    let pow_type = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, pow_type);
    // int path (work in raw integers)
    asm.mov_mem_reg(RBP, -16, RDX);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.sar_imm(RAX, 3);
    asm.mov_mem_reg(RBP, -40, RAX);
    asm.mov_reg_imm64(RAX, 1);
    asm.mov_mem_reg(RBP, -24, RAX);
    let loop_l = asm.new_label();
    let done_l = asm.new_label();
    asm.bind(loop_l);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, done_l);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_mem(RDX, RBP, -40);
    asm.imul_rr(RAX, RDX);
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.sub_imm32(RCX, 1);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.jmp(loop_l);
    asm.bind(done_l);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    // float base, integer exponent
    asm.bind(float_pow);
    asm.mov_mem_reg(RBP, -16, RDX);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -32, XMM0);
    asm.mov_reg_imm64(RAX, 1);
    asm.cvtsi2sd(XMM0, RAX);
    let loop_f = asm.new_label();
    let done_f = asm.new_label();
    asm.bind(loop_f);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, done_f);
    asm.movsd_load(XMM1, RBP, -32);
    asm.mulsd(XMM0, XMM1);
    asm.sub_imm32(RCX, 1);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.jmp(loop_f);
    asm.bind(done_f);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    // float exponent or negative exponent: base^exp as a float.
    asm.bind(powf);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_powf");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    // non-numeric operand
    asm.bind(pow_type);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("raise_exp_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// rt_raise: rdi = error value. Unwinds to the innermost `may` handler, or
/// reports the error and exits if there is none.
fn emit_raise(asm: &mut Asm, target: Target, depth_slot: usize, stack_off: usize) {
    asm.bind_symbol("rt_raise");
    asm.mov_reg_abs(R11, AbsRef::Data(depth_slot));
    asm.mov_reg_mem(RCX, R11, 0);
    let uncaught = asm.new_label();
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, uncaught);
    asm.sub_imm32(RCX, 1);
    asm.mov_mem_reg(R11, 0, RCX);
    // entry = stack + rcx * 24
    asm.mov_reg_reg(RDX, RCX);
    asm.shl_imm(RDX, 1);
    asm.add_rr(RDX, RCX);
    asm.shl_imm(RDX, 3);
    asm.mov_reg_abs(R11, AbsRef::Data(stack_off));
    asm.add_rr(RDX, R11);
    asm.mov_reg_mem(RAX, RDX, 0);
    asm.mov_reg_mem(RSI, RDX, 8);
    asm.mov_reg_mem(R11, RDX, 16);
    asm.mov_reg_reg(RSP, RAX);
    asm.mov_reg_reg(RBP, RSI);
    asm.jmp_reg(R11);
    asm.bind(uncaught);
    asm.call_sym("print_error");
    asm.mov_reg_imm64(RAX, target.exit_nr());
    asm.mov_reg_imm64(RDI, 70);
    asm.syscall();
}

/// rt_call: r11 = first-class function value; arguments in RDI, RSI, RDX, ...
fn emit_call(asm: &mut Asm, data: &RuntimeData) {
    asm.bind_symbol("rt_call");
    // Use R10 as scratch: RCX/RDX/R8/R9 may hold argument registers.
    asm.mov_reg_reg(RAX, R11);
    asm.mov_reg_imm64(R10, 7);
    asm.and_rr(RAX, R10);
    asm.cmp_imm32(RAX, LIST_TAG);
    let bad = asm.new_label();
    asm.jcc(CC_NE, bad);
    asm.mov_reg_imm64(R10, -8);
    asm.and_rr(R11, R10);
    asm.mov_reg_mem(RAX, R11, 0);
    asm.mov_reg_imm64(R10, -1);
    asm.cmp_rr(RAX, R10);
    asm.jcc(CC_NE, bad);
    asm.mov_reg_mem(RAX, R11, 8); // code address
    asm.mov_reg_imm64(R10, -8);
    asm.and_rr(R11, R10); // r11 = untagged closure object
    asm.jmp_reg(RAX);
    asm.bind(bad);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.not_callable));
    asm.add_imm32(RDI, 1);
    asm.call_sym("rt_raise");
}

/// rt_range: rdi = start (tagged int), rsi = end (tagged int),
/// rdx = inclusive flag. Returns a list of integers.
fn emit_range(asm: &mut Asm) {
    asm.bind_symbol("rt_range");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.sar_imm(RDI, 3);
    asm.sar_imm(RSI, 3);
    asm.sar_imm(RDX, 3);
    asm.test_rr(RDX, RDX);
    let no_inc = asm.new_label();
    asm.jcc(CC_E, no_inc);
    asm.add_imm32(RSI, 1);
    asm.bind(no_inc);
    asm.mov_mem_reg(RBP, -8, RDI); // start
    asm.mov_mem_reg(RBP, -16, RSI); // end
    // step = sign(end - start); count = |end - start| (ranges may descend).
    asm.mov_reg_reg(RAX, RSI);
    asm.sub_rr(RAX, RDI);
    asm.mov_reg_imm64(RCX, 1);
    let asc = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NS, asc);
    asm.mov_reg_imm64(RCX, -1);
    asm.neg(RAX);
    asm.bind(asc);
    asm.mov_mem_reg(RBP, -56, RCX); // step
    asm.mov_mem_reg(RBP, -24, RAX); // count
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc_list");
    asm.mov_mem_reg(RBP, -32, RAX); // header
    asm.mov_reg_mem(RDI, RBP, -24);
    asm.shl_imm(RDI, 3);
    let have = asm.new_label();
    asm.test_rr(RDI, RDI);
    asm.jcc(CC_NE, have);
    asm.mov_reg_imm64(RDI, 8);
    asm.bind(have);
    asm.call_sym("rt_alloc_array");
    asm.mov_mem_reg(RBP, -40, RAX); // data
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.mov_mem_reg(RAX, 16, RCX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -48, RAX); // i
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, done);
    // value = start + i * step
    asm.mov_reg_mem(RDX, RBP, -56);
    asm.imul_rr(RDX, RAX);
    asm.mov_reg_mem(RCX, RBP, -8);
    asm.add_rr(RDX, RCX);
    asm.shl_imm(RDX, 3);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.shl_imm(RAX, 3);
    asm.add_rr(RCX, RAX);
    asm.mov_mem_reg(RCX, 0, RDX);
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -48, RAX);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_single(asm: &mut Asm, name: &str, data_offset: usize) {
    asm.bind_symbol(name);
    asm.mov_reg_abs(RDI, AbsRef::Data(data_offset));
    asm.call_sym("rt_print_cstr");
    asm.ret();
}

fn emit_print_int(asm: &mut Asm) {
    asm.bind_symbol("rt_print_int");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_reg_reg(RAX, RDI);
    asm.xor_rr(R8, R8);
    asm.test_rr(RAX, RAX);
    let positive = asm.new_label();
    asm.jcc(CC_NS, positive);
    asm.neg(RAX);
    asm.mov_reg_imm64(R8, 1);
    asm.bind(positive);
    asm.lea(RSI, RBP, -1);
    asm.mov_reg_reg(R9, RSI);
    asm.mov_reg_imm64(R10, 10);
    let loop_label = asm.new_label();
    asm.bind(loop_label);
    asm.xor_rr(RDX, RDX);
    asm.div(R10);
    asm.add_imm32(RDX, '0' as i32);
    asm.sub_imm32(RSI, 1);
    asm.mov_byte_mem_reg(RSI, 0, RDX);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, loop_label);
    let no_sign = asm.new_label();
    asm.test_rr(R8, R8);
    asm.jcc(CC_E, no_sign);
    asm.sub_imm32(RSI, 1);
    asm.mov_byte_mem_imm(RSI, 0, b'-');
    asm.bind(no_sign);
    asm.mov_reg_reg(RDX, R9);
    asm.sub_rr(RDX, RSI);
    asm.call_sym("rt_write");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// rt_memcpy: rdi = dst, rsi = src, rdx = count.
fn emit_memcpy(asm: &mut Asm) {
    asm.bind_symbol("rt_memcpy");
    asm.xor_rr(R8, R8);
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.cmp_rr(R8, RDX);
    asm.jcc(CC_GE, done);
    asm.mov_reg_reg(R9, RSI);
    asm.add_rr(R9, R8);
    asm.movzx_byte_mem(RAX, R9, 0);
    asm.mov_reg_reg(R10, RDI);
    asm.add_rr(R10, R8);
    asm.mov_byte_mem_reg(R10, 0, RAX);
    asm.add_imm32(R8, 1);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.ret();
}

fn emit_len(asm: &mut Asm) {
    asm.bind_symbol("rt_len");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let map = asm.new_label();
    asm.jcc(CC_E, map);
    let str = asm.new_label();
    asm.cmp_imm32(RAX, STR_TAG);
    asm.jcc(CC_E, str);
    asm.cmp_imm32(RAX, LIST_TAG);
    let list = asm.new_label();
    asm.jcc(CC_E, list);
    asm.xor_rr(RAX, RAX);
    asm.ret();
    // Lists: the stored element count.
    asm.bind(list);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.mov_reg_imm64(R11, -1);
    asm.cmp_rr(RAX, R11);
    let not_fun = asm.new_label();
    asm.jcc(CC_NE, not_fun);
    asm.xor_rr(RAX, RAX);
    asm.ret();
    asm.bind(not_fun);
    asm.shl_imm(RAX, 3);
    asm.ret();
    // Strings: count UTF-8 codepoints (skip continuation bytes 10xxxxxx).
    asm.bind(str);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RDX, RDI, 0); // byte length
    asm.add_imm32(RDI, 8);
    asm.add_rr(RDX, RDI); // end pointer
    asm.xor_rr(RAX, RAX); // codepoint count
    let str_loop = asm.new_label();
    let str_skip = asm.new_label();
    let str_done = asm.new_label();
    asm.bind(str_loop);
    asm.cmp_rr(RDI, RDX);
    asm.jcc(CC_AE, str_done);
    asm.movzx_byte_mem(RCX, RDI, 0);
    asm.mov_reg_reg(R8, RCX);
    asm.mov_reg_imm64(R11, 0xC0);
    asm.and_rr(R8, R11);
    asm.cmp_imm32(R8, 0x80);
    asm.jcc(CC_E, str_skip);
    asm.add_imm32(RAX, 1);
    asm.bind(str_skip);
    asm.add_imm32(RDI, 1);
    asm.jmp(str_loop);
    asm.bind(str_done);
    asm.shl_imm(RAX, 3);
    asm.ret();
    asm.bind(map);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.sar_imm(RAX, 1);
    asm.shl_imm(RAX, 3);
    asm.ret();
}

fn emit_str_cat(asm: &mut Asm) {
    asm.bind_symbol("rt_str_cat");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.and_rr(RSI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RCX, RDI, 0);
    asm.mov_mem_reg(RBP, -24, RCX);
    asm.mov_reg_mem(RDX, RSI, 0);
    asm.mov_mem_reg(RBP, -32, RDX);
    asm.add_rr(RCX, RDX);
    asm.mov_mem_reg(RBP, -40, RCX); // total
    asm.mov_reg_reg(RDI, RCX);
    asm.add_imm32(RDI, 8);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -48, RAX);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.mov_mem_reg(RAX, 0, RCX); // len
    asm.mov_reg_mem(RDI, RBP, -48);
    asm.add_imm32(RDI, 8);
    asm.mov_reg_mem(RSI, RBP, -8);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RDI, RBP, -48);
    asm.add_imm32(RDI, 8);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.add_rr(RDI, RAX);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RDX, RBP, -32);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RAX, RBP, -48);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_char_at(asm: &mut Asm) {
    // `rt_char_at(s, i)` -> the i-th UTF-8 codepoint of `s` as a tagged int.
    asm.bind_symbol("rt_char_at");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.sar_imm(RSI, 3); // codepoint index
    let missing = asm.new_label();
    asm.test_rr(RSI, RSI);
    asm.jcc(CC_S, missing);
    asm.mov_reg_mem(RDX, RDI, 0); // byte length
    asm.add_imm32(RDI, 8); // byte pointer
    asm.add_rr(RDX, RDI); // end
    asm.xor_rr(RCX, RCX); // codepoint counter
    let next = asm.new_label();
    let adv = asm.new_label();
    let adv1 = asm.new_label();
    let decode = asm.new_label();
    asm.bind(next);
    asm.cmp_rr(RCX, RSI);
    asm.jcc(CC_E, decode);
    asm.cmp_rr(RDI, RDX);
    asm.jcc(CC_AE, missing);
    asm.movzx_byte_mem(RAX, RDI, 0);
    asm.mov_reg_imm64(R11, 1);
    asm.cmp_imm32(RAX, 0x80);
    asm.jcc(CC_B, adv1);
    asm.mov_reg_imm64(R11, 2);
    asm.cmp_imm32(RAX, 0xE0);
    asm.jcc(CC_B, adv);
    asm.mov_reg_imm64(R11, 3);
    asm.cmp_imm32(RAX, 0xF0);
    asm.jcc(CC_B, adv);
    asm.mov_reg_imm64(R11, 4);
    asm.jmp(adv);
    asm.bind(adv1);
    asm.mov_reg_imm64(R11, 1);
    asm.bind(adv);
    asm.add_rr(RDI, R11);
    asm.add_imm32(RCX, 1);
    asm.jmp(next);
    asm.bind(decode);
    asm.cmp_rr(RDI, RDX);
    asm.jcc(CC_AE, missing);
    asm.movzx_byte_mem(RAX, RDI, 0);
    let ret_int = asm.new_label();
    let dec2 = asm.new_label();
    let dec3 = asm.new_label();
    asm.cmp_imm32(RAX, 0x80);
    asm.jcc(CC_B, ret_int);
    asm.cmp_imm32(RAX, 0xE0);
    asm.jcc(CC_B, dec2);
    asm.cmp_imm32(RAX, 0xF0);
    asm.jcc(CC_B, dec3);
    // four-byte sequence
    asm.mov_reg_imm64(R11, 0x07);
    asm.and_rr(RAX, R11);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 1);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 2);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 3);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.jmp(ret_int);
    asm.bind(dec3);
    asm.mov_reg_imm64(R11, 0x0F);
    asm.and_rr(RAX, R11);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 1);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 2);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.jmp(ret_int);
    asm.bind(dec2);
    asm.mov_reg_imm64(R11, 0x1F);
    asm.and_rr(RAX, R11);
    asm.shl_imm(RAX, 6);
    asm.movzx_byte_mem(R8, RDI, 1);
    asm.mov_reg_imm64(R11, 0x3F);
    asm.and_rr(R8, R11);
    asm.or_rr(RAX, R8);
    asm.bind(ret_int);
    asm.shl_imm(RAX, 3);
    asm.ret();
    asm.bind(missing);
    asm.mov_reg_imm64(RAX, -8); // tagged -1
    asm.ret();
}

fn emit_char_from(asm: &mut Asm) {
    // `rt_char_from(code)` -> a UTF-8 encoded string for a Unicode codepoint.
    asm.bind_symbol("rt_char_from");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.sar_imm(RDI, 3);
    asm.mov_mem_reg(RBP, -8, RDI); // codepoint
    asm.mov_reg_imm64(RSI, 1);
    asm.cmp_imm32(RDI, 0x80);
    let clen = asm.new_label();
    asm.jcc(CC_B, clen);
    asm.mov_reg_imm64(RSI, 2);
    asm.cmp_imm32(RDI, 0x800);
    asm.jcc(CC_B, clen);
    asm.mov_reg_imm64(RSI, 3);
    asm.cmp_imm32(RDI, 0x10000);
    asm.jcc(CC_B, clen);
    asm.mov_reg_imm64(RSI, 4);
    asm.bind(clen);
    asm.mov_mem_reg(RBP, -16, RSI); // byte length
    asm.lea(RDI, RSI, 8);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -24, RAX); // payload pointer
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_mem_reg(RAX, 0, RCX); // string byte length
    asm.mov_reg_mem(R8, RBP, -8); // codepoint
    asm.mov_reg_mem(RSI, RBP, -16);
    let e1 = asm.new_label();
    let e2 = asm.new_label();
    let e3 = asm.new_label();
    let fin = asm.new_label();
    asm.cmp_imm32(RSI, 1);
    asm.jcc(CC_E, e1);
    asm.cmp_imm32(RSI, 2);
    asm.jcc(CC_E, e2);
    asm.cmp_imm32(RSI, 3);
    asm.jcc(CC_E, e3);
    // 4-byte sequence.
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 18);
    asm.mov_reg_imm64(R10, 0xF0);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 8, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 12);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 9, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 6);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 10, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 11, RCX);
    asm.jmp(fin);
    asm.bind(e3);
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 12);
    asm.mov_reg_imm64(R10, 0xE0);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 8, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 6);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 9, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 10, RCX);
    asm.jmp(fin);
    asm.bind(e2);
    asm.mov_reg_reg(RCX, R8);
    asm.shr_imm(RCX, 6);
    asm.mov_reg_imm64(R10, 0xC0);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 8, RCX);
    asm.mov_reg_reg(RCX, R8);
    asm.mov_reg_imm64(R10, 0x3F);
    asm.and_rr(RCX, R10);
    asm.mov_reg_imm64(R10, 0x80);
    asm.or_rr(RCX, R10);
    asm.mov_byte_mem_reg(RAX, 9, RCX);
    asm.jmp(fin);
    asm.bind(e1);
    asm.mov_byte_mem_reg(RAX, 8, R8);
    asm.bind(fin);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_int_to_str(asm: &mut Asm) {
    asm.bind_symbol("rt_int_to_str");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_reg_reg(RAX, RDI);
    asm.xor_rr(R8, R8);
    asm.test_rr(RAX, RAX);
    let positive = asm.new_label();
    asm.jcc(CC_NS, positive);
    asm.neg(RAX);
    asm.mov_reg_imm64(R8, 1);
    asm.bind(positive);
    asm.mov_mem_reg(RBP, -8, RAX); // absolute value
    asm.mov_mem_reg(RBP, -40, R8); // sign flag (allocation clobbers R8)
    asm.mov_reg_imm64(RDI, 48);
    asm.call_sym("rt_alloc_str");
    asm.mov_reg_mem(R8, RBP, -40); // restore sign
    asm.mov_mem_reg(RBP, -16, RAX); // header
    asm.mov_reg_reg(RSI, RAX);
    asm.add_imm32(RSI, 48); // end of the digit buffer
    asm.mov_mem_reg(RBP, -24, RSI);
    asm.mov_reg_imm64(R10, 10);
    asm.mov_reg_mem(RAX, RBP, -8);
    let loop_label = asm.new_label();
    asm.bind(loop_label);
    asm.xor_rr(RDX, RDX);
    asm.div(R10);
    asm.add_imm32(RDX, '0' as i32);
    asm.sub_imm32(RSI, 1);
    asm.mov_byte_mem_reg(RSI, 0, RDX);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, loop_label);
    let no_sign = asm.new_label();
    asm.test_rr(R8, R8);
    asm.jcc(CC_E, no_sign);
    asm.sub_imm32(RSI, 1);
    asm.mov_byte_mem_imm(RSI, 0, b'-');
    asm.bind(no_sign);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.sub_rr(RDX, RSI);
    asm.mov_mem_reg(RBP, -32, RDX); // length
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.add_imm32(RDI, 8);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RAX, RBP, -16);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_str_of(asm: &mut Asm, data: &RuntimeData) {
    asm.bind_symbol("rt_str_of");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, STR_TAG);
    let self_ = asm.new_label();
    asm.jcc(CC_E, self_);
    asm.cmp_imm32(RAX, NIL_TAG);
    let nil = asm.new_label();
    asm.jcc(CC_E, nil);
    asm.cmp_imm32(RAX, FALSE_TAG);
    let false_l = asm.new_label();
    asm.jcc(CC_E, false_l);
    asm.cmp_imm32(RAX, TRUE_TAG);
    let true_l = asm.new_label();
    asm.jcc(CC_E, true_l);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_l = asm.new_label();
    asm.jcc(CC_E, float_l);
    let container = asm.new_label();
    asm.cmp_imm32(RAX, LIST_TAG);
    asm.jcc(CC_E, container);
    asm.cmp_imm32(RAX, MAP_TAG);
    asm.jcc(CC_E, container);
    asm.sar_imm(RDI, 3);
    asm.jmp_sym("rt_int_to_str"); // tail call
    asm.bind(container);
    asm.call_sym("string_repr");
    asm.ret();
    asm.bind(self_);
    asm.mov_reg_reg(RAX, RDI);
    asm.ret();
    asm.bind(nil);
    asm.mov_reg_abs(RAX, AbsRef::Data(data.nil));
    asm.ret();
    asm.bind(false_l);
    asm.mov_reg_abs(RAX, AbsRef::Data(data.false_));
    asm.ret();
    asm.bind(true_l);
    asm.mov_reg_abs(RAX, AbsRef::Data(data.true_));
    asm.ret();
    asm.bind(float_l);
    asm.jmp_sym("float_str");
}

fn emit_value_eq(asm: &mut Asm) {
    asm.bind_symbol("rt_value_eq");
    asm.cmp_rr(RDI, RSI);
    let true_l = asm.new_label();
    asm.jcc(CC_E, true_l);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    asm.cmp_rr(RAX, RCX);
    let false_l = asm.new_label();
    asm.jcc(CC_NE, false_l);
    asm.cmp_imm32(RAX, STR_TAG);
    asm.jcc(CC_NE, false_l);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.and_rr(RSI, R11);
    asm.mov_reg_mem(RCX, RDI, 0);
    asm.mov_reg_mem(RDX, RSI, 0);
    asm.cmp_rr(RCX, RDX);
    asm.jcc(CC_NE, false_l);
    asm.xor_rr(R8, R8);
    let loop_label = asm.new_label();
    asm.bind(loop_label);
    asm.cmp_rr(R8, RCX);
    asm.jcc(CC_GE, true_l);
    asm.mov_reg_reg(R9, RDI);
    asm.add_rr(R9, R8);
    asm.movzx_byte_mem(RAX, R9, 8);
    asm.mov_reg_reg(R10, RSI);
    asm.add_rr(R10, R8);
    asm.movzx_byte_mem(R11, R10, 8);
    asm.cmp_rr(RAX, R11);
    asm.jcc(CC_NE, false_l);
    asm.add_imm32(R8, 1);
    asm.jmp(loop_label);
    asm.bind(true_l);
    asm.mov_reg_imm64(RAX, TRUE_TAG as i64);
    asm.ret();
    asm.bind(false_l);
    asm.mov_reg_imm64(RAX, FALSE_TAG as i64);
    asm.ret();
}

fn emit_str_cmp(asm: &mut Asm) {
    asm.bind_symbol("rt_str_cmp");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.and_rr(RSI, R11);
    asm.mov_reg_mem(RCX, RDI, 0);
    asm.mov_reg_mem(RDX, RSI, 0);
    asm.mov_reg_reg(R8, RCX);
    let min_ok = asm.new_label();
    asm.cmp_rr(R8, RDX);
    asm.jcc(CC_LE, min_ok);
    asm.mov_reg_reg(R8, RDX);
    asm.bind(min_ok);
    asm.xor_rr(R9, R9);
    let loop_label = asm.new_label();
    let prefix = asm.new_label();
    let lt = asm.new_label();
    let gt = asm.new_label();
    asm.bind(loop_label);
    asm.cmp_rr(R9, R8);
    asm.jcc(CC_GE, prefix);
    asm.mov_reg_reg(R10, RDI);
    asm.add_rr(R10, R9);
    asm.movzx_byte_mem(RAX, R10, 8);
    asm.mov_reg_reg(R10, RSI);
    asm.add_rr(R10, R9);
    asm.movzx_byte_mem(R11, R10, 8);
    asm.cmp_rr(RAX, R11);
    asm.jcc(CC_L, lt);
    asm.jcc(CC_G, gt);
    asm.add_imm32(R9, 1);
    asm.jmp(loop_label);
    asm.bind(prefix);
    asm.cmp_rr(RCX, RDX);
    asm.jcc(CC_L, lt);
    asm.jcc(CC_G, gt);
    asm.xor_rr(RAX, RAX);
    asm.ret();
    asm.bind(lt);
    asm.mov_reg_imm64(RAX, -8);
    asm.ret();
    asm.bind(gt);
    asm.mov_reg_imm64(RAX, 8);
    asm.ret();
}

fn emit_map_get(asm: &mut Asm) {
    asm.bind_symbol("rt_map_get");
    // Non-map receivers (e.g. nil from `?.`) yield nil instead of faulting.
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let is_map = asm.new_label();
    asm.jcc(CC_E, is_map);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.ret();
    asm.bind(is_map);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -32, RAX);
    let loop_label = asm.new_label();
    let not_found = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, not_found);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.mov_reg_mem(RDX, RDX, 16);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RDX, RCX);
    asm.mov_mem_reg(RBP, -40, RDX);
    asm.mov_reg_mem(RDI, RDX, 0);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_value_eq");
    asm.cmp_imm32(RAX, TRUE_TAG);
    let found = asm.new_label();
    asm.jcc(CC_E, found);
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.add_imm32(RAX, 2);
    asm.mov_mem_reg(RBP, -32, RAX);
    asm.jmp(loop_label);
    asm.bind(found);
    asm.mov_reg_mem(RDX, RBP, -40);
    asm.mov_reg_mem(RAX, RDX, 8);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(not_found);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_map_set(asm: &mut Asm) {
    asm.bind_symbol("rt_map_set");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let is_map = asm.new_label();
    asm.jcc(CC_E, is_map);
    asm.mov_reg_reg(RAX, RDX); // return the value, ignore the write
    asm.ret();
    asm.bind(is_map);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_mem_reg(RBP, -24, RDX);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.mov_mem_reg(RBP, -32, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -40, RAX);
    let loop_label = asm.new_label();
    let append = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RAX, RBP, -40);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, append);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.mov_reg_mem(RDX, RDX, 16);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RDX, RCX);
    asm.mov_mem_reg(RBP, -48, RDX);
    asm.mov_reg_mem(RDI, RDX, 0);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_value_eq");
    asm.cmp_imm32(RAX, TRUE_TAG);
    let update = asm.new_label();
    asm.jcc(CC_E, update);
    asm.mov_reg_mem(RAX, RBP, -40);
    asm.add_imm32(RAX, 2);
    asm.mov_mem_reg(RBP, -40, RAX);
    asm.jmp(loop_label);
    asm.bind(update);
    asm.mov_reg_mem(RDX, RBP, -48);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_mem_reg(RDX, 8, RAX);
    let done = asm.new_label();
    asm.jmp(done);
    asm.bind(append);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_push");
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -24);
    asm.call_sym("rt_push");
    asm.bind(done);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.add_imm32(RAX, MAP_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// Build a list from either the keys (`offset = 0`) or values (`offset = 8`)
/// of a flat map.
fn emit_map_keys(asm: &mut Asm, name: &str, offset: i32) {
    asm.bind_symbol(name);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.sar_imm(RAX, 1);
    asm.mov_mem_reg(RBP, -16, RAX); // entries
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc_list");
    asm.mov_mem_reg(RBP, -24, RAX); // header
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.shl_imm(RDI, 3);
    let d = asm.new_label();
    asm.test_rr(RDI, RDI);
    asm.jcc(CC_NE, d);
    asm.mov_reg_imm64(RDI, 8);
    asm.bind(d);
    asm.call_sym("rt_alloc_array");
    asm.mov_mem_reg(RBP, -32, RAX); // data
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_mem_reg(RAX, 16, RCX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -40, RAX); // i
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RAX, RBP, -40);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, done);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.mov_reg_mem(RDX, RDX, 16);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 4); // i * 16 = pair_i * 8
    asm.add_rr(RDX, RCX);
    asm.mov_reg_mem(RDX, RDX, offset);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_reg_reg(R9, RAX);
    asm.shl_imm(R9, 3);
    asm.add_rr(RCX, R9);
    asm.mov_mem_reg(RCX, 0, RDX);
    asm.mov_reg_mem(RAX, RBP, -40);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -40, RAX);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_map_has(asm: &mut Asm) {
    asm.bind_symbol("rt_map_has");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -32, RAX);
    let loop_label = asm.new_label();
    let not_found = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, not_found);
    asm.mov_reg_mem(RDX, RBP, -8);
    asm.mov_reg_mem(RDX, RDX, 16);
    asm.mov_reg_reg(RCX, RAX);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RDX, RCX);
    asm.mov_reg_mem(RDI, RDX, 0);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_value_eq");
    asm.cmp_imm32(RAX, TRUE_TAG);
    let found = asm.new_label();
    asm.jcc(CC_E, found);
    asm.mov_reg_mem(RAX, RBP, -32);
    asm.add_imm32(RAX, 2);
    asm.mov_mem_reg(RBP, -32, RAX);
    asm.jmp(loop_label);
    asm.bind(found);
    asm.mov_reg_imm64(RAX, TRUE_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(not_found);
    asm.mov_reg_imm64(RAX, FALSE_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_to_map(asm: &mut Asm) {
    asm.bind_symbol("rt_to_map");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_imm64(R11, MAP_TAG as i64);
    asm.or_rr(RDI, R11);
    asm.mov_reg_reg(RAX, RDI);
    asm.ret();
}

fn emit_value_tag(asm: &mut Asm) {
    asm.bind_symbol("rt_value_tag");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.shl_imm(RAX, 3);
    asm.ret();
}

fn emit_index(asm: &mut Asm) {
    asm.bind_symbol("rt_index");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, LIST_TAG);
    let list_l = asm.new_label();
    asm.jcc(CC_E, list_l);
    asm.cmp_imm32(RAX, MAP_TAG);
    let map_l = asm.new_label();
    asm.jcc(CC_E, map_l);
    asm.cmp_imm32(RAX, STR_TAG);
    let str_l = asm.new_label();
    asm.jcc(CC_E, str_l);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(list_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.mov_reg_imm64(R11, -1);
    asm.cmp_rr(RAX, R11);
    let not_fun = asm.new_label();
    asm.jcc(CC_NE, not_fun);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(not_fun);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.sar_imm(RSI, 3);
    let in_bounds = asm.new_label();
    asm.test_rr(RSI, RSI);
    asm.jcc(CC_S, in_bounds); // negative -> nil-ish, fall through to guard below
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.cmp_rr(RSI, RAX);
    let oob = asm.new_label();
    asm.jcc(CC_AE, oob);
    asm.mov_reg_mem(RCX, RDI, 16);
    asm.shl_imm(RSI, 3);
    asm.add_rr(RCX, RSI);
    asm.mov_reg_mem(RAX, RCX, 0);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(oob);
    asm.bind(in_bounds);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(map_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_map_get");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(str_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.call_sym("rt_char_at");
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("rt_char_from");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// `rt_iter_get(seq, tagged_i)`: the i-th iterable element. Lists and strings
/// use `rt_index`; maps iterate their keys (`data[2*i]`), so `for k in m` walks
/// keys.
fn emit_iter_get(asm: &mut Asm) {
    asm.bind_symbol("rt_iter_get");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let not_map = asm.new_label();
    asm.jcc(CC_NE, not_map);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.sar_imm(RSI, 3); // entry index
    asm.mov_reg_mem(RCX, RDI, 16); // data array
    asm.shl_imm(RSI, 4); // 2 words per entry
    asm.add_rr(RCX, RSI);
    asm.mov_reg_mem(RAX, RCX, 0);
    asm.ret();
    asm.bind(not_map);
    asm.jmp_sym("rt_index");
}

/// `rt_syscall(nr, args)`: make a raw Linux syscall. `nr` is a tagged integer
/// and `args` is a list of up to six tagged integers; the result is tagged.
/// This is the freestanding escape hatch for low-level/OS access.
fn emit_syscall(asm: &mut Asm) {
    asm.bind_symbol("rt_syscall");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 96);
    asm.sar_imm(RDI, 3);
    asm.mov_mem_reg(RBP, -24, RDI); // syscall number
    asm.mov_mem_reg(RBP, -16, RSI); // argument list
    // Zero the six argument slots.
    for off in [-40, -48, -56, -64, -72, -80] {
        asm.mov_reg_imm64(RAX, 0);
        asm.mov_mem_reg(RBP, off, RAX);
    }
    // n = min(len(args), 6)
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_len");
    asm.sar_imm(RAX, 3);
    asm.cmp_imm32(RAX, 6);
    let clamped = asm.new_label();
    asm.jcc(CC_LE, clamped);
    asm.mov_reg_imm64(RAX, 6);
    asm.bind(clamped);
    asm.mov_mem_reg(RBP, -32, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -88, RAX); // i
    let loop_l = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_l);
    asm.mov_reg_mem(RAX, RBP, -88);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.cmp_rr(RAX, RCX);
    asm.jcc(CC_GE, done);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_mem(RSI, RBP, -88);
    asm.shl_imm(RSI, 3);
    asm.call_sym("rt_index");
    asm.sar_imm(RAX, 3);
    // slot = rbp - 40 - i*8
    asm.mov_reg_mem(RCX, RBP, -88);
    asm.shl_imm(RCX, 3);
    asm.mov_reg_reg(RDX, RBP);
    asm.sub_rr(RDX, RCX);
    asm.sub_imm32(RDX, 40);
    asm.mov_mem_reg(RDX, 0, RAX);
    asm.mov_reg_mem(RAX, RBP, -88);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -88, RAX);
    asm.jmp(loop_l);
    asm.bind(done);
    asm.mov_reg_mem(RDI, RBP, -40);
    asm.mov_reg_mem(RSI, RBP, -48);
    asm.mov_reg_mem(RDX, RBP, -56);
    asm.mov_reg_mem(R10, RBP, -64);
    asm.mov_reg_mem(R8, RBP, -72);
    asm.mov_reg_mem(R9, RBP, -80);
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.syscall();
    asm.shl_imm(RAX, 3);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_set_index(asm: &mut Asm) {
    asm.bind_symbol("rt_set_index");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_mem_reg(RBP, -24, RDX);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let map_l = asm.new_label();
    asm.jcc(CC_E, map_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.sar_imm(RSI, 3);
    asm.mov_reg_mem(RCX, RDI, 16);
    asm.shl_imm(RSI, 3);
    asm.add_rr(RCX, RSI);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.mov_mem_reg(RCX, 0, RDX);
    asm.mov_reg_reg(RAX, RDX);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(map_l);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -16);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.call_sym("rt_map_set");
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_push(asm: &mut Asm) {
    asm.bind_symbol("rt_push");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RAX, R11);
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_mem(RCX, RAX, 0);
    asm.mov_mem_reg(RBP, -24, RCX);
    asm.mov_reg_mem(RDX, RAX, 8);
    asm.cmp_rr(RCX, RDX);
    let have_space = asm.new_label();
    asm.jcc(CC_L, have_space);
    asm.mov_reg_mem(RDX, RAX, 8);
    asm.test_rr(RDX, RDX);
    let double = asm.new_label();
    asm.jcc(CC_NE, double);
    asm.mov_reg_imm64(RDX, 4);
    let alloc = asm.new_label();
    asm.jmp(alloc);
    asm.bind(double);
    asm.shl_imm(RDX, 1);
    asm.bind(alloc);
    asm.mov_mem_reg(RBP, -32, RDX);
    asm.mov_reg_reg(RDI, RDX);
    asm.shl_imm(RDI, 3);
    asm.call_sym("rt_alloc_array");
    asm.mov_mem_reg(RBP, -40, RAX);
    asm.xor_rr(R8, R8);
    let copy_loop = asm.new_label();
    let copied = asm.new_label();
    asm.bind(copy_loop);
    asm.mov_reg_mem(R11, RBP, -24);
    asm.cmp_rr(R8, R11);
    asm.jcc(CC_GE, copied);
    asm.mov_reg_mem(R9, RBP, -8);
    asm.mov_reg_mem(R9, R9, 16);
    asm.mov_reg_reg(R11, R8);
    asm.shl_imm(R11, 3);
    asm.add_rr(R11, R9);
    asm.mov_reg_mem(R10, R11, 0);
    asm.mov_reg_mem(R11, RBP, -40);
    asm.mov_reg_reg(R9, R8);
    asm.shl_imm(R9, 3);
    asm.add_rr(R11, R9);
    asm.mov_mem_reg(R11, 0, R10);
    asm.add_imm32(R8, 1);
    asm.jmp(copy_loop);
    asm.bind(copied);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.mov_reg_mem(RCX, RBP, -40);
    asm.mov_mem_reg(RAX, 16, RCX);
    asm.mov_reg_mem(RCX, RBP, -32);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.bind(have_space);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.mov_reg_mem(RDX, RAX, 16);
    asm.mov_reg_reg(R11, RCX);
    asm.shl_imm(R11, 3);
    asm.add_rr(RDX, R11);
    asm.mov_reg_mem(R11, RBP, -16);
    asm.mov_mem_reg(RDX, 0, R11);
    asm.add_imm32(RCX, 1);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_pop(asm: &mut Asm) {
    asm.bind_symbol("rt_pop");
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.test_rr(RAX, RAX);
    let empty = asm.new_label();
    asm.jcc(CC_E, empty);
    asm.sub_imm32(RAX, 1);
    asm.mov_mem_reg(RDI, 0, RAX);
    asm.mov_reg_mem(RCX, RDI, 16);
    asm.mov_reg_reg(R11, RAX);
    asm.shl_imm(R11, 3);
    asm.add_rr(RCX, R11);
    asm.mov_reg_mem(RAX, RCX, 0);
    asm.ret();
    asm.bind(empty);
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.ret();
}

fn emit_print_list(asm: &mut Asm, _data: &RuntimeData) {
    asm.bind_symbol("rt_print_list");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RDI, R11);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -16, RAX);
    asm.call_sym("rt_lbracket");
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RAX, RDI, 0);
    asm.cmp_rr(RCX, RAX);
    asm.jcc(CC_GE, done);
    let no_sep = asm.new_label();
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, no_sep);
    asm.call_sym("rt_comma");
    asm.bind(no_sep);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RAX, RDI, 16);
    asm.shl_imm(RCX, 3);
    asm.add_rr(RAX, RCX);
    asm.mov_reg_mem(RDI, RAX, 0);
    asm.call_sym("rt_print_repr");
    asm.mov_reg_mem(RAX, RBP, -16);
    asm.add_imm32(RAX, 1);
    asm.mov_mem_reg(RBP, -16, RAX);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.call_sym("rt_rbracket");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_print_map(asm: &mut Asm, data: &RuntimeData) {
    asm.bind_symbol("rt_print_map");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 48);
    asm.mov_mem_reg(RBP, -8, RDI); // map
    // Structured errors print as their message, matching `str` display.
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_abs(RSI, AbsRef::Data(data.err_key));
    asm.add_imm32(RSI, 1);
    asm.call_sym("rt_map_has");
    asm.cmp_imm32(RAX, TRUE_TAG as i32);
    let normal = asm.new_label();
    asm.jcc(CC_NE, normal);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_abs(RSI, AbsRef::Data(data.msg_key));
    asm.add_imm32(RSI, 1);
    asm.call_sym("rt_map_get");
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("rt_print_value");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(normal);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_map_keys"); // rdi = map -> rax = keys list
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("sort"); // prelude sort (comparison-based, stable)
    asm.mov_mem_reg(RBP, -16, RAX); // sorted keys
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.call_sym("rt_lbrace");
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_len"); // tagged length
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.cmp_rr(RCX, RAX);
    asm.jcc(CC_GE, done);
    let no_sep = asm.new_label();
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_E, no_sep);
    asm.call_sym("rt_comma");
    asm.bind(no_sep);
    // key = keys[i]
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_mem(RSI, RBP, -24);
    asm.call_sym("rt_index");
    asm.mov_mem_reg(RBP, -32, RAX); // key
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("rt_print_repr");
    asm.call_sym("rt_colon");
    // value = map_get(map, key)
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_mem(RSI, RBP, -32);
    asm.call_sym("rt_map_get");
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("rt_print_repr");
    asm.mov_reg_mem(RAX, RBP, -24);
    asm.add_imm32(RAX, 8);
    asm.mov_mem_reg(RBP, -24, RAX);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.call_sym("rt_rbrace");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// Print a value using `repr` rules: strings are quoted when nested.
fn emit_print_repr(asm: &mut Asm, data: &RuntimeData) {
    asm.bind_symbol("rt_print_repr");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, STR_TAG);
    let other = asm.new_label();
    asm.jcc(CC_NE, other);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.quote));
    asm.add_imm32(RDI, 1);
    asm.call_sym("rt_print_str");
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_print_str");
    asm.mov_reg_abs(RDI, AbsRef::Data(data.quote));
    asm.add_imm32(RDI, 1);
    asm.call_sym("rt_print_str");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(other);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_print_value");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_print_value(asm: &mut Asm, data: &RuntimeData) {
    asm.bind_symbol("rt_print_value");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, STR_TAG);
    let str_l = asm.new_label();
    asm.jcc(CC_E, str_l);
    asm.cmp_imm32(RAX, NIL_TAG);
    let nil = asm.new_label();
    asm.jcc(CC_E, nil);
    asm.cmp_imm32(RAX, FALSE_TAG);
    let false_l = asm.new_label();
    asm.jcc(CC_E, false_l);
    asm.cmp_imm32(RAX, TRUE_TAG);
    let true_l = asm.new_label();
    asm.jcc(CC_E, true_l);
    asm.cmp_imm32(RAX, LIST_TAG);
    let list_l = asm.new_label();
    asm.jcc(CC_E, list_l);
    asm.cmp_imm32(RAX, MAP_TAG);
    let map_l = asm.new_label();
    asm.jcc(CC_E, map_l);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_l = asm.new_label();
    asm.jcc(CC_E, float_l);
    asm.sar_imm(RDI, 3);
    asm.call_sym("rt_print_int");
    asm.ret();
    asm.bind(str_l);
    asm.call_sym("rt_print_str");
    asm.ret();
    asm.bind(nil);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.nil));
    asm.call_sym("rt_print_cstr");
    asm.ret();
    asm.bind(false_l);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.false_));
    asm.call_sym("rt_print_cstr");
    asm.ret();
    asm.bind(true_l);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.true_));
    asm.call_sym("rt_print_cstr");
    asm.ret();
    asm.bind(list_l);
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, -8);
    asm.and_rr(RAX, R11);
    asm.mov_reg_mem(RCX, RAX, 0);
    asm.mov_reg_imm64(R11, -1);
    asm.cmp_rr(RCX, R11);
    let not_fun = asm.new_label();
    asm.jcc(CC_NE, not_fun);
    asm.mov_reg_abs(RDI, AbsRef::Data(data.fun_repr));
    asm.call_sym("rt_print_cstr");
    asm.ret();
    asm.bind(not_fun);
    asm.call_sym("rt_print_list");
    asm.ret();
    asm.bind(map_l);
    asm.call_sym("rt_print_map");
    asm.ret();
    asm.bind(float_l);
    asm.call_sym("float_str");
    asm.mov_reg_reg(RDI, RAX);
    asm.call_sym("rt_print_str");
    asm.ret();
}

fn emit_add(asm: &mut Asm) {
    asm.bind_symbol("rt_add");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    // both ints?
    let not_int = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, not_int);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, not_int);
    asm.add_rr(RDI, RSI);
    let add_ok = asm.new_label();
    asm.jcc(CC_NO, add_ok);
    asm.call_sym("raise_overflow");
    asm.bind(add_ok);
    asm.mov_reg_reg(RAX, RDI);
    asm.ret();
    // string concatenation if either side is a string (checked before floats,
    // so `"n = " + 1.5` concatenates).
    asm.bind(not_int);
    asm.cmp_imm32(RAX, STR_TAG);
    let concat = asm.new_label();
    asm.jcc(CC_E, concat);
    asm.cmp_imm32(RCX, STR_TAG);
    asm.jcc(CC_E, concat);
    // list + list
    let not_list = asm.new_label();
    asm.cmp_imm32(RAX, LIST_TAG);
    asm.jcc(CC_NE, not_list);
    asm.cmp_imm32(RCX, LIST_TAG);
    asm.jcc(CC_NE, not_list);
    asm.call_sym("concat_lists");
    asm.ret();
    // Otherwise both operands must be numeric: add as floats.
    asm.bind(not_list);
    let add_err = asm.new_label();
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let left_ok = asm.new_label();
    asm.jcc(CC_E, left_ok);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, add_err);
    asm.bind(left_ok);
    asm.cmp_imm32(RCX, FLOAT_TAG);
    let right_ok = asm.new_label();
    asm.jcc(CC_E, right_ok);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, add_err);
    asm.bind(right_ok);
    let float_add = asm.new_label();
    asm.jmp(float_add);
    asm.bind(add_err);
    // Operator overloading: a map/struct left operand may define a "+" method.
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.cmp_imm32(RAX, MAP_TAG);
    let no_overload = asm.new_label();
    asm.jcc(CC_NE, no_overload);
    asm.call_sym("__op_add");
    asm.cmp_imm32(RAX, NIL_TAG as i32);
    asm.jcc(CC_E, no_overload);
    asm.ret();
    asm.bind(no_overload);
    asm.call_sym("raise_add_error");
    asm.mov_reg_imm64(RAX, NIL_TAG as i64);
    asm.ret();
    asm.bind(float_add);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_rr(XMM1, XMM0);
    asm.movsd_load(XMM0, RBP, -24);
    asm.addsd(XMM0, XMM1);
    asm.call_sym("rt_box_float");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(concat);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 16);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.call_sym("rt_str_of");
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_str_of");
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.mov_reg_reg(RSI, RAX);
    asm.call_sym("rt_str_cat");
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

fn emit_cmp(asm: &mut Asm) {
    asm.bind_symbol("rt_cmp");
    asm.mov_reg_reg(RAX, RDI);
    asm.mov_reg_imm64(R11, 7);
    asm.and_rr(RAX, R11);
    asm.mov_reg_reg(RCX, RSI);
    asm.and_rr(RCX, R11);
    asm.cmp_imm32(RAX, FLOAT_TAG);
    let float_l = asm.new_label();
    asm.jcc(CC_E, float_l);
    asm.cmp_imm32(RCX, FLOAT_TAG);
    asm.jcc(CC_E, float_l);
    let strings = asm.new_label();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_NE, strings);
    asm.test_rr(RCX, RCX);
    asm.jcc(CC_NE, strings);
    let lt = asm.new_label();
    let gt = asm.new_label();
    asm.cmp_rr(RDI, RSI);
    asm.jcc(CC_L, lt);
    asm.jcc(CC_G, gt);
    asm.xor_rr(RAX, RAX);
    asm.ret();
    asm.bind(lt);
    asm.mov_reg_imm64(RAX, -8);
    asm.ret();
    asm.bind(gt);
    asm.mov_reg_imm64(RAX, 8);
    asm.ret();
    asm.bind(float_l);
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_mem_reg(RBP, -8, RDI);
    asm.mov_mem_reg(RBP, -16, RSI);
    asm.mov_reg_mem(RDI, RBP, -8);
    asm.call_sym("rt_num_f64");
    asm.movsd_store(RBP, -24, XMM0);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.call_sym("rt_num_f64");
    asm.movsd_rr(XMM1, XMM0);
    asm.movsd_load(XMM0, RBP, -24);
    asm.comisd(XMM0, XMM1);
    let ceq = asm.new_label();
    let clt = asm.new_label();
    let cgt = asm.new_label();
    asm.jcc(CC_E, ceq);
    asm.jcc(CC_B, clt);
    asm.jcc(CC_A, cgt);
    asm.bind(ceq);
    asm.xor_rr(RAX, RAX);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(clt);
    asm.mov_reg_imm64(RAX, -8);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(cgt);
    asm.mov_reg_imm64(RAX, 8);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
    asm.bind(strings);
    asm.jmp_sym("rt_str_cmp");
}

fn emit_read_stdin(asm: &mut Asm, target: Target) {
    asm.bind_symbol("rt_read_stdin");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 32);
    asm.mov_reg_imm64(RDI, 65544);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -16, RAX);
    let loop_label = asm.new_label();
    let done = asm.new_label();
    asm.bind(loop_label);
    asm.mov_reg_imm64(RAX, target.read_nr());
    asm.xor_rr(RDI, RDI);
    asm.mov_reg_mem(RSI, RBP, -8);
    asm.add_imm32(RSI, 8);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.add_rr(RSI, RCX);
    asm.mov_reg_imm64(RDX, 65536);
    asm.sub_rr(RDX, RCX);
    asm.syscall();
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_LE, done);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.add_rr(RCX, RAX);
    asm.mov_mem_reg(RBP, -16, RCX);
    asm.jmp(loop_label);
    asm.bind(done);
    asm.mov_reg_mem(RAX, RBP, -8);
    asm.mov_reg_mem(RCX, RBP, -16);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}

/// rt_args: 0 args -> list of the process command-line arguments (including the
/// program path at index 0). The pointers were captured at `_start`.
fn emit_args(asm: &mut Asm, gc: &crate::gc::GcData) {
    asm.bind_symbol("rt_args");
    asm.push(RBP);
    asm.mov_reg_reg(RBP, RSP);
    asm.sub_imm32(RSP, 64);
    // an empty list
    asm.mov_reg_imm64(RDI, 24);
    asm.call_sym("rt_alloc_list");
    asm.mov_mem_reg(RBP, -8, RAX);
    asm.mov_reg_imm64(RCX, 0);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.mov_mem_reg(RAX, 8, RCX);
    asm.mov_mem_reg(RAX, 16, RCX);
    asm.add_imm32(RAX, LIST_TAG);
    asm.mov_mem_reg(RBP, -16, RAX); // tagged list
    asm.mov_reg_imm64(RAX, 0);
    asm.mov_mem_reg(RBP, -48, RAX); // i
    asm.mov_reg_abs(R11, AbsRef::Data(gc.argc));
    asm.mov_reg_mem(RAX, R11, 0);
    asm.mov_mem_reg(RBP, -56, RAX); // argc
    let loop_l = asm.new_label();
    let done = asm.new_label();
    let len_loop = asm.new_label();
    let len_done = asm.new_label();
    asm.bind(loop_l);
    asm.mov_reg_mem(RCX, RBP, -48);
    asm.mov_reg_mem(RDX, RBP, -56);
    asm.cmp_rr(RCX, RDX);
    asm.jcc(CC_AE, done);
    // src = argv[i]
    asm.mov_reg_abs(R10, AbsRef::Data(gc.argv));
    asm.mov_reg_mem(R10, R10, 0); // argv base
    asm.mov_reg_reg(R11, RCX);
    asm.shl_imm(R11, 3);
    asm.add_rr(R10, R11);
    asm.mov_reg_mem(RSI, R10, 0);
    asm.mov_mem_reg(RBP, -32, RSI);
    // NUL-terminated length
    asm.mov_reg_imm64(RCX, 0);
    asm.bind(len_loop);
    asm.mov_reg_mem(RDX, RBP, -32);
    asm.add_rr(RDX, RCX);
    asm.movzx_byte_mem(RAX, RDX, 0);
    asm.test_rr(RAX, RAX);
    asm.jcc(CC_E, len_done);
    asm.add_imm32(RCX, 1);
    asm.jmp(len_loop);
    asm.bind(len_done);
    asm.mov_mem_reg(RBP, -24, RCX);
    asm.mov_reg_reg(RDI, RCX);
    asm.add_imm32(RDI, 8);
    asm.call_sym("rt_alloc_str");
    asm.mov_mem_reg(RBP, -40, RAX);
    asm.mov_reg_mem(RDI, RBP, -40);
    asm.add_imm32(RDI, 8); // data lives after the 8-byte length header
    asm.mov_reg_mem(RSI, RBP, -32);
    asm.mov_reg_mem(RDX, RBP, -24);
    asm.call_sym("rt_memcpy");
    asm.mov_reg_mem(RAX, RBP, -40);
    asm.mov_reg_mem(RCX, RBP, -24);
    asm.mov_mem_reg(RAX, 0, RCX);
    asm.add_imm32(RAX, STR_TAG);
    asm.mov_reg_mem(RDI, RBP, -16);
    asm.mov_reg_reg(RSI, RAX);
    asm.call_sym("rt_push");
    asm.mov_mem_reg(RBP, -16, RAX);
    asm.mov_reg_mem(RCX, RBP, -48);
    asm.add_imm32(RCX, 1);
    asm.mov_mem_reg(RBP, -48, RCX);
    asm.jmp(loop_l);
    asm.bind(done);
    asm.mov_reg_mem(RAX, RBP, -16);
    asm.mov_reg_reg(RSP, RBP);
    asm.pop(RBP);
    asm.ret();
}
