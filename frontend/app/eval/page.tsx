'use client';

import { useEffect, useState } from 'react';
import { EvalResultOut } from '@/lib/types';
import ThemeToggle from '@/components/ThemeToggle';

export default function EvalPage() {
  const [results, setResults] = useState<EvalResultOut[]>([]);
  const [selected, setSelected] = useState<EvalResultOut | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/eval/results')
      .then((r) => r.json())
      .then(setResults)
      .catch(console.error);
  }, []);

  const submitFeedback = async () => {
    if (!selected) return;
    setLoading(true);
    const feedback = {
      human_score: parseInt((document.getElementById('human_score') as HTMLSelectElement)?.value || '0', 10) || null,
      human_note: (document.getElementById('human_note') as HTMLTextAreaElement)?.value || null,
      is_adopted: (document.getElementById('is_adopted') as HTMLInputElement)?.checked || false,
      is_modified: (document.getElementById('is_modified') as HTMLInputElement)?.checked || false,
    };
    try {
      const res = await fetch(`/api/eval/results/${selected.id}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feedback),
      });
      const updated = await res.json();
      setSelected(updated);
      setResults((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen p-6 bg-background">
      <header className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-card-foreground">RAGAS 评测审计</h1>
        <ThemeToggle />
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-card border border-border rounded shadow-sm">
          <div className="p-3 border-b border-border font-medium text-card-foreground">评测记录</div>
          <ul className="divide-y divide-border max-h-[80vh] overflow-auto">
            {results.map((r) => {
              const scores = JSON.parse(r.ragas_scores_json || '{}');
              return (
                <li
                  key={r.id}
                  onClick={() => setSelected(r)}
                  className={`p-3 cursor-pointer hover:bg-muted ${selected?.id === r.id ? 'bg-blue-50 dark:bg-blue-950' : ''}`}
                >
                  <p className="text-sm font-medium text-card-foreground truncate">{r.question}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    命中 {scores.hit_rate ?? '-'} / 引用 {scores.citation_accuracy ?? '-'} / 忠实 {scores.faithfulness ?? '-'}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="lg:col-span-2 bg-card border border-border rounded shadow-sm p-4">
          {selected ? (
            <div className="space-y-4">
              <div>
                <h2 className="font-semibold text-card-foreground">问题</h2>
                <p className="text-sm text-card-foreground">{selected.question}</p>
              </div>
              <div>
                <h2 className="font-semibold text-card-foreground">生成答案</h2>
                <p className="text-sm whitespace-pre-wrap bg-muted p-2 rounded text-card-foreground">{selected.answer || '（拒答）'}</p>
              </div>
              <div>
                <h2 className="font-semibold text-card-foreground">期望答案要点</h2>
                <p className="text-sm whitespace-pre-wrap bg-muted p-2 rounded text-card-foreground">{selected.ground_truth || '-'}</p>
              </div>
              <div>
                <h2 className="font-semibold text-card-foreground">检索片段</h2>
                <ul className="text-sm space-y-1">
                  {JSON.parse(selected.contexts_json || '[]').map((ctx: any, idx: number) => (
                    <li key={idx} className="p-2 bg-muted rounded">
                      <span className="font-medium text-card-foreground">[{ctx.chunk_id}] {ctx.title}</span>
                      <p className="text-muted-foreground mt-1">{ctx.content}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h2 className="font-semibold text-card-foreground">RAGAS 指标</h2>
                <pre className="text-xs bg-muted p-2 rounded overflow-auto text-card-foreground">
                  {JSON.stringify(JSON.parse(selected.ragas_scores_json || '{}'), null, 2)}
                </pre>
              </div>
              <div className="border-t border-border pt-4">
                <h2 className="font-semibold text-card-foreground">人工反馈</h2>
                <div className="grid grid-cols-2 gap-4 mt-2">
                  <div>
                    <label className="text-sm text-card-foreground">评分（1-5）</label>
                    <select id="human_score" defaultValue={selected.human_score || ''} className="w-full border border-border rounded p-1 text-sm bg-card text-card-foreground">
                      <option value="">-</option>
                      {[1,2,3,4,5].map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-1 text-sm text-card-foreground">
                      <input id="is_adopted" type="checkbox" defaultChecked={selected.is_adopted} /> 采用
                    </label>
                    <label className="flex items-center gap-1 text-sm text-card-foreground">
                      <input id="is_modified" type="checkbox" defaultChecked={selected.is_modified} /> 需修改
                    </label>
                  </div>
                </div>
                <div className="mt-2">
                  <label className="text-sm text-card-foreground">备注</label>
                  <textarea id="human_note" defaultValue={selected.human_note || ''} className="w-full border border-border rounded p-2 text-sm bg-card text-card-foreground" rows={3} />
                </div>
                <button
                  onClick={submitFeedback}
                  disabled={loading}
                  className="mt-2 px-4 py-2 text-sm text-primary-foreground bg-primary rounded hover:opacity-90 disabled:opacity-50"
                >
                  保存反馈
                </button>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground">选择左侧记录查看详情</p>
          )}
        </div>
      </div>
    </main>
  );
}
