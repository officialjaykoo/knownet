"use client";

import { useMemo, useState } from "react";
import { ChevronsDown, ChevronsUp } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type CitationSource = {
  key: string;
  display_title?: string | null;
  definition?: string | null;
  excerpt?: string | null;
  status?: string | null;
  reason?: string | null;
};

type MarkdownViewProps = {
  markdown: string;
  citationSources?: CitationSource[];
  compact?: boolean;
  collapsible?: boolean;
  onOpenPage?: (slug: string) => void;
};

function stripFrontmatter(markdown: string): string {
  if (!markdown.startsWith("---\n")) {
    return markdown;
  }
  const end = markdown.indexOf("\n---\n", 4);
  return end === -1 ? markdown : markdown.slice(end + 5).trimStart();
}

function pageSlug(target: string): string {
  return String(target).trim().toLowerCase().replace(/[^a-z0-9\uac00-\ud7a3_-]+/g, "-").replace(/^-+|-+$/g, "");
}

function domId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]+/g, "-");
}

function prepareMarkdown(markdown: string, citationSources: CitationSource[] = []): string {
  const indexByKey = new Map(citationSources.map((source, index) => [source.key, String(index + 1)]));
  return stripFrontmatter(markdown)
    .split("\n")
    .filter((line) => !/^\s*\[\^[^\]]+\]:/.test(line))
    .map((line) =>
      line
        .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_match, target, label) => {
          const text = label || target;
          return `[${text}](page:${encodeURIComponent(pageSlug(target))})`;
        })
        .replace(/\[\^([^\]]+)\]/g, (_match, key) => {
          const cleanKey = String(key).trim();
          const label = indexByKey.get(cleanKey) || cleanKey;
          return `[${label}](#citation-ref-${domId(cleanKey)})`;
        }),
    )
    .join("\n");
}

function citationPreview(source?: CitationSource): string {
  if (!source) {
    return "Citation source not loaded.";
  }
  return source.excerpt || source.definition || source.reason || source.key;
}

function citationTitle(source?: CitationSource): string {
  return source?.display_title || source?.key || "Citation";
}

function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export function MarkdownView({
  markdown,
  citationSources = [],
  compact = false,
  collapsible = false,
  onOpenPage,
}: MarkdownViewProps) {
  const [expanded, setExpanded] = useState(false);
  const [activeCitationKey, setActiveCitationKey] = useState<string | null>(null);
  const prepared = useMemo(() => prepareMarkdown(markdown, citationSources), [markdown, citationSources]);
  const citationByKey = useMemo(() => new Map(citationSources.map((source) => [source.key, source])), [citationSources]);
  const citationKeyByDomId = useMemo(
    () => new Map(citationSources.map((source) => [`citation-ref-${domId(source.key)}`, source.key])),
    [citationSources],
  );
  const activeCitation = activeCitationKey ? citationByKey.get(activeCitationKey) : undefined;
  const shouldCollapse = collapsible && (prepared.length > 2200 || /\n\|.+\|\n\|[-:|\s]+\|/.test(prepared));

  return (
    <>
      <article className={`${compact ? "markdown compact" : "markdown"} ${shouldCollapse && !expanded ? "is-collapsed" : ""}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              const target = href || "";
              if (target.startsWith("page:")) {
                const slug = decodeURIComponent(target.slice(5));
                return (
                  <button className="page-inline-link" onClick={() => onOpenPage?.(slug)} type="button">
                    {children}
                  </button>
                );
              }
              if (target.startsWith("#citation-ref-")) {
                const citationDomId = target.slice(1);
                const key = citationKeyByDomId.get(citationDomId) || citationDomId.replace(/^citation-ref-/, "");
                const source = citationByKey.get(key);
                return (
                  <sup className="citation-ref">
                    <button
                      aria-label={`Open citation ${citationTitle(source)}`}
                      data-preview={citationPreview(source)}
                      onBlur={() => setActiveCitationKey(null)}
                      onClick={() => document.getElementById(`citation-${domId(key)}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                      onFocus={() => setActiveCitationKey(key)}
                      onMouseEnter={() => setActiveCitationKey(key)}
                      onMouseLeave={() => setActiveCitationKey(null)}
                      title={citationPreview(source)}
                      type="button"
                    >
                      {children}
                    </button>
                  </sup>
                );
              }
              return (
                <a href={target} rel={isExternalHref(target) ? "noreferrer" : undefined} target={isExternalHref(target) ? "_blank" : undefined}>
                  {children}
                </a>
              );
            },
          }}
        >
          {prepared}
        </ReactMarkdown>
      </article>
      {shouldCollapse ? (
        <button className="markdown-toggle" onClick={() => setExpanded((value) => !value)} type="button">
          {expanded ? <ChevronsUp aria-hidden size={16} /> : <ChevronsDown aria-hidden size={16} />}
          {expanded ? "Collapse" : "Expand"}
        </button>
      ) : null}
      {activeCitation ? (
        <aside className="citation-hover-card" role="status">
          <strong>{citationTitle(activeCitation)}</strong>
          {activeCitation.display_title && activeCitation.display_title !== activeCitation.key ? <small>{activeCitation.key}</small> : null}
          <small>{activeCitation.status || "unchecked"}</small>
          <p>{citationPreview(activeCitation)}</p>
          {activeCitation.reason ? <small>{activeCitation.reason}</small> : null}
        </aside>
      ) : null}
      {!compact && citationSources.length ? (
        <section className="citation-references" aria-label="References">
          <p className="eyebrow">References</p>
          {citationSources.map((source, index) => (
            <div className="citation-reference" id={`citation-${domId(source.key)}`} key={source.key}>
              <span>{index + 1}</span>
              <div>
                <strong>{source.display_title || source.key}</strong>
                {source.display_title && source.display_title !== source.key ? <small>{source.key}</small> : null}
                <small>{source.status || "unchecked"}</small>
                <p>{source.excerpt || source.definition || "No source excerpt available."}</p>
                {source.reason ? <small>{source.reason}</small> : null}
              </div>
            </div>
          ))}
        </section>
      ) : null}
    </>
  );
}
