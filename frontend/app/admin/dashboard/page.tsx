'use client';

import { useState } from 'react';
import { LayoutDashboard, RefreshCw } from 'lucide-react';
import { StatCards } from './_components/StatCards';
import { EvalScoresCard } from './_components/EvalScoresCard';
import { RecentTasksCard } from './_components/RecentTasksCard';
import { GraphRagCard } from './_components/GraphRagCard';
import { SystemHealthCard } from './_components/SystemHealthCard';

export default function DashboardPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setRefreshKey((k) => k + 1);
    // 模块各自重新加载，按钮旋转 600ms 作为视觉反馈
    setTimeout(() => setIsRefreshing(false), 600);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-card-foreground flex items-center gap-2">
          <LayoutDashboard className="w-5 h-5" />
          Dashboard
        </h1>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-1 px-3 py-1.5 text-sm text-muted-foreground bg-card border border-border rounded-md hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <StatCards refreshKey={refreshKey} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EvalScoresCard refreshKey={refreshKey} />
        <RecentTasksCard refreshKey={refreshKey} />
        <GraphRagCard refreshKey={refreshKey} />
        <SystemHealthCard refreshKey={refreshKey} />
      </div>
    </div>
  );
}
