/* Stage-zero runtime: libc allocation, retained until process exit. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <setjmp.h>
#include <math.h>
#include <errno.h>
#include <unistd.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/wait.h>

typedef struct { int tag; int64_t i; void *p; } V;
typedef struct { size_t n; char *data; } Str;
typedef struct { size_t n, cap; V *items; } Items;
typedef V (*Fn)(V **, int, V *);
typedef struct { Fn fn; int arity; V **captures; const char *name; } Closure;
typedef struct Handler { jmp_buf jump; V error; struct Handler *previous; } Handler;
static Handler *handler;
static const V nil = {2,0,NULL};
static int process_argc;
static char **process_argv;

static void *allocate(size_t n) {
    void *p=calloc(1,n?n:1);
    if(!p) { fputs("may-bootstrap: out of memory\n",stderr); exit(70); }
    return p;
}
static V integer(int64_t n) { return (V){0,n,NULL}; }
static V boolean(int b) { return (V){b?4:3,0,NULL}; }
static V floating(double d) { double *p=allocate(sizeof(double)); *p=d; return (V){6,0,p}; }
static V string_value(Str *s) { return (V){1,0,s}; }
#define S(text,size) ({ static Str literal={size,text}; string_value(&literal); })
static V string(const char *bytes,size_t n) {
    Str *s=allocate(sizeof(Str)); s->n=n; s->data=allocate(n+1);
    memcpy(s->data,bytes,n); return string_value(s);
}
static V *cell(V v) { V *p=allocate(sizeof(V)); *p=v; return p; }
static V list(int tag,size_t n,V *values) {
    Items *p=allocate(sizeof(Items)); p->n=n; p->cap=n?n:4;
    p->items=allocate(p->cap*sizeof(V)); if(n) memcpy(p->items,values,n*sizeof(V));
    return (V){tag,0,p};
}
static V closure(Fn fn,int arity,int n,V **captures) {
    Closure *p=allocate(sizeof(Closure)); p->fn=fn; p->arity=arity;
    p->captures=allocate(n*sizeof(V*)); if(n) memcpy(p->captures,captures,n*sizeof(V*));
    return (V){8,0,p};
}
#define primitive(text) ({ static Closure p={.name=text}; (V){8,0,&p}; })
static V set_index(V,V,V);
static V stringify(V);
static void raise_value(V v) {
    if(handler) { handler->error=v; longjmp(handler->jump,1); }
    V text=stringify(v); Str *s=text.p;
    fprintf(stderr,"may-bootstrap runtime: %.*s\n",(int)s->n,s->data); exit(70);
}
static void fault(const char *text) {
    V error=list(7,0,NULL);
    set_index(error,S("kind",4),S("runtime",7));
    set_index(error,S("message",7),string(text,strlen(text)));
    raise_value(error);
}
static int truth(V v) { return v.tag!=2 && v.tag!=3 && (v.tag!=0 || v.i!=0); }
static int64_t number(V v) { if(v.tag!=0) fault("expected an integer"); return v.i; }
static double real(V v) {
    if(v.tag==6) return *(double*)v.p;
    return (double)number(v);
}
static size_t length(V v) {
    if(v.tag==1) return ((Str*)v.p)->n;
    if(v.tag==5 || v.tag==7) return ((Items*)v.p)->n/(v.tag==7?2:1);
    fault("len expects a string, list or map"); return 0;
}
static int equal(V a,V b) {
    if(a.tag!=b.tag) return (a.tag==0 || a.tag==6) && (b.tag==0 || b.tag==6) && real(a)==real(b);
    if(a.tag==0) return a.i==b.i;
    if(a.tag==6) return real(a)==real(b);
    if(a.tag==1) { Str *x=a.p,*y=b.p; return x->n==y->n && !memcmp(x->data,y->data,x->n); }
    if(a.tag==5 || a.tag==7) {
        if(a.p==b.p) return 1;
        Items *x=a.p,*y=b.p;
        if(x->n!=y->n) return 0;
        for(size_t i=0;i<x->n;i++) if(!equal(x->items[i],y->items[i])) return 0;
        return 1;
    }
    return a.p==b.p;
}
static int compare(V a,V b) {
    if(a.tag==0 && b.tag==0) return (a.i>b.i)-(a.i<b.i);
    if(a.tag==1 && b.tag==1) {
        Str *x=a.p,*y=b.p; size_t n=x->n<y->n?x->n:y->n;
        int r=memcmp(x->data,y->data,n); return r?r:(x->n>y->n)-(x->n<y->n);
    }
    double x=real(a),y=real(b); return (x>y)-(x<y);
}
static int64_t position(V v,V key) {
    int64_t n=number(key), len=length(v); if(n<0) n+=len;
    if(n<0 || n>=len) fault("get_index out of bounds"); return n;
}
static int64_t map_position(V v,V key) {
    Items *p=v.p;
    for(size_t i=0;i<p->n;i+=2) if(equal(p->items[i],key)) return i;
    return -1;
}
static V get_index(V v,V key) {
    if(v.tag==7) { int64_t i=map_position(v,key); return i<0?nil:((Items*)v.p)->items[i+1]; }
    if(v.tag==5) return ((Items*)v.p)->items[position(v,key)];
    if(v.tag==1) return string(((Str*)v.p)->data+position(v,key),1);
    fault("get_index expects a collection"); return nil;
}
static V safe_index(V v,V key) { return v.tag==2?nil:get_index(v,key); }
static void reserve(Items *p,size_t n) {
    if(n<=p->cap) return;
    size_t cap=p->cap*2; if(cap<n) cap=n;
    V *next=realloc(p->items,cap*sizeof(V));
    if(!next) fault("out of memory"); p->items=next; p->cap=cap;
}
static V push(V v,V value) {
    if(v.tag!=5) fault("push expects a list");
    Items *p=v.p; reserve(p,p->n+1); p->items[p->n++]=value; return v;
}
static V set_index(V v,V key,V value) {
    if(v.tag==7) {
        Items *p=v.p; int64_t i=map_position(v,key);
        if(i<0) { reserve(p,p->n+2); i=p->n; p->n+=2; p->items[i]=key; }
        p->items[i+1]=value; return value;
    }
    if(v.tag==5) { ((Items*)v.p)->items[position(v,key)]=value; return value; }
    fault("assignment expects a list or map"); return nil;
}
static V iter(V v,size_t i) { return v.tag==7?((Items*)v.p)->items[i*2]:get_index(v,integer(i)); }
static V concat(V a,V b) {
    if(a.tag==5 && b.tag==5) {
        Items *x=a.p,*y=b.p; V out=list(5,0,NULL);
        for(size_t i=0;i<x->n;i++) push(out,x->items[i]);
        for(size_t i=0;i<y->n;i++) push(out,y->items[i]); return out;
    }
    a=stringify(a); b=stringify(b); Str *x=a.p,*y=b.p;
    Str *s=allocate(sizeof(Str)); s->n=x->n+y->n; s->data=allocate(s->n+1);
    memcpy(s->data,x->data,x->n); memcpy(s->data+x->n,y->data,y->n); return string_value(s);
}
static V stringify(V v) {
    char buffer[96];
    if(v.tag==1) return v;
    if(v.tag==2) return S("nil",3);
    if(v.tag==3) return S("false",5);
    if(v.tag==4) return S("true",4);
    if(v.tag==0) { int n=snprintf(buffer,sizeof(buffer),"%lld",(long long)v.i); return string(buffer,n); }
    if(v.tag==6) { int n=snprintf(buffer,sizeof(buffer),"%.17g",real(v)); return string(buffer,n); }
    if(v.tag==8) return S("<function>",10);
    V out=v.tag==5?S("[",1):S("{",1); Items *p=v.p;
    for(size_t i=0;i<p->n;i++) {
        if(i) out=concat(out,(v.tag==7 && i%2)?S(": ",2):S(", ",2));
        if(p->items[i].tag==1) out=concat(out,concat(S("\"",1),concat(p->items[i],S("\"",1))));
        else out=concat(out,stringify(p->items[i]));
    }
    return concat(out,v.tag==5?S("]",1):S("}",1));
}
static V checked(__int128 n) {
    if(n<-((__int128)1<<60) || n>(((__int128)1<<60)-1)) fault("integer overflow");
    return integer(n);
}
static V negate(V v) { return v.tag==6?floating(-real(v)):checked(-(__int128)number(v)); }
static V binary_add(V a,V b) {
    if(a.tag==1 || b.tag==1 || (a.tag==5 && b.tag==5)) return concat(a,b);
    if(a.tag==6 || b.tag==6) return floating(real(a)+real(b));
    return checked((__int128)number(a)+number(b));
}
static V binary_sub(V a,V b) { return a.tag==6 || b.tag==6?floating(real(a)-real(b)):checked((__int128)number(a)-number(b)); }
static V binary_mul(V a,V b) { return a.tag==6 || b.tag==6?floating(real(a)*real(b)):checked((__int128)number(a)*number(b)); }
static V binary_div(V a,V b) {
    if(real(b)==0) fault("division by zero");
    return a.tag==6 || b.tag==6?floating(real(a)/real(b)):checked((__int128)number(a)/number(b));
}
static V binary_mod(V a,V b) {
    if(real(b)==0) fault("division by zero");
    return a.tag==6 || b.tag==6?floating(fmod(real(a),real(b))):checked((__int128)number(a)%number(b));
}
static V binary_pow(V a,V b) {
    if(a.tag==0 && b.tag==0 && b.i>=0) {
        V out=integer(1); uint64_t n=b.i;
        while(n) { if(n&1) out=binary_mul(out,a); n>>=1; if(n) a=binary_mul(a,a); } return out;
    }
    return floating(pow(real(a),real(b)));
}
static V binary_eq(V a,V b) { return boolean(equal(a,b)); }
static V binary_ne(V a,V b) { return boolean(!equal(a,b)); }
static V binary_lt(V a,V b) { return boolean(compare(a,b)<0); }
static V binary_le(V a,V b) { return boolean(compare(a,b)<=0); }
static V binary_gt(V a,V b) { return boolean(compare(a,b)>0); }
static V binary_ge(V a,V b) { return boolean(compare(a,b)>=0); }
static V range_exclusive(V a,V b) {
    V out=list(5,0,NULL); int64_t start=number(a),end=number(b);
    for(int64_t i=start;i<end;i++) push(out,integer(i)); return out;
}
static V range_inclusive(V a,V b) {
    V out=range_exclusive(a,b); if(number(a)<=number(b)) push(out,b); return out;
}
static V builtin(const char *,int,V *);
static V call(V fn,int argc,V *args) {
    if(fn.tag!=8) fault("expected a function"); Closure *c=fn.p;
    if(c->name) return builtin(c->name,argc,args);
    if(argc!=c->arity) fault("argument count mismatch"); return c->fn(c->captures,argc,args);
}
static void arity(int argc,int required) { if(argc!=required) fault("primitive argument count mismatch"); }
static V builtin(const char *name,int n,V *a) {
#define IS(s) (!strcmp(name,s))
    if(IS("print")) {
        for(int i=0;i<n;i++) { if(i) putchar(' '); Str *s=stringify(a[i]).p; fwrite(s->data,1,s->n,stdout); }
        putchar('\n'); return integer(0);
    }
    if(IS("syscall")) {
        if(n<1 || n>7) fault("syscall expects 1 to 7 arguments");
        long v[7]={0}; for(int i=0;i<n;i++) v[i]=number(a[i]);
        long r=syscall(v[0],v[1],v[2],v[3],v[4],v[5],v[6]); return integer(r==-1?-errno:r);
    }
    if(IS("fail")) {
        V message=S("",0); for(int i=0;i<n;i++) { if(i) message=concat(message,S(" ",1)); message=concat(message,a[i]); }
        V error=list(7,0,NULL); set_index(error,S("kind",4),S("fail",4)); set_index(error,S("message",7),message); raise_value(error);
    }
    if(IS("rt_raise")) { arity(n,1); raise_value(a[0]); }
    if(IS("len")) { arity(n,1); return integer(length(a[0])); }
    if(IS("push")) { arity(n,2); return push(a[0],a[1]); }
    if(IS("pop")) { arity(n,1); if(a[0].tag!=5 || !length(a[0])) fault("pop expects a nonempty list"); Items *p=a[0].p; return p->items[--p->n]; }
    if(IS("map") || IS("filter") || IS("any") || IS("all")) {
        arity(n,2); V out=list(5,0,NULL);
        for(size_t i=0;i<length(a[0]);i++) {
            V item=iter(a[0],i),r=call(a[1],1,&item);
            if(IS("map")) push(out,r); else if(IS("filter") && truth(r)) push(out,item);
            else if(IS("any") && truth(r)) return boolean(1); else if(IS("all") && !truth(r)) return boolean(0);
        }
        return IS("any")?boolean(0):IS("all")?boolean(1):out;
    }
    if(IS("reduce")) { arity(n,3); V out=a[2]; for(size_t i=0;i<length(a[0]);i++) { V args[]={out,iter(a[0],i)}; out=call(a[1],2,args); } return out; }
    if(IS("str_of") || IS("int_to_str")) { arity(n,1); return stringify(a[0]); }
    if(IS("value_tag")) { arity(n,1); return integer(a[0].tag); }
    if(IS("value_eq")) { arity(n,2); return boolean(equal(a[0],a[1])); }
    if(IS("str_cmp") || IS("cmp")) { arity(n,2); return integer(compare(a[0],a[1])); }
    if(IS("char_at")) { arity(n,2); if(a[0].tag!=1) fault("char_at expects a string"); return integer((unsigned char)((Str*)a[0].p)->data[position(a[0],a[1])]); }
    if(IS("char_from")) { arity(n,1); char c=number(a[0]); return string(&c,1); }
    if(IS("map_get")) { arity(n,2); return get_index(a[0],a[1]); }
    if(IS("map_set")) { arity(n,3); return set_index(a[0],a[1],a[2]); }
    if(IS("map_has")) { arity(n,2); if(a[0].tag!=7) fault("map_has expects a map"); return boolean(map_position(a[0],a[1])>=0); }
    if(IS("map_keys") || IS("map_values")) {
        arity(n,1); if(a[0].tag!=7) fault("expected a map"); Items *p=a[0].p; V out=list(5,0,NULL);
        for(size_t i=IS("map_values")?1:0;i<p->n;i+=2) push(out,p->items[i]); return out;
    }
    if(IS("to_map")) { arity(n,1); if(a[0].tag==7) return a[0]; fault("to_map expects a map"); }
    if(IS("addr") || IS("cstr")) {
        arity(n,1); if(a[0].tag==1) return integer((intptr_t)((Str*)a[0].p)->data);
        if(a[0].tag==6) return integer((intptr_t)a[0].p); return integer(0);
    }
    if(!strncmp(name,"load",4) || !strncmp(name,"store",5)) {
        int store=name[0]=='s'; arity(n,store?2:1);
        int bits=atoi(name+(store?5:4)); if(bits!=8 && bits!=16 && bits!=32 && bits!=64) fault("unsupported memory primitive");
        void *p=(void*)(intptr_t)number(a[0]);
        if(store) { uint64_t value=number(a[1]); memcpy(p,&value,bits/8); return integer(0); }
        uint64_t value=0; memcpy(&value,p,bits/8); return integer((int64_t)value);
    }
    if(IS("to_float")) { arity(n,1); return floating(real(a[0])); }
    if(IS("trunc")) { arity(n,1); double d=real(a[0]); if(!isfinite(d) || d<-(double)(INT64_C(1)<<60) || d>=(double)(INT64_C(1)<<60)) fault("integer overflow"); return integer((int64_t)d); }
#define MATH(s,f) if(IS(s)) { arity(n,1); return floating(f(real(a[0]))); }
    MATH("sqrt",sqrt) MATH("floor",floor) MATH("ceil",ceil)
    MATH("sin",sin) MATH("cos",cos) MATH("tan",tan) MATH("asin",asin) MATH("acos",acos) MATH("atan",atan)
    MATH("ln",log) MATH("log2",log2) MATH("log10",log10) MATH("exp",exp)
    if(IS("pow") || IS("atan2")) { arity(n,2); return floating(IS("pow")?pow(real(a[0]),real(a[1])):atan2(real(a[0]),real(a[1]))); }
    if(IS("exit")) { arity(n,1); exit(number(a[0])); }
    if(IS("args")) { arity(n,0); V out=list(5,0,NULL); for(int i=0;i<process_argc;i++) push(out,string(process_argv[i],strlen(process_argv[i]))); return out; }
    if(IS("clock")) { arity(n,0); struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return floating(t.tv_sec+t.tv_nsec/1e9); }
    if(IS("time")) { arity(n,0); return integer(time(NULL)); }
    if(IS("read_file") || IS("read_stdin")) {
        arity(n,IS("read_file")?1:0); FILE *f=stdin;
        if(n) { if(a[0].tag!=1) fault("read_file expects a string"); f=fopen(((Str*)a[0].p)->data,"rb"); if(!f) fault("cannot read file"); }
        size_t used=0,cap=4096; char *bytes=allocate(cap);
        for(;;) { if(used==cap) { cap*=2; char *next=realloc(bytes,cap); if(!next) fault("out of memory"); bytes=next; } size_t count=fread(bytes+used,1,cap-used,f); used+=count; if(!count) break; }
        if(ferror(f)) fault("cannot read file"); if(n) fclose(f); V out=string(bytes,used); free(bytes); return out;
    }
    if(IS("file_exists")) { arity(n,1); if(a[0].tag!=1) fault("expected a path string"); return boolean(access(((Str*)a[0].p)->data,F_OK)==0); }
    char message[128]; snprintf(message,sizeof(message),"unsupported bootstrap primitive: %s",name); fault(message); return nil;
}
