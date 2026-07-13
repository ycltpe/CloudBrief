import { useEffect, useRef, useState } from 'react';
import { IndexStep, IndexTaskStatus } from '@/lib/types';

export type EventType = 'start' | 'complete' | 'error' | 'info';

export interface RebuildEvent {
  id: string;
  timestamp: Date;
  type: EventType;
  message: string;
}

const STEP_LABELS: Record<string, string> = {
  parse: '解析知识源',
  chunking: '文本切分',
  embedding: '生成 Embedding',
  write_milvus: '写入向量库',
  build_bm25: '重建 BM25',
  atomic_switch: '原子切换索引',
  task: '整体任务',
};

const STEP_ORDER = [
  'parse',
  'chunking',
  'embedding',
  'write_milvus',
  'build_bm25',
  'atomic_switch',
];

function stepLabel(name: string): string {
  return STEP_LABELS[name] || name;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useIndexRebuild() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [steps, setSteps] = useState<IndexStep[]>([]);
  const [events, setEvents] = useState<RebuildEvent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevStepsRef = useRef<IndexStep[]>([]);

  const addEvent = (type: EventType, message: string) => {
    setEvents((prev) => [
      ...prev,
      { id: generateId(), timestamp: new Date(), type, message },
    ]);
  };

  const reset = () => {
    setTaskId(null);
    setSteps([]);
    setEvents([]);
    setIsRunning(false);
    setError(null);
    prevStepsRef.current = [];
  };

  const start = async () => {
    reset();
    setIsRunning(true);
    try {
      const res = await fetch('/api/index/rebuild', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTaskId(data.task_id as string);
      addEvent('info', '重建任务已创建');
    } catch (err) {
      setError(err instanceof Error ? err.message : '启动失败');
      setIsRunning(false);
    }
  };

  const stop = () => {
    setIsRunning(false);
    addEvent('info', '已停止前端轮询');
  };

  useEffect(() => {
    if (!taskId || !isRunning) return;

    let stopped = false;
    let consecutiveErrors = 0;

    const loadStatus = async () => {
      try {
        const res = await fetch(`/api/index/tasks/${taskId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: IndexTaskStatus = await res.json();
        consecutiveErrors = 0;

        const newSteps = data.steps || [];
        const oldSteps = prevStepsRef.current;

        // 只在状态变化时生成事件，避免重复
        newSteps.forEach((step) => {
          const old = oldSteps.find((s) => s.name === step.name);
          if (!old || old.status !== step.status) {
            const label = stepLabel(step.name);
            if (step.status === 'running') {
              addEvent('start', `开始 ${label}`);
            } else if (step.status === 'completed') {
              addEvent(
                'complete',
                `${label} 完成${step.log ? `：${step.log}` : ''}`
              );
            } else if (step.status === 'failed') {
              addEvent(
                'error',
                `${label} 失败：${step.log || '未知错误'}`
              );
            }
          }
        });

        prevStepsRef.current = newSteps;
        setSteps(newSteps);

        if (data.status === 'completed' || data.status === 'failed') {
          stopped = true;
          setIsRunning(false);
          if (data.error) {
            addEvent('error', `任务失败：${data.error}`);
          } else if (data.status === 'completed') {
            addEvent('info', '索引重建全部完成');
          }
        }
      } catch (err) {
        consecutiveErrors += 1;
        if (consecutiveErrors >= 5) {
          stopped = true;
          setError(err instanceof Error ? err.message : '轮询失败');
          setIsRunning(false);
        }
      }
    };

    loadStatus();
    const interval = setInterval(() => {
      if (!stopped) {
        loadStatus();
      } else {
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [taskId, isRunning]);

  const normalizedSteps: IndexStep[] = STEP_ORDER.map((name) => {
    const found = steps.find((s) => s.name === name);
    return (
      found || {
        name,
        status: 'pending' as const,
        created_at: '',
      }
    );
  });

  const successCount = normalizedSteps.filter((s) => s.status === 'completed').length;
  const errorCount = normalizedSteps.filter((s) => s.status === 'failed').length;
  const progress =
    STEP_ORDER.length === 0
      ? 0
      : Math.round((successCount / STEP_ORDER.length) * 100);

  return {
    steps: normalizedSteps,
    events,
    isRunning,
    error,
    progress,
    successCount,
    errorCount,
    start,
    stop,
    reset,
  };
}
