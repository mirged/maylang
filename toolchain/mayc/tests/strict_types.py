#!/usr/bin/env python3
"""Compile and run concrete strict programs; reject mistakes before codegen."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PASS = {
    'basics': ('fun add(a: Int, b: Int) { return a + b; }\nlet n = add(2,3);\nprint(n);', '5\n'),
    'inferred_builtin_return': ('fun size() { return len("hello"); }\nlet n: Int = size();\nprint(n);', '5\n'),
    'inferred_handler_builtin': ('fun test_may() {\nlet result = may {\nlet bad = 10 / 0\nbad\n} otherwise {\nprint("Caught an error: ${err}");\n}\nprint(result)\nreturn nil;\n}\ntest_may()', 'Caught an error: division by zero\n0\n'),
    'branches': ('fun f(flag: Bool) -> Int { if(flag) { return 1; } else { return 2; } }\nprint(f(false));', '2\n'),
    'generics': ('fun identity<T>(x: T) -> T { return x; }\nlet n: Int = identity(7);\nprint(n);', '7\n'),
    'closures': ('fun factory(start: Int) -> () -> Int { mut n: Int = start; return fun() -> Int { n += 1; return n; }; }\nlet f: () -> Int = factory(4);\nprint(f(), f());', '5 6\n'),
    'inferred_closure_binding': ('let f = fun() -> Int { return 7; };\nprint(f());', '7\n'),
    'collections': ('let xs = [1,2];\nlet ys = map(xs, fun(x: Int) -> Int { return x*2; });\nmut total = 0;\nfor x in ys { total += x; }\nprint(total);', '6\n'),
    'records': ('struct Point { x: Int, y: Int }\nlet p: Point = Point(3,4);\np.x = 5;\nprint(p.x);', '5\n'),
    'optional': ('let m: Map<Str, Int> = {"a": 7};\nlet value: Optional<Int> = m["a"];\nlet n: Int = value ?? 0;\nprint(n);', '7\n'),
    'void': ('fun announce() -> Nil { print("hello"); return; }\nannounce();', 'hello\n'),
    'dynamic_escape': ('let value: Any = "x";\nprint(value);', 'x\n'),
    'empty_collections': ('let xs: List<Int> = [];\nlet m: Map<Str, Int> = {};\nprint(sum(xs), len(m));', '0 0\n'),
}
FAIL = {
    'missing_struct_field_type': ('struct P { x }', 'explicit type annotation'),
    'missing_enum_payload_type': ('enum E { Value(x) }', 'explicit type annotation'),
    'untyped_comprehension': ('let xs: List<Int> = [x for x in [1]];', 'explicit type annotation'),
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
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'toolchain/mayc/mayc_new')
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
        # Preserve closure-valued tails and existing typed fields during migration.
        source = work/'migration.may'
        source.write_text('struct P { x: Int }\nfun make(n) { fun(x) { x+n } }\nlet f=make(4); print(f(5), P(2).x);')
        subprocess.run(['python3', str(ROOT/'toolchain/mayc/tools/migrate_strict.py'), str(source), '--write'], check=True)
        result = subprocess.run([str(compiler), str(source), '-o', str(work/'migration')], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        assert subprocess.check_output([str(work/'migration')]) == b'9 2\n'
        print('PASS migration preserves closures and typed fields', flush=True)

if __name__ == '__main__':main()
