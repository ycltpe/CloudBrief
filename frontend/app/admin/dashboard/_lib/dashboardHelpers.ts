import {
  DashboardEvalScores,
  DashboardIndexStatus,
  DashboardStatsResponse,
} from '@/lib/types';

export function taskStatusBadgeClass(status: string) {
  switch (status) {
    case 'completed':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300';
    case 'running':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300';
    case 'failed':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300';
    default:
      return 'bg-slate-100 text-slate-500 dark:bg-slate-900 dark:text-slate-400';
  }
}

export function indexStatusBadgeClass(isReady: boolean) {
  return isReady
    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300';
}

export function averageScore(scores: DashboardEvalScores) {
  const values = [
    scores.context_precision,
    scores.context_recall,
    scores.faithfulness,
    scores.answer_relevancy,
  ].filter((v): v is number => v !== undefined && v !== null && Number.isFinite(v));
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

export function scoreLabelClass(score: number | null) {
  if (score === null) return 'text-slate-400';
  if (score >= 0.8) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= 0.6) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

export function scorePercent(score: number | null | undefined) {
  if (score === undefined || score === null || !Number.isFinite(score)) return null;
  return `${(score * 100).toFixed(0)}%`;
}

export function healthBadgeClass(status: string) {
  switch (status) {
    case 'healthy':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300';
    case 'degraded':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300';
    case 'unhealthy':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300';
    default:
      return 'bg-slate-100 text-slate-500 dark:bg-slate-900 dark:text-slate-400';
  }
}

export function healthStatusLabel(status: string) {
  switch (status) {
    case 'healthy':
      return '健康';
    case 'degraded':
      return '降级';
    case 'unhealthy':
      return '异常';
    default:
      return '未知';
  }
}

export function formatIndexStatus(data: DashboardStatsResponse | null) {
  if (!data) return { isReady: false, activeCollection: null };
  return {
    isReady: data.index_status.is_ready,
    activeCollection: data.index_status.active_collection || '无活跃索引',
  };
}
