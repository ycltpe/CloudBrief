'use client';

import { useState } from 'react';
import InlineMarkdown from './InlineMarkdown';
import { formatIsoDate } from '@/lib/datetime';
import { Citation } from '@/lib/types';

interface AnswerWithCitationsProps {
  answer: string;
  citations: Citation[];
}

export default function AnswerWithCitations({ answer, citations }: AnswerWithCitationsProps) {
  const [selected, setSelected] = useState<Citation | null>(null);

  // 支持 [^1] 也支持 [^help_doc:help_docs/export-guide.md:0]
  const parts = answer.split(/(\[\^[^\]]+\])/g);

  // 按答案里首次出现的顺序给每个 chunk_id 编号
  const seenOrder = new Map<string, number>();
  const getOrder = (key: string) => {
    if (!seenOrder.has(key)) {
      seenOrder.set(key, seenOrder.size + 1);
    }
    return seenOrder.get(key)!;
  };

  const resolveCitation = (raw: string): Citation | undefined => {
    // raw 形如 "help_doc:help_docs/export-guide.md:0" 或 "1"
    const byId = citations.find((c) => c.chunk_id === raw);
    if (byId) return byId;
    // 兼容后端已重写为 [^1] 的场景
    if (/^\d+$/.test(raw)) {
      return citations[parseInt(raw, 10) - 1];
    }
    return undefined;
  };

  return (
    <div className="relative">
      <div className="prose prose-sm max-w-none dark:prose-invert">
        {parts.map((part, idx) => {
          const match = part.match(/^\[\^([^\]]+)\]$/);
          if (!match) {
            return (
              <InlineMarkdown key={idx} text={part} />
            );
          }

          const raw = match[1];
          const citation = resolveCitation(raw);
          if (!citation) {
            return <span key={idx}>{part}</span>;
          }

          const order = getOrder(citation.chunk_id);
          return (
            <button
              key={idx}
              onClick={() => setSelected(citation)}
              className="inline-flex items-center justify-center w-5 h-5 ml-0.5 text-xs font-medium text-primary bg-primary/10 rounded hover:bg-primary/20"
              title={citation.source_title}
            >
              {order}
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setSelected(null)}>
          <div
            className="w-full max-w-md p-4 mx-4 bg-card rounded-lg shadow-lg border border-border"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <h3 className="text-sm font-semibold text-card-foreground">引用来源</h3>
              <button
                onClick={() => setSelected(null)}
                className="text-muted-foreground hover:text-card-foreground"
              >
                ✕
              </button>
            </div>
            <div className="mt-3 space-y-2 text-sm">
              <p>
                <span className="font-medium text-card-foreground">标题：</span>
                {selected.source_title}
              </p>
              <p>
                <span className="font-medium text-card-foreground">类型：</span>
                {selected.source_type}
              </p>
              <p>
                <span className="font-medium text-card-foreground">更新时间：</span>
                {formatIsoDate(selected.updated_at)}
              </p>
              <div className="p-2 mt-2 text-card-foreground bg-muted rounded max-h-48 overflow-auto">
                {selected.content_summary}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
