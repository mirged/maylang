#!/usr/bin/env python3
"""Compile and run concrete strict programs; reject mistakes before codegen."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PASS = {
    'enum_payload_match': ('enum Shape { Empty, Point(x: Int, label: Str) } fun describe(s: Shape) -> Str { return match(s) { Empty() => "empty", Point(x, label) => label + str(x) }; } print(describe(Empty()), describe(Point(7,"x")));', 'empty x7\n'),
    'enum_match_guard': ('enum E { A(n: Int), B } fun f(e: E) -> Int { return match(e) { A(n) if n>0 => n, A(_) => 0, B() => -1 }; } print(f(A(2)), f(A(-2)), f(B()));', '2 0 -1\n'),
    'result_payload_match': ('fun f(r: Result<Int, Str>) -> Str { return match(r) { Ok(n) => str(n), Err(e) => e }; } print(f(Ok(7)), f(Err("bad")));', '7 bad\n'),
    'enum_match_capture': ('enum E { A(n: Int), B } fun f(e: E) -> () -> Int { return match(e) { A(n) => fun() -> Int { return n; }, B() => fun() -> Int { return 0; } }; } print(f(A(7))());', '7\n'),
    'typed_results': ('fun divide(a: Int, b: Int) -> Result<Int, Str> { if (b == 0) { return Err("zero"); } return Ok(a/b); } fun compute(b: Int) -> Result<Int, Str> { let n: Int = divide(10,b)?; return Ok(n+1); } print(compute(2).value ?? 0, compute(0).error ?? "missing");', '6 zero\n'),
    'inferred_results': ('fun choose(b: Bool) { if (b) { return Ok(7); } return Err("bad"); } fun use() -> Result<Int, Str> { return Ok(choose(true)? + 1); } print(use().value ?? 0);', '8\n'),
    'result_error_widening': ('fun source() -> Result<Int, Str> { return Err("bad"); } fun use() -> Result<Str, Str> { let n: Int = source()?; return Ok(str(n)); } print(use().error ?? "missing");', 'bad\n'),
    'basics': ('fun add(a: Int, b: Int) { return a + b; }\nlet n = add(2,3);\nprint(n);', '5\n'),
    'inferred_builtin_return': ('fun size() { return len("hello"); }\nlet n: Int = size();\nprint(n);', '5\n'),
    'ccall6_returns_int': ('fun unused() -> Int { return __ccall6(0, 0, 0, 0, 0, 0, 0); } print(1);', '1\n'),
    'inferred_handler_builtin': ('fun test_may() {\nlet result = may {\nlet bad = 10 / 0\nbad\n} otherwise {\nprint("Caught an error: ${err}");\n}\nprint(result)\nreturn nil;\n}\ntest_may()', 'Caught an error: division by zero\n0\n'),
    'branches': ('fun f(flag: Bool) -> Int { if(flag) { return 1; } else { return 2; } }\nprint(f(false));', '2\n'),
    'generics': ('fun identity<T>(x: T) -> T { return x; }\nlet n: Int = identity(7);\nprint(n);', '7\n'),
    'closures': ('fun factory(start: Int) -> () -> Int { mut n: Int = start; return fun() -> Int { n += 1; return n; }; }\nlet f: () -> Int = factory(4);\nprint(f(), f());', '5 6\n'),
    'inferred_closure_binding': ('let f = fun() -> Int { return 7; };\nprint(f());', '7\n'),
    'collections': ('let xs = [1,2];\nlet ys = map(xs, fun(x: Int) -> Int { return x*2; });\nmut total = 0;\nfor x in ys { total += x; }\nprint(total);', '6\n'),
    'inferred_comprehension': ('let xs: List<Int> = [x for x in [1]];\nprint(xs);', '[1]\n'),
    'filtered_comprehension': ('fun test_comprehension() -> Int {\nlet nums: List<Int> = [1,2,3,4,5,6,7,8,9,10]\nlet xs: List<Int> = [x*x for x in nums if x%2==0]\nprint(xs)\nreturn 0\n}\ntest_comprehension()', '[4, 16, 36, 64, 100]\n'),
    'typed_comprehension': ('let xs = [x*2 for x: Int in [1,2,3]]; print(xs);', '[2, 4, 6]\n'),
    'array_slice_comprehension': ('let a: [Int; 2] = [1,2]; let s: Slice<Str> = ["hi","bye"]; let ns: List<Int> = [x+1 for x in a]; let ss: List<Str> = [x+"!" for x in s]; print(ns,ss);', '[2, 3] ["hi!", "bye!"]\n'),
    'nested_comprehension': ('let xs: List<List<Int>> = [[x+y for y in [10,20]] for x in [1,2]]; print(xs);', '[[11, 21], [12, 22]]\n'),
    'dynamic_comprehension': ('let xs: Any = [1,2]; let ys = [x*2 for x in xs]; print(ys);', '[2, 4]\n'),
    'records': ('struct Point { x: Int, y: Int }\nlet p: Point = Point(3,4);\np.x = 5;\nprint(p.x);', '5\n'),
    'optional': ('let m: Map<Str, Int> = {"a": 7};\nlet value: Optional<Int> = m["a"];\nlet n: Int = value ?? 0;\nprint(n);', '7\n'),
    'void': ('fun announce() -> Nil { print("hello"); return; }\nannounce();', 'hello\n'),
    'dynamic_escape': ('let value: Any = "x";\nprint(value);', 'x\n'),
    'empty_collections': ('let xs: List<Int> = [];\nlet m: Map<Str, Int> = {};\nprint(sum(xs), len(m));', '0 0\n'),
    'bitwise_integers': ('fun mask(a: Int, b: Int) -> Int { return (a & b) | (a ^ b); } print(mask(6,3), ~0, 3 << 2, -8 >> 2);', '7 -1 12 -2\n'),
}
PASS.update({
    'explicit_dynamic_conversions': ('let n: Any = 123; let s: Str = str(n); let i: Int = int("7"); let b: Bool = bool(n); let f: Float = float(n); print(s, i, b, f);', '123 7 true 123.0\n'),
    'generic_callback_parameter': ('fun apply<T>(f: (List<T>) -> Int) -> Int { return 7; } fun size(xs: List<Int>) -> Int { return len(xs); } print(apply(size));', '7\n'),
    'callback_accepts_widening': ('fun f(x: Any) -> Str { return str(x); } let g: (Int) -> Str = f; print(g(7));', '7\n'),
    'typed_map_helpers': ('let a: Map<Str, Int> = {"x": 1}; let b: Map<Str, Int> = merge({},a); let c: Map<Str, Int> = remove(b,"x"); print(b,c);', '{"x": 1} {}\n'),
    'some_preserves_payload': ('let s: Str = Some("value").value ?? "missing"; let n: Int = Ok(7).value ?? 0; print(s,n);', 'value 7\n'),
    'dynamic_reduce': ('print(reduce([1,2], fun(a: Any, b: Any) -> Any { return a + b; }, 0));', '3\n'),
    'any_remains_dynamic': ('let value: Any = 7; let xs: List<Any> = []; push(xs,value); if value { print(xs); }', '[7]\n'),
})
FAIL = {
    'native_helper_arity': ('substring("hello", 0);', 'argument count mismatch'),
    'native_helper_result': ('let n: Int = chr(65);', 'expected Int, found Str'),
    'any_function_parameter': ('fun f(s: Str) -> Str { return s; } let g: (Any) -> Str = f;', 'expected (Any) -> Str'),
    'any_reduce_feedback': ('reduce([1,2], fun(a: Int, b: Int) -> Any { return "wrong"; }, 0);', 'expected Int, found Any'),
    'any_reduce_result': ('let xs: List<Int> = [1]; let n: Int = reduce(xs, fun(a: Int, b: Int) -> Any { return "wrong"; }, 0);', 'expected Int, found Any'),
    'any_string_binding': ('fun identity(x: Any) -> Any { return x; } let s: Str = identity(123);', 'expected Str, found Any'),
    'any_int_binding': ('let n: Any = "hello"; let i: Int = n;', 'expected Int, found Any'),
    'any_bool_binding': ('let n: Any = nil; let b: Bool = n;', 'expected Bool, found Any'),
    'any_assignment': ('mut n: Int = 1; let x: Any = "wrong"; n = x;', 'expected Int, found Any'),
    'any_argument': ('fun take(x: Str) -> Nil { return; } let x: Any = 1; take(x);', 'expected Str, found Any'),
    'any_return': ('fun f(x: Any) -> Int { return x; }', 'expected Int, found Any'),
    'any_list_push': ('let xs: List<Str> = []; let x: Any = 1; xs.push(x);', 'expected Str, found Any'),
    'any_list_item': ('let xs: List<Int> = [1]; let x: Any = "wrong"; xs[0] = x;', 'expected Int, found Any'),
    'any_map_merge_value': ('let a: Map<Str, Any> = {"x": 1}; let b: Map<Str, Int> = merge({},a);', 'expected Map<Str, Int>'),
    'any_map_merge_source': ('let a: Any = {"x": 1}; let b: Map<Str, Int> = merge({},a);', 'expected Map<Str, Int>'),
    'any_map_set_key': ('let m: Map<Str, Str> = {}; let x: Any = 1; map_set(m,x,"a");', 'expected Str, found Any'),
    'any_map_set_value': ('let m: Map<Str, Str> = {}; let x: Any = 1; map_set(m,"a",x);', 'expected Str, found Any'),
    'any_map_key': ('let m: Map<Str, Int> = {}; let x: Any = 1; m[x] = 2;', 'expected Str, found Any'),
    'any_map_value': ('let m: Map<Str, Str> = {}; let x: Any = 1; m["x"] = x;', 'expected Str, found Any'),
    'any_map_property': ('let m: Map<Str, Str> = {}; let x: Any = 1; m.x = x;', 'expected Str, found Any'),
    'any_record_field': ('struct P { x: Int } let p: P = P(1); let x: Any = "wrong"; p.x = x;', 'expected Int, found Any'),
    'any_nested_list': ('let xs: List<Any> = ["wrong"]; let ys: List<Int> = xs;', 'expected List<Int>, found List<Any>'),
    'any_nested_map': ('let m: Map<Str, Any> = {"x": "wrong"}; let n: Map<Str, Int> = m;', 'expected Map<Str, Int>'),
    'any_optional': ('let x: Any = nil; let y: Optional<Int> = x;', 'expected Optional<Int>, found Any'),
    'any_result': ('let r: Result<Any, Str> = Ok("wrong"); let s: Result<Int, Str> = r;', 'expected Result<Int, Str>'),
    'any_function_return': ('fun f() -> Any { return "wrong"; } let g: () -> Int = f;', 'expected () -> Int'),
    'any_generic_argument': ('fun first<T>(x: T, y: T) -> T { return x; } let x: Any = "wrong"; first(1,x);', 'expected Int, found Any'),
    'any_loop_binding': ('let xs: List<Any> = ["wrong"]; for x: Int in xs { print(x); }', 'expected Int, found Any'),
    'any_comprehension_binding': ('let xs: List<Any> = ["wrong"]; print([x for x: Int in xs]);', 'expected Int, found Any'),
    'any_some_payload': ('let x: Any = 123; let s: Str = Some(x).value ?? "";', 'expected Str, found Any'),
    'concrete_some_payload': ('let s: Str = Some(123).value ?? "";', 'expected Str'),
    'enum_missing_variant': ('enum E { A, B } fun f(e: E) -> Int { return match(e) { A() => 1 }; }', 'non-exhaustive E match; missing B'),
    'enum_guard_coverage': ('enum E { A(n: Int) } fun f(e: E) -> Int { return match(e) { A(n) if n>0 => n }; }', 'non-exhaustive E match'),
    'enum_wrong_payload_arity': ('enum E { A(n: Int) } fun f(e: E) -> Int { return match(e) { A() => 1 }; }', 'argument count mismatch'),
    'enum_wrong_payload_type': ('enum E { A(n: Int) } fun f(e: E) -> Str { return match(e) { A(n) => n }; }', 'expected Str, found Int'),
    'enum_wrong_identity': ('enum E { A } enum F { B } fun f(e: E) -> Int { return match(e) { B() => 1, _ => 0 }; }', 'variant pattern does not belong'),
    'result_non_exhaustive': ('fun f(r: Result<Int, Str>) -> Int { return match(r) { Ok(n) => n }; }', 'non-exhaustive Result<Int, Str> match; missing Err'),
    'result_constructor_value': ('fun f() -> Result<Int, Str> { return Ok("bad"); }', 'expected Result<Int, Str>'),
    'result_constructor_error': ('fun f() -> Result<Int, Str> { return Err(1); }', 'expected Result<Int, Str>'),
    'result_propagation_error': ('fun a() -> Result<Int, Int> { return Err(1); } fun b() -> Result<Int, Str> { return Ok(a()?); }', 'expected Str, found Int'),
    'result_propagation_return': ('fun a() -> Result<Int, Str> { return Ok(1); } fun b() -> Int { return a()?; }', 'typed ? requires an enclosing function'),
    'result_propagation_top_level': ('let x: Int = Ok(1)?;', 'typed ? requires an enclosing function'),
    'result_missing_payload': ('let r: Result<Int, Str> = Err("bad"); let x: Int = r.value;', 'expected Int, found Optional<Int>'),
    'missing_struct_field_type': ('struct P { x }', 'explicit type annotation'),
    'missing_enum_payload_type': ('enum E { Value(x) }', 'explicit type annotation'),
    'comprehension_binding_type': ('let xs = [x for x: Str in [1]];', 'expected Str, found Int'),
    'comprehension_filter_type': ('let xs = [x for x in [1] if x];', 'expected Bool, found Int'),
    'comprehension_result_type': ('let xs: List<Str> = [x for x in [1]];', 'expected List<Str>, found List<Int>'),
    'comprehension_element_type': ('let xs = [x*"bad" for x in [1]];', 'expected a number, found Str'),
    'comprehension_iterable_type': ('let xs = [x for x in 1];', 'comprehension requires an iterable collection'),
    'comprehension_binding_scope': ('let xs = [x for x in [1]]; print(x);', 'unknown type or name'),
    'missing_parameter_type': ('fun f(x) -> Int { return 1; }', 'explicit type annotation'),
    'implicit_return': ('fun f() -> Int { 1 }', 'explicit return'),
    'fallthrough': ('fun f(flag: Bool) -> Int { if(flag) { return 1; } }', 'not every path returns'),
    'wrong_initializer': ('let n: Int = "wrong";', 'expected Int, found Str'),
    'wrong_inferred_assignment': ('mut n = 1;\nn = "wrong";', 'expected Int, found Str'),
    'wrong_inferred_builtin_result': ('fun size() { return len("hello"); }\nlet n: Str = size();', 'expected Str, found Int'),
    'wrong_return': ('fun f() -> Int { return "wrong"; }', 'expected Int, found Str'),
    'wrong_argument': ('fun f(x: Int) -> Int { return x; }\nlet n: Int = f("wrong");', 'expected Int, found Str'),
    'wrong_arity': ('fun f(x: Int) -> Int { return x; }\nf();', 'argument count mismatch'),
    'unknown_type': ('let n: Imaginary = 1;', 'unknown type'),
    'wrong_assignment': ('mut n: Int = 1;\nn = "wrong";', 'expected Int, found Str'),
    'condition_type': ('if(1) { print(1); }', 'expected Bool, found Int'),
    'list_elements': ('let xs: List<Int> = [1, "wrong"];', 'expected List<Int>'),
    'indexed_write': ('let xs: List<Int> = [1];\nxs[0] = "wrong";', 'expected Int, found Str'),
    'bad_push': ('let xs: List<Int> = [1];\npush(xs, "wrong");', 'expected Int, found Str'),
    'bad_field': ('struct P { x: Int }\nlet p: P = P(1);\np.x = "wrong";', 'expected Int, found Str'),
    'missing_field': ('struct P { x: Int }\nlet p: P = P(1);\nprint(p.y);', 'unknown field'),
    'constructor': ('struct P { x: Int }\nlet p: P = P("wrong");', 'expected Int, found Str'),
    'bad_callback': ('let xs: List<Int> = [1];\nmap(xs, fun(x: Str) -> Str { return x; });', 'expected Str, found Int'),
    'generic_conflict': ('fun choose<T>(a: T, b: T) -> T { return a; }\nchoose(1,"wrong");', 'expected Int, found Str'),
    'bad_generic_arguments': ('let xs: List = [];', 'requires one type argument'),
    'map_key': ('let m: Map<Str, Int> = {"a": 1};\nprint(m[1]);', 'expected Str, found Int'),
    'map_write': ('let m: Map<Str, Int> = {"a": 1};\nm["b"] = "wrong";', 'expected Int, found Str'),
    'nil_call': ('let f: Nil = nil;\nf();', 'cannot call Nil'),
    'wrong_loop_type': ('for x: Str in [1] { print(x); }', 'expected Str, found Int'),
    'compare_float_int': ('let f: Float = 1.5;\nprint(f > 0);', 'cannot compare Float with Int'),
    'compare_int_float': ('let n: Int = 1;\nprint(n == 1.0);', 'cannot compare Int with Float'),
    'bitwise_rejects_float': ('let f: Float = 1.5;\nprint(f & 1);', 'expected an integer, found Float'),
    'bitnot_rejects_float': ('let f: Float = 1.5;\nprint(~f);', 'expected an integer, found Float'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'compiler/mayc/mayc_new')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    with tempfile.TemporaryDirectory(prefix='mayc-strict-tests-') as d:
        work = Path(d)
        for name, (code, expected) in PASS.items():
            source = work/(name+'.may'); source.write_text(code)
            binary = work/name
            result = subprocess.run([str(compiler), str(source), '-o', str(binary)], capture_output=True, timeout=60)
            assert result.returncode == 0, (name, result.stderr.decode())
            result = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert result.returncode == 0 and result.stdout.decode() == expected, (name, result)
            print('PASS strict '+name, flush=True)
        for name, (code, expected) in FAIL.items():
            source = work/(name+'.may'); source.write_text(code); binary = work/name
            result = subprocess.run([str(compiler), str(source), '-o', str(binary)], capture_output=True, timeout=60)
            error = result.stderr.decode()
            assert result.returncode != 0 and not binary.exists() and expected in error and '^' in error, (name,error)
            print('PASS reject '+name, flush=True)
        source = work/'legacy.may'; source.write_text('fun f(x) { x+1 }\nlet n = f(2);\nprint(n);')
        result = subprocess.run([str(compiler), '--legacy', str(source), '-o', str(work/'legacy')], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        assert subprocess.check_output([str(work/'legacy')]) == b'3\n'
        print('PASS explicit legacy mode', flush=True)
        lib=work/'library.may';lib.write_text('pub struct Point { x: Int }\npub fun value() -> Int { return 7; }')
        source=work/'imports.may';source.write_text('import "library" as lib;\nlet p: lib.Point = lib.Point(3);\nlet n: Int = lib.value();\nprint(p.x, n);')
        result=subprocess.run([str(compiler),str(source),'-o',str(work/'imports')],capture_output=True)
        assert result.returncode==0,result.stderr.decode()
        assert subprocess.check_output([str(work/'imports')])==b'3 7\n'
        print('PASS strict module types and calls',flush=True)
        lib.write_text('pub enum E { Value(n: Int), Empty }')
        source.write_text('import "library" as lib;\nfun use(e: lib.E) -> Int { return match(e) { lib.Value(n) => n, lib.Empty() => 0 }; } print(use(lib.Value(9)));')
        result=subprocess.run([str(compiler),str(source),'-o',str(work/'imports')],capture_output=True)
        assert result.returncode==0,result.stderr.decode()
        assert subprocess.check_output([str(work/'imports')])==b'9\n'
        print('PASS namespaced enum patterns',flush=True)

        # Preserve closure-valued tails and existing typed fields during migration.
        source = work/'migration.may'
        source.write_text('struct P { x: Int }\nfun make(n) { fun(x) { x+n } }\nlet f=make(4); print(f(5), P(2).x);')
        subprocess.run(['python3', str(ROOT/'compiler/mayc/tools/migrate_strict.py'), str(source), '--write'], check=True)
        result = subprocess.run([str(compiler), str(source), '-o', str(work/'migration')], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        assert subprocess.check_output([str(work/'migration')]) == b'9 2\n'
        print('PASS migration preserves closures and typed fields', flush=True)

if __name__ == '__main__':main()
