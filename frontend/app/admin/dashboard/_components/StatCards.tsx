'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Database, MessageSquare, Users } from 'lucide-react';
import { DashboardStatsResponse } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import {
  averageScore,
  formatIndexStatus,
  indexStatusBadgeClass,
  scoreLabelClass,
} from '../_lib/dashboardHelpers';
import { CardSkeleton } from './CardSkeleton';
import { DashboardError } from './DashboardError';

interface StatCardsProps {
  refreshKey?: number;
}

export function StatCards({ refreshKey = 0 }: StatCardsProps) {
  const [data, setData] = useState<DashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard/stats');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取统计数据失败');
      }
      const payload = (await res.json()) as DashboardStatsResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取统计数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const avgScore = useMemo(() => {
    if (!data) return null;
    return averageScore(data.latest_eval_scores);
  }, [data]);

  const { isReady, activeCollection } = formatIndexStatus(data);

  if (loading && !data) {
    return <CardSkeleton variant="stats" />;
  }

  if (error && !data) {
    return <DashboardError message={error} onRetry={fetchData} />;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <div className="bg-card p-5 rounded-lg border border-border shadow-sm">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
          <Users className="w-4 h-4" />
          用户总数
        </div>
        <div className="text-2xl font-semibold text-card-foreground">
          {data?.user_count ?? '—'}
        </div>
      </div>

      <div className="bg-card p-5 rounded-lg border border-border shadow-sm">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
          <MessageSquare className="w-4 h-4" />
          今日会话
        </div>
        <div className="text-2xl font-semibold text-card-foreground">
          {data?.conversation_count_today ?? '—'}
        </div>
      </div>

      <div className="bg-card p-5 rounded-lg border border-border shadow-sm">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
          <Database className="w-4 h-4" />
          索引状态
        </div>
        <div className="flex items-center gap-2">
          {data ? (
            <>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${indexStatusBadgeClass(
                  isReady
                )}`}
              >
                {isReady ? '就绪' : '未就绪'}
              </span>
              <span className="text-sm text-muted-foreground truncate">{activeCollection}</span>
            </>
          ) : (
            <span className="text-2xl font-semibold text-card-foreground">—</span>
          )}
        </div>
      </div>

      <div className="bg-card p-5 rounded-lg border border-border shadow-sm">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
          <BarChart3 className="w-4 h-4" />
          评测平均分
        </div>
        <div className="flex items-baseline gap-2">
          <div className={`text-2xl font-semibold ${scoreLabelClass(avgScore)}`}>
            {avgScore !== null ? `${(avgScore * 100).toFixed(0)}%` : '—'}
          </div>
          {avgScore !== null && (
            <span className="text-xs text-muted-foreground">最新一次</span>
          )}
        </div>
      </div>
    </div>
  );
}
