'use client';

import { useEffect, useState } from 'react';
import { BarChart3 } from 'lucide-react';
import { DashboardEvalScoresResponse } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { scoreLabelClass, scorePercent } from '../_lib/dashboardHelpers';
import { CardSkeleton } from './CardSkeleton';
import { DashboardError } from './DashboardError';

interface EvalScoresCardProps {
  refreshKey?: number;
}

export function EvalScoresCard({ refreshKey = 0 }: EvalScoresCardProps) {
  const [data, setData] = useState<DashboardEvalScoresResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard/eval-scores');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取评测分数失败');
      }
      const payload = (await res.json()) as DashboardEvalScoresResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取评测分数失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (loading && !data) {
    return <CardSkeleton variant="scores" />;
  }

  if (error && !data) {
    return <DashboardError message={error} onRetry={fetchData} />;
  }

  const scores = data?.latest_eval_scores;
  const items = [
    { label: 'Context Precision', value: scores?.context_precision },
    { label: 'Context Recall', value: scores?.context_recall },
    { label: 'Faithfulness', value: scores?.faithfulness },
    { label: 'Answer Relevancy', value: scores?.answer_relevancy },
  ];

  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
        <BarChart3 className="w-4 h-4" />
        最新 RAGAS 评测分数
      </h2>
      {scores ? (
        <div className="grid grid-cols-2 gap-4">
          {items.map((item) => (
            <div
              key={item.label}
              className="p-4 rounded-lg border border-border bg-muted"
            >
              <div className="text-xs text-muted-foreground mb-1">{item.label}</div>
              <div
                className={`text-xl font-semibold ${scoreLabelClass(
                  item.value ?? null
                )}`}
              >
                {scorePercent(item.value)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-8 text-center text-muted-foreground">暂无数据</div>
      )}
    </div>
  );
}
