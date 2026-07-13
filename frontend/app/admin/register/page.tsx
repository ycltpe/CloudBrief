'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { register } from '@/lib/auth';
import ThemeToggle from '@/components/ThemeToggle';

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    if (password.length < 6) {
      setError('密码至少需要 6 位');
      return;
    }

    setLoading(true);
    try {
      await register(username, password);
      router.push('/admin/login');
    } catch (err: any) {
      setError(err.message || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md bg-card rounded-lg border border-border shadow-sm p-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold text-card-foreground">注册账号</h1>
          <p className="mt-2 text-sm text-muted-foreground">注册后默认角色为 user</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-card-foreground mb-1">
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="3-32 位字母/数字/下划线"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-card-foreground mb-1">
              密码
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="至少 6 位"
            />
          </div>

          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-card-foreground mb-1">
              确认密码
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="再次输入密码"
            />
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 rounded-md px-3 py-2 dark:bg-red-950 dark:text-red-300">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password || !confirmPassword}
            className="w-full py-2 px-4 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? '注册中...' : '注册'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-muted-foreground">
          已有账号？
          <Link href="/admin/login" className="text-primary hover:underline">
            立即登录
          </Link>
        </div>
      </div>
    </div>
  );
}
