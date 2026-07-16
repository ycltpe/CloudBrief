'use client';

import { useEffect, useMemo, useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import { authFetch } from '@/lib/auth';

type SettingSource = 'db' | 'env' | 'default';

interface SettingItem {
  key: string;
  label: string;
  description: string;
  type: 'float' | 'int' | 'str' | 'choice' | 'bool';
  value: string | number | boolean;
  default: string | number | boolean;
  source: SettingSource;
  secret: boolean;
  restart_required: boolean;
  requires_reindex: boolean;
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
  '功能开关': '🎛️',
  '适配器': '🔌',
  '大语言模型': '🧠',
  '向量模型': '🧮',
  'Reranker 模型': '🎯',
  '文档解析': '📄',
  'GraphRAG 监控': '📈',
  '存储连接': '🗄️',
  '认证与安全': '🔐',
  '系统': '🖥️',
};

// 模型组按 provider 条件渲染：选中云端/本地时只显示对应字段块
const PROVIDER_FIELD_RULES: Record<
  string,
  { providerKey: string; cloudKeys: string[]; localKeys: string[] }
> = {
  '大语言模型': {
    providerKey: 'llm_provider',
    cloudKeys: ['llm_api_key', 'llm_base_url', 'llm_model'],
    localKeys: ['local_llm_url', 'local_llm_model'],
  },
  '向量模型': {
    providerKey: 'embedding_provider',
    cloudKeys: ['embedding_api_key', 'embedding_base_url', 'embedding_model'],
    localKeys: ['local_embedding_url', 'local_embedding_model'],
  },
  'Reranker 模型': {
    providerKey: 'reranker_provider',
    cloudKeys: ['reranker_api_key', 'rerank_base_url', 'reranker_model'],
    localKeys: ['local_reranker_url', 'local_reranker_model'],
  },
};

const isItemVisible = (groupName: string, key: string, vals: Record<string, string>) => {
  const rule = PROVIDER_FIELD_RULES[groupName];
  if (!rule) return true;
  const provider = vals[rule.providerKey];
  if (rule.localKeys.includes(key)) return provider === 'local';
  if (rule.cloudKeys.includes(key)) return provider !== 'local';
  return true;
};

const PROVIDER_OPTION_LABELS: Record<string, string> = {
  dashscope: '云端 DashScope',
  local: '本地部署',
};

const SOURCE_BADGES: Record<SettingSource, { text: string; className: string }> = {
  db: {
    text: '数据库覆盖',
    className: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  },
  env: {
    text: '.env 配置',
    className: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  },
  default: {
    text: '默认值',
    className: 'bg-muted text-muted-foreground',
  },
};

const FLAG_BADGES = {
  restart: {
    text: '重启生效',
    className: 'bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300',
  },
  reindex: {
    text: '需重建索引',
    className: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  },
};

function Badge({ text, className }: { text: string; className: string }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] leading-4 ${className}`}>
      {text}
    </span>
  );
}

export default function SettingsPage() {
  const [groups, setGroups] = useState<SettingGroup[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [baselines, setBaselines] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const itemMeta = useMemo(() => {
    const map: Record<string, SettingItem> = {};
    groups.forEach((g) => g.items.forEach((item) => { map[item.key] = item; }));
    return map;
  }, [groups]);

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
          // 密钥项出参为掩码，表单留空表示不修改
          init[item.key] = item.secret ? '' : String(item.value);
        });
      });
      setValues(init);
      setBaselines(init);
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
    setSuccess(null);
  };

  const handleFillDefaults = () => {
    const init: Record<string, string> = {};
    groups.forEach((g) => {
      g.items.forEach((item) => {
        init[item.key] = item.secret ? '' : String(item.default);
      });
    });
    setValues(init);
    setSuccess(null);
  };

  const handleResetItem = async (item: SettingItem) => {
    if (!window.confirm(`确定删除「${item.label}」的数据库覆盖，恢复为 .env / 默认值？`)) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      const res = await authFetch(`/api/admin/settings/${item.key}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '恢复默认失败');
      }
      setSuccess(`「${item.label}」已恢复默认`);
      await fetchSettings();
    } catch (err: any) {
      setError(err.message || '恢复默认失败');
    }
  };

  const keyGroup = useMemo(() => {
    const map: Record<string, string> = {};
    groups.forEach((g) => g.items.forEach((item) => { map[item.key] = g.group; }));
    return map;
  }, [groups]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    // 当前隐藏字段（非激活 provider 的字段块）的改动不提交，避免"改了看不见的字段"
    const changedKeys = Object.keys(values).filter(
      (k) => values[k] !== baselines[k] && isItemVisible(keyGroup[k] || '', k, values)
    );
    if (changedKeys.length === 0) {
      setSuccess('没有需要保存的修改');
      return;
    }

    const labelsOf = (keys: string[]) => keys.map((k) => itemMeta[k]?.label || k).join('、');
    const reindexChanged = changedKeys.filter((k) => itemMeta[k]?.requires_reindex);
    const restartChanged = changedKeys.filter((k) => itemMeta[k]?.restart_required);
    const notes: string[] = [];
    if (reindexChanged.length > 0) {
      notes.push(`以下配置需重建索引后才能对存量数据生效：${labelsOf(reindexChanged)}`);
    }
    if (restartChanged.length > 0) {
      notes.push(`以下配置需重启服务后生效：${labelsOf(restartChanged)}`);
    }
    if (notes.length > 0 && !window.confirm(`${notes.join('\n')}\n\n是否继续保存？`)) {
      return;
    }

    setSaving(true);
    try {
      // 切到本地部署时，校验本地服务地址与模型名
      for (const rule of Object.values(PROVIDER_FIELD_RULES)) {
        const providerChanged = changedKeys.includes(rule.providerKey);
        const localChanged = changedKeys.some((k) => rule.localKeys.includes(k));
        if ((providerChanged || localChanged) && values[rule.providerKey] === 'local') {
          const [urlKey, modelKey] = rule.localKeys;
          try {
            new URL(values[urlKey]);
          } catch {
            throw new Error(`「${itemMeta[urlKey]?.label || urlKey}」必须是有效 URL，如 http://127.0.0.1:8000/v1`);
          }
          if (!values[modelKey]?.trim()) {
            throw new Error(`「${itemMeta[modelKey]?.label || modelKey}」不能为空`);
          }
        }
      }
      const payload = Object.fromEntries(changedKeys.map((k) => [k, values[k]]));
      const res = await authFetch('/api/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: payload }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '保存失败');
      }
      setSuccess('设置已保存');
      await fetchSettings();
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const secretPlaceholder = (item: SettingItem) => {
    if (item.source === 'db') return '已在数据库设置，留空则不修改';
    if (item.source === 'env') return '已在 .env 配置，留空则不修改';
    return '未设置';
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          配置按「数据库覆盖 → .env 环境配置 → 代码默认值」的优先级生效，仅保存被修改的项。
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleFillDefaults}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
          >
            <RotateCcw className="w-4 h-4" />
            填入默认值
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
          {success}
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
                  if (!isItemVisible(group.group, item.key, values)) {
                    return null;
                  }
                  return (
                    <div
                      key={item.key}
                      className={item.type === 'str' ? 'md:col-span-2' : ''}
                    >
                      <div className="flex flex-wrap items-center gap-1.5 mb-1">
                        <label className="text-sm font-medium text-card-foreground">
                          {item.label}
                        </label>
                        <Badge
                          text={SOURCE_BADGES[item.source].text}
                          className={SOURCE_BADGES[item.source].className}
                        />
                        {item.restart_required && (
                          <Badge text={FLAG_BADGES.restart.text} className={FLAG_BADGES.restart.className} />
                        )}
                        {item.requires_reindex && (
                          <Badge text={FLAG_BADGES.reindex.text} className={FLAG_BADGES.reindex.className} />
                        )}
                        {item.source === 'db' && (
                          <button
                            type="button"
                            title="删除数据库覆盖，恢复默认"
                            onClick={() => handleResetItem(item)}
                            className="ml-auto p-1 text-muted-foreground hover:text-card-foreground rounded hover:bg-muted"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                      {item.secret ? (
                        <input
                          type="password"
                          autoComplete="new-password"
                          value={values[item.key] ?? ''}
                          placeholder={secretPlaceholder(item)}
                          onChange={(e) => handleChange(item.key, e.target.value)}
                          className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                      ) : item.type === 'choice' ? (
                        <select
                          value={values[item.key] ?? String(item.default)}
                          onChange={(e) => handleChange(item.key, e.target.value)}
                          className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        >
                          {item.options?.map((opt) => (
                            <option key={opt} value={opt}>{PROVIDER_OPTION_LABELS[opt] || opt}</option>
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
