#!/usr/bin/env python3
"""Migrate legacy Maylang source to explicit annotations and return statements.

Any marks boundaries whose types cannot be recovered safely from syntax.
Review those boundaries manually; this is a syntax migration, not inference.
"""
import argparse
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Token:
    value: str
    a: int
    b: int


def lex(text):
    pattern = re.compile(r'//[^\n]*|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|=>|->|\|>|\.\.\.?=?|\?\?|\?\.|==|!=|<=|>=|\+=|-=|\*=|/=|&&|\|\||[^\s]', re.S)
    tokens = [Token(m.group(), m.start(), m.end()) for m in pattern.finditer(text) if not m.group().startswith('//')]
    pairs = {}; stack=[]
    for i,t in enumerate(tokens):
        if t.value in ('(', '[', '{'):stack.append(i)
        elif t.value in (')', ']', '}'):
            if not stack or tokens[stack[-1]].value != {')':'(',']':'[','}':'{'}[t.value]:
                raise ValueError('unbalanced source')
            j=stack.pop();pairs[j]=i;pairs[i]=j
    if stack:raise ValueError('unbalanced source')
    return tokens,pairs


def apply(text, edits):
    for a,b,replacement in sorted(edits,key=lambda e:(e[0],e[1]),reverse=True):text=text[:a]+replacement+text[b:]
    return text


def destructures(text):
    ts,pairs=lex(text);edits=[];serial=0
    def binds(first,last,expression,keyword):
        out=[];i=first+1;index=0
        while i<last:
            t=ts[i]
            if t.value==',':i+=1;continue
            key=str(index) if ts[first].value=='[' else '"'+t.value+'"'
            if ts[first].value=='{' and i+1<last and ts[i+1].value==':':i+=2;t=ts[i]
            access=expression+'['+key+']'
            if t.value in ('[','{'):
                stop=pairs[i];out+=binds(i,stop,access,keyword);i=stop+1
            else:
                if t.value!='_':out.append(f'{keyword} {t.value}: Any = {access};')
                i+=1
            index+=1
        return out
    for i,t in enumerate(ts[:-2]):
        if t.value not in ('let','mut') or ts[i+1].value not in ('[','{'):continue
        stop=pairs[i+1]
        if ts[stop+1].value!='=':continue
        end=stop+2
        while end<len(ts) and ts[end].value!=';':
            if end in pairs and pairs[end]>end:end=pairs[end]
            end+=1
        if end>=len(ts):continue
        serial+=1;name=f'__typed_binding_{serial}';expr=text[ts[stop+2].a:ts[end].a]
        replacement=f'let {name}: Any = {expr}; '+' '.join(binds(i+1,stop,name,t.value))
        edits.append((t.a,ts[end].b,replacement))
    return apply(text,edits)


def migrate(text):
    text=destructures(text);ts,pairs=lex(text);edits=[];bodies=[]
    def insert(at,value):edits.append((at,at,value))
    def parameters(first,last):
        i=first
        while i<last:
            if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',ts[i].value):
                if i+1==last or ts[i+1].value==',':insert(ts[i].b,': Any')
            while i<last and ts[i].value!=',':
                if i in pairs and pairs[i]>i:i=pairs[i]
                i+=1
            i+=1
    def expression_end(first):
        i=first
        while i<len(ts) and ts[i].value not in (',',';',')',']','}'):
            if i in pairs and pairs[i]>i:i=pairs[i]
            i+=1
        return i
    # Match arm arrows are syntax separators, not short lambdas.
    arm_arrows=set()
    for i,t in enumerate(ts):
        if t.value!='match':continue
        j=i+1
        if ts[j].value=='(':j=pairs[j]+1
        else:
            while j<len(ts) and ts[j].value!='{':j+=1
        if j>=len(ts) or j not in pairs:continue
        end=pairs[j];j+=1;need_arrow=True
        while j<end:
            if ts[j].value==',' :need_arrow=True
            elif ts[j].value=='=>' and need_arrow:arm_arrows.add(j);need_arrow=False
            if j in pairs and pairs[j]>j:j=pairs[j]
            j+=1
    for i,t in enumerate(ts):
        if t.value=='for' and i+2<len(ts) and ts[i+2].value=='in':
            insert(ts[i+1].b,': Any')
        if t.value in ('let','mut') and i+2<len(ts) and ts[i+2].value=='=':
            insert(ts[i+1].b,': Any')
        if t.value in ('struct','enum'):
            j=i+2
            if j>=len(ts) or ts[j].value!='{' or j not in pairs:continue
            end=pairs[j];k=j+1
            while k<end:
                if ts[k].value==',':k+=1;continue
                if t.value=='struct' and ts[k].value.startswith(chr(34)):
                    k+=1
                    while k<end and ts[k].value!=',':
                        if k in pairs and pairs[k]>k:k=pairs[k]
                        k+=1
                    continue
                if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',ts[k].value):
                    if t.value=='struct':
                        if k+1==end or ts[k+1].value==',':insert(ts[k].b,': Any')
                        k+=1
                        while k<end and ts[k].value!=',':
                            if k in pairs and pairs[k]>k:k=pairs[k]
                            k+=1
                        continue
                    if t.value=='enum' and ts[k+1].value=='(':
                        stop=pairs[k+1];parameters(k+2,stop);k=stop
                if k in pairs and pairs[k]>k:k=pairs[k]
                k+=1
        if t.value=='fun':
            j=i+1
            if j<len(ts) and ts[j].value!='(':
                j+=1
                if j<len(ts) and ts[j].value=='<':
                    while j<len(ts) and ts[j].value!='>':j+=1
                    j+=1
            if j>=len(ts) or ts[j].value!='(' or j not in pairs:continue
            stop=pairs[j];parameters(j+1,stop);body=stop+1
            if ts[body].value!='->':insert(ts[stop].b,' -> Any')
            else:
                body+=1
                while body<len(ts) and ts[body].value not in ('{',';','='):
                    if body in pairs and pairs[body]>body:body=pairs[body]
                    body+=1
            if body<len(ts) and ts[body].value=='{':bodies.append((body,pairs[body]))
        if t.value=='|' and (i==0 or ts[i-1].value in ('(', ',', '=', '[', ':', 'return', '|>', '{', ';')):
            j=i+1
            while j<len(ts) and ts[j].value not in ('|',';','{'):j+=1
            if j==len(ts) or ts[j].value!='|':continue
            parameters(i+1,j);body=j+1
            if ts[body].value!='->':insert(ts[j].b,' -> Any')
            else:
                body+=1
                while body<len(ts) and ts[body].value!='{':body+=1
            if body<len(ts) and ts[body].value=='{':bodies.append((body,pairs[body]))
            elif body<len(ts):
                end=expression_end(body);insert(ts[body].a,'{ return ');insert(ts[end].a if end<len(ts) else len(text),'; }')
        if t.value=='=>' and i not in arm_arrows and i>0 and re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',ts[i-1].value):
            edits.append((ts[i-1].a,t.b,'|'+ts[i-1].value+': Any| -> Any'))
            body=i+1
            if ts[body].value=='{':bodies.append((body,pairs[body]))
            else:
                end=expression_end(body);insert(ts[body].a,'{ return ');insert(ts[end].a if end<len(ts) else len(text),'; }')
    body_queue=list(set(bodies));seen_bodies=set()
    while body_queue:
        first,last=body_queue.pop()
        if (first,last) in seen_bodies:continue
        seen_bodies.add((first,last))
        # Walk only the outer statements; all nested blocks are paired.
        segments=[];start=first+1;i=start
        while i<last:
            if ts[i].value==';':segments.append((start,i));start=i+1;i+=1;continue
            if ts[i].value=='{' and i==start and i+1<last and ts[i+1].value in ('let','mut','if','while','for','return'):
                j=pairs[i];segments.append((start,j));start=j+1;i=start;continue
            if ts[i].value in ('if','unless','while','for','fun') and i==start:
                j=i+1
                while j<last and ts[j].value not in ('{',';'):
                    if j in pairs and pairs[j]>j:j=pairs[j]
                    j+=1
                if j<last and ts[j].value=='{':
                    j=pairs[j]
                    while j+1<last and ts[j+1].value=='else':
                        j+=2
                        while j<last and ts[j].value!='{':
                            if j in pairs and pairs[j]>j:j=pairs[j]
                            j+=1
                        if j<last:j=pairs[j]
                    if j+1<last and ts[j+1].value==';':j+=1
                    segments.append((start,j));start=j+1;i=start;continue
            if i in pairs and pairs[i]>i:i=pairs[i]
            i+=1
        if start<last:segments.append((start,last-1))
        if not segments:insert(ts[last].a,' return nil; ');continue
        a,b=segments[-1];kind=ts[a].value
        if kind=='return':continue
        if kind=='{':
            body_queue.append((a,pairs[a]));continue
        if kind in ('while','for','break','continue') or (kind=='fun' and ts[a+1].value!='('):
            insert(ts[last].a,' return nil; ')
        elif kind in ('let','mut'):
            insert(ts[last].a,' return '+ts[a+1].value+'; ')
        elif a+1<=b and ts[a+1].value in ('=','+=','-=','*=','/='):
            insert(ts[last].a,' return '+ts[a].value+'; ')
        else:
            insert(ts[a].a,'return ')
            # Semicolons are optional; nested lambda edits may end here too.
    # Existing coarse collection annotations become explicitly dynamic elements.
    for i,t in enumerate(ts):
        if t.value in ('List','Map') and i>0 and ts[i-1].value in (':','->','<',',') and i+1<len(ts) and ts[i+1].value!='<':
            insert(t.b,'<Any>' if t.value=='List' else '<Any, Any>')
    return apply(text,edits)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('files',nargs='+',type=Path);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    for path in args.files:
        result=migrate(path.read_text())
        if args.write:path.write_text(result)
        else:print(result)

if __name__=='__main__':main()
