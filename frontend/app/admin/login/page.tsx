'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { login } from '@/lib/auth';
import ThemeToggle from '@/components/ThemeToggle';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      router.push('/admin/dashboard');
    } catch (err: any) {
      setError(err.message || '登录失败，请检查用户名和密码');
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
          <h1 className="text-2xl font-semibold text-card-foreground">CloudBrief Admin</h1>
          <p className="mt-2 text-sm text-muted-foreground">登录管理后台</p>
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
              placeholder="请输入用户名"
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
              placeholder="请输入密码"
            />
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 rounded-md px-3 py-2 dark:bg-red-950 dark:text-red-300">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full py-2 px-4 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-muted-foreground">
          还没有账号？
          <Link href="/admin/register" className="text-primary hover:underline">
            立即注册
          </Link>
        </div>
      </div>
    </div>
  );
}
