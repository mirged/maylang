//! Native x86-64 code generation for a typed subset of Maylang.
//!
//! Supported: integers, booleans, nil, string literals, `let`/`mut` locals and
//! top-level globals, arithmetic/comparisons/logical operators, `if`/`unless`,
//! `while`, `for` over integer ranges, functions (register and stack
//! arguments, recursion), `return`, `break`/`continue`, and `print`.
//!
//! Anything outside the supported subset produces a clear [`NativeError`]
//! rather than a silent miscompile.

use std::collections::{HashMap, HashSet};

use may_ast::*;

use crate::runtime::{self, RuntimeData};
use crate::x86::*;
use crate::{NativeError, Target};

const ARG_REGS: [Reg; 6] = [RDI, RSI, RDX, RCX, R8, R9];

const NIL: i64 = 0b010;
const FALSE: i64 = 0b011;
const TRUE: i64 = 0b100;
const LIST_TAG: i32 = 0b101;
const MAP_TAG: i32 = 0b111;

struct LoopCtx {
    continue_label: usize,
    break_label: usize,
}

/// How a closure captures one free variable.
enum Capture {
    /// A cell held in a local slot of the enclosing function.
    Local(usize),
    /// A cell held by the enclosing closure's upvalue array.
    Upvalue(usize),
}

struct Local {
    name: String,
    slot: usize,
    is_cell: bool,
}

/// Self-recursion information used for tail-call optimisation.
struct TailInfo {
    name: String,
    params: Vec<usize>,
    body_start: usize,
}

struct FnState {
    scopes: Vec<Vec<Local>>,
    next_slot: usize,
    epilogue: usize,
    loops: Vec<LoopCtx>,
    /// Names captured by nested functionals (boxed into heap cells).
    captured: HashSet<String>,
    /// Names this function closes over from its enclosing function, in order.
    upvalues: Vec<String>,
    is_closure: bool,
    /// Set once the function's prologue is complete, enabling self-TCO.
    tail: Option<TailInfo>,
}

impl FnState {
    fn new() -> Self {
        FnState {
            scopes: Vec::new(),
            next_slot: 0,
            epilogue: 0,
            loops: Vec::new(),
            captured: HashSet::new(),
            upvalues: Vec::new(),
            is_closure: false,
            tail: None,
        }
    }
    fn begin_scope(&mut self) {
        self.scopes.push(Vec::new());
    }
    fn end_scope(&mut self) {
        self.scopes.pop();
    }
    fn push_local(&mut self, name: &str, is_cell: bool) -> usize {
        let slot = self.next_slot;
        self.next_slot += 1;
        self.scopes.last_mut().unwrap().push(Local {
            name: name.to_string(),
            slot,
            is_cell,
        });
        slot
    }
    fn declare(&mut self, name: &str) -> usize {
        let is_cell = self.captured.contains(name);
        self.push_local(name, is_cell)
    }
    fn declare_cell(&mut self, name: &str) -> usize {
        self.push_local(name, true)
    }
    fn resolve(&self, name: &str) -> Option<(usize, bool)> {
        for scope in self.scopes.iter().rev() {
            for local in scope.iter().rev() {
                if local.name == name {
                    return Some((local.slot, local.is_cell));
                }
            }
        }
        None
    }
    fn is_cell_slot(&self, slot: usize) -> bool {
        self.scopes
            .iter()
            .flatten()
            .any(|local| local.slot == slot && local.is_cell)
    }
    fn upvalue_index(&self, name: &str) -> Option<usize> {
        self.upvalues.iter().position(|n| n == name)
    }
}

pub struct Codegen {
    asm: Asm,
    target: Target,
    globals: HashMap<String, usize>,
    functions: HashSet<String>,
    data: RuntimeData,
    current: Option<FnState>,
    heap_ptr_slot: usize,
    heap_end_slot: usize,
    gc_stack_top: usize,
    gc_data_begin: usize,
    gc_data_end: usize,
    gc_heap_start: usize,
    gc_all_head: usize,
    gc_mark_sp: usize,
    gc_busy: usize,
    gc_minor: usize,
    gc_free_heads: usize,
    gc_regs: usize,
    argc_slot: usize,
    argv_slot: usize,
    fib_count_slot: usize,
    fib_current_slot: usize,
    fib_cur_stack_hi_slot: usize,
    fib_rr_slot: usize,
    handler_depth_slot: usize,
    handler_stack_off: usize,
    err_slot: usize,
    function_values: HashMap<String, usize>,
    lambda_counter: usize,
    pending_functions: Vec<(String, Vec<Param>, Block, Vec<String>)>,
    fn_depth: usize,
    heap_size: usize,
}

impl Codegen {
    /// Create a code generator with an explicit GC heap size (bytes). Tests use
    /// a small heap to exercise collection cheaply.
    pub fn with_heap(target: Target, heap_size: usize) -> Self {
        Codegen {
            asm: Asm::new(),
            target,
            globals: HashMap::new(),
            functions: HashSet::new(),
            data: RuntimeData {
                newline: 0,
                space: 0,
                nil: 0,
                true_: 0,
                false_: 0,
                lbracket: 0,
                rbracket: 0,
                lbrace: 0,
                rbrace: 0,
                comma: 0,
                colon: 0,
                quote: 0,
                err_key: 0,
                msg_key: 0,
                not_callable: 0,
                fun_repr: 0,
                sym_sub: 0,
                sym_mul: 0,
                sym_div: 0,
                sym_mod: 0,
            },
            current: None,
            heap_ptr_slot: 0,
            heap_end_slot: 0,
            gc_stack_top: 0,
            gc_data_begin: 0,
            gc_data_end: 0,
            gc_heap_start: 0,
            gc_all_head: 0,
            gc_mark_sp: 0,
            gc_busy: 0,
            gc_minor: 0,
            gc_free_heads: 0,
            gc_regs: 0,
            argc_slot: 0,
            argv_slot: 0,
            fib_count_slot: 0,
            fib_current_slot: 0,
            fib_cur_stack_hi_slot: 0,
            fib_rr_slot: 0,
            handler_depth_slot: 0,
            handler_stack_off: 0,
            err_slot: 0,
            function_values: HashMap::new(),
            lambda_counter: 0,
            pending_functions: Vec::new(),
            fn_depth: 0,
            heap_size,
        }
    }

    /// Produce a complete executable image for the target.
    pub fn build(mut self, program: &Program) -> Result<Vec<u8>, NativeError> {
        self.prescan(program)?;
        self.heap_ptr_slot = self.asm.alloc_global();
        self.heap_end_slot = self.asm.alloc_global();
        self.gc_stack_top = self.asm.alloc_global();
        self.gc_data_begin = self.asm.alloc_global();
        self.gc_data_end = self.asm.alloc_global();
        self.gc_heap_start = self.asm.alloc_global();
        self.gc_all_head = self.asm.alloc_global();
        self.gc_mark_sp = self.asm.alloc_global();
        self.gc_busy = self.asm.alloc_global();
        self.gc_minor = self.asm.alloc_global();
        self.gc_free_heads = self.asm.reserve_zeros(8);
        self.gc_regs = self.asm.reserve_zeros(16 * 8);
        self.argc_slot = self.asm.alloc_global();
        self.argv_slot = self.asm.alloc_global();
        self.fib_count_slot = self.asm.alloc_global();
        self.fib_current_slot = self.asm.alloc_global();
        self.fib_cur_stack_hi_slot = self.asm.alloc_global();
        self.fib_rr_slot = self.asm.alloc_global();
        self.handler_depth_slot = self.asm.alloc_global();
        self.handler_stack_off = self.asm.reserve_zeros(64 * 24);
        self.err_slot = self.asm.alloc_global();
        self.globals.insert("err".to_string(), self.err_slot);
        self.emit_start();
        self.data = runtime::emit_data(&mut self.asm);
        let data = self.data.clone();
        let gc = crate::gc::GcData {
            data_begin: self.gc_data_begin,
            data_end: self.gc_data_end,
            heap_start: self.gc_heap_start,
            heap_ptr: self.heap_ptr_slot,
            all_head: self.gc_all_head,
            mark_sp: self.gc_mark_sp,
            gc_busy: self.gc_busy,
            gc_minor: self.gc_minor,
            free_heads: self.gc_free_heads,
            gc_regs: self.gc_regs,
            argc: self.argc_slot,
            argv: self.argv_slot,
            cur_stack_hi: self.fib_cur_stack_hi_slot,
            fib_count: self.fib_count_slot,
        };
        runtime::emit_runtime(
            &mut self.asm,
            self.target,
            &data,
            &gc,
            self.heap_ptr_slot,
            self.heap_end_slot,
            self.handler_depth_slot,
            self.handler_stack_off,
        );

        for stmt in &program.body.stmts {
            if let StmtKind::Fun {
                name, params, body, ..
            } = &stmt.kind
            {
                self.compile_function(name, params, body, Vec::new(), stmt.line)?;
            }
        }
        self.compile_main(&program.body)?;

        // Emit lambdas / nested functions as separate functions.
        while let Some((name, params, body, upvalues)) = self.pending_functions.pop() {
            self.compile_function(&name, &params, &body, upvalues, 0)?;
        }

        // Cooperative fibers (spawn/yield/run) and their scheduler state.
        crate::fibers::emit(
            &mut self.asm,
            self.target,
            &crate::fibers::FibData {
                count: self.fib_count_slot,
                current: self.fib_current_slot,
                cur_stack_hi: self.fib_cur_stack_hi_slot,
                rr: self.fib_rr_slot,
            },
        );

        // The mark worklist is demand-zero memory appended after the
        // file-backed data, so it does not bloat the executable. The heap is
        // mapped at startup by `_start` (see `emit_start`), not stored here.
        let mark_stack = self.asm.reserve_bss(crate::gc::MARK_STACK_BYTES);
        self.asm.bind_data_symbol("mark_stack", mark_stack);
        let fib_table = self.asm.reserve_bss(65 * 64);
        self.asm.bind_data_symbol("fib_table", fib_table);
        // Scratch for exec/system argument vectors and C strings (demand-zero).
        let proc_argv = self.asm.reserve_bss(crate::PROC_SCRATCH_ARGV_BYTES);
        self.asm.bind_data_symbol("proc_argv", proc_argv);
        let proc_str = self.asm.reserve_bss(crate::PROC_SCRATCH_STR_CAP);
        self.asm.bind_data_symbol("proc_str", proc_str);
        self.asm.bind_data_symbol("data_begin", 0);
        let data_end = self.asm.data.len();
        self.asm.bind_data_symbol("data_end", data_end);

        let code_off = self.target.header_size();
        let base = self.target.base_vaddr();
        let target = self.target;
        let mut symbols: Vec<(String, usize)> = self
            .asm
            .symbols
            .iter()
            .map(|(name, off)| (name.clone(), *off))
            .collect();
        symbols.sort_by_key(|(_, off)| *off);
        let lines = self.asm.lines.clone();
        let (code, data_bytes, entry, bss) = self.finish(code_off)?;
        Ok(match target {
            Target::LinuxElf => {
                crate::elf::build(base, &code, &data_bytes, entry, bss, &symbols, &lines)
            }
            Target::MacOS => crate::macho::build(base, &code, &data_bytes, entry, bss),
        })
    }

    fn prescan(&mut self, program: &Program) -> Result<(), NativeError> {
        for stmt in &program.body.stmts {
            match &stmt.kind {
                StmtKind::Fun { name, .. } => {
                    self.functions.insert(name.clone());
                }
                StmtKind::Let { name, .. } => {
                    let offset = self.asm.alloc_global();
                    self.globals.insert(name.clone(), offset);
                }
                StmtKind::Import { .. } => {
                    return Err(NativeError::new(
                        "unresolved `import` reached codegen (imports are inlined before compilation)",
                    ));
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn emit_start(&mut self) {
        self.asm.bind_symbol("_start");
        self.asm.xor_rr(RBP, RBP);
        // Capture argc/argv for `args()` before touching the stack.
        self.asm.mov_reg_reg(RAX, RSP);
        self.asm.mov_reg_mem(RAX, RAX, 0); // argc
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.argc_slot));
        self.asm.mov_mem_abs_reg(R11, RAX);
        self.asm.mov_reg_reg(RAX, RSP);
        self.asm.add_imm32(RAX, 8); // argv
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.argv_slot));
        self.asm.mov_mem_abs_reg(R11, RAX);
        // Map the heap: mmap(NULL, heap_size, PROT_READ|WRITE,
        //                       MAP_PRIVATE|MAP_ANONYMOUS, -1, 0).
        // It is demand-zero, so only touched pages consume physical memory.
        self.asm.xor_rr(RDI, RDI); // addr = NULL
        self.asm.mov_reg_imm64(RSI, self.heap_size as i64); // length
        self.asm.mov_reg_imm64(RDX, 3); // PROT_READ | PROT_WRITE
        self.asm.mov_reg_imm64(R10, self.target.mmap_anon_flags());
        self.asm.mov_reg_imm64(R8, -1); // fd
        self.asm.xor_rr(R9, R9); // offset
        self.asm.mov_reg_imm64(RAX, self.target.mmap_nr());
        self.asm.syscall();
        // A result in the top page (-4095..-1) is an error.
        let mmap_ok = self.asm.new_label();
        self.asm.mov_reg_imm64(RCX, -4095);
        self.asm.cmp_rr(RAX, RCX);
        self.asm.jcc(CC_B, mmap_ok);
        self.asm.mov_reg_imm64(RAX, self.target.exit_nr());
        self.asm.mov_reg_imm64(RDI, 70);
        self.asm.syscall();
        self.asm.bind(mmap_ok);
        // heap_ptr = heap_start = base; heap_end = base + heap_size
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.heap_ptr_slot));
        self.asm.mov_mem_abs_reg(R11, RAX);
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.gc_heap_start));
        self.asm.mov_mem_abs_reg(R11, RAX);
        self.asm.mov_reg_imm64(RCX, self.heap_size as i64);
        self.asm.add_rr(RAX, RCX);
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.heap_end_slot));
        self.asm.mov_mem_abs_reg(R11, RAX);
        // GC root bounds: the initial stack pointer and the data segment.
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.gc_stack_top));
        self.asm.mov_mem_abs_reg(R11, RSP);
        // Fiber scheduler: slot 0 is the main stack; its scan upper bound is
        // the initial stack pointer, as is the current stack bound.
        self.asm
            .mov_reg_abs(R11, AbsRef::Data(self.fib_cur_stack_hi_slot));
        self.asm.mov_mem_abs_reg(R11, RSP);
        self.asm
            .mov_reg_abs(R11, AbsRef::DataSym("fib_table".to_string()));
        self.asm.add_imm32(R11, 24);
        self.asm.mov_mem_abs_reg(R11, RSP);
        self.asm
            .mov_reg_abs(RAX, AbsRef::DataSym("data_begin".to_string()));
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.gc_data_begin));
        self.asm.mov_mem_abs_reg(R11, RAX);
        self.asm
            .mov_reg_abs(RAX, AbsRef::DataSym("data_end".to_string()));
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.gc_data_end));
        self.asm.mov_mem_abs_reg(R11, RAX);
        self.asm.call_sym("__main__");
        self.asm.mov_reg_imm64(RAX, self.target.exit_nr());
        self.asm.xor_rr(RDI, RDI);
        self.asm.syscall();
    }

    // ----- functions -----------------------------------------------------

    fn compile_function(
        &mut self,
        name: &str,
        params: &[Param],
        body: &Block,
        upvalues: Vec<String>,
        line: u32,
    ) -> Result<(), NativeError> {
        let saved = self.current.take();
        let is_closure = !upvalues.is_empty();
        self.fn_depth += 1;
        self.asm.bind_symbol(name);
        self.asm.push(RBP);
        if is_closure {
            self.asm.push(RBX);
        }
        self.asm.mov_reg_reg(RBP, RSP);
        if is_closure {
            self.asm.mov_reg_reg(RBX, R11); // incoming closure object
        }
        let frame_patch = self.asm.sub_rsp_placeholder();

        let mut state = FnState::new();
        state.captured = crate::capture::captured_names(body);
        state.upvalues = upvalues;
        state.is_closure = is_closure;
        state.begin_scope();
        let param_slots: Vec<usize> = params
            .iter()
            .map(|param| state.declare(&param.name))
            .collect();
        state.epilogue = self.asm.new_label();
        self.current = Some(state);

        for (i, slot) in param_slots.iter().enumerate() {
            if i < ARG_REGS.len() {
                self.asm.mov_reg_reg(RAX, ARG_REGS[i]);
            } else {
                // System V: the 7th+ arguments live above the return address.
                let disp = 16 + ((i - ARG_REGS.len()) * 8) as i32;
                self.asm.mov_reg_mem(RAX, RBP, disp);
            }
            self.asm.mov_mem_reg(RBP, slot_disp(*slot), RAX);
        }
        // Box captured parameters only after every argument has been spilled:
        // allocating a cell clobbers scratch registers (including RDX), which
        // would otherwise corrupt a later argument.
        for slot in &param_slots {
            if self.current.as_ref().unwrap().is_cell_slot(*slot) {
                self.asm.mov_reg_mem(RDI, RBP, slot_disp(*slot));
                self.asm.call_sym("rt_alloc_cell");
                self.asm.mov_mem_reg(RBP, slot_disp(*slot), RAX);
            }
        }

        // Enable self tail-call optimisation for the body: jumping back to this
        // label reuses the current frame after the arguments are rebound.
        let body_start = self.asm.new_label();
        self.asm.bind(body_start);
        self.current.as_mut().unwrap().tail = Some(TailInfo {
            name: name.to_string(),
            params: param_slots.clone(),
            body_start,
        });

        self.compile_fn_body(body, line)?;

        let state = self.current.take().unwrap();
        self.asm.bind(state.epilogue);
        self.asm.mov_reg_reg(RSP, RBP);
        if is_closure {
            self.asm.pop(RBX);
        }
        self.asm.pop(RBP);
        self.asm.ret();
        self.asm
            .patch_u32(frame_patch, frame_size(state.next_slot));
        self.current = saved;
        self.fn_depth -= 1;
        Ok(())
    }

    /// Store the value in `reg` into a freshly declared local slot, boxing it
    /// into a heap cell when the local is captured.
    fn store_local_decl(&mut self, slot: usize, reg: Reg) {
        if self.current.as_ref().unwrap().is_cell_slot(slot) {
            self.asm.mov_reg_reg(RDI, reg);
            self.asm.call_sym("rt_alloc_cell");
            self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
        } else {
            self.asm.mov_mem_reg(RBP, slot_disp(slot), reg);
        }
    }



    fn compile_main(&mut self, body: &Block) -> Result<(), NativeError> {
        self.asm.bind_symbol("__main__");
        self.asm.push(RBP);
        self.asm.mov_reg_reg(RBP, RSP);
        let frame_patch = self.asm.sub_rsp_placeholder();

        let mut state = FnState::new();
        state.captured = crate::capture::captured_names(body);
        state.begin_scope();
        state.epilogue = self.asm.new_label();
        self.current = Some(state);

        for stmt in &body.stmts {
            if !matches!(stmt.kind, StmtKind::Fun { .. }) {
                self.compile_stmt(stmt)?;
            }
        }
        match &body.tail {
            Some(expr) => self.compile_expr(expr, body.tail_line)?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }

        let state = self.current.take().unwrap();
        self.asm.bind(state.epilogue);
        self.asm.mov_reg_reg(RSP, RBP);
        self.asm.pop(RBP);
        self.asm.ret();
        self.asm
            .patch_u32(frame_patch, frame_size(state.next_slot));
        Ok(())
    }

    // ----- statements ----------------------------------------------------

    fn compile_stmt(&mut self, stmt: &Stmt) -> Result<(), NativeError> {
        let line = stmt.line;
        self.asm.mark_line(line);
        match &stmt.kind {
            StmtKind::Let {
                name, value, ..
            } => {
                match value {
                    Some(expr) => self.compile_expr(expr, line)?,
                    None => self.asm.mov_reg_imm64(RAX, NIL),
                }
                if self.fn_depth == 0 {
                    if let Some(offset) = self.globals.get(name).copied() {
                        self.asm.mov_reg_abs(R11, AbsRef::Data(offset));
                        self.asm.mov_mem_abs_reg(R11, RAX);
                        return Ok(());
                    }
                }
                let slot = self.current.as_mut().unwrap().declare(name);
                self.store_local_decl(slot, RAX);
                Ok(())
            }
            StmtKind::Fun {
                name, params, body, ..
            } => self.compile_nested_fun(name, params, body, line),
            StmtKind::While { cond, body } => {
                let start = self.asm.new_label();
                let end = self.asm.new_label();
                self.asm.bind(start);
                self.compile_expr(cond, line)?;
                self.branch_falsy(end);
                self.current.as_mut().unwrap().loops.push(LoopCtx {
                    continue_label: start,
                    break_label: end,
                });
                self.compile_block_stmt(body, line)?;
                self.current.as_mut().unwrap().loops.pop();
                self.asm.jmp(start);
                self.asm.bind(end);
                Ok(())
            }
            StmtKind::For {
                name,
                iterable,
                body,
            } => self.compile_for(name, iterable, body, line),
            StmtKind::Return(value) => {
                match value {
                    Some(expr) => {
                        // `return self(...)` becomes a jump to the entry.
                        if !self.try_tail_self_call(expr, line)? {
                            self.compile_expr(expr, line)?;
                        } else {
                            return Ok(());
                        }
                    }
                    None => self.asm.mov_reg_imm64(RAX, NIL),
                }
                let epilogue = self.current.as_ref().unwrap().epilogue;
                self.asm.jmp(epilogue);
                Ok(())
            }
            StmtKind::Break => {
                let label = self
                    .current
                    .as_ref()
                    .unwrap()
                    .loops
                    .last()
                    .ok_or_else(|| NativeError::new("`break` outside of a loop"))?
                    .break_label;
                self.asm.jmp(label);
                Ok(())
            }
            StmtKind::Continue => {
                let label = self
                    .current
                    .as_ref()
                    .unwrap()
                    .loops
                    .last()
                    .ok_or_else(|| NativeError::new("`continue` outside of a loop"))?
                    .continue_label;
                self.asm.jmp(label);
                Ok(())
            }
            StmtKind::Block(block) => self.compile_block_stmt(block, line),
            StmtKind::Expr { expr, .. } => {
                self.compile_expr(expr, line)?;
                Ok(())
            }
            StmtKind::Import { .. } => Err(NativeError::new(
                "native builds do not support `import`",
            )),
        }
    }

    fn compile_for(
        &mut self,
        name: &str,
        iterable: &Expr,
        body: &Block,
        line: u32,
    ) -> Result<(), NativeError> {
        let (start, end_expr, inclusive) = match iterable {
            Expr::Range {
                start,
                end,
                inclusive,
            } => (start, end, *inclusive),
            // Any non-range iterable is treated as a list to walk by index.
            _ => return self.compile_for_list(name, iterable, body, line),
        };

        self.current.as_mut().unwrap().begin_scope();
        let index_slot = self.current.as_mut().unwrap().declare("$index");
        let end_slot = self.current.as_mut().unwrap().declare("$end");

        self.compile_expr(start, line)?;
        self.asm.mov_mem_reg(RBP, slot_disp(index_slot), RAX);
        self.compile_expr(end_expr, line)?;
        if inclusive {
            self.asm.add_imm32(RAX, 8); // tagged +1
        }
        self.asm.mov_mem_reg(RBP, slot_disp(end_slot), RAX);

        let loop_start = self.asm.new_label();
        let increment = self.asm.new_label();
        let end = self.asm.new_label();
        self.asm.bind(loop_start);

        self.asm.mov_reg_mem(RAX, RBP, slot_disp(index_slot));
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(end_slot));
        self.asm.cmp_rr(RAX, RCX);
        self.asm.jcc(CC_GE, end);

        self.current.as_mut().unwrap().begin_scope();
        let var_slot = self.current.as_mut().unwrap().declare(name);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(index_slot));
        self.store_local_decl(var_slot, RAX);

        self.current.as_mut().unwrap().loops.push(LoopCtx {
            continue_label: increment,
            break_label: end,
        });
        for stmt in &body.stmts {
            self.compile_stmt(stmt)?;
        }
        if let Some(tail) = &body.tail {
            self.compile_expr(tail, body.tail_line.max(line))?;
        }
        self.current.as_mut().unwrap().loops.pop();
        self.current.as_mut().unwrap().end_scope();

        self.asm.bind(increment);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(index_slot));
        self.asm.add_imm32(RAX, 8); // tagged +1
        self.asm.mov_mem_reg(RBP, slot_disp(index_slot), RAX);
        self.asm.jmp(loop_start);
        self.asm.bind(end);
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    /// `for x in <list> { .. }` — walk the list by index.
    fn compile_for_list(
        &mut self,
        name: &str,
        iterable: &Expr,
        body: &Block,
        line: u32,
    ) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        self.compile_expr(iterable, line)?;
        let seq_slot = self.current.as_mut().unwrap().declare("$seq");
        self.asm.mov_mem_reg(RBP, slot_disp(seq_slot), RAX);

        self.asm.mov_reg_imm64(RAX, 0);
        let idx_slot = self.current.as_mut().unwrap().declare("$i");
        self.asm.mov_mem_reg(RBP, slot_disp(idx_slot), RAX);

        let loop_start = self.asm.new_label();
        let increment = self.asm.new_label();
        let end = self.asm.new_label();
        self.asm.bind(loop_start);

        self.asm.mov_reg_mem(RCX, RBP, slot_disp(idx_slot));
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.call_sym("rt_len");
        self.asm.cmp_rr(RCX, RAX);
        self.asm.jcc(CC_GE, end);

        self.current.as_mut().unwrap().begin_scope();
        let var_slot = self.current.as_mut().unwrap().declare(name);
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.mov_reg_mem(RSI, RBP, slot_disp(idx_slot));
        self.asm.call_sym("rt_iter_get");
        self.store_local_decl(var_slot, RAX);

        self.current.as_mut().unwrap().loops.push(LoopCtx {
            continue_label: increment,
            break_label: end,
        });
        for stmt in &body.stmts {
            self.compile_stmt(stmt)?;
        }
        if let Some(tail) = &body.tail {
            self.compile_expr(tail, body.tail_line.max(line))?;
        }
        self.current.as_mut().unwrap().loops.pop();
        self.current.as_mut().unwrap().end_scope();

        self.asm.bind(increment);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(idx_slot));
        self.asm.add_imm32(RAX, 8);
        self.asm.mov_mem_reg(RBP, slot_disp(idx_slot), RAX);
        self.asm.jmp(loop_start);
        self.asm.bind(end);
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    fn compile_block_value(&mut self, block: &Block, line: u32) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        for stmt in &block.stmts {
            self.compile_stmt(stmt)?;
        }
        match &block.tail {
            Some(expr) => self.compile_expr(expr, block.tail_line.max(line))?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    /// Compile a function body, attempting self-TCO throughout its tail
    /// positions (the body's tail expression and `if`/`unless` branch tails).
    fn compile_fn_body(&mut self, body: &Block, line: u32) -> Result<(), NativeError> {
        self.compile_tail_block(body, line)
    }

    fn compile_tail_block(&mut self, block: &Block, line: u32) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        for stmt in &block.stmts {
            self.compile_stmt(stmt)?;
        }
        match &block.tail {
            Some(expr) => self.compile_tail(expr, block.tail_line.max(line))?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    /// Compile an expression in tail position, descending into `if`/`unless`
    /// branch tails so self-recursive calls there are optimised too.
    fn compile_tail(&mut self, expr: &Expr, line: u32) -> Result<(), NativeError> {
        if self.try_tail_self_call(expr, line)? {
            return Ok(());
        }
        match expr {
            Expr::If {
                cond,
                then_branch,
                else_branch,
            } => self.compile_tail_if(cond, then_branch, else_branch.as_deref(), false, line),
            Expr::Unless {
                cond,
                body,
                else_branch,
            } => self.compile_tail_if(cond, body, else_branch.as_deref(), true, line),
            Expr::Block(block) => self.compile_tail_block(block, line),
            _ => self.compile_expr(expr, line),
        }
    }

    fn compile_tail_if(
        &mut self,
        cond: &Expr,
        then_branch: &Block,
        else_branch: Option<&Block>,
        negate: bool,
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(cond, line)?;
        let else_label = self.asm.new_label();
        let end = self.asm.new_label();
        if negate {
            self.branch_truthy(else_label);
        } else {
            self.branch_falsy(else_label);
        }
        self.compile_tail_block(then_branch, line)?;
        self.asm.jmp(end);
        self.asm.bind(else_label);
        match else_branch {
            Some(block) => self.compile_tail_block(block, line)?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }
        self.asm.bind(end);
        Ok(())
    }

    /// If `expr` is a direct call to the function currently being compiled and
    /// the arity matches, rebind the parameters and jump to the entry instead
    /// of growing the stack. Returns `true` when it emitted the jump.
    fn try_tail_self_call(&mut self, expr: &Expr, line: u32) -> Result<bool, NativeError> {
        let Expr::Call { callee, args } = expr else {
            return Ok(false);
        };
        let Expr::Variable(name) = callee.as_ref() else {
            return Ok(false);
        };
        let Some(info) = self.current.as_ref().and_then(|s| s.tail.as_ref()) else {
            return Ok(false);
        };
        if &info.name != name || info.params.len() != args.len() {
            return Ok(false);
        }
        let params = info.params.clone();
        let body_start = info.body_start;
        // Evaluate every argument before rebinding any parameter.
        for arg in args {
            self.compile_expr(arg, line)?;
            self.asm.push(RAX);
        }
        let cell: Vec<bool> = params
            .iter()
            .map(|slot| self.current.as_ref().unwrap().is_cell_slot(*slot))
            .collect();
        for (slot, is_cell) in params.iter().zip(cell.iter()).rev() {
            self.asm.pop(RAX);
            if *is_cell {
                self.asm.mov_reg_mem(RCX, RBP, slot_disp(*slot));
                self.asm.mov_mem_reg(RCX, 0, RAX);
            } else {
                self.asm.mov_mem_reg(RBP, slot_disp(*slot), RAX);
            }
        }
        self.asm.jmp(body_start);
        Ok(true)
    }

    fn compile_block_stmt(&mut self, block: &Block, line: u32) -> Result<(), NativeError> {
        self.compile_block_value(block, line)
    }

    // ----- expressions ---------------------------------------------------

    fn compile_expr(&mut self, expr: &Expr, line: u32) -> Result<(), NativeError> {
        match expr {
            Expr::Literal(lit) => {
                self.compile_literal(lit, line)?;
                Ok(())
            }
            Expr::Variable(name) => self.load_variable(name),
            Expr::Assign { name, value } => {
                self.compile_expr(value, line)?;
                self.store_variable(name)
            }
            Expr::Unary { op, right } => {
                self.compile_expr(right, line)?;
                match op {
                    UnaryOp::Neg => {
                        self.asm.mov_reg_reg(RDI, RAX);
                        self.asm.call_sym("rt_neg");
                    }
                    UnaryOp::Not => {
                        let is_true = self.asm.new_label();
                        let done = self.asm.new_label();
                        self.branch_truthy(is_true);
                        self.asm.mov_reg_imm64(RAX, TRUE);
                        self.asm.jmp(done);
                        self.asm.bind(is_true);
                        self.asm.mov_reg_imm64(RAX, FALSE);
                        self.asm.bind(done);
                    }
                }
                Ok(())
            }
            Expr::Binary { op, left, right } => self.compile_binary(op, left, right, line),
            Expr::Logical { op, left, right } => {
                self.compile_expr(left, line)?;
                let end = self.asm.new_label();
                match op {
                    LogicalOp::And => self.branch_falsy(end),
                    LogicalOp::Or => self.branch_truthy(end),
                }
                self.compile_expr(right, line)?;
                self.asm.bind(end);
                Ok(())
            }
            Expr::NilCoalesce { left, right } => {
                self.compile_expr(left, line)?;
                let end = self.asm.new_label();
                self.asm.cmp_imm32(RAX, NIL as i32);
                self.asm.jcc(CC_NE, end);
                self.compile_expr(right, line)?;
                self.asm.bind(end);
                Ok(())
            }
            Expr::Try { expr } => self.compile_try(expr, line),
            Expr::Call { callee, args } => self.compile_call(callee, args, line),
            Expr::Pipe { left, right } => self.compile_pipe(left, right, line),
            Expr::If {
                cond,
                then_branch,
                else_branch,
            } => self.compile_if(cond, then_branch, else_branch.as_deref(), false, line),
            Expr::Unless {
                cond,
                body,
                else_branch,
            } => self.compile_if(cond, body, else_branch.as_deref(), true, line),
            Expr::Block(block) => self.compile_block_value(block, line),
            Expr::Get { target, name } => {
                self.compile_expr(target, line)?;
                self.asm.mov_reg_reg(RDI, RAX);
                let offset = self.asm.intern(name.as_bytes());
                self.asm.mov_reg_abs(RSI, AbsRef::Data(offset));
                self.asm.add_imm32(RSI, 1); // tag as string
                self.asm.call_sym("rt_map_get");
                Ok(())
            }
            Expr::Map(entries) => self.compile_map(entries, line),
            Expr::SafeGet { target, name } => {
                self.compile_expr(target, line)?;
                let end = self.asm.new_label();
                self.asm.cmp_imm32(RAX, NIL as i32);
                self.asm.jcc(CC_E, end);
                self.asm.mov_reg_reg(RDI, RAX);
                let offset = self.asm.intern(name.as_bytes());
                self.asm.mov_reg_abs(RSI, AbsRef::Data(offset));
                self.asm.add_imm32(RSI, 1);
                self.asm.call_sym("rt_map_get");
                self.asm.bind(end);
                Ok(())
            }
            Expr::Range {
                start,
                end,
                inclusive,
            } => {
                let args = vec![
                    (**start).clone(),
                    (**end).clone(),
                    Expr::Literal(Literal::Int(if *inclusive { 1 } else { 0 })),
                ];
                self.compile_primitive("rt_range", &args, line)
            }
            Expr::Match { scrutinee, arms } => self.compile_match(scrutinee, arms, line),
            Expr::May { body, fallback } => {
                self.compile_may(body, fallback.as_deref(), line)
            }
            Expr::Lambda { params, body } => self.compile_closure(params, body),
            Expr::SetProp { target, name, value } => {
                self.compile_expr(target, line)?;
                let temp = self.current.as_mut().unwrap().declare("$set");
                self.asm.mov_mem_reg(RBP, slot_disp(temp), RAX);
                self.compile_expr(value, line)?;
                self.asm.mov_reg_reg(RDX, RAX);
                self.asm.mov_reg_mem(RDI, RBP, slot_disp(temp));
                let offset = self.asm.intern(name.as_bytes());
                self.asm.mov_reg_abs(RSI, AbsRef::Data(offset));
                self.asm.add_imm32(RSI, 1);
                self.asm.call_sym("rt_map_set");
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(temp));
                Ok(())
            }
            Expr::List(items) => self.compile_list(items, line),
            Expr::Index { target, index } => {
                self.compile_expr(target, line)?;
                self.asm.push(RAX);
                self.compile_expr(index, line)?;
                self.asm.mov_reg_reg(RSI, RAX);
                self.asm.pop(RDI);
                self.asm.call_sym("rt_index");
                Ok(())
            }
            Expr::SetIndex {
                target,
                index,
                value,
            } => {
                self.compile_expr(target, line)?;
                self.asm.push(RAX);
                self.compile_expr(index, line)?;
                self.asm.push(RAX);
                self.compile_expr(value, line)?;
                self.asm.mov_reg_reg(RDX, RAX);
                self.asm.pop(RSI);
                self.asm.pop(RDI);
                self.asm.call_sym("rt_set_index");
                Ok(())
            }
        }
    }

    fn dispatch_binop(&mut self, symbol: &str, left: Reg, right: Reg) {
        self.asm.mov_reg_reg(RDI, left);
        self.asm.mov_reg_reg(RSI, right);
        self.asm.call_sym(symbol);
    }

    fn compile_literal(&mut self, lit: &Literal, _line: u32) -> Result<(), NativeError> {
        match lit {
            Literal::Nil => self.asm.mov_reg_imm64(RAX, NIL),
            Literal::Bool(true) => self.asm.mov_reg_imm64(RAX, TRUE),
            Literal::Bool(false) => self.asm.mov_reg_imm64(RAX, FALSE),
            Literal::Int(v) => self.asm.mov_reg_imm64(RAX, v.wrapping_mul(8)),
            Literal::Float(v) => {
                let offset = self.asm.intern_raw(&v.to_bits().to_le_bytes());
                self.asm.mov_reg_abs(RAX, AbsRef::Data(offset));
                self.asm.add_imm32(RAX, 6); // FLOAT_TAG
            }
            Literal::Str(s) => {
                let offset = self.asm.intern(s.as_bytes());
                self.asm.mov_reg_abs(RAX, AbsRef::Data(offset));
                self.asm.add_imm32(RAX, 1);
            }
        }
        Ok(())
    }

    /// Compile a lambda expression to a first-class closure value.
    fn compile_closure(&mut self, params: &[Param], body: &Block) -> Result<(), NativeError> {
        let mut free: Vec<String> = crate::capture::free_vars(params, body).into_iter().collect();
        free.sort();
        let mut captures = Vec::new();
        let mut upvalue_names = Vec::new();
        for name in &free {
            if let Some((slot, _)) = self.current.as_ref().unwrap().resolve(name) {
                captures.push(Capture::Local(slot));
                upvalue_names.push(name.clone());
            } else if let Some(index) = self.current.as_ref().unwrap().upvalue_index(name) {
                captures.push(Capture::Upvalue(index));
                upvalue_names.push(name.clone());
            }
        }
        let fn_name = format!("__lambda_{}", self.lambda_counter);
        self.lambda_counter += 1;
        self.pending_functions.push((
            fn_name.clone(),
            params.to_vec(),
            body.clone(),
            upvalue_names,
        ));
        self.emit_closure_object(&fn_name, &captures);
        Ok(())
    }

    fn emit_closure_object(&mut self, fn_name: &str, captures: &[Capture]) {
        let size = 24 + captures.len() * 8;
        self.asm.mov_reg_imm64(RDI, size as i64);
        self.asm.call_sym("rt_alloc_closure");
        let slot = self.current.as_mut().unwrap().declare("$closure");
        self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
        self.asm.mov_reg_imm64(R11, -1);
        self.asm.mov_mem_reg(RAX, 0, R11);
        self.asm
            .mov_reg_abs(R11, AbsRef::CodeSym(fn_name.to_string()));
        self.asm.mov_mem_reg(RAX, 8, R11);
        self.asm.mov_reg_imm64(R11, captures.len() as i64);
        self.asm.mov_mem_reg(RAX, 16, R11);
        for (i, capture) in captures.iter().enumerate() {
            match capture {
                Capture::Local(local_slot) => {
                    self.asm.mov_reg_mem(R11, RBP, slot_disp(*local_slot))
                }
                Capture::Upvalue(index) => {
                    self.asm.mov_reg_mem(R11, RBX, 24 + (*index * 8) as i32)
                }
            }
            self.asm.mov_mem_reg(RAX, 24 + (i * 8) as i32, R11);
        }
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(slot));
        self.asm.add_imm32(RAX, LIST_TAG);
    }

    /// A nested `fun` declaration binds a local closure (supports recursion).
    fn compile_nested_fun(
        &mut self,
        name: &str,
        params: &[Param],
        body: &Block,
        _line: u32,
    ) -> Result<(), NativeError> {
        let slot = self.current.as_mut().unwrap().declare_cell(name);
        self.asm.mov_reg_imm64(RDI, NIL);
        self.asm.call_sym("rt_alloc_cell");
        self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
        self.compile_closure(params, body)?;
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(slot));
        self.asm.mov_mem_reg(RCX, 0, RAX);
        Ok(())
    }

    /// Build a map `{ k: v, ... }` as a flat `[k0, v0, k1, v1, ...]` tagged map.
    fn compile_map(&mut self, entries: &[(Expr, Expr)], line: u32) -> Result<(), NativeError> {
        let slots = entries.len() * 2;
        self.asm.mov_reg_imm64(RDI, 24);
        self.asm.call_sym("rt_alloc_list");
        let header_slot = self.current.as_mut().unwrap().declare("$map");
        self.asm.mov_mem_reg(RBP, slot_disp(header_slot), RAX);
        self.asm.mov_reg_imm64(RDI, (slots.max(1) * 8) as i64);
        self.asm.call_sym("rt_alloc_array");
        let data_slot = self.current.as_mut().unwrap().declare("$mdata");
        self.asm.mov_mem_reg(RBP, slot_disp(data_slot), RAX);
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(header_slot));
        self.asm.mov_reg_imm64(RAX, slots as i64);
        self.asm.mov_mem_reg(RCX, 0, RAX);
        self.asm.mov_reg_imm64(RAX, slots as i64);
        self.asm.mov_mem_reg(RCX, 8, RAX);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(data_slot));
        self.asm.mov_mem_reg(RCX, 16, RAX);
        for (i, (key, value)) in entries.iter().enumerate() {
            self.compile_expr(key, line)?;
            self.store_in_map_data(data_slot, i * 2);
            self.compile_expr(value, line)?;
            self.store_in_map_data(data_slot, i * 2 + 1);
        }
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(header_slot));
        self.asm.add_imm32(RAX, MAP_TAG);
        Ok(())
    }

    fn store_in_map_data(&mut self, data_slot: usize, index: usize) {
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(data_slot));
        if index > 0 {
            self.asm.add_imm32(RCX, (index * 8) as i32);
        }
        self.asm.mov_mem_reg(RCX, 0, RAX);
    }

    /// Compile `may { body } [otherwise { fallback }]` using the handler stack.
    fn compile_may(
        &mut self,
        body: &Block,
        fallback: Option<&Block>,
        line: u32,
    ) -> Result<(), NativeError> {
        // push handler: save rsp, rbp and the catch address
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.handler_depth_slot));
        self.asm.mov_reg_mem(RCX, R11, 0);
        self.asm.mov_reg_reg(RDX, RCX);
        self.asm.shl_imm(RDX, 1);
        self.asm.add_rr(RDX, RCX);
        self.asm.shl_imm(RDX, 3); // * 24
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.handler_stack_off));
        self.asm.add_rr(RDX, R11);
        self.asm.mov_mem_reg(RDX, 0, RSP);
        self.asm.mov_mem_reg(RDX, 8, RBP);
        let addr_imm = self.asm.mov_reg_abs_code_placeholder(R11);
        self.asm.mov_mem_reg(RDX, 16, R11);
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.handler_depth_slot));
        self.asm.add_imm32(RCX, 1);
        self.asm.mov_mem_reg(R11, 0, RCX);

        self.compile_block_value(body, line)?;

        // normal completion: pop handler
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.handler_depth_slot));
        self.asm.mov_reg_mem(RCX, R11, 0);
        self.asm.sub_imm32(RCX, 1);
        self.asm.mov_mem_reg(R11, 0, RCX);
        let done = self.asm.new_label();
        self.asm.jmp(done);

        // catch: rdi holds the error value
        let catch_pos = self.asm.here();
        self.asm.set_abs_code(addr_imm, catch_pos);
        self.asm.mov_reg_abs(R11, AbsRef::Data(self.err_slot));
        self.asm.mov_mem_reg(R11, 0, RDI);
        match fallback {
            Some(block) => self.compile_block_value(block, line)?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }
        self.asm.bind(done);
        Ok(())
    }

    /// Compile `match` as a chain of tests/branches.
    fn compile_match(
        &mut self,
        scrutinee: &Expr,
        arms: &[MatchArm],
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(scrutinee, line)?;
        self.current.as_mut().unwrap().begin_scope();
        let slot = self.current.as_mut().unwrap().declare("$match");
        self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);

        let end = self.asm.new_label();
        for arm in arms {
            let next = self.asm.new_label();
            self.current.as_mut().unwrap().begin_scope();
            match &arm.pattern {
                Pattern::Wildcard => {}
                Pattern::Binding(name) => {
                    let bind = self.current.as_mut().unwrap().declare(name);
                    self.asm.mov_reg_mem(RAX, RBP, slot_disp(slot));
                    self.store_local_decl(bind, RAX);
                }
                Pattern::Literal(lit) => {
                    self.compile_literal(lit, line)?;
                    self.asm.mov_reg_reg(RSI, RAX);
                    self.asm.mov_reg_mem(RDI, RBP, slot_disp(slot));
                    self.asm.call_sym("rt_value_eq");
                    // jump to next arm when not equal
                    self.asm.cmp_imm32(RAX, TRUE as i32);
                    self.asm.jcc(CC_NE, next);
                }
            }
            if let Some(guard) = &arm.guard {
                self.compile_expr(guard, line)?;
                self.branch_falsy(next);
            }
            self.compile_expr(&arm.body, line)?;
            self.current.as_mut().unwrap().end_scope();
            self.asm.jmp(end);
            self.asm.bind(next);
        }
        self.asm.mov_reg_imm64(RAX, NIL);
        self.asm.bind(end);
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    fn compile_list(&mut self, items: &[Expr], line: u32) -> Result<(), NativeError> {
        let count = items.len();
        // header = alloc(24)
        self.asm.mov_reg_imm64(RDI, 24);
        self.asm.call_sym("rt_alloc_list");
        let header_slot = self.current.as_mut().unwrap().declare("$list");
        self.asm.mov_mem_reg(RBP, slot_disp(header_slot), RAX);
        // data = alloc(max(count, 1) * 8)
        self.asm.mov_reg_imm64(RDI, ((count.max(1)) * 8) as i64);
        self.asm.call_sym("rt_alloc_array");
        let data_slot = self.current.as_mut().unwrap().declare("$ldata");
        self.asm.mov_mem_reg(RBP, slot_disp(data_slot), RAX);
        // header.len = count, header.cap = count, header.data = data
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(header_slot));
        self.asm.mov_reg_imm64(RAX, count as i64);
        self.asm.mov_mem_reg(RCX, 0, RAX);
        self.asm.mov_reg_imm64(RAX, count as i64);
        self.asm.mov_mem_reg(RCX, 8, RAX);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(data_slot));
        self.asm.mov_mem_reg(RCX, 16, RAX);
        // elements
        for (i, item) in items.iter().enumerate() {
            self.compile_expr(item, line)?;
            self.asm.mov_reg_mem(RCX, RBP, slot_disp(data_slot));
            if i > 0 {
                self.asm.add_imm32(RCX, (i * 8) as i32);
            }
            self.asm.mov_mem_reg(RCX, 0, RAX);
        }
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(header_slot));
        self.asm.add_imm32(RAX, LIST_TAG);
        Ok(())
    }

    fn compile_binary(
        &mut self,
        op: &BinaryOp,
        left: &Expr,
        right: &Expr,
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(left, line)?;
        self.asm.push(RAX);
        self.compile_expr(right, line)?;
        self.asm.pop(RCX); // rcx = left, rax = right

        match op {
            BinaryOp::Add => {
                self.asm.mov_reg_reg(RDI, RCX);
                self.asm.mov_reg_reg(RSI, RAX);
                self.asm.call_sym("rt_add");
            }
            BinaryOp::Sub => self.dispatch_binop("rt_sub", RCX, RAX),
            BinaryOp::Mul => self.dispatch_binop("rt_mul", RCX, RAX),
            BinaryOp::Div => self.dispatch_binop("rt_div", RCX, RAX),
            BinaryOp::Mod => self.dispatch_binop("rt_mod", RCX, RAX),
            BinaryOp::Eq | BinaryOp::Ne => {
                self.asm.mov_reg_reg(RDI, RCX);
                self.asm.mov_reg_reg(RSI, RAX);
                self.asm.call_sym("rt_value_eq");
                if matches!(op, BinaryOp::Ne) {
                    self.asm.mov_reg_imm64(R11, 7); // 3 <-> 4
                    self.asm.sub_rr(R11, RAX);
                    self.asm.mov_reg_reg(RAX, R11);
                }
            }
            BinaryOp::Lt | BinaryOp::Le | BinaryOp::Gt | BinaryOp::Ge => {
                self.asm.mov_reg_reg(RDI, RCX);
                self.asm.mov_reg_reg(RSI, RAX);
                self.asm.call_sym("rt_cmp");
                self.asm.cmp_imm32(RAX, 0);
                let cc = match op {
                    BinaryOp::Lt => CC_L,
                    BinaryOp::Le => CC_LE,
                    BinaryOp::Gt => CC_G,
                    BinaryOp::Ge => CC_GE,
                    _ => unreachable!(),
                };
                self.asm.setcc(cc, RAX);
                self.asm.movzx_byte(RAX, RAX);
                self.asm.add_imm32(RAX, FALSE as i32);
            }
            BinaryOp::Pow => self.dispatch_binop("rt_pow", RCX, RAX),
        }
        Ok(())
    }

    fn compile_if(
        &mut self,
        cond: &Expr,
        then_branch: &Block,
        else_branch: Option<&Block>,
        inverted: bool,
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(cond, line)?;
        let else_label = self.asm.new_label();
        if inverted {
            self.branch_truthy(else_label);
        } else {
            self.branch_falsy(else_label);
        }
        self.compile_block_value(then_branch, line)?;
        let end = self.asm.new_label();
        self.asm.jmp(end);
        self.asm.bind(else_label);
        match else_branch {
            Some(block) => self.compile_block_value(block, line)?,
            None => self.asm.mov_reg_imm64(RAX, NIL),
        }
        self.asm.bind(end);
        Ok(())
    }

    fn compile_call(
        &mut self,
        callee: &Expr,
        args: &[Expr],
        line: u32,
    ) -> Result<(), NativeError> {
        if let Expr::Variable(name) = callee {
            if name == "print" {
                return self.compile_print(args, line);
            }
            if name == "fail" {
                let list = Expr::List(args.to_vec());
                self.compile_expr(&list, line)?;
                self.asm.mov_reg_reg(RDI, RAX);
                self.asm.call_sym("fail_list");
                self.asm.mov_reg_imm64(RAX, NIL);
                return Ok(());
            }
            if name == "input" {
                if let Some(prompt) = args.first() {
                    self.compile_expr(prompt, line)?;
                    self.asm.mov_reg_reg(RDI, RAX);
                    self.asm.call_sym("rt_print_value");
                }
                self.asm.call_sym("rt_input");
                return Ok(());
            }
            if name == "len" && args.len() == 1 {
                self.compile_expr(&args[0], line)?;
                self.asm.mov_reg_reg(RDI, RAX);
                self.asm.call_sym("rt_len");
                return Ok(());
            }
            if name == "push" && args.len() == 2 {
                self.compile_expr(&args[0], line)?;
                self.asm.push(RAX);
                self.compile_expr(&args[1], line)?;
                self.asm.mov_reg_reg(RSI, RAX);
                self.asm.pop(RDI);
                self.asm.call_sym("rt_push");
                return Ok(());
            }
            if name == "pop" && args.len() == 1 {
                self.compile_expr(&args[0], line)?;
                self.asm.mov_reg_reg(RDI, RAX);
                self.asm.call_sym("rt_pop");
                return Ok(());
            }
            if name == "range" && (args.len() == 1 || args.len() == 2) {
                let start = if args.len() == 1 {
                    Expr::Literal(Literal::Int(0))
                } else {
                    args[0].clone()
                };
                let end = if args.len() == 1 {
                    args[0].clone()
                } else {
                    args[1].clone()
                };
                let call = vec![start, end, Expr::Literal(Literal::Int(0))];
                return self.compile_primitive("rt_range", &call, line);
            }
            if matches!(name.as_str(), "map" | "filter") && args.len() == 2 {
                return self.compile_iterate(&args[0], &args[1], name == "filter", line);
            }
            if name == "reduce" && args.len() == 3 {
                return self.compile_reduce(&args[0], &args[1], &args[2], line);
            }
            if matches!(name.as_str(), "any" | "all") && args.len() == 2 {
                return self.compile_quantifier(name == "all", &args[0], &args[1], line);
            }
            if name == "syscall" {
                return self.compile_syscall(args, line);
            }
            if let Some((symbol, arity)) = primitive(name) {
                if args.len() != arity {
                    return Err(NativeError::new(format!(
                        "native primitive `{name}` expects {arity} argument(s)"
                    )));
                }
                return self.compile_primitive(symbol, args, line);
            }
            if self.functions.contains(name) {
                let n = args.len();
                for arg in args {
                    self.compile_expr(arg, line)?;
                    self.asm.push(RAX);
                }
                // After pushing arg0..arg{n-1}, arg_i lives at [rsp + (n-1-i)*8].
                // Load the register-passed prefix.
                for i in 0..n.min(ARG_REGS.len()) {
                    let disp = ((n - 1 - i) * 8) as i32;
                    self.asm.mov_reg_mem(ARG_REGS[i], RSP, disp);
                }
                // Extra arguments stay on the stack, but must be in ascending
                // order (arg6 nearest the return address). The pushes left them
                // reversed, so swap the tail in place.
                if n > ARG_REGS.len() {
                    let extras = n - ARG_REGS.len();
                    for k in 0..extras / 2 {
                        let lo = (k * 8) as i32;
                        let hi = ((n - 1 - ARG_REGS.len() - k) * 8) as i32;
                        self.asm.mov_reg_mem(RAX, RSP, lo);
                        self.asm.mov_reg_mem(R10, RSP, hi);
                        self.asm.mov_mem_reg(RSP, lo, R10);
                        self.asm.mov_mem_reg(RSP, hi, RAX);
                    }
                }
                self.asm.call_sym(name);
                if n > 0 {
                    self.asm.add_imm32(RSP, (n * 8) as i32);
                }
                return Ok(());
            }
            // A local/global (or parameter) holding a function value.
            return self.compile_indirect_call(callee, args, line);
        }
        // Method call: `receiver.name(args)` becomes `name(receiver, args)`.
        if let Expr::Get { target, name } = callee {
            if let Some(function) = method_name(name) {
                let mut all = Vec::with_capacity(args.len() + 1);
                all.push((**target).clone());
                all.extend(args.iter().cloned());
                return self.compile_call(&Expr::Variable(function.to_string()), &all, line);
            }
        }
        // Safe method call: `receiver?.name(args)` yields nil for a nil receiver.
        if let Expr::SafeGet { target, name } = callee {
            if let Some(function) = method_name(name) {
                self.compile_expr(target, line)?;
                let slot = self.current.as_mut().unwrap().declare("$safe");
                self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
                let end = self.asm.new_label();
                self.asm.cmp_imm32(RAX, NIL as i32);
                self.asm.jcc(CC_E, end);
                if function == "len" {
                    self.asm.mov_reg_mem(RDI, RBP, slot_disp(slot));
                    self.asm.call_sym("rt_len");
                    self.asm.bind(end);
                    return Ok(());
                }
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(slot));
                self.asm.push(RAX);
                for arg in args {
                    self.compile_expr(arg, line)?;
                    self.asm.push(RAX);
                }
                for i in (0..args.len()).rev() {
                    self.asm.pop(ARG_REGS[i + 1]);
                }
                self.asm.pop(RDI);
                self.asm.call_sym(function);
                self.asm.bind(end);
                return Ok(());
            }
        }
        // Safe call on a non-method name: `receiver?.name(args)`; a nil
        // receiver short-circuits the whole call to nil.
        if matches!(callee, Expr::SafeGet { .. }) {
            return self.compile_safe_indirect_call(callee, args, line);
        }
        // Any other callee expression (a call result, index, lambda, ...).
        self.compile_indirect_call(callee, args, line)
    }

    /// `syscall(id, a, b, ...)` — variadic raw syscall. The arguments are
    /// collected into a list and passed untagged by `rt_syscall`.
    fn compile_syscall(&mut self, args: &[Expr], line: u32) -> Result<(), NativeError> {
        if args.is_empty() {
            return Err(NativeError::new("syscall expects at least a syscall number"));
        }
        self.compile_expr(&args[0], line)?;
        self.asm.push(RAX); // syscall number
        self.asm.mov_reg_imm64(RDI, 24);
        self.asm.call_sym("rt_alloc_list");
        self.asm.xor_rr(RCX, RCX);
        self.asm.mov_mem_reg(RAX, 0, RCX);
        self.asm.mov_mem_reg(RAX, 8, RCX);
        self.asm.mov_mem_reg(RAX, 16, RCX);
        let slot = self.current.as_mut().unwrap().declare("$sysargs");
        self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
        for arg in &args[1..] {
            self.compile_expr(arg, line)?;
            self.asm.push(RAX);
            self.asm.mov_reg_mem(RDI, RBP, slot_disp(slot));
            self.asm.add_imm32(RDI, LIST_TAG);
            self.asm.pop(RSI);
            self.asm.call_sym("rt_push");
        }
        self.asm.pop(RDI); // syscall number
        self.asm.mov_reg_mem(RSI, RBP, slot_disp(slot));
        self.asm.add_imm32(RSI, LIST_TAG);
        self.asm.call_sym("rt_syscall");
        Ok(())
    }

    fn compile_primitive(
        &mut self,
        symbol: &str,
        args: &[Expr],
        line: u32,
    ) -> Result<(), NativeError> {
        const PRIM_REGS: [Reg; 3] = [RDI, RSI, RDX];
        for arg in args {
            self.compile_expr(arg, line)?;
            self.asm.push(RAX);
        }
        for i in (0..args.len()).rev() {
            self.asm.pop(PRIM_REGS[i]);
        }
        self.asm.call_sym(symbol);
        Ok(())
    }

    /// Compile `f(x)` where `x` is in `x_slot`; result in RAX.
    fn compile_apply1(
        &mut self,
        f: &Expr,
        x_slot: usize,
        line: u32,
    ) -> Result<(), NativeError> {
        match f {
            Expr::Variable(name) if self.functions.contains(name) => {
                self.asm.mov_reg_mem(RDI, RBP, slot_disp(x_slot));
                self.asm.call_sym(name);
                Ok(())
            }
            Expr::Lambda { params, body } if params.len() == 1 => {
                self.current.as_mut().unwrap().begin_scope();
                let slot = self.current.as_mut().unwrap().declare(&params[0].name);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(x_slot));
                self.store_local_decl(slot, RAX);
                self.compile_block_value(body, line)?;
                self.current.as_mut().unwrap().end_scope();
                Ok(())
            }
            _ => {
                self.compile_expr(f, line)?;
                self.asm.push(RAX);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(x_slot));
                self.asm.push(RAX);
                self.asm.pop(RDI);
                self.asm.pop(R11);
                self.asm.call_sym("rt_call");
                Ok(())
            }
        }
    }

    /// Compile `f(a, b)` where `a`/`b` live in slots; result in RAX.
    fn compile_apply2(
        &mut self,
        f: &Expr,
        a_slot: usize,
        b_slot: usize,
        line: u32,
    ) -> Result<(), NativeError> {
        match f {
            Expr::Variable(name) if self.functions.contains(name) => {
                self.asm.mov_reg_mem(RDI, RBP, slot_disp(a_slot));
                self.asm.mov_reg_mem(RSI, RBP, slot_disp(b_slot));
                self.asm.call_sym(name);
                Ok(())
            }
            Expr::Lambda { params, body } if params.len() == 2 => {
                self.current.as_mut().unwrap().begin_scope();
                let s0 = self.current.as_mut().unwrap().declare(&params[0].name);
                let s1 = self.current.as_mut().unwrap().declare(&params[1].name);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(a_slot));
                self.store_local_decl(s0, RAX);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(b_slot));
                self.store_local_decl(s1, RAX);
                self.compile_block_value(body, line)?;
                self.current.as_mut().unwrap().end_scope();
                Ok(())
            }
            _ => {
                self.compile_expr(f, line)?;
                self.asm.push(RAX);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(a_slot));
                self.asm.push(RAX);
                self.asm.mov_reg_mem(RAX, RBP, slot_disp(b_slot));
                self.asm.push(RAX);
                self.asm.pop(RSI);
                self.asm.pop(RDI);
                self.asm.pop(R11);
                self.asm.call_sym("rt_call");
                Ok(())
            }
        }
    }

    fn compile_iterate(
        &mut self,
        seq: &Expr,
        f: &Expr,
        is_filter: bool,
        line: u32,
    ) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        self.compile_expr(seq, line)?;
        let seq_slot = self.current.as_mut().unwrap().declare("$seq");
        self.asm.mov_mem_reg(RBP, slot_disp(seq_slot), RAX);
        self.compile_list(&[], line)?;
        let out_slot = self.current.as_mut().unwrap().declare("$out");
        self.asm.mov_mem_reg(RBP, slot_disp(out_slot), RAX);
        self.asm.mov_reg_imm64(RAX, 0);
        let i_slot = self.current.as_mut().unwrap().declare("$i");
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);

        let loop_start = self.asm.new_label();
        let skip = self.asm.new_label();
        let end = self.asm.new_label();
        self.asm.bind(loop_start);
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(i_slot));
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.call_sym("rt_len");
        self.asm.cmp_rr(RCX, RAX);
        self.asm.jcc(CC_GE, end);

        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.mov_reg_mem(RSI, RBP, slot_disp(i_slot));
        self.asm.call_sym("rt_index");
        let x_slot = self.current.as_mut().unwrap().declare("$x");
        self.asm.mov_mem_reg(RBP, slot_disp(x_slot), RAX);

        self.compile_apply1(f, x_slot, line)?;
        if is_filter {
            self.branch_falsy(skip);
            self.asm.mov_reg_mem(RDI, RBP, slot_disp(out_slot));
            self.asm.mov_reg_mem(RSI, RBP, slot_disp(x_slot));
            self.asm.call_sym("rt_push");
            self.asm.bind(skip);
        } else {
            self.asm.mov_reg_reg(RSI, RAX);
            self.asm.mov_reg_mem(RDI, RBP, slot_disp(out_slot));
            self.asm.call_sym("rt_push");
        }
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(i_slot));
        self.asm.add_imm32(RAX, 8);
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);
        self.asm.jmp(loop_start);
        self.asm.bind(end);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(out_slot));
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    fn compile_reduce(
        &mut self,
        seq: &Expr,
        f: &Expr,
        init: &Expr,
        line: u32,
    ) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        self.compile_expr(seq, line)?;
        let seq_slot = self.current.as_mut().unwrap().declare("$seq");
        self.asm.mov_mem_reg(RBP, slot_disp(seq_slot), RAX);
        self.compile_expr(init, line)?;
        let acc_slot = self.current.as_mut().unwrap().declare("$acc");
        self.asm.mov_mem_reg(RBP, slot_disp(acc_slot), RAX);
        self.asm.mov_reg_imm64(RAX, 0);
        let i_slot = self.current.as_mut().unwrap().declare("$i");
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);

        let loop_start = self.asm.new_label();
        let end = self.asm.new_label();
        self.asm.bind(loop_start);
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(i_slot));
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.call_sym("rt_len");
        self.asm.cmp_rr(RCX, RAX);
        self.asm.jcc(CC_GE, end);
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.mov_reg_mem(RSI, RBP, slot_disp(i_slot));
        self.asm.call_sym("rt_index");
        let x_slot = self.current.as_mut().unwrap().declare("$x");
        self.asm.mov_mem_reg(RBP, slot_disp(x_slot), RAX);
        self.compile_apply2(f, acc_slot, x_slot, line)?;
        self.asm.mov_mem_reg(RBP, slot_disp(acc_slot), RAX);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(i_slot));
        self.asm.add_imm32(RAX, 8);
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);
        self.asm.jmp(loop_start);
        self.asm.bind(end);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(acc_slot));
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    fn compile_quantifier(
        &mut self,
        is_all: bool,
        seq: &Expr,
        f: &Expr,
        line: u32,
    ) -> Result<(), NativeError> {
        self.current.as_mut().unwrap().begin_scope();
        self.compile_expr(seq, line)?;
        let seq_slot = self.current.as_mut().unwrap().declare("$seq");
        self.asm.mov_mem_reg(RBP, slot_disp(seq_slot), RAX);
        self.asm.mov_reg_imm64(RAX, if is_all { TRUE } else { FALSE });
        let result_slot = self.current.as_mut().unwrap().declare("$res");
        self.asm.mov_mem_reg(RBP, slot_disp(result_slot), RAX);
        self.asm.mov_reg_imm64(RAX, 0);
        let i_slot = self.current.as_mut().unwrap().declare("$i");
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);
        let loop_start = self.asm.new_label();
        let hit = self.asm.new_label();
        let avoid = self.asm.new_label();
        let end = self.asm.new_label();
        self.asm.bind(loop_start);
        self.asm.mov_reg_mem(RCX, RBP, slot_disp(i_slot));
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.call_sym("rt_len");
        self.asm.cmp_rr(RCX, RAX);
        self.asm.jcc(CC_GE, end);
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(seq_slot));
        self.asm.mov_reg_mem(RSI, RBP, slot_disp(i_slot));
        self.asm.call_sym("rt_index");
        let x_slot = self.current.as_mut().unwrap().declare("$x");
        self.asm.mov_mem_reg(RBP, slot_disp(x_slot), RAX);
        self.compile_apply1(f, x_slot, line)?;
        if is_all {
            self.branch_truthy(avoid); // pred true => keep looking
            self.asm.mov_reg_imm64(RAX, FALSE);
        } else {
            self.branch_falsy(avoid); // pred false => keep looking
            self.asm.mov_reg_imm64(RAX, TRUE);
        }
        self.asm.mov_mem_reg(RBP, slot_disp(result_slot), RAX);
        self.asm.jmp(hit);
        self.asm.bind(avoid);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(i_slot));
        self.asm.add_imm32(RAX, 8);
        self.asm.mov_mem_reg(RBP, slot_disp(i_slot), RAX);
        self.asm.jmp(loop_start);
        self.asm.bind(hit);
        self.asm.bind(end);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(result_slot));
        self.current.as_mut().unwrap().end_scope();
        Ok(())
    }

    /// `expr?` — propagate `{ok: false, ..}` results (and nil) out of the
    /// enclosing function, otherwise yield the result's `value` field.
    fn compile_try(&mut self, expr: &Expr, line: u32) -> Result<(), NativeError> {
        self.compile_expr(expr, line)?;
        let slot = self.current.as_mut().unwrap().declare("$try");
        self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
        let propagate = self.asm.new_label();
        let done = self.asm.new_label();
        // nil propagates unchanged.
        self.asm.cmp_imm32(RAX, NIL as i32);
        self.asm.jcc(CC_E, propagate);
        // `ok == false` propagates the whole result object.
        self.asm.mov_reg_reg(RDI, RAX);
        let ok_key = self.asm.intern(b"ok");
        self.asm.mov_reg_abs(RSI, AbsRef::Data(ok_key));
        self.asm.add_imm32(RSI, 1);
        self.asm.call_sym("rt_map_get");
        self.asm.cmp_imm32(RAX, FALSE as i32);
        self.asm.jcc(CC_E, propagate);
        // Otherwise yield `value`.
        self.asm.mov_reg_mem(RDI, RBP, slot_disp(slot));
        let value_key = self.asm.intern(b"value");
        self.asm.mov_reg_abs(RSI, AbsRef::Data(value_key));
        self.asm.add_imm32(RSI, 1);
        self.asm.call_sym("rt_map_get");
        self.asm.jmp(done);
        self.asm.bind(propagate);
        self.asm.mov_reg_mem(RAX, RBP, slot_disp(slot));
        let epilogue = self.current.as_ref().unwrap().epilogue;
        self.asm.jmp(epilogue);
        self.asm.bind(done);
        Ok(())
    }

    fn compile_pipe(&mut self, left: &Expr, right: &Expr, line: u32) -> Result<(), NativeError> {
        match right {
            Expr::Call { callee, args } => {
                let mut all = Vec::with_capacity(args.len() + 1);
                all.push(left.clone());
                all.extend(args.iter().cloned());
                self.compile_call(callee, &all, line)
            }
            Expr::Variable(name) => self.compile_call(
                &Expr::Variable(name.clone()),
                std::slice::from_ref(left),
                line,
            ),
            _ => Err(NativeError::new(
                "native pipes must target a named function",
            )),
        }
    }

    fn compile_print(&mut self, args: &[Expr], line: u32) -> Result<(), NativeError> {
        // Evaluate every argument left-to-right before printing any of them,
        // so side effects (e.g. an `otherwise` handler) happen first.
        let mut slots = Vec::with_capacity(args.len());
        for arg in args {
            self.compile_expr(arg, line)?;
            let slot = self.current.as_mut().unwrap().declare("$print");
            self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
            slots.push(slot);
        }
        for (i, slot) in slots.iter().enumerate() {
            self.asm.mov_reg_mem(RDI, RBP, slot_disp(*slot));
            self.asm.call_sym("rt_print_value");
            if i + 1 < slots.len() {
                self.asm.call_sym("rt_space");
            }
        }
        self.asm.call_sym("rt_newline");
        self.asm.mov_reg_imm64(RAX, NIL);
        Ok(())
    }

    // ----- variables -----------------------------------------------------

    fn load_variable(&mut self, name: &str) -> Result<(), NativeError> {
        if let Some((slot, is_cell)) = self.current.as_ref().unwrap().resolve(name) {
            self.asm.mov_reg_mem(RAX, RBP, slot_disp(slot));
            if is_cell {
                self.asm.mov_reg_mem(RAX, RAX, 0);
            }
            return Ok(());
        }
        if let Some(index) = self.current.as_ref().unwrap().upvalue_index(name) {
            self.asm.mov_reg_mem(RAX, RBX, 24 + (index * 8) as i32);
            self.asm.mov_reg_mem(RAX, RAX, 0);
            return Ok(());
        }
        if let Some(offset) = self.globals.get(name).copied() {
            self.asm.mov_reg_abs(R11, AbsRef::Data(offset));
            self.asm.mov_reg_mem_abs(RAX, R11);
            return Ok(());
        }
        if self.functions.contains(name) {
            self.emit_function_value(name);
            return Ok(());
        }
        Err(NativeError::new(format!("unknown variable `{name}`")))
    }

    fn store_variable(&mut self, name: &str) -> Result<(), NativeError> {
        if let Some((slot, is_cell)) = self.current.as_ref().unwrap().resolve(name) {
            if is_cell {
                self.asm.mov_reg_mem(RCX, RBP, slot_disp(slot));
                self.asm.mov_mem_reg(RCX, 0, RAX);
            } else {
                self.asm.mov_mem_reg(RBP, slot_disp(slot), RAX);
            }
            return Ok(());
        }
        if let Some(index) = self.current.as_ref().unwrap().upvalue_index(name) {
            self.asm.mov_reg_mem(RCX, RBX, 24 + (index * 8) as i32);
            self.asm.mov_mem_reg(RCX, 0, RAX);
            return Ok(());
        }
        if let Some(offset) = self.globals.get(name).copied() {
            self.asm.mov_reg_abs(R11, AbsRef::Data(offset));
            self.asm.mov_mem_abs_reg(R11, RAX);
            return Ok(());
        }
        Err(NativeError::new(format!("unknown variable `{name}`")))
    }

    fn emit_function_value(&mut self, name: &str) {
        let offset = match self.function_values.get(name) {
            Some(offset) => *offset,
            None => {
                let offset = self.asm.alloc_function_value(name);
                self.function_values.insert(name.to_string(), offset);
                offset
            }
        };
        self.asm.mov_reg_abs(RAX, AbsRef::Data(offset));
        self.asm.add_imm32(RAX, LIST_TAG);
    }

    fn compile_indirect_call(
        &mut self,
        callee: &Expr,
        args: &[Expr],
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(callee, line)?;
        self.asm.push(RAX);
        for arg in args {
            self.compile_expr(arg, line)?;
            self.asm.push(RAX);
        }
        self.emit_indirect_args(args.len());
        self.asm.call_sym("rt_call");
        self.asm.add_imm32(RSP, ((args.len() + 1) * 8) as i32);
        Ok(())
    }

    /// Arrange the pushed callee/arguments for an indirect call: load the
    /// register prefix, move extra arguments above the return address, and
    /// load the callee into R11. The callee value is pushed first, so it sits
    /// at offset `n * 8`.
    fn emit_indirect_args(&mut self, n: usize) {
        for i in 0..n.min(ARG_REGS.len()) {
            let disp = ((n - 1 - i) * 8) as i32;
            self.asm.mov_reg_mem(ARG_REGS[i], RSP, disp);
        }
        if n > ARG_REGS.len() {
            let extras = n - ARG_REGS.len();
            for k in 0..extras / 2 {
                let lo = (k * 8) as i32;
                let hi = ((n - 1 - ARG_REGS.len() - k) * 8) as i32;
                self.asm.mov_reg_mem(RAX, RSP, lo);
                self.asm.mov_reg_mem(R10, RSP, hi);
                self.asm.mov_mem_reg(RSP, lo, R10);
                self.asm.mov_mem_reg(RSP, hi, RAX);
            }
        }
        self.asm.mov_reg_mem(R11, RSP, (n * 8) as i32);
    }

    /// Like `compile_indirect_call`, but a nil callee (from `?.`) yields nil
    /// instead of faulting.
    fn compile_safe_indirect_call(
        &mut self,
        callee: &Expr,
        args: &[Expr],
        line: u32,
    ) -> Result<(), NativeError> {
        self.compile_expr(callee, line)?;
        let done = self.asm.new_label();
        self.asm.cmp_imm32(RAX, NIL as i32);
        self.asm.jcc(CC_E, done);
        self.asm.push(RAX);
        for arg in args {
            self.compile_expr(arg, line)?;
            self.asm.push(RAX);
        }
        self.emit_indirect_args(args.len());
        self.asm.call_sym("rt_call");
        self.asm.add_imm32(RSP, ((args.len() + 1) * 8) as i32);
        self.asm.bind(done);
        Ok(())
    }

    // ----- control helpers ----------------------------------------------

    /// Jump to `label` when the tagged value in RAX is falsy (nil or false).
    fn branch_falsy(&mut self, label: usize) {
        self.asm.mov_reg_reg(RCX, RAX);
        self.asm.sub_imm32(RCX, NIL as i32);
        self.asm.cmp_imm32(RCX, 1);
        self.asm.jcc(CC_BE, label);
    }

    fn branch_truthy(&mut self, label: usize) {
        self.asm.mov_reg_reg(RCX, RAX);
        self.asm.sub_imm32(RCX, NIL as i32);
        self.asm.cmp_imm32(RCX, 1);
        self.asm.jcc(CC_A, label);
    }

    // ----- finalize ------------------------------------------------------

    fn finish(mut self, code_off: usize) -> Result<(Vec<u8>, Vec<u8>, usize, usize), NativeError> {
        let base = self.target.base_vaddr();
        // Keep the data segment 8-byte aligned so pointer tags stay valid.
        while !self.asm.code.len().is_multiple_of(8) {
            self.asm.code.push(0x90); // NOP padding
        }
        let code_len = self.asm.code.len() as u64;
        let data_start = code_off as u64 + code_len;

        // Resolve calls.
        for (pos, name) in self.asm.call_fixups.clone() {
            let target = *self.asm.symbols.get(&name).ok_or_else(|| {
                NativeError::new(format!("internal: unresolved symbol `{name}`"))
            })?;
            let rel = target as i64 - (pos as i64 + 4);
            self.asm.patch_u32(pos, rel as i32 as u32);
        }

        // Resolve absolute addresses.
        for (pos, reference) in self.asm.abs_fixups.clone() {
            let addr = match reference {
                AbsRef::Data(off) => base + data_start + off as u64,
                AbsRef::DataSym(name) => {
                    let off = *self.asm.data_symbols.get(&name).ok_or_else(|| {
                        NativeError::new(format!("internal: unresolved data symbol `{name}`"))
                    })?;
                    base + data_start + off as u64
                }
                AbsRef::Code(p) => base + code_off as u64 + p as u64,
                AbsRef::CodeSym(name) => {
                    let target = *self.asm.symbols.get(&name).ok_or_else(|| {
                        NativeError::new(format!("internal: unresolved function `{name}`"))
                    })?;
                    base + code_off as u64 + target as u64
                }
            };
            let bytes = addr.to_le_bytes();
            self.asm.code[pos..pos + 8].copy_from_slice(&bytes);
        }

        // Patch code addresses into first-class function objects in data.
        for (data_pos, name) in self.asm.data_code_fixups.clone() {
            let target = *self.asm.symbols.get(&name).ok_or_else(|| {
                NativeError::new(format!("internal: unresolved function `{name}`"))
            })?;
            let addr = base + code_off as u64 + target as u64;
            self.asm.data[data_pos..data_pos + 8].copy_from_slice(&addr.to_le_bytes());
        }

        let entry = *self
            .asm
            .symbols
            .get("_start")
            .ok_or_else(|| NativeError::new("internal: missing `_start`"))?;
        Ok((
            self.asm.code,
            self.asm.data,
            entry,
            self.asm.bss_size,
        ))
    }
}

fn slot_disp(slot: usize) -> i32 {
    -8 * (slot as i32 + 1)
}

fn frame_size(locals: usize) -> u32 {
    let bytes = (locals as u32) * 8;
    let padded = (bytes + 15) & !15;
    padded.max(16)
}


/// Runtime primitives exposed to the native prelude / codegen.
fn primitive(name: &str) -> Option<(&'static str, usize)> {
    Some(match name {
        "str_of" => ("rt_str_of", 1),
        "int_to_str" => ("rt_int_to_str", 1),
        "char_at" => ("rt_char_at", 2),
        "char_from" => ("rt_char_from", 1),
        "str_cmp" => ("rt_str_cmp", 2),
        "cmp" => ("rt_cmp", 2),
        "value_eq" => ("rt_value_eq", 2),
        "value_tag" => ("rt_value_tag", 1),
        "map_get" => ("rt_map_get", 2),
        "map_set" => ("rt_map_set", 3),
        "map_keys" => ("rt_map_keys", 1),
        "map_values" => ("rt_map_values", 1),
        "map_has" => ("rt_map_has", 2),
        "to_map" => ("rt_to_map", 1),
        "read_stdin" => ("rt_read_stdin", 0),
        "args" => ("rt_args", 0),
        "clock" => ("rt_clock", 0),
        "spawn" => ("rt_spawn", 1),
        "yield" => ("rt_yield", 0),
        "run" => ("rt_run", 0),
        "time" => ("rt_time", 0),
        "sin" => ("rt_sin", 1),
        "cos" => ("rt_cos", 1),
        "tan" => ("rt_tan", 1),
        "asin" => ("rt_asin", 1),
        "acos" => ("rt_acos", 1),
        "atan" => ("rt_atan", 1),
        "atan2" => ("rt_atan2", 2),
        "ln" => ("rt_ln", 1),
        "log2" => ("rt_log2", 1),
        "log10" => ("rt_log10", 1),
        "exp" => ("rt_exp", 1),
        "pow" => ("rt_powf", 2),
        "read_file" => ("rt_read_file", 1),
        "write_file" => ("rt_write_file", 2),
        "file_exists" => ("rt_file_exists", 1),
        "mkdir" => ("rt_mkdir", 1),
        "read_dir" => ("rt_read_dir", 1),
        "exec" => ("rt_exec", 1),
        "wait" => ("rt_wait", 1),
        "system" => ("rt_system", 1),
        "sleep" => ("rt_sleep", 1),
        "addr" => ("rt_addr", 1),
        "cstr" => ("rt_cstr", 1),
        "load8" => ("rt_load8", 1),
        "load16" => ("rt_load16", 1),
        "load32" => ("rt_load32", 1),
        "load64" => ("rt_load64", 1),
        "store8" => ("rt_store8", 2),
        "store16" => ("rt_store16", 2),
        "store32" => ("rt_store32", 2),
        "store64" => ("rt_store64", 2),
        "ccall" => ("rt_ccall", 2),
        "extern_c" => ("rt_extern_c", 1),
        "exit" => ("rt_exit", 1),
        "rt_raise" => ("rt_raise", 1),
        "floor" => ("rt_float_floor", 1),
        "ceil" => ("rt_float_ceil", 1),
        "trunc" => ("rt_float_trunc", 1),
        "sqrt" => ("rt_float_sqrt", 1),
        "to_float" => ("rt_to_float", 1),
        _ => return None,
    })
}

/// Receiver-first method names desugared to plain function calls.
fn method_name(name: &str) -> Option<&'static str> {
    Some(match name {
        "trim" => "trim",
        "to_lower" => "to_lower",
        "to_upper" => "to_upper",
        "split" => "split",
        "contains" => "contains",
        "starts_with" => "starts_with",
        "ends_with" => "ends_with",
        "replace" => "replace",
        "index_of" => "index_of",
        "chars" => "chars",
        "repeat" => "repeat",
        "len" => "len",
        "map" => "map",
        "filter" => "filter",
        "reduce" => "reduce",
        "has" => "has",
        "keys" => "keys",
        "values" => "values",
        "join" => "join",
        "reverse" => "reverse",
        "sort" => "sort",
        "push" => "push",
        "pop" => "pop",
        _ => return None,
    })
}
