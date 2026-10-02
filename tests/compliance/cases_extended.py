from common import WORK, run_cases

cases={
'call_integer_min':('may { let x=42; x(); } otherwise { print("caught"); }','caught\n'),
'cycle_caught':('let a=[]; push(a,a); may { print(a); } otherwise { print("caught"); }','[<cycle>]\n'),
'json_confirm':('let s=chr(34)+chr(92)+"u00e9"+chr(34); print(s); print(json_parse(s));','"\\u00e9"\né\n'),
'valid_max_literal':('print(1152921504606846975);','1152921504606846975\n'),
'valid_large_literal':('print(144115188075855872);','144115188075855872\n'),
'max_runtime':('let x=int("1152921504606846975"); print(x); print(may { x+1 } otherwise { err.kind });','1152921504606846975\narithmetic\n'),
'min_runtime_neg':('let x=int("-1152921504606846976"); print(x); print(may { -x } otherwise { err.kind });','-1152921504606846976\narithmetic\n'),
'min_runtime_div':('let x=int("-1152921504606846976"); print(may { x / -1 } otherwise { err.kind });','arithmetic\n'),
'compound_index':('let xs=[10]; mut n=0; fun idx() { n+=1; 0 } xs[idx()]+=5; print(xs,n);','[15] 1\n'),
'compound_receiver':('let xs=[10]; mut n=0; fun getxs() { n+=1; xs } getxs()[0]+=5; print(xs,n);','[15] 1\n'),
'json_trailing':('print(may { json_parse("{\\\"a\\\":1} garbage") } otherwise { "caught" });','caught\n'),
'missing_expr':('let x = ;',None),
'missing_brace':('fun f() { print(1);',None),
'dangling_operator':('print(1 + );',None),
}
(WORK/'module_a.may').write_text('let secret=11; pub fun value() { secret }\n')
(WORK/'module_b.may').write_text('let secret=22; pub fun value() { secret }\n')
cases['module_isolation']=('import "module_a.may" as a;\nimport "module_b.may" as b;\nprint(a.value(),b.value());','11 22\n')
cases['module_private']=('import "module_a.may" as a;\nprint(a.secret);',None)
import random
rng=random.Random(42);lines=[];expected=[]
for i in range(100):
 a=rng.randint(-1000000,1000000);b=rng.randint(1,1000000);op=rng.choice(['+','-','*','/','%'])
 q=abs(a)//b*(-1 if a<0 else 1)
 v={'+':a+b,'-':a-b,'*':a*b,'/':q,'%':a-q*b}[op]
 lines.append(f'let a{i}={a}; let b{i}={b}; print(a{i} {op} b{i});');expected.append(str(v))
cases['arithmetic_oracle']=('\n'.join(lines),'\n'.join(expected)+'\n')
run_cases(cases, "round2.json")
