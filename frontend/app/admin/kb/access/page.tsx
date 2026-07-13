'use client';

import { useEffect, useState } from 'react';
import { Search, CheckCircle, XCircle, ChevronLeft, ChevronRight, AlertCircle, Shield } from 'lucide-react';
import { KbAccessRequest, KbAccessListResponse, KbAccessStatus } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate } from '@/lib/datetime';

const STATUS_LABELS: Record<KbAccessStatus, string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已拒绝',
};

const STATUS_BADGE: Record<KbAccessStatus, string> = {
  pending: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  approved: 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300',
};

export default function KbAccessApprovalPage() {
  const [items, setItems] = useState<KbAccessRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<KbAccessStatus | ''>('pending');
  const [kbId, setKbId] = useState('');
  const [offset, setOffset] = useState(0);
  const [limit] = useState(10);

  const [reviewingId, setReviewingId] = useState<number | null>(null);

  const fetchRequests = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      if (status) params.set('status', status);
      if (kbId.trim()) params.set('kb_id', kbId.trim());
      const res = await authFetch(`/api/admin/kb/access-requests?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取申请列表失败');
      }
      const data = (await res.json()) as KbAccessListResponse;
      setItems(data.items);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || '获取申请列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRequests();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, status]);

  const handleSearch = () => {
    setOffset(0);
    fetchRequests();
  };

  const handleReview = async (id: number, decision: 'approved' | 'rejected') => {
    if (!confirm(`确定要${decision === 'approved' ? '通过' : '拒绝'}该权限申请吗？`)) return;
    setReviewingId(id);
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/access-requests/${id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: decision }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '审批失败');
      }
      await fetchRequests();
    } catch (err: any) {
      setError(err.message || '审批失败');
    } finally {
      setReviewingId(null);
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold text-card-foreground">知识库权限审批</h1>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={kbId}
              onChange={(e) => setKbId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="搜索知识库 ID"
              className="pl-9 pr-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring w-48"
            />
          </div>
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value as KbAccessStatus | ''); setOffset(0); }}
            className="px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="pending">待审批</option>
            <option value="approved">已通过</option>
            <option value="rejected">已拒绝</option>
            <option value="">全部状态</option>
          </select>
          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:opacity-90"
          >
            查询
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-900 rounded-md flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">ID</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">知识库 ID</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">申请人</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">状态</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">申请时间</th>
              <th className="px-4 py-3 text-right font-medium text-muted-foreground">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">加载中...</td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">暂无权限申请</td>
              </tr>
            ) : (
              items.map((req) => (
                <tr key={req.id} className="hover:bg-muted">
                  <td className="px-4 py-3 text-muted-foreground">{req.id}</td>
                  <td className="px-4 py-3 font-medium text-card-foreground">{req.kb_id}</td>
                  <td className="px-4 py-3 text-card-foreground">{req.username || `用户 #${req.user_id}`}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[req.status]}`}>
                      {STATUS_LABELS[req.status]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{formatIsoDate(req.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    {req.status === 'pending' && (
                      <div className="inline-flex items-center gap-2">
                        <button
                          onClick={() => handleReview(req.id, 'approved')}
                          disabled={reviewingId === req.id}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-green-600 hover:bg-green-50 rounded-md disabled:opacity-50 dark:text-green-400 dark:hover:bg-green-950"
                        >
                          <CheckCircle className="w-3.5 h-3.5" />
                          通过
                        </button>
                        <button
                          onClick={() => handleReview(req.id, 'rejected')}
                          disabled={reviewingId === req.id}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 rounded-md disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950"
                        >
                          <XCircle className="w-3.5 h-3.5" />
                          拒绝
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

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
    </div>
  );
}
