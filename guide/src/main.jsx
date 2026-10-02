import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BookOpen, ChevronDown, ChevronRight, Code2, Copy, ExternalLink, FileCode2, Menu, Search, X } from 'lucide-react';
import { docs, groups } from './docs.js';
import './style.css';

const flatItems = groups.flatMap(group => group.items);
const titleFor = id => flatItems.find(item => item[0] === id)?.[1] ?? 'Maylang reference';

function tokenize(source) {
  const re = /(\/\*[\s\S]*?\*\/|\/\/[^\n]*|"(?:\\.|[^"\\])*"|\b(?:fun|let|mut|return|if|else|while|for|in|break|continue|struct|enum|match|may|otherwise|unless|import|from|as|pub|true|false|nil|and|or)\b|\b(?:Int|Int8|Int16|Int32|Int64|UInt8|UInt16|UInt32|UInt64|Float|Float32|Float64|F32|F64|Str|Bool|Nil|Void|Any|Ptr|RawPtr|List|Slice|Map|Option|Optional|Result|Tuple|Fn)\b|\b(?:print|str|int|float|bool|type|len|push|pop|range|keys|values|has|merge|remove|map|filter|reduce|any|all|sum|product|sort|reverse|assert|fail|may|env|exit|clock|time|read_file|write_file|json_parse|json_stringify|spawn|yield|run|addr|ccall|syscall)\b|\b\d+(?:\.\d+)?\b|(?:\?\?|\?\.|\|>|=>|->|\*\*|==|!=|<=|>=|\+=|-=|\*=|\/=|\.\.=|\.\.)|[{}()[\].,:;]|[+*/%=<>!-])/g;
  const tokens = [];
  let last = 0, match;
  while ((match = re.exec(source))) {
    if (match.index > last) tokens.push({ text: source.slice(last, match.index), type: '' });
    const value = match[0];
    let type = 'punct';
    if (value.startsWith('//') || value.startsWith('/*')) type = 'comment';
    else if (value.startsWith('"')) type = 'string';
    else if (/^\d/.test(value)) type = 'number';
    else if (/^(Int|Int8|Int16|Int32|Int64|UInt8|UInt16|UInt32|UInt64|Float|Float32|Float64|F32|F64|Str|Bool|Nil|Void|Any|Ptr|RawPtr|List|Slice|Map|Option|Optional|Result|Tuple|Fn)$/.test(value)) type = 'type';
    else if (/^(print|str|int|float|bool|type|len|push|pop|range|keys|values|has|merge|remove|map|filter|reduce|any|all|sum|product|sort|reverse|assert|fail|env|exit|clock|time|read_file|write_file|json_parse|json_stringify|spawn|yield|run|addr|ccall|syscall)$/.test(value)) type = 'builtin';
    else if (/^(fun|let|mut|return|if|else|while|for|in|break|continue|struct|enum|match|may|otherwise|unless|import|from|as|pub|true|false|nil|and|or)$/.test(value)) type = 'keyword';
    else if (/^(\?\?|\?\.|\|>|=>|->|\*\*|==|!=|<=|>=|\+=|-=|\*=|\/=|\.\.=|\.\.|[+*/%=<>!-])$/.test(value)) type = 'operator';
    tokens.push({ text: value, type }); last = re.lastIndex;
  }
  if (last < source.length) tokens.push({ text: source.slice(last), type: '' });
  return tokens;
}

function Code({ code, language = 'may' }) {
  const [copied, setCopied] = useState(false);
  const tokens = useMemo(() => language === 'may' ? tokenize(code) : [{ text: code, type: '' }], [code, language]);
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1300); } catch { /* Clipboard access is optional. */ }
  }
  return <div className="codebox"><div className="codebar"><span><Code2 size={13}/>{language === 'may' ? 'Maylang' : language}</span><button onClick={copy} aria-label="Copy code"><Copy size={13}/>{copied ? 'Copied' : 'Copy'}</button></div><pre><code>{tokens.map((token, i) => <span key={i} className={token.type ? `tok-${token.type}` : undefined}>{token.text}</span>)}</code></pre></div>;
}

function App() {
  const [page, setPage] = useState(() => location.hash.slice(1) || 'overview');
  const [query, setQuery] = useState('');
  const [openGroups, setOpenGroups] = useState(Object.fromEntries(groups.map(group => [group.title, true])));
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const current = docs[page] ?? docs.overview;
  const filteredGroups = useMemo(() => groups.map(group => ({ ...group, items: group.items.filter(([id, label]) => {
    const text = `${label} ${docs[id]?.title ?? ''} ${docs[id]?.intro ?? ''} ${docs[id]?.sections?.map(s => s.join(' ')).join(' ') ?? ''}`.toLowerCase();
    return text.includes(query.toLowerCase());
  }) })).filter(group => group.items.length), [query]);

  useEffect(() => {
    const sync = () => { const next = location.hash.slice(1); if (docs[next]) setPage(next); };
    addEventListener('hashchange', sync);
    return () => removeEventListener('hashchange', sync);
  }, []);
  useEffect(() => { document.title = `${current.title} - Maylang language reference`; window.scrollTo({ top: 0, behavior: 'instant' }); }, [page]);
  useEffect(() => {
    const onKey = e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearchOpen(v => !v); document.querySelector('#doc-search')?.focus(); } if (e.key === 'Escape') { setSearchOpen(false); setMenuOpen(false); } };
    addEventListener('keydown', onKey); return () => removeEventListener('keydown', onKey);
  }, []);

  function navigate(id) { location.hash = id; setPage(id); setMenuOpen(false); setSearchOpen(false); setQuery(''); }
  const idx = flatItems.findIndex(([id]) => id === page);
  const previous = idx > 0 ? flatItems[idx - 1] : null;
  const next = idx < flatItems.length - 1 ? flatItems[idx + 1] : null;
  const related = current.see?.map(id => [id, titleFor(id)]) ?? [];

  return <div className="site-shell">
    <header className="topbar"><button className="icon-button mobile-menu" onClick={() => setMenuOpen(v => !v)} aria-label="Toggle navigation">{menuOpen ? <X/> : <Menu/>}</button><a className="brand" href="#overview" onClick={() => navigate('overview')}><span className="brand-icon"><BookOpen size={17}/></span><span>Maylang <small>Language reference</small></span></a><div className="top-links"><a href="../../README.md">Repository <ExternalLink size={13}/></a><a href="../../docs/STRICT.md">Strict syntax <ExternalLink size={13}/></a></div><button className="search-trigger" onClick={() => { setSearchOpen(true); document.querySelector('#doc-search')?.focus(); }}><Search size={15}/><span>Search documentation</span><kbd>Ctrl K</kbd></button></header>
    {searchOpen && <div className="search-scrim" onClick={() => setSearchOpen(false)}><div className="search-modal" onClick={e => e.stopPropagation()}><div className="search-input"><Search size={17}/><input id="doc-search" autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search Maylang documentation"/><kbd>ESC</kbd></div><div className="search-results">{filteredGroups.flatMap(g => g.items).slice(0, 12).map(([id, label]) => <button key={id} onClick={() => navigate(id)}><FileCode2 size={16}/><span><b>{label}</b><small>{docs[id]?.intro}</small></span><ChevronRight size={15}/></button>)}{!filteredGroups.length && <p>No matching topics found.</p>}</div><div className="search-hint">Search titles and page content</div></div></div>}
    <div className="doc-layout">
      <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}><div className="sidebar-search"><Search size={15}/><input aria-label="Filter navigation" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter topics"/></div><div className="tree">{filteredGroups.map(group => <section className="nav-group" key={group.title}><button className="group-title" onClick={() => setOpenGroups(v => ({ ...v, [group.title]: !v[group.title] }))}>{openGroups[group.title] ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}<span>{group.title}</span><i>{group.items.length}</i></button>{openGroups[group.title] && <div className="nav-items">{group.items.map(([id, label]) => <button className={page === id ? 'selected' : ''} key={id} onClick={() => navigate(id)}>{label}</button>)}</div>}</section>)}</div><div className="sidebar-bottom"><span className="status-dot"/>Maylang self-hosted compiler docs<br/><a href="../../docs/STRICT.md">See compiler syntax notes ↗</a></div></aside>
      <main className="article-wrap"><article className="article"><div className="breadcrumbs"><span>Documentation</span><ChevronRight size={13}/><span>{groups.find(g => g.items.some(([id]) => id === page))?.title ?? 'Reference'}</span><ChevronRight size={13}/><b>{current.title}</b></div><div className="article-header"><p className="kicker">MAYLANG LANGUAGE REFERENCE</p><h1>{current.title}</h1><p className="intro">{current.intro}</p><div className="article-meta"><span><BookOpen size={14}/>Language reference</span><span>Strict compiler · mayc</span></div></div>
        {current.sections.map(([heading, body, code], i) => <section className="article-section" id={`section-${i}`} key={heading}><h2>{heading}</h2>{body && <p>{body}</p>}{code && <Code code={code}/>}</section>)}
        {related.length > 0 && <section className="see-also"><h2>Related topics</h2><div>{related.map(([id, title]) => <button key={id} onClick={() => navigate(id)}><FileCode2 size={15}/>{title}<ChevronRight size={14}/></button>)}</div></section>}
        <div className="page-nav">{previous ? <button onClick={() => navigate(previous[0])}><small>← Previous</small><b>{previous[1]}</b></button> : <span/>}{next && <button className="next-page" onClick={() => navigate(next[0])}><small>Next →</small><b>{next[1]}</b></button>}</div>
        <footer className="article-footer"><span>Maylang Language Reference</span><a href="../../README.md">Edit or report an issue in the repository <ExternalLink size={13}/></a></footer>
      </article><aside className="right-rail"><div className="rail-inner"><h4>ON THIS PAGE</h4>{current.sections.map(([heading], i) => <a key={heading} href={`#section-${i}`}>{heading}</a>)}{related.length > 0 && <><h4 className="related-label">RELATED TOPICS</h4>{related.slice(0, 4).map(([id, title]) => <button key={id} onClick={() => navigate(id)}>{title}</button>)}</>}</div></aside></main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
