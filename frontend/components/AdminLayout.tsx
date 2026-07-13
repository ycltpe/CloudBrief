'use client';

import Link from 'next/link';
import { useRouter, usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { LayoutDashboard, Settings, Users, MessageSquare, FolderOpen, BarChart3, LogOut } from 'lucide-react';
import { User, logout, getCurrentUser } from '@/lib/auth';
import ThemeToggle from '@/components/ThemeToggle';

const MENU_ITEMS = [
  { code: 'dashboard', label: 'Dashboard', href: '/admin/dashboard', icon: LayoutDashboard, roles: ['admin', 'qa', 'user'] },
  { code: 'settings', label: '系统设置', href: '/admin/settings', icon: Settings, roles: ['admin'] },
  { code: 'users', label: '用户管理', href: '/admin/users', icon: Users, roles: ['admin'] },
  { code: 'chat', label: '聊天助手', href: '/admin/chat', icon: MessageSquare, roles: ['admin', 'qa', 'user'] },
  { code: 'kb', label: '知识库管理', href: '/admin/kb', icon: FolderOpen, roles: ['admin'] },
  { code: 'eval', label: 'RAGAS 评测审计', href: '/admin/eval', icon: BarChart3, roles: ['admin', 'qa'] },
];

interface AdminLayoutProps {
  children: React.ReactNode;
}

const PUBLIC_ADMIN_PATHS = ['/admin/login', '/admin/register'];

export default function AdminLayout({ children }: AdminLayoutProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 登录/注册页不需要鉴权和后台布局
  const isPublicPath = PUBLIC_ADMIN_PATHS.includes(pathname);

  useEffect(() => {
    if (isPublicPath) {
      setLoading(false);
      return;
    }
    getCurrentUser()
      .then((u) => {
        if (!u) {
          router.push('/admin/login');
          return;
        }
        setUser(u);
      })
      .finally(() => setLoading(false));
  }, [router, pathname, isPublicPath]);

  if (isPublicPath) {
    return <>{children}</>;
  }

  const handleLogout = async () => {
    await logout();
    router.push('/admin/login');
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-muted-foreground text-sm">加载中...</div>
      </div>
    );
  }

  if (!user) return null;

  const visibleMenu = MENU_ITEMS.filter((item) => item.roles.includes(user.role));

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-60 bg-card border-r border-border flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-border font-semibold text-card-foreground">
          ☁️ CloudBrief Admin
        </div>

        <nav className="flex-1 p-3">
          {visibleMenu.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.code}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm mb-1 transition-colors ${
                  active
                    ? 'bg-muted text-primary border-l-2 border-primary -ml-0.5 pl-[13px]'
                    : 'text-muted-foreground hover:bg-muted'
                }`}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-border">
          <div className="flex items-center gap-3 px-3 py-2">
            <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xs font-medium">
              {user.username.slice(0, 1).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-card-foreground truncate">{user.username}</div>
              <div className="text-xs text-muted-foreground capitalize">{user.role}</div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="mt-2 w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-muted rounded-md"
          >
            <LogOut className="w-4 h-4" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-card border-b border-border flex items-center justify-between px-6">
          <div className="text-lg font-semibold text-card-foreground">
            {visibleMenu.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))?.label || 'Admin'}
          </div>
          <ThemeToggle />
        </header>
        <main className="flex-1 p-6 bg-background overflow-auto">{children}</main>
      </div>
    </div>
  );
}
