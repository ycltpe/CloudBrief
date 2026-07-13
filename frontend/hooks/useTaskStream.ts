'use client';

import { useEffect, useRef, useState } from 'react';
import { authFetch } from '@/lib/auth';

export interface TaskStreamEvent {
  step: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  log?: string;
  timestamp: string;
  task_id?: string;
}

interface IndexStep {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  log?: string;
  created_at: string;
}

interface IndexTaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  steps: IndexStep[];
  error?: string;
}

export interface UseTaskStreamResult {
  events: TaskStreamEvent[];
  status: 'pending' | 'running' | 'completed' | 'failed';
  error: string | null;
  connected: boolean;
}

const POLL_INTERVAL_MS = 1200;

function sortEvents(events: TaskStreamEvent[]): TaskStreamEvent[] {
  return [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );
}

export function useTaskStream(taskId: string | null): UseTaskStreamResult {
  const [events, setEvents] = useState<TaskStreamEvent[]>([]);
  const [status, setStatus] = useState<'pending' | 'running' | 'completed' | 'failed'>('pending');
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const finalizedRef = useRef(false);

  useEffect(() => {
    if (!taskId) {
      setEvents([]);
      setStatus('pending');
      setError(null);
      setConnected(false);
      return;
    }

    finalizedRef.current = false;
    setConnected(true);

    const load = async () => {
      if (finalizedRef.current) return;
      try {
        const res = await authFetch(`/api/index/tasks/${taskId}`);
        if (!res.ok) {
          // 忽略轮询中的临时错误，避免中断 UI
          return;
        }
        const data = (await res.json()) as IndexTaskStatus;

        const mapped: TaskStreamEvent[] = data.steps.map((s) => ({
          step: s.name,
          status: s.status,
          duration_ms: s.duration_ms,
          log: s.log,
          timestamp: s.created_at,
          task_id: data.task_id,
        }));
        // 补充一个整体任务事件
        mapped.push({
          step: 'task',
          status: data.status,
          timestamp: new Date().toISOString(),
          task_id: data.task_id,
        });
        setEvents(sortEvents(mapped));
        setStatus(data.status);
        if (data.error) {
          setError(data.error);
        }

        if (data.status === 'completed' || data.status === 'failed') {
          finalizedRef.current = true;
          if (timerRef.current) clearInterval(timerRef.current);
          setConnected(false);
        }
      } catch {
        // 忽略轮询错误
      }
    };

    load();
    timerRef.current = setInterval(load, POLL_INTERVAL_MS);

    return () => {
      finalizedRef.current = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [taskId]);

  return { events, status, error, connected };
}
