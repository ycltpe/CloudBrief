'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, CheckCircle, Clock, Shield, XCircle } from 'lucide-react';
import { authFetch } from '@/lib/auth';

interface KbInfo {
  kb_id: string;
  name: string;
  description?: string;
}

interface AccessRequest {
  id: number;
  kb_id: string;
  user_id: number;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  updated_at: string;
}

export default function KbAccessPage() {
  const router = useRouter();
  const [accessible, setAccessible] = useState<KbInfo[]>([]);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [allKbs, setAllKbs] = useState<KbInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = document.cookie
      .split('; ')
      .find((row) => row.startsWith('access_token='))
      ?.split('=')[1];
    if (!token) {
      router.push('/admin/login');
      return;
    }
    loadData();
  }, [router]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [accessibleRes, requestsRes] = await Promise.all([
        authFetch('/api/kb-access/accessible'),
        authFetch('/api/kb-access/my-requests'),
      ]);
      if (!accessibleRes.ok || !requestsRes.ok) {
        if (accessibleRes.status === 401 || requestsRes.status === 401) {
          router.push('/admin/login');
          return;
        }
        throw new Error('加载数据失败');
      }
      const accessibleData = await accessibleRes.json();
      const requestsData = await requestsRes.json();
      setAccessible(accessibleData.items || []);
      setRequests(requestsData || []);

      // 同时拉取全部知识库（用于展示可申请项）
      const allRes = await authFetch('/api/admin/kb/tree');
      if (allRes.ok) {
        const tree = await allRes.json();
        const flatten = (nodes: any[]): KbInfo[] =>
          nodes.flatMap((n) => [
            { kb_id: String(n.id), name: n.name, description: n.description },
            ...flatten(n.children || []),
          ]);
        setAllKbs(flatten(tree.directories || []));
      }
    } catch (err: any) {
      setError(err.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const accessibleIds = new Set(accessible.map((k) => k.kb_id));
  const requestKbIds = new Set(requests.map((r) => r.kb_id));
  const availableKbs = allKbs.filter(
    (kb) => !accessibleIds.has(kb.kb_id) && !requestKbIds.has(kb.kb_id)
  );

  const requestAccess = async (kbId: string) => {
    setSubmitting(kbId);
    try {
      const res = await authFetch('/api/kb-access/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kb_id: kbId }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || '申请失败');
      }
      await loadData();
    } catch (err: any) {
      setError(err.message || '申请失败');
    } finally {
      setSubmitting(null);
    }
  };

  const statusBadge = (status: string) => {
    if (status === 'approved')
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200">
          <CheckCircle className="w-3 h-3" />
          已通过
        </span>
      );
    if (status === 'rejected')
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200">
          <XCircle className="w-3 h-3" />
          已拒绝
        </span>
      );
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
        <Clock className="w-3 h-3" />
        待审批
      </span>
    );
  };

  return (
    <div className="min-h-screen p-4 md:p-6 bg-background">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-card-foreground flex items-center gap-2">
          <Shield className="w-5 h-5 text-primary" />
          知识库访问权限
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          申请访问更多业务知识库，或查看已有权限与申请状态
        </p>
      </header>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-md bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : (
        <div className="space-y-6 max-w-3xl">
          {/* 已授权 */}
          <section className="bg-card border border-border rounded-lg p-4">
            <h2 className="text-sm font-medium text-card-foreground mb-3">已授权知识库</h2>
            {accessible.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无可访问知识库</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {accessible.map((kb) => (
                  <div
                    key={kb.kb_id}
                    className="flex items-start gap-3 p-3 rounded-md bg-muted"
                  >
                    <BookOpen className="w-4 h-4 text-primary mt-0.5" />
                    <div>
                      <div className="text-sm font-medium text-card-foreground">{kb.name}</div>
                      {kb.description && (
                        <div className="text-xs text-muted-foreground">{kb.description}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 可申请 */}
          {availableKbs.length > 0 && (
            <section className="bg-card border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium text-card-foreground mb-3">可申请知识库</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {availableKbs.map((kb) => (
                  <div
                    key={kb.kb_id}
                    className="flex items-center justify-between p-3 rounded-md border border-border"
                  >
                    <div className="flex items-start gap-3">
                      <BookOpen className="w-4 h-4 text-muted-foreground mt-0.5" />
                      <div>
                        <div className="text-sm font-medium text-card-foreground">{kb.name}</div>
                        {kb.description && (
                          <div className="text-xs text-muted-foreground">{kb.description}</div>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => requestAccess(kb.kb_id)}
                      disabled={submitting === kb.kb_id}
                      className="px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50 transition-opacity"
                    >
                      {submitting === kb.kb_id ? '申请中…' : '申请'}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 我的申请 */}
          {requests.length > 0 && (
            <section className="bg-card border border-border rounded-lg p-4">
              <h2 className="text-sm font-medium text-card-foreground mb-3">我的申请记录</h2>
              <div className="space-y-2">
                {requests.map((req) => (
                  <div
                    key={req.id}
                    className="flex items-center justify-between p-3 rounded-md bg-muted"
                  >
                    <div>
                      <div className="text-sm font-medium text-card-foreground">
                        {allKbs.find((k) => k.kb_id === req.kb_id)?.name || req.kb_id}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {new Date(req.created_at).toLocaleString()}
                      </div>
                    </div>
                    {statusBadge(req.status)}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
