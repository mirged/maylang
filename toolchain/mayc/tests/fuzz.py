#!/usr/bin/env python3
"""Seeded frontend mutations with bounded checks and minimized crash artifacts."""
import argparse
import json
import random
import resource
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
TEMPLATES=[
    'fun add(a: Int, b: Int) -> Int { return a+b; } let n=add(1,2);',
    'enum E { A(n: Int), B } fun use(e: E) -> Int { return match(e) { A(n) => n, B() => 0 }; }',
    'fun use(r: Result<Int, Str>) -> Result<Int, Str> { return Ok(r?+1); }',
    'let xs: List<Int> = [1,2,3]; let ys = [x*2 for x in xs if x>1];',
]
TOKENS=[';', '{', '}', '(', ')', '[', ']', '<', '>', '?', '"', '/*', '*/', '\n', '🙂', '\x00', 'return', 'import "missing";']


def resource_limits():
    resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',type=Path,default=ROOT/'toolchain/mayc/mayc_new');parser.add_argument('--seed',type=int,default=731);parser.add_argument('--cases',type=int,default=48);args=parser.parse_args()
    rng=random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix='mayc-fuzz-') as directory:
        work=Path(directory);source=work/'input.may'
        def check(text):
            source.write_text(text)
            try:
                result=subprocess.run([str(args.compiler.resolve()),'--check',str(source)],capture_output=True,timeout=5,preexec_fn=resource_limits)
                return result.returncode in (0,1),result.returncode,result.stderr.decode(errors='replace')
            except subprocess.TimeoutExpired:
                return False,'timeout','frontend exceeded five seconds'
        for case in range(args.cases):
            text=rng.choice(TEMPLATES)
            for _ in range(rng.randint(1,4)):
                start=rng.randrange(len(text)+1)
                stop=min(len(text),start+rng.randrange(0,8))
                text=text[:start]+rng.choice(TOKENS)+text[stop:]
            ok,status,message=check(text)
            if not ok:
                original=text
                # Bounded deletion minimization preserves the crash/timeout.
                chunk=max(1,len(text)//2);attempts=0
                while chunk and attempts<32:
                    changed=False
                    for start in range(0,len(text),chunk):
                        candidate=text[:start]+text[start+chunk:];attempts+=1
                        if not check(candidate)[0]:text=candidate;changed=True;break
                        if attempts>=32:break
                    if not changed:chunk//=2
                artifacts=ROOT/'tests/compliance/build/fuzz';artifacts.mkdir(parents=True,exist_ok=True)
                prefix=artifacts/f'seed-{args.seed}-case-{case}'
                prefix.with_suffix('.may').write_text(text)
                prefix.with_suffix('.json').write_text(json.dumps({'seed':args.seed,'case':case,'status':status,'stderr':message,'original':original},indent=2)+'\n')
                raise AssertionError(f'frontend failure; minimized reproduction: {prefix}.may')
        # Import graphs must also terminate, even with cycles and alternate paths.
        (work/'a.may').write_text('import "b";\nfun a() -> Int { return 1; }')
        (work/'b.may').write_text('import "./a.may";\nfun b() -> Int { return 2; }')
        assert check('import "a";\nimport "./a.may";\nprint(a());')[0]
        for case in range(8):
            for index in range(4):
                imports = []
                for edge in range(rng.randrange(4)):
                    target = rng.randrange(4)
                    name = rng.choice([f'm{target}', f'./m{target}.may', f'./nested/../m{target}.may'])
                    imports.append(f'import "{name}" as edge{edge};')
                (work/f'm{index}.may').write_text('\n'.join(imports)+f'\npub fun value{index}() -> Int {{ return {index}; }}')
            ok, status, message = check('import "m0";\nprint(42);')
            if not ok:
                artifacts = ROOT/f'tests/compliance/build/fuzz/seed-{args.seed}-graph-{case}'
                artifacts.mkdir(parents=True, exist_ok=True)
                for module in work.glob('*.may'): (artifacts/module.name).write_bytes(module.read_bytes())
                (artifacts/'failure.json').write_text(json.dumps({'seed':args.seed,'case':case,'token_cases':args.cases,'status':status,'stderr':message},indent=2)+'\n')
                raise AssertionError(f'import graph failure; saved reproduction: {artifacts}')
        print(f'PASS {args.cases} seeded frontend mutations and cyclic/alternate/mutated import graphs (seed {args.seed})')


if __name__=='__main__':main()
