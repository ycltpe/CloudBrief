'use client';

import { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { DashboardSystemHealthResponse } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { healthBadgeClass, healthStatusLabel } from '../_lib/dashboardHelpers';
import { CardSkeleton } from './CardSkeleton';
import { DashboardError } from './DashboardError';

interface SystemHealthCardProps {
  refreshKey?: number;
}

export function SystemHealthCard({ refreshKey = 0 }: SystemHealthCardProps) {
  const [data, setData] = useState<DashboardSystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard/system-health');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取系统健康状态失败');
      }
      const payload = (await res.json()) as DashboardSystemHealthResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取系统健康状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (loading && !data) {
    return <CardSkeleton variant="health" />;
  }

  if (error && !data) {
    return <DashboardError message={error} onRetry={fetchData} />;
  }

  const health = data?.system_health;

  if (!health) {
    return (
      <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
        <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
          <Activity className="w-4 h-4" />
          系统健康
        </h2>
        <div className="p-8 text-center text-muted-foreground">暂无数据</div>
      </div>
    );
  }

  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
        <Activity className="w-4 h-4" />
        系统健康
      </h2>
      <div className="space-y-4">
        <div className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted">
          <span className="text-sm text-muted-foreground">整体状态</span>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${healthBadgeClass(
              health.status
            )}`}
          >
            {healthStatusLabel(health.status)}
          </span>
        </div>
        <ul className="space-y-2">
          {health.dependencies.map((dep) => (
            <li
              key={dep.name}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted"
            >
              <div className="min-w-0 mr-3">
                <div className="text-sm text-card-foreground">{dep.name}</div>
                {dep.message && (
                  <div className="text-xs text-rose-600 dark:text-rose-400 truncate">
                    {dep.message}
                  </div>
                )}
                {dep.latency_ms !== undefined && dep.latency_ms !== null && (
                  <div className="text-xs text-muted-foreground">{dep.latency_ms} ms</div>
                )}
              </div>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${healthBadgeClass(
                  dep.status
                )}`}
              >
                {healthStatusLabel(dep.status)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
