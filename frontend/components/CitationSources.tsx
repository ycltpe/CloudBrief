'use client';

import { useState } from 'react';
import { formatIsoDate } from '@/lib/datetime';
import { Citation } from '@/lib/types';

interface CitationSourcesProps {
  citations: Citation[];
}

export default function CitationSources({ citations }: CitationSourcesProps) {
  const [open, setOpen] = useState(false);
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border pt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs font-medium text-primary hover:opacity-80"
        aria-expanded={open}
      >
        <span>{open ? '▼' : '▶'}</span>
        <span>引用来源 ({citations.length})</span>
      </button>
      {open && (
        <ul className="mt-2 space-y-2">
          {citations.map((c, idx) => (
            <li
              key={c.chunk_id || idx}
              className="text-xs text-card-foreground bg-muted rounded p-2"
            >
              <div className="flex items-center gap-2 font-medium text-card-foreground">
                <span className="inline-flex items-center justify-center w-5 h-5 text-xs font-medium text-primary bg-primary/10 rounded">
                  {idx + 1}
                </span>
                <span className="truncate">{c.source_title}</span>
                <span className="shrink-0 text-muted-foreground">· {c.source_type}</span>
              </div>
              <div className="mt-1 text-muted-foreground">
                更新时间：{formatIsoDate(c.updated_at)}
              </div>
              <div className="mt-1 text-muted-foreground line-clamp-3">
                {c.content_summary}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
