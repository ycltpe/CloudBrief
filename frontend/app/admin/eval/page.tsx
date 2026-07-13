'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  MessageSquare,
  Search,
  Star,
  X,
} from 'lucide-react';
import { AdminEvalResult } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate as formatDate } from '@/lib/datetime';

interface AdminEvalListResponse {
  total: number;
  items: AdminEvalResult[];
}

const HAS_FEEDBACK_OPTIONS = [
  { value: '', label: '全部反馈状态' },
  { value: 'true', label: '已反馈' },
  { value: 'false', label: '未反馈' },
];

function getFaithfulness(scores: Record<string, number | string | null>) {
  const v = scores.faithfulness;
  if (v === undefined || v === null) return null;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return Number.isFinite(n) ? n : null;
}

function scoreBadgeClass(score: number | null) {
  if (score === null) return 'bg-muted text-muted-foreground';
  if (score >= 0.8) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300';
  if (score >= 0.6) return 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300';
  return 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300';
}

export default function EvalAuditPage() {
  const [items, setItems] = useState<AdminEvalResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<AdminEvalResult | null>(null);

  const [q, setQ] = useState('');
  const [minScore, setMinScore] = useState('');
  const [hasFeedback, setHasFeedback] = useState('');
  const [limit] = useState(10);
  const [offset, setOffset] = useState(0);

  const [feedbackScore, setFeedbackScore] = useState<string>('');
  const [feedbackNote, setFeedbackNote] = useState('');
  const [feedbackAdopted, setFeedbackAdopted] = useState(false);
  const [feedbackModified, setFeedbackModified] = useState(false);
  const [savingFeedback, setSavingFeedback] = useState(false);

  const fetchResults = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      if (minScore) params.set('min_score', minScore);
      if (hasFeedback) params.set('has_feedback', hasFeedback);
      const res = await authFetch(`/api/admin/eval/results?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取评测记录失败');
      }
      const data = (await res.json()) as AdminEvalListResponse;
      setItems(data.items);
      setTotal(data.total);
      if (selected) {
        const stillSelected = data.items.find((r) => r.id === selected.id);
        if (stillSelected) setSelected(stillSelected);
      }
    } catch (err: any) {
      alert(err.message || '获取评测记录失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, minScore, hasFeedback]);

  useEffect(() => {
    if (selected) {
      setFeedbackScore(selected.human_score ? String(selected.human_score) : '');
      setFeedbackNote(selected.human_note || '');
      setFeedbackAdopted(selected.is_adopted);
      setFeedbackModified(selected.is_modified);
    }
  }, [selected]);

  const filteredItems = useMemo(() => {
    if (!q.trim()) return items;
    const query = q.toLowerCase();
    return items.filter(
      (r) =>
        r.question.toLowerCase().includes(query) ||
        (r.answer || '').toLowerCase().includes(query) ||
        (r.ground_truth || '').toLowerCase().includes(query)
    );
  }, [items, q]);

  const handleSearch = () => {
    setOffset(0);
    fetchResults();
  };

  const handleExport = async (format: 'csv' | 'json') => {
    try {
      const params = new URLSearchParams();
      params.set('format', format);
      if (minScore) params.set('min_score', minScore);
      if (hasFeedback) params.set('has_feedback', hasFeedback);
      const res = await authFetch(`/api/admin/eval/export?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '导出失败');
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eval_results.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err.message || '导出失败');
    }
  };

  const handleSaveFeedback = async () => {
    if (!selected) return;
    setSavingFeedback(true);
    try {
      const body = {
        human_score: feedbackScore ? parseInt(feedbackScore, 10) : null,
        human_note: feedbackNote.trim() || null,
        is_adopted: feedbackAdopted,
        is_modified: feedbackModified,
      };
      const res = await authFetch(`/api/admin/eval/results/${selected.id}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '保存反馈失败');
      }
      const updated = (await res.json()) as AdminEvalResult;
      setSelected(updated);
      setItems((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err: any) {
      alert(err.message || '保存反馈失败');
    } finally {
      setSavingFeedback(false);
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  const avgScore = useMemo(() => {
    const scores = items.map((r) => getFaithfulness(r.ragas_scores)).filter((s): s is number => s !== null);
    if (!scores.length) return null;
    return scores.reduce((a, b) => a + b, 0) / scores.length;
  }, [items]);

  const feedbackCount = useMemo(
    () => items.filter((r) => r.human_score !== null || r.is_adopted || r.is_modified).length,
    [items]
  );

  return (
    <div className="space-y-4">
      {/* Header / filters */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="搜索问题、答案、期望要点"
              className="pl-9 pr-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring w-64"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-muted-foreground" />
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={minScore}
              onChange={(e) => { setMinScore(e.target.value); setOffset(0); }}
              placeholder="最低 faithfulness"
              className="px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring w-40"
            />
            <select
              value={hasFeedback}
              onChange={(e) => { setHasFeedback(e.target.value); setOffset(0); }}
              className="px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {HAS_FEEDBACK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handleExport('csv')}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
          >
            <Download className="w-4 h-4" />
            导出 CSV
          </button>
          <button
            onClick={() => handleExport('json')}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
          >
            <Download className="w-4 h-4" />
            导出 JSON
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">总记录数</div>
          <div className="text-2xl font-semibold text-card-foreground">{total}</div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">平均 Faithfulness</div>
          <div className={`text-2xl font-semibold ${avgScore !== null ? (avgScore >= 0.7 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400') : 'text-muted-foreground'}`}>
            {avgScore !== null ? avgScore.toFixed(2) : '-'}
          </div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
          <div className="text-xs text-muted-foreground mb-1">已人工反馈</div>
          <div className="text-2xl font-semibold text-blue-600 dark:text-blue-400">{feedbackCount}</div>
        </div>
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* List */}
        <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border font-medium text-card-foreground flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            评测记录
          </div>
          <div className="max-h-[60vh] overflow-auto">
            {loading ? (
              <div className="p-8 text-center text-muted-foreground">加载中...</div>
            ) : filteredItems.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">暂无记录</div>
            ) : (
              <ul className="divide-y divide-border">
                {filteredItems.map((r) => {
                  const faithfulness = getFaithfulness(r.ragas_scores);
                  const hasFeedbackLocal = r.human_score !== null || r.is_adopted || r.is_modified;
                  return (
                    <li
                      key={r.id}
                      onClick={() => setSelected(r)}
                      className={`p-4 cursor-pointer hover:bg-muted transition-colors ${
                        selected?.id === r.id ? 'bg-blue-50 dark:bg-blue-950 border-l-4 border-blue-600' : ''
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium text-card-foreground line-clamp-2 flex-1">{r.question}</p>
                        {hasFeedbackLocal && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                            <Star className="w-3 h-3 mr-0.5" />
                            {r.human_score ?? '·'}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-2 text-xs">
                        <span className={`px-2 py-0.5 rounded-full font-medium ${scoreBadgeClass(faithfulness)}`}>
                          F {faithfulness !== null ? faithfulness.toFixed(2) : '-'}
                        </span>
                        <span className="text-muted-foreground">{formatDate(r.created_at)}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {total > 0 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-border">
              <div className="text-xs text-muted-foreground">
                共 {total} 条 · 第 {currentPage}/{totalPages} 页
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setOffset((p) => Math.max(0, p - limit))}
                  disabled={offset === 0}
                  className="p-1.5 border border-border rounded-md hover:bg-muted disabled:opacity-50"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setOffset((p) => p + limit)}
                  disabled={offset + limit >= total}
                  className="p-1.5 border border-border rounded-md hover:bg-muted disabled:opacity-50"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Detail */}
        <div className="lg:col-span-2 bg-card border border-border rounded-lg shadow-sm">
          {selected ? (
            <div className="p-5 space-y-5 max-h-[80vh] overflow-auto">
              <div className="flex items-start justify-between gap-4">
                <h2 className="text-lg font-semibold text-card-foreground">评测详情</h2>
                <button
                  onClick={() => setSelected(null)}
                  className="text-muted-foreground hover:text-muted-foreground"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div>
                <h3 className="text-sm font-medium text-card-foreground mb-1">问题</h3>
                <p className="text-sm text-card-foreground bg-muted p-3 rounded-md">{selected.question}</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <h3 className="text-sm font-medium text-card-foreground mb-1">生成答案</h3>
                  <div className="text-sm text-card-foreground bg-muted p-3 rounded-md whitespace-pre-wrap min-h-[80px]">
                    {selected.answer || '（拒答）'}
                  </div>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-card-foreground mb-1">期望答案要点</h3>
                  <div className="text-sm text-card-foreground bg-muted p-3 rounded-md whitespace-pre-wrap min-h-[80px]">
                    {selected.ground_truth || '-'}
                  </div>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-card-foreground mb-2">RAGAS 指标</h3>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(selected.ragas_scores).map(([k, v]) => (
                    <span
                      key={k}
                      className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-muted text-card-foreground"
                    >
                      {k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}
                    </span>
                  ))}
                </div>
              </div>

              {selected.reasoning && Object.keys(selected.reasoning).length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-card-foreground mb-2">评测 reasoning</h3>
                  <pre className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-40">
                    {JSON.stringify(selected.reasoning, null, 2)}
                  </pre>
                </div>
              )}

              <div>
                <h3 className="text-sm font-medium text-card-foreground mb-2 flex items-center gap-1">
                  <MessageSquare className="w-4 h-4" />
                  检索片段
                </h3>
                <ul className="space-y-2">
                  {selected.contexts.length === 0 && (
                    <li className="text-sm text-muted-foreground">无检索片段</li>
                  )}
                  {selected.contexts.map((ctx, idx) => (
                    <li key={idx} className="text-sm bg-muted p-3 rounded-md">
                      <div className="font-medium text-card-foreground">
                        [{ctx.chunk_id}] {ctx.source_title}
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">{ctx.source_type}</div>
                      <p className="text-card-foreground mt-1">{ctx.content}</p>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="border-t border-border pt-5">
                <h3 className="text-sm font-medium text-card-foreground mb-3">人工反馈</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-muted-foreground mb-1">人工评分（1-5）</label>
                    <select
                      value={feedbackScore}
                      onChange={(e) => setFeedbackScore(e.target.value)}
                      className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    >
                      <option value="">-</option>
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-6">
                    <label className="flex items-center gap-2 text-sm text-card-foreground">
                      <input
                        type="checkbox"
                        checked={feedbackAdopted}
                        onChange={(e) => setFeedbackAdopted(e.target.checked)}
                        className="w-4 h-4 text-primary rounded border-border"
                      />
                      采用
                    </label>
                    <label className="flex items-center gap-2 text-sm text-card-foreground">
                      <input
                        type="checkbox"
                        checked={feedbackModified}
                        onChange={(e) => setFeedbackModified(e.target.checked)}
                        className="w-4 h-4 text-primary rounded border-border"
                      />
                      需修改
                    </label>
                  </div>
                </div>
                <div className="mt-3">
                  <label className="block text-xs font-medium text-muted-foreground mb-1">备注</label>
                  <textarea
                    value={feedbackNote}
                    onChange={(e) => setFeedbackNote(e.target.value)}
                    rows={3}
                    className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div className="mt-3 flex justify-end">
                  <button
                    onClick={handleSaveFeedback}
                    disabled={savingFeedback}
                    className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                  >
                    {savingFeedback ? '保存中...' : '保存反馈'}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-64 text-muted-foreground">
              选择左侧记录查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
