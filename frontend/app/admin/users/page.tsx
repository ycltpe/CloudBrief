'use client';

import { useEffect, useState } from 'react';
import { Search, Plus, Trash2, X, ChevronLeft, ChevronRight } from 'lucide-react';
import { User } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate } from '@/lib/datetime';

interface UserListResponse {
  total: number;
  items: User[];
}

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  qa: '质检',
  user: '普通用户',
};

const ROLE_BADGE: Record<string, string> = {
  admin: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  qa: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  user: 'bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-400',
};

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const [offset, setOffset] = useState(0);
  const [limit] = useState(10);

  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('user');
  const [creating, setCreating] = useState(false);

  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      if (q) params.set('q', q);
      if (role) params.set('role', role);
      const res = await authFetch(`/api/admin/users?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取用户列表失败');
      }
      const data = (await res.json()) as UserListResponse;
      setUsers(data.items);
      setTotal(data.total);
    } catch (err: any) {
      alert(err.message || '获取用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [offset, q, role]);

  const handleSearch = () => {
    setOffset(0);
    fetchUsers();
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const res = await authFetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '创建用户失败');
      }
      setShowCreate(false);
      setNewUsername('');
      setNewPassword('');
      setNewRole('user');
      setOffset(0);
      fetchUsers();
    } catch (err: any) {
      alert(err.message || '创建用户失败');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (userId: number) => {
    if (!confirm('删除后无法恢复，是否继续？')) return;
    setDeletingId(userId);
    try {
      const res = await authFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '删除用户失败');
      }
      fetchUsers();
    } catch (err: any) {
      alert(err.message || '删除用户失败');
    } finally {
      setDeletingId(null);
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="搜索用户名"
              className="pl-9 pr-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring w-48"
            />
          </div>
          <select
            value={role}
            onChange={(e) => { setRole(e.target.value); setOffset(0); }}
            className="px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部角色</option>
            <option value="admin">admin</option>
            <option value="qa">qa</option>
            <option value="user">user</option>
          </select>
        </div>

        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:opacity-90"
        >
          <Plus className="w-4 h-4" />
          新增用户
        </button>
      </div>

      <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">ID</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">用户名</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">角色</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">创建时间</th>
              <th className="px-4 py-3 text-right font-medium text-muted-foreground">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">加载中...</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">暂无用户</td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.id} className="hover:bg-muted">
                  <td className="px-4 py-3 text-muted-foreground">{user.id}</td>
                  <td className="px-4 py-3 font-medium text-card-foreground">{user.username}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_BADGE[user.role] || 'bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-400'}`}>
                      {ROLE_LABELS[user.role] || user.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{formatIsoDate(user.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(user.id)}
                      disabled={deletingId === user.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 rounded-md disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      {deletingId === user.id ? '删除中...' : '删除'}
                    </button>
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

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg shadow-lg w-full max-w-md p-6 border border-border">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-card-foreground">新增用户</h3>
              <button
                onClick={() => setShowCreate(false)}
                className="text-muted-foreground hover:text-card-foreground"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">用户名</label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="3-32 位字母/数字/下划线"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">初始密码</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="至少 6 位"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">角色</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="user">普通用户</option>
                  <option value="qa">质检</option>
                  <option value="admin">管理员</option>
                </select>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                >
                  {creating ? '创建中...' : '创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
