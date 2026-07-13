'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Database,
  LayoutDashboard,
  MessageSquare,
  Network,
  RefreshCw,
  Users,
  XCircle,
} from 'lucide-react';
import { AdminDashboardResponse, DashboardRecentTask } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate as formatDate } from '@/lib/datetime';

function taskStatusBadgeClass(status: string) {
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

function indexStatusBadgeClass(isReady: boolean) {
  return isReady
    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300';
}

function averageScore(scores: AdminDashboardResponse['latest_eval_scores']) {
  const values = [
    scores.context_precision,
    scores.context_recall,
    scores.faithfulness,
    scores.answer_relevancy,
  ].filter((v): v is number => v !== undefined && v !== null && Number.isFinite(v));
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function scoreLabelClass(score: number | null) {
  if (score === null) return 'text-slate-400';
  if (score >= 0.8) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= 0.6) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

function healthBadgeClass(status: string) {
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

function healthStatusLabel(status: string) {
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

function SystemHealthCard({ health }: { health?: AdminDashboardResponse['system_health'] | null }) {
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

export default function DashboardPage() {
  const [data, setData] = useState<AdminDashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/dashboard');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取仪表盘数据失败');
      }
      const payload = (await res.json()) as AdminDashboardResponse;
      setData(payload);
    } catch (err: any) {
      setError(err.message || '获取仪表盘数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  const avgScore = useMemo(() => {
    if (!data) return null;
    return averageScore(data.latest_eval_scores);
  }, [data]);

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-card-foreground">Dashboard</h1>
        </div>
        <div className="p-8 text-center text-muted-foreground bg-card rounded-lg border border-border shadow-sm">
          加载中...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-card-foreground flex items-center gap-2">
          <LayoutDashboard className="w-5 h-5" />
          Dashboard
        </h1>
        <button
          onClick={fetchDashboard}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-1.5 text-sm text-muted-foreground bg-card border border-border rounded-md hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {error && (
        <div className="p-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md flex items-center gap-2 dark:bg-red-950 dark:text-red-300 dark:border-red-900">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

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
                    data.index_status.is_ready
                  )}`}
                >
                  {data.index_status.is_ready ? '就绪' : '未就绪'}
                </span>
                <span className="text-sm text-muted-foreground truncate">
                  {data.index_status.active_collection || '无活跃索引'}
                </span>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
          <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            最新 RAGAS 评测分数
          </h2>
          {data ? (
            <div className="grid grid-cols-2 gap-4">
              {[
                {
                  label: 'Context Precision',
                  value: data.latest_eval_scores.context_precision,
                },
                {
                  label: 'Context Recall',
                  value: data.latest_eval_scores.context_recall,
                },
                {
                  label: 'Faithfulness',
                  value: data.latest_eval_scores.faithfulness,
                },
                {
                  label: 'Answer Relevancy',
                  value: data.latest_eval_scores.answer_relevancy,
                },
              ].map((item) => (
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
                    {item.value !== undefined && item.value !== null
                      ? `${(item.value * 100).toFixed(0)}%`
                      : '—'}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center text-muted-foreground">暂无数据</div>
          )}
        </div>

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
                      {formatDate(task.created_at)}
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

        <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
          <h2 className="text-base font-semibold text-card-foreground mb-4 flex items-center gap-2">
            <Network className="w-4 h-4" />
            GraphRAG 状态
          </h2>
          {data ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-lg border border-border bg-muted">
                  <div className="text-xs text-muted-foreground mb-1">启用知识库</div>
                  <div className="text-xl font-semibold text-card-foreground">
                    {data.graph_rag_status.enabled_kb_count} / {data.graph_rag_status.total_kb_count}
                  </div>
                </div>
                <div className="p-4 rounded-lg border border-border bg-muted">
                  <div className="text-xs text-muted-foreground mb-1">平均查询耗时</div>
                  <div className="text-xl font-semibold text-card-foreground">
                    {data.graph_rag_status.avg_query_duration_ms !== null &&
                    data.graph_rag_status.avg_query_duration_ms !== undefined
                      ? `${data.graph_rag_status.avg_query_duration_ms.toFixed(0)} ms`
                      : '—'}
                  </div>
                </div>
              </div>
              <div className="p-4 rounded-lg border border-border bg-muted">
                <div className="text-xs text-muted-foreground mb-1">最近一次构建</div>
                {data.graph_rag_status.last_build_at ? (
                  <div className="space-y-1">
                    <div className="text-sm text-card-foreground">
                      {formatDate(data.graph_rag_status.last_build_at)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      实体 {data.graph_rag_status.last_build_entities ?? '—'} · 关系{' '}
                      {data.graph_rag_status.last_build_relations ?? '—'}
                    </div>
                    {data.graph_rag_status.last_build_error && (
                      <div className="text-xs text-red-600 dark:text-red-400 truncate">
                        错误：{data.graph_rag_status.last_build_error}
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

        <SystemHealthCard health={data?.system_health} />
      </div>
    </div>
  );
}
