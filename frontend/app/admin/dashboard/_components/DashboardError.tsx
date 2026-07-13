import { AlertCircle, RefreshCw } from 'lucide-react';

interface DashboardErrorProps {
  message?: string;
  onRetry?: () => void;
}

export function DashboardError({ message, onRetry }: DashboardErrorProps) {
  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <div className="p-6 text-center">
        <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-red-100 dark:bg-red-950 mb-3">
          <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
        </div>
        <p className="text-sm text-muted-foreground mb-3">
          {message || '加载失败，请稍后重试'}
        </p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-muted-foreground bg-card border border-border rounded-md hover:bg-muted"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            重试
          </button>
        )}
      </div>
    </div>
  );
}
