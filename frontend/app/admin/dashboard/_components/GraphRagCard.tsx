'use client';

import { useEffect, useState } from 'react';
import { Network } from 'lucide-react';
import { DashboardGraphRagResponse } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate } from '@/lib/datetime';
import { CardSkeleton } from './CardSkeleton';
import { DashboardError } from './DashboardError';

interface GraphRagCardProps {
  refreshKey?: number;
}

export function GraphRagCard({ refreshKey = 0 }: GraphRagCardProps) {
  const [data, setData] = useState<DashboardGraphRagResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard/graph-rag');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取 GraphRAG 状态失败');
      }
      const payload = (await res.json()) as DashboardGraphRagResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取 GraphRAG 状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (loading && !data) {
    return <CardSkeleton variant="graph-rag" />;
  }

  if (error && !data) {
    return <DashboardError message={error} onRetry={fetchData} />;
  }

  const status = data?.graph_rag_status;

  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
        <Network className="w-4 h-4" />
        GraphRAG 状态
      </h2>
      {status ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 rounded-lg border border-border bg-muted">
              <div className="text-xs text-muted-foreground mb-1">启用知识库</div>
              <div className="text-xl font-semibold text-card-foreground">
                {status.enabled_kb_count} / {status.total_kb_count}
              </div>
            </div>
            <div className="p-4 rounded-lg border border-border bg-muted">
              <div className="text-xs text-muted-foreground mb-1">平均查询耗时</div>
              <div className="text-xl font-semibold text-card-foreground">
                {status.avg_query_duration_ms !== null &&
                status.avg_query_duration_ms !== undefined
                  ? `${status.avg_query_duration_ms.toFixed(0)} ms`
                  : '—'}
              </div>
            </div>
          </div>
          <div className="p-4 rounded-lg border border-border bg-muted">
            <div className="text-xs text-muted-foreground mb-1">最近一次构建</div>
            {status.last_build_at ? (
              <div className="space-y-1">
                <div className="text-sm text-card-foreground">
                  {formatIsoDate(status.last_build_at)}
                </div>
                <div className="text-xs text-muted-foreground">
                  实体 {status.last_build_entities ?? '—'} · 关系{' '}
                  {status.last_build_relations ?? '—'}
                </div>
                {status.last_build_error && (
                  <div className="text-xs text-red-600 dark:text-red-400 truncate">
                    错误：{status.last_build_error}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">尚未构建</div>
            )}
          </div>
        </div>
      ) : (
        <div className="p-8 text-center text-muted-foreground">暂无数据</div>
      )}
    </div>
  );
}
