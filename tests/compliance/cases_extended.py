import random

from common import REJECT

CASES = {
'json_confirm':('let s=chr(34)+chr(92)+"u00e9"+chr(34); print(s); print(json_parse(s));','"\\u00e9"\né\n'),
'valid_max_literal':('print(1152921504606846975);','1152921504606846975\n'),
'valid_large_literal':('print(144115188075855872);','144115188075855872\n'),
'max_runtime':('let x=int("1152921504606846975"); print(x); print(may { x+1 } otherwise { err.kind });','1152921504606846975\narithmetic\n'),
'min_runtime_neg':('let x=int("-1152921504606846976"); print(x); print(may { -x } otherwise { err.kind });','-1152921504606846976\narithmetic\n'),
'min_runtime_div':('let x=int("-1152921504606846976"); print(may { x / -1 } otherwise { err.kind });','arithmetic\n'),
'json_trailing':('print(may { json_parse("{\\\"a\\\":1} garbage") } otherwise { "caught" });','caught\n'),
'missing_expr':('let x = ;',REJECT),
'missing_brace':('fun f() { print(1);',REJECT),
'dangling_operator':('print(1 + );',REJECT),
}
FIXTURES = {
    'module_a.may': 'let secret=11; pub fun value() { secret }\n',
    'module_b.may': 'let secret=22; pub fun value() { secret }\n',
}
CASES['module_isolation']=('import "module_a.may" as a;\nimport "module_b.may" as b;\nprint(a.value(),b.value());','11 22\n')
CASES['module_private']=('import "module_a.may" as a;\nprint(a.secret);',REJECT)
rng=random.Random(42);lines=[];expected=[]
for i in range(100):
 a=rng.randint(-1000000,1000000);b=rng.randint(1,1000000);op=rng.choice(['+','-','*','/','%'])
 q=abs(a)//b*(-1 if a<0 else 1)
 v={'+':a+b,'-':a-b,'*':a*b,'/':q,'%':a-q*b}[op]
 lines.append(f'let a{i}={a}; let b{i}={b}; print(a{i} {op} b{i});');expected.append(str(v))
CASES['arithmetic_oracle']=('\n'.join(lines),'\n'.join(expected)+'\n')
