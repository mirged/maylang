from common import WORK, run_cases

cases={
 'unicode':('print(len("é🙂中"), "é🙂中"[0], "é🙂中"[1], "é🙂中"[2]);','3 é 🙂 中\n'),
 'tail_swap':('fun f(n,a,b) { if n == 0 { [a,b] } else { f(n-1,b,a) } } print(f(100001,1,2));','[2, 1]\n'),
 'tail_capture':('fun f(n,x) { let g = fun() { x }; if n == 0 { g() } else { f(n-1,x+1) } } print(f(10000,0));','10000\n'),
 'loop_closures':('fun make() { let fs=[]; for i in 0..3 { push(fs,fun() { i }); } fs } let fs=make(); print(fs[0](),fs[1](),fs[2]());','0 1 2\n'),
 'handler_break':('for i in 0..3 { may { break; } otherwise { print("BAD"); } } print(may { fail("after") } otherwise { "caught" });','caught\n'),
 'handler_continue':('for i in 0..3 { may { continue; } otherwise { print("BAD"); } } print(may { fail("after") } otherwise { "caught" });','caught\n'),
 'handler_return':('fun f() { may { return 7; } otherwise { 0 } } print(f()); print(may { fail("after") } otherwise { "caught" });','7\ncaught\n'),
 'handler_result':('fun f() { may { let x = Err("bad")?; Ok(x) } otherwise { Err("wrong") } } print(f().error); print(may { fail("after") } otherwise { "caught" });','bad\ncaught\n'),
 'nested_rethrow':('print(may { may { fail("one") } otherwise { fail("two") } } otherwise { err.message });','two\n'),
 'safe_side_effect':('mut n=0; fun hit() { n+=1; 0 } let x=nil; print(x?.a, n); print(true or hit(), false and hit(), n);','nil 0\ntrue false 0\n'),
 'coalesce_side_effect':('mut n=0; fun hit() { n+=1; 99 } print(0 ?? hit(), false ?? hit(), "" ?? hit()); print(n);','0 false \n0\n'),
 'min_div':('let x = -1152921504606846975 - 1; print(may { x / -1 } otherwise { err.kind });','arithmetic\n'),
 'min_negate':('let x = -1152921504606846975 - 1; print(may { -x } otherwise { err.kind });','arithmetic\n'),
 'max_add':('let x=1152921504606846975; print(may { x+1 } otherwise { err.kind });','arithmetic\n'),
 'huge_literal':('print(999999999999999999999999999999999999999999999999999999);',None),
 'cycle_list':('let a=[]; push(a,a); print(a);',None),
 'cycle_map':('let a={}; a.self=a; print(a);',None),
 'cycle_equal':('let a=[]; push(a,a); let b=[]; push(b,b); print(a == b);',None),
 'bad_call':('print(may { let x=42; x() } otherwise { "caught" });','caught\n'),
 'bad_index':('print(may { [1,2]["oops"] } otherwise { "caught" });',None),
 'negative_index':('print(may { [1,2][-1000000000] } otherwise { "caught" });',None),
 'empty_pop':('print(may { pop([]) } otherwise { "caught" });',None),
 'div_zero_float':('print(may { 1.0 / 0.0 } otherwise { "caught" });',None),
 'return_top':('return 42;',None),
 'duplicate_params':('fun f(x,x) { x } print(f(1,2));',None),
 'json_unicode':('print(json_parse("\\\"\\u00e9\\uD83D\\uDE42\\\""));','é🙂\n'),
 'eval_order':('mut n=0; fun next() { n+=1; n } fun f(a,b,c,d,e,f,g,h) { [a,b,c,d,e,f,g,h] } print(f(next(),next(),next(),next(),next(),next(),next(),next()));','[1, 2, 3, 4, 5, 6, 7, 8]\n'),
}
observed = {
 'cycle_list': '[<cycle>]\n', 'cycle_map': '{"self": <cycle>}\n',
 'cycle_equal': 'false\n', 'bad_index': 'nil\n', 'negative_index': 'nil\n',
 'empty_pop': 'nil\n', 'div_zero_float': 'caught\n',
 'json_unicode': 'u00e9uD83DuDE42\n',
}
for name, expected in observed.items(): cases[name] = (cases[name][0], expected)
run_cases(cases, "results.json")
