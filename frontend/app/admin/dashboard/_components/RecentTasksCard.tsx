'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import { DashboardRecentTasksResponse } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate } from '@/lib/datetime';
import { taskStatusBadgeClass } from '../_lib/dashboardHelpers';
import { CardSkeleton } from './CardSkeleton';
import { DashboardError } from './DashboardError';

interface RecentTasksCardProps {
  refreshKey?: number;
}

export function RecentTasksCard({ refreshKey = 0 }: RecentTasksCardProps) {
  const [data, setData] = useState<DashboardRecentTasksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard/recent-tasks');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取重建任务失败');
      }
      const payload = (await res.json()) as DashboardRecentTasksResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取重建任务失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (loading && !data) {
    return <CardSkeleton variant="tasks" />;
  }

  if (error && !data) {
    return <DashboardError message={error} onRetry={fetchData} />;
  }

  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
        <RefreshCw className="w-4 h-4" />
        最近索引重建任务
      </h2>
      {data && data.recent_tasks.length > 0 ? (
        <ul className="space-y-3">
          {data.recent_tasks.map((task) => (
            <li
              key={task.task_id}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted"
            >
              <div className="min-w-0">
                <div className="text-xs text-muted-foreground truncate">
                  {task.task_id}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {formatIsoDate(task.created_at)}
                </div>
              </div>
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${taskStatusBadgeClass(
                  task.status
                )}`}
              >
                {task.status === 'completed' && (
                  <CheckCircle2 className="w-3 h-3" />
                )}
                {task.status === 'failed' && <XCircle className="w-3 h-3" />}
                {task.status === 'running' && (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                )}
                {task.status}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="p-8 text-center text-muted-foreground">暂无重建任务</div>
      )}
    </div>
  );
}
