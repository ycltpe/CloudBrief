'use client';

import CodeBlock from './CodeBlock';

interface InlineMarkdownProps {
  text: string;
}

/**
 * 轻量级 Markdown 渲染。
 * 支持：
 * - **粗体**
 * - *斜体* 或 _斜体_
 * - `行内代码`
 * - ``` 围栏代码块（含语法高亮）
 */
export default function InlineMarkdown({ text }: InlineMarkdownProps) {
  // 先按围栏代码块拆分
  const parts = text.split(/(```[\s\S]*?```)/g);

  return (
    <span className="whitespace-pre-wrap">
      {parts.map((part, idx) => {
        const codeMatch = part.match(/^```(\w*)\n?([\s\S]*?)```$/);
        if (codeMatch) {
          const lang = codeMatch[1] || 'text';
          const code = codeMatch[2].trim();
          return <CodeBlock key={idx} code={code} language={lang} />;
        }

        return <InlineText key={idx} text={part} />;
      })}
    </span>
  );
}

function InlineText({ text }: { text: string }) {
  // 按粗体、斜体、行内代码拆分，同时保留普通文本
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|`[^`]+`)/g);

  return (
    <span className="whitespace-pre-wrap">
      {parts.map((part, idx) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={idx} className="font-semibold">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if ((part.startsWith('*') && part.endsWith('*')) ||
            (part.startsWith('_') && part.endsWith('_'))) {
          return (
            <em key={idx} className="italic">
              {part.slice(1, -1)}
            </em>
          );
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code
              key={idx}
              className="px-1 py-0.5 text-xs font-mono bg-muted text-card-foreground rounded"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={idx}>{part}</span>;
      })}
    </span>
  );
}
