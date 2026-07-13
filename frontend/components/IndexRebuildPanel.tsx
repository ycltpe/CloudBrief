'use client';

import {
  Play,
  Square,
  RotateCcw,
  CheckCircle,
  XCircle,
  Clock,
  CircleDot,
} from 'lucide-react';
import { useIndexRebuild } from '@/hooks/useIndexRebuild';
import { formatTimeSeconds } from '@/lib/datetime';
import { IndexStep } from '@/lib/types';

const statusConfig = {
  pending: {
    icon: CircleDot,
    color: 'text-muted-foreground',
    bg: 'bg-muted',
    border: 'border-border',
    label: '等待中',
  },
  running: {
    icon: Clock,
    color: 'text-blue-500 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-950',
    border: 'border-blue-200 dark:border-blue-900',
    label: '执行中',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-500 dark:text-green-400',
    bg: 'bg-green-50 dark:bg-green-950',
    border: 'border-green-200 dark:border-green-900',
    label: '成功',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-500 dark:text-red-400',
    bg: 'bg-red-50 dark:bg-red-950',
    border: 'border-red-200 dark:border-red-900',
    label: '失败',
  },
};

const STEP_LABELS: Record<string, string> = {
  parse: '解析知识源',
  chunking: '文本切分',
  embedding: '生成 Embedding',
  write_milvus: '写入向量库',
  build_bm25: '重建 BM25',
  atomic_switch: '原子切换索引',
};

export default function IndexRebuildPanel() {
  const {
    steps,
    events,
    isRunning,
    error,
    progress,
    successCount,
    errorCount,
    start,
    stop,
    reset,
  } = useIndexRebuild();

  const allDone = successCount === steps.length && steps.length > 0;

  return (
    <div className="flex flex-col h-full min-h-[480px] bg-card rounded-lg border border-border shadow-sm">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-card-foreground">知识库索引重建</h2>
          <p className="text-sm text-muted-foreground">
            解析知识源 → 文本切分 → 生成 Embedding → 写入向量库 → 重建 BM25 → 原子切换索引
          </p>
        </div>
        <div className="flex gap-2">
          {isRunning ? (
            <button
              onClick={stop}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-50 text-red-600 hover:bg-red-100 text-sm font-medium dark:bg-red-950 dark:text-red-300 dark:hover:bg-red-900"
            >
              <Square className="w-4 h-4 fill-current" />
              停止
            </button>
          ) : (
            <button
              onClick={start}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 text-sm font-medium"
            >
              <Play className="w-4 h-4 fill-current" />
              重建索引
            </button>
          )}
          <button
            onClick={reset}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border text-muted-foreground hover:bg-muted text-sm font-medium"
          >
            <RotateCcw className="w-4 h-4" />
            重置
          </button>
        </div>
      </div>

      {/* Progress summary */}
      <div className="px-4 py-3 bg-muted border-b border-border flex items-center gap-4 text-sm">
        <span className="text-muted-foreground">
          步骤：
          <strong className="text-card-foreground">
            {successCount + errorCount}/{steps.length}
          </strong>
        </span>
        {errorCount > 0 && (
          <span className="text-red-600 dark:text-red-400">
            失败：<strong>{errorCount}</strong>
          </span>
        )}
        {isRunning && (
          <span className="text-blue-600 dark:text-blue-400 font-medium">总进度：{progress}%</span>
        )}
        {allDone && <span className="text-green-600 dark:text-green-400 font-medium">全部完成</span>}
        {error && <span className="text-red-600 dark:text-red-400">错误：{error}</span>}
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Steps */}
        <div className="w-1/2 p-4 overflow-y-auto border-r border-border">
          <h3 className="text-sm font-medium text-card-foreground mb-3">执行步骤</h3>
          <div className="space-y-3">
            {steps.map((step, index) => {
              const config = statusConfig[step.status];
              const StatusIcon = config.icon;
              return (
                <div
                  key={step.name}
                  className={`rounded-lg border p-3 transition-all ${config.border} ${config.bg}`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center bg-card/80`}
                    >
                      <StatusIcon className={`w-4 h-4 ${config.color}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-card-foreground">
                          {STEP_LABELS[step.name] ?? step.name}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full bg-card/80 ${config.color}`}
                        >
                          {config.label}
                        </span>
                      </div>
                      {step.duration_ms !== undefined && step.duration_ms > 0 && (
                        <p className="text-xs text-muted-foreground mt-1">
                          耗时 {step.duration_ms} ms
                        </p>
                      )}
                      {step.log && step.status !== 'failed' && (
                        <p className="text-xs text-muted-foreground mt-1 truncate">
                          {step.log}
                        </p>
                      )}
                      {step.log && step.status === 'failed' && (
                        <p className="text-xs text-red-600 dark:text-red-400 mt-1 line-clamp-3">
                          {step.log}
                        </p>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">#{index + 1}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Events */}
        <div className="w-1/2 p-4 overflow-y-auto bg-muted/50">
          <h3 className="text-sm font-medium text-card-foreground mb-3">事件日志</h3>
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              点击「重建索引」开始运行
            </p>
          ) : (
            <div className="space-y-2">
              {events.map((event) => (
                <div key={event.id} className="text-sm flex items-start gap-2">
                  <span className="text-muted-foreground text-xs whitespace-nowrap mt-0.5">
                    {formatTimeSeconds(event.timestamp)}
                  </span>
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full mt-2 flex-shrink-0 ${
                      event.type === 'error'
                        ? 'bg-red-500 dark:bg-red-400'
                        : event.type === 'complete'
                        ? 'bg-green-500 dark:bg-green-400'
                        : event.type === 'start'
                        ? 'bg-blue-500 dark:bg-blue-400'
                        : 'bg-muted-foreground'
                    }`}
                  />
                  <span className="text-card-foreground break-all">{event.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
