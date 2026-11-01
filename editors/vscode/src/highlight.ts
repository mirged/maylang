// Highlighting for ```may and ```maylang fences in the Markdown preview.
//
// The preview colours code with highlight.js, which knows no Maylang, rather
// than with TextMate grammars, so this small tokenizer emits highlight.js
// classes that the preview's themes already style. Its word lists come from
// the TextMate grammar, so the preview and the editor agree.
import * as fs from "fs";

export const FENCE_NAMES = ["may", "maylang"];

export interface Vocabulary {
  keywords: Set<string>;
  literals: Set<string>;
  builtins: Set<string>;
  types: Set<string>;
}

interface Grammar {
  repository: Record<string, { patterns: { match?: string }[] }>;
}

/** The words of a `\b(a|b|c)\b` grammar pattern. */
function alternatives(match: string | undefined): string[] {
  const words = match ? /^\\b\(([\w|]+)\)\\b$/.exec(match) : null;
  return words ? words[1].split("|") : [];
}

export function loadVocabulary(grammarPath: string): Vocabulary {
  const grammar = JSON.parse(fs.readFileSync(grammarPath, "utf8")) as Grammar;
  const collect = (key: string): Set<string> =>
    new Set(grammar.repository[key].patterns.flatMap((pattern) => alternatives(pattern.match)));
  return {
    keywords: collect("keywords"),
    literals: collect("constants"),
    builtins: collect("builtins"),
    types: collect("types"),
  };
}

function escape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function span(className: string, text: string): string {
  return `<span class="${className}">${escape(text)}</span>`;
}

const TOKEN =
  /(\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$))|("(?:\\[\s\S]|[^"\\])*"?)|(\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?[\d_]+)?\b)|([A-Za-z_]\w*)/g;

/** Maylang source as HTML with highlight.js token classes. */
export function highlight(code: string, words: Vocabulary): string {
  let out = "";
  let last = 0;
  let previous = "";
  for (const match of code.matchAll(TOKEN)) {
    const index = match.index ?? 0;
    out += escape(code.slice(last, index));
    last = index + match[0].length;
    const [text, comment, string, number, word] = match;
    if (comment) out += span("hljs-comment", text);
    else if (string) out += span("hljs-string", text);
    else if (number) out += span("hljs-number", text);
    else if (word) {
      const call = /^\s*\(/.test(code.slice(last));
      if (words.keywords.has(word)) out += span("hljs-keyword", word);
      else if (words.literals.has(word)) out += span("hljs-literal", word);
      else if (words.types.has(word) || /^[A-Z]/.test(word)) out += span("hljs-type", word);
      else if (previous === "fun") out += span("hljs-title function_", word);
      else if (words.builtins.has(word) && call) out += span("hljs-built_in", word);
      else if (call) out += span("hljs-title function_", word);
      else out += escape(word);
      previous = word;
      continue;
    }
    previous = "";
  }
  return out + escape(code.slice(last));
}

type Highlighter = (code: string, lang: string, attrs: string) => string;

/** The part of markdown-it's instance the preview plugin touches. */
export interface MarkdownIt {
  options: { highlight?: Highlighter | null };
}

/** markdown-it plugin: highlight Maylang fences and defer to the preview for others. */
export function extendMarkdownIt<T extends MarkdownIt>(md: T, words: Vocabulary): T {
  const previous = md.options.highlight;
  md.options.highlight = (code, lang, attrs) => {
    if (FENCE_NAMES.includes((lang || "").trim().toLowerCase())) {
      return `<div>${highlight(code, words)}</div>`;
    }
    return previous ? previous(code, lang, attrs) : "";
  };
  return md;
}
