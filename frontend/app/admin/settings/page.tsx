'use client';

import { useEffect, useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import { authFetch } from '@/lib/auth';

interface SettingItem {
  key: string;
  label: string;
  description: string;
  type: 'float' | 'int' | 'str' | 'choice' | 'bool';
  value: string | number | boolean;
  default: string | number | boolean;
  options?: string[];
  min?: number;
  max?: number;
}

interface SettingGroup {
  group: string;
  items: SettingItem[];
}

interface SettingsResponse {
  groups: SettingGroup[];
}

const GROUP_ICONS: Record<string, string> = {
  '业务阈值': '⚖️',
  '适配器': '🔌',
  '模型': '🧠',
};

export default function SettingsPage() {
  const [groups, setGroups] = useState<SettingGroup[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const fetchSettings = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/settings');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取系统设置失败');
      }
      const data = (await res.json()) as SettingsResponse;
      setGroups(data.groups);
      const init: Record<string, string> = {};
      data.groups.forEach((g) => {
        g.items.forEach((item) => {
          init[item.key] = String(item.value);
        });
      });
      setValues(init);
    } catch (err: any) {
      setError(err.message || '获取系统设置失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setSuccess(false);
  };

  const handleReset = () => {
    const init: Record<string, string> = {};
    groups.forEach((g) => {
      g.items.forEach((item) => {
        init[item.key] = String(item.default);
      });
    });
    setValues(init);
    setSuccess(false);
  };

  const LOCAL_RERANKER_FIELDS = ['local_reranker_url', 'local_reranker_model'];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      if (values.reranker_provider === 'local') {
        try {
          new URL(values.local_reranker_url);
        } catch {
          throw new Error('本地重排服务地址必须是有效 URL，如 http://127.0.0.1:8000/v1');
        }
        if (!values.local_reranker_model?.trim()) {
          throw new Error('本地重排模型名称不能为空');
        }
      }
      const res = await authFetch('/api/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '保存失败');
      }
      setSuccess(true);
      await fetchSettings();
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          运行期配置会持久化到数据库，覆盖 .env 中的默认值。
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleReset}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
          >
            <RotateCcw className="w-4 h-4" />
            恢复默认值
          </button>
          <button
            form="settings-form"
            type="submit"
            disabled={saving || loading}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saving ? '保存中...' : '保存设置'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md dark:bg-red-950 dark:text-red-300 dark:border-red-900">
          {error}
        </div>
      )}

      {success && (
        <div className="p-3 text-sm text-green-700 bg-green-50 border border-green-200 rounded-md dark:bg-green-950 dark:text-green-300 dark:border-green-900">
          设置已保存
        </div>
      )}

      <form id="settings-form" onSubmit={handleSubmit} className="space-y-6">
        {loading ? (
          <div className="p-8 text-center text-muted-foreground bg-card border border-border rounded-lg">加载中...</div>
        ) : (
          groups.map((group) => (
            <div key={group.group} className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
              <div className="px-5 py-3 bg-muted border-b border-border font-medium text-card-foreground flex items-center gap-2">
                <span>{GROUP_ICONS[group.group] || '⚙️'}</span>
                {group.group}
              </div>
              <div className="p-5 grid gap-5 md:grid-cols-2">
                {group.items.map((item) => {
                  if (
                    LOCAL_RERANKER_FIELDS.includes(item.key) &&
                    values.reranker_provider !== 'local'
                  ) {
                    return null;
                  }
                  return (
                    <div
                      key={item.key}
                      className={item.type === 'str' ? 'md:col-span-2' : ''}
                    >
                      <label className="block text-sm font-medium text-card-foreground mb-1">
                        {item.label}
                      </label>
                    {item.type === 'choice' ? (
                      <select
                        value={values[item.key] ?? String(item.default)}
                        onChange={(e) => handleChange(item.key, e.target.value)}
                        className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        {item.options?.map((opt) => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    ) : item.type === 'bool' ? (
                      <label className="inline-flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(values[item.key] ?? String(item.default)) === 'true'}
                          onChange={(e) => handleChange(item.key, String(e.target.checked))}
                          className="w-4 h-4 text-primary border-border rounded focus:ring-ring"
                        />
                        <span className="text-sm text-muted-foreground">
                          {(values[item.key] ?? String(item.default)) === 'true' ? '开启' : '关闭'}
                        </span>
                      </label>
                    ) : (
                      <input
                        type={item.type === 'int' ? 'number' : item.type === 'float' ? 'number' : 'text'}
                        step={item.type === 'float' ? '0.01' : '1'}
                        min={item.min}
                        max={item.max}
                        value={values[item.key] ?? String(item.default)}
                        onChange={(e) => handleChange(item.key, e.target.value)}
                        className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                      />
                    )}
                    <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>
                  </div>
                );
              })}
              </div>
            </div>
          ))
        )}
      </form>
    </div>
  );
}
