from common import WORK, run_cases

cases={
'string_backslash':('let s="\\\\u00e9"; print(len(s), ord(s[0]), s);','6 92 \\u00e9\n'),
'json_surrogate':('let s=chr(34)+chr(92)+"uD83D"+chr(92)+"uDE42"+chr(34); print(json_parse(s));','🙂\n'),
'min_construct':('let x=0-int("1152921504606846975")-1; print(may { -x } otherwise { err.kind });','arithmetic\n'),
'min_parse_caught':('print(may { int("-1152921504606846976") } otherwise { err.kind });','-1152921504606846976\n'),
'json_string_roundtrip':('let s=chr(92)+"u00e9"; print(json_parse(json_stringify(s)) == s);','true\n'),
}
# Neighboring cases ensure the fixes cover more than the original examples.
cases.update({
 'minimum_literal': ('print(-1152921504606846976);', '-1152921504606846976\n'),
 'minimum_abs': ('print(may { abs(-1152921504606846976) } otherwise { err.kind });', 'arithmetic\n'),
 'integer_parse_limits': ('print(may { int("1152921504606846976") } otherwise { err.kind }); print(may { int("-1152921504606846977") } otherwise { err.kind });', 'arithmetic\narithmetic\n'),
 'shared_collection': ('let a=[1]; print([a,a]);', '[[1], [1]]\n'),
 'mutual_cycle': ('let a=[]; let b={}; push(a,b); b.back=a; print(a); print([1]);', '[{"back": <cycle>}]\n[1]\n'),
 'invalid_calls': ('for x in [nil, true, "x", [], {}, 3.0, -1] { print(may { x() } otherwise { err.kind }); }', 'type\n'*7),
 'valid_closure': ('fun make(x) { fun(y) { x+y } } print(make(4)(5));', '9\n'),
 'compound_property': ('let m={x:10}; mut n=0; fun getm() { n+=1; m } getm().x+=5; print(m.x,n);', '15 1\n'),
 'compound_sequence': ('let a=[8]; a[0]*=3; a[0]-=4; a[0]/=2; print(a);', '[10]\n'),
 'compound_order': ('let a=[10]; mut order=""; fun obj() { order+="o"; a } fun idx() { order+="i"; 0 } fun rhs() { order+="r"; a[0]=100; 5 } obj()[idx()]+=rhs(); print(a,order);', '[15] oir\n'),
 'json_invalid_surrogates': ('let q=chr(34); let b=chr(92); for s in ["uD800", "uDC00", "uD800"+b+"u0041", "uZZZZ", "u12"] { print(may { json_parse(q+b+s+q) } otherwise { err.kind }); }', 'parse\n'*5),
 'json_surrogate_roundtrip': ('let x="🙂é中"; print(json_parse(json_stringify(x)) == x);', 'true\n'),
 'float_large_mantissa': ('print(100000000000000000000.0 > 1.0);', 'true\n'),
})
(WORK/'module_select.may').write_text('pub let value=7; pub let other=9;\n')
cases['module_selective'] = ('from "module_select.may" import value;\nprint(value);', '7\n')
cases['module_string_preserved'] = ('import "module_a.may" as a;\nprint("a.value", a.value());', 'a.value 11\n')
cases['module_shared_name'] = ('import "module_a.may";\nimport "module_b.may";\nprint(value());', None)
cases['module_selective_hidden'] = ('from "module_select.may" import value;\nprint(other);', None)
cases['integer_positive_overflow'] = ('print(1152921504606846976);', None)
cases['integer_negative_overflow'] = ('print(-1152921504606846977);', None)

cases['module_alias_shadow'] = ('import "module_a.may" as a;\nfun local(a) { a.value } print(local({value:8}),a.value());', '8 11\n')

run_cases(cases, "followup.json")
