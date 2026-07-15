'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Folder,
  FolderOpen,
  FileText,
  Trash2,
  Plus,
  Upload,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  X,
  AlertCircle,
  CheckCircle,
  Clock,
  XCircle,
  Loader2,
  Play,
  Network,
  HelpCircle,
  Sparkles,
  Save,
  Wand2,
  Shield,
} from 'lucide-react';
import { KbDirectory, KbFile } from '@/lib/types';
import { authFetch } from '@/lib/auth';
import { formatIsoDate } from '@/lib/datetime';
import { useTaskStream } from '@/hooks/useTaskStream';
import GraphSchemaViz from '@/components/kb/GraphSchemaViz';
import Link from 'next/link';

interface KbTreeResponse {
  directories: KbDirectory[];
}

interface KbFileListResponse {
  files: KbFile[];
}

interface EntityType {
  name: string;
  description?: string;
  examples?: string[];
}

interface RelationType {
  name: string;
  description?: string;
  source_types?: string[];
  target_types?: string[];
}

interface KbGraphSchema {
  directory_id: number;
  enabled: boolean;
  enabled_by_user: boolean;
  shadow_mode: boolean;
  entity_types: EntityType[];
  relation_types: RelationType[];
  version: number;
  updated_at?: string;
}

interface KbGraphSchemaRecommendResponse {
  directory_id: number;
  entity_types: EntityType[];
  relation_types: RelationType[];
}

interface IndexStep {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  log?: string;
}

interface IndexTaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  steps: IndexStep[];
  error?: string;
}

const STEP_ORDER = [
  'parse',
  'chunking',
  'embedding',
  'write_milvus',
  'build_bm25',
  'atomic_switch',
];

const STEP_LABELS: Record<string, string> = {
  parse: '解析知识源',
  chunking: '文本切分',
  embedding: '生成 Embedding',
  write_milvus: '写入向量库',
  build_bm25: '重建 BM25',
  atomic_switch: '原子切换索引',
  load_active: '加载现有索引',
  task: '整体任务',
  graph_load_chunks: '加载图谱 chunks',
  graph_extraction: '抽取实体关系',
  graph_building: '写入图数据库',
  graph_indexing_complete: '图谱构建完成',
  graph_subtask_triggered: '图索引子任务已触发',
};

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`;
}

function flattenDirectories(dirs: KbDirectory[], depth = 0): Array<KbDirectory & { depth: number }> {
  const result: Array<KbDirectory & { depth: number }> = [];
  for (const d of dirs) {
    result.push({ ...d, depth });
    result.push(...flattenDirectories(d.children, depth + 1));
  }
  return result;
}

export default function KbPage() {
  const [tree, setTree] = useState<KbDirectory[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [files, setFiles] = useState<KbFile[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDescription, setCreateDescription] = useState('');
  const [createParentId, setCreateParentId] = useState<number | null>(null);
  const [createGraphragEnabled, setCreateGraphragEnabled] = useState(false);
  const [creating, setCreating] = useState(false);

  const [showUpload, setShowUpload] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDirId, setUploadDirId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);

  const [rebuildTaskId, setRebuildTaskId] = useState<string | null>(null);
  const [rebuildStatus, setRebuildStatus] = useState<IndexTaskStatus | null>(null);
  const rebuildTimer = useRef<NodeJS.Timeout | null>(null);

  const [graphSchema, setGraphSchema] = useState<KbGraphSchema | null>(null);
  const [loadingGraphSchema, setLoadingGraphSchema] = useState(false);
  const [schemaSaving, setSchemaSaving] = useState(false);
  const [recommending, setRecommending] = useState(false);
  const [selectedSchemaItem, setSelectedSchemaItem] = useState<
    | { type: 'entity'; data: EntityType }
    | { type: 'relation'; data: RelationType }
    | null
  >(null);
  const [graphTaskId, setGraphTaskId] = useState<string | null>(null);
  const [graphTaskStatus, setGraphTaskStatus] = useState<IndexTaskStatus | null>(null);
  const graphTaskTimer = useRef<NodeJS.Timeout | null>(null);

  const [logFile, setLogFile] = useState<KbFile | null>(null);
  const logTaskId = logFile?.task_id || null;
  const { events: logEvents, status: logStatus, error: logError, connected: logConnected } =
    useTaskStream(logTaskId);

  // 索引任务完成/失败后刷新文件列表状态
  useEffect(() => {
    if (logStatus === 'completed' || logStatus === 'failed') {
      if (selectedId !== null) fetchFiles(selectedId);
      fetchTree();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logStatus, selectedId]);

  const fetchTree = async () => {
    setLoadingTree(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/kb/tree');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取目录树失败');
      }
      const data = (await res.json()) as KbTreeResponse;
      setTree(data.directories);
    } catch (err: any) {
      setError(err.message || '获取目录树失败');
    } finally {
      setLoadingTree(false);
    }
  };

  const fetchFiles = async (directoryId: number) => {
    setLoadingFiles(true);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${directoryId}/files`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取文件列表失败');
      }
      const data = (await res.json()) as KbFileListResponse;
      setFiles(data.files);
    } catch (err: any) {
      setError(err.message || '获取文件列表失败');
    } finally {
      setLoadingFiles(false);
    }
  };

  useEffect(() => {
    fetchTree();
  }, []);

  const fetchGraphSchema = async (directoryId: number) => {
    setLoadingGraphSchema(true);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${directoryId}/graph-schema`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '获取 GraphRAG 配置失败');
      }
      setGraphSchema((await res.json()) as KbGraphSchema);
    } catch (err: any) {
      setError(err.message || '获取 GraphRAG 配置失败');
      setGraphSchema(null);
    } finally {
      setLoadingGraphSchema(false);
    }
  };

  useEffect(() => {
    if (selectedId !== null) {
      fetchFiles(selectedId);
      fetchGraphSchema(selectedId);
    } else {
      setFiles([]);
      setGraphSchema(null);
    }
    setSelectedSchemaItem(null);
  }, [selectedId]);

  const selectedDirectory = useMemo(() => {
    const find = (dirs: KbDirectory[]): KbDirectory | null => {
      for (const d of dirs) {
        if (d.id === selectedId) return d;
        const found = find(d.children);
        if (found) return found;
      }
      return null;
    };
    return find(tree);
  }, [selectedId, tree]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const res = await authFetch('/api/admin/kb/directories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: createName.trim(),
          description: createDescription.trim() || undefined,
          parent_id: createParentId,
          graphrag_enabled: createGraphragEnabled,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '创建目录失败');
      }
      setShowCreate(false);
      setCreateName('');
      setCreateDescription('');
      setCreateGraphragEnabled(false);
      await fetchTree();
    } catch (err: any) {
      setError(err.message || '创建目录失败');
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteDirectory = async (id: number) => {
    if (!confirm('删除目录会同时删除其下所有子目录和文件，是否继续？')) return;
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '删除目录失败');
      }
      if (selectedId === id) setSelectedId(null);
      await fetchTree();
    } catch (err: any) {
      setError(err.message || '删除目录失败');
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || uploadDirId === null) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('directory_id', String(uploadDirId));
      form.append('file', uploadFile);
      const res = await authFetch('/api/admin/kb/files', {
        method: 'POST',
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '上传失败');
      }
      const data = (await res.json()) as { file: KbFile; task_id?: string | null };
      setShowUpload(false);
      setUploadFile(null);
      await fetchTree();
      if (selectedId === uploadDirId) await fetchFiles(uploadDirId);
      if (data.task_id && data.file) {
        const uploadedFile = { ...data.file, task_id: data.task_id };
        setLogFile(uploadedFile);
      }
    } catch (err: any) {
      setError(err.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteFile = async (fileId: number) => {
    if (!confirm('删除后无法恢复，是否继续？')) return;
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/files/${fileId}`, { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '删除文件失败');
      }
      if (selectedId !== null) await fetchFiles(selectedId);
      await fetchTree();
    } catch (err: any) {
      setError(err.message || '删除文件失败');
    }
  };

  const handleReindexFile = async (file: KbFile) => {
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/files/${file.id}/index`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '触发索引失败');
      }
      const data = (await res.json()) as { task_id: string };
      setLogFile({ ...file, task_id: data.task_id, status: 'indexing' });
      if (selectedId !== null) await fetchFiles(selectedId);
    } catch (err: any) {
      setError(err.message || '触发索引失败');
    }
  };

  const openLog = (file: KbFile) => {
    setLogFile(file);
  };

  const handleSaveGraphSchema = async () => {
    if (!graphSchema || selectedId === null) return;
    setSchemaSaving(true);
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${selectedId}/graph-schema`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: graphSchema.enabled,
          shadow_mode: graphSchema.shadow_mode,
          entity_types: graphSchema.entity_types,
          relation_types: graphSchema.relation_types,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '保存失败');
      }
      setGraphSchema((await res.json()) as KbGraphSchema);
      await fetchTree();
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setSchemaSaving(false);
    }
  };

  const handleRecommendSchema = async () => {
    if (selectedId === null) return;
    setRecommending(true);
    setError(null);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${selectedId}/graph-schema/recommend`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '推荐失败');
      }
      const data = (await res.json()) as KbGraphSchemaRecommendResponse;
      setGraphSchema((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          entity_types: data.entity_types,
          relation_types: data.relation_types,
        };
      });
      setSelectedSchemaItem(null);
    } catch (err: any) {
      setError(err.message || '推荐失败');
    } finally {
      setRecommending(false);
    }
  };

  const handleRebuildGraph = async () => {
    if (selectedId === null) return;
    setError(null);
    setGraphTaskStatus(null);
    try {
      const res = await authFetch(`/api/admin/kb/directories/${selectedId}/graph-schema/rebuild`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '触发图索引重建失败');
      }
      const data = (await res.json()) as { task_id: string };
      setGraphTaskId(data.task_id);
    } catch (err: any) {
      setError(err.message || '触发图索引重建失败');
    }
  };

  useEffect(() => {
    if (!graphTaskId) return;
    let stopped = false;
    const load = async () => {
      try {
        const res = await authFetch(`/api/index/tasks/${graphTaskId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: IndexTaskStatus = await res.json();
        if (stopped) return;
        setGraphTaskStatus(data);
        if (data.status === 'completed' || data.status === 'failed') {
          stopped = true;
          if (graphTaskTimer.current) clearInterval(graphTaskTimer.current);
        }
      } catch (err) {
        // 忽略轮询错误
      }
    };
    load();
    graphTaskTimer.current = setInterval(() => {
      if (!stopped) load();
    }, 1500);
    return () => {
      stopped = true;
      if (graphTaskTimer.current) clearInterval(graphTaskTimer.current);
    };
  }, [graphTaskId]);

  const handleRebuild = async () => {
    setError(null);
    setRebuildStatus(null);
    try {
      const res = await authFetch('/api/admin/kb/rebuild', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || '触发索引重建失败');
      }
      const data = await res.json();
      setRebuildTaskId(data.task_id as string);
    } catch (err: any) {
      setError(err.message || '触发索引重建失败');
    }
  };

  useEffect(() => {
    if (!rebuildTaskId) return;
    let stopped = false;
    const load = async () => {
      try {
        const res = await authFetch(`/api/index/tasks/${rebuildTaskId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: IndexTaskStatus = await res.json();
        if (stopped) return;
        setRebuildStatus(data);
        if (data.status === 'completed' || data.status === 'failed') {
          stopped = true;
          if (rebuildTimer.current) clearInterval(rebuildTimer.current);
        }
      } catch (err) {
        // 忽略轮询错误，避免中断 UI
      }
    };
    load();
    rebuildTimer.current = setInterval(() => {
      if (!stopped) load();
    }, 1500);
    return () => {
      stopped = true;
      if (rebuildTimer.current) clearInterval(rebuildTimer.current);
    };
  }, [rebuildTaskId]);

  const openCreate = (parentId: number | null = null) => {
    setCreateParentId(parentId);
    setCreateName('');
    setCreateDescription('');
    setShowCreate(true);
  };

  const openUpload = (dirId: number) => {
    setUploadDirId(dirId);
    setUploadFile(null);
    setShowUpload(true);
  };

  const renderDirectoryNode = (dir: KbDirectory, depth = 0) => {
    const isExpanded = expanded.has(dir.id);
    const isSelected = selectedId === dir.id;
    const hasChildren = dir.children && dir.children.length > 0;
    return (
      <div key={dir.id}>
        <div
          className={`flex items-center gap-1 px-2 py-1.5 rounded-md cursor-pointer text-sm group ${
            isSelected ? 'bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300' : 'hover:bg-muted text-card-foreground'
          }`}
          style={{ paddingLeft: `${12 + depth * 16}px` }}
          onClick={() => setSelectedId(dir.id)}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (hasChildren) toggleExpand(dir.id);
            }}
            className={`p-0.5 rounded hover:bg-muted ${hasChildren ? 'visible' : 'invisible'}`}
          >
            {isExpanded ? (
              <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
            )}
          </button>
          {isExpanded ? (
            <FolderOpen className="w-4 h-4 text-amber-500 flex-shrink-0" />
          ) : (
            <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
          )}
          <span className="flex-1 truncate">{dir.name}</span>
          <span className="text-xs text-muted-foreground flex-shrink-0">{dir.file_count}</span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openCreate(dir.id);
            }}
            className="p-1 rounded hover:bg-muted text-muted-foreground opacity-0 group-hover:opacity-100"
            title="新建子目录"
          >
            <Plus className="w-3 h-3" />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openUpload(dir.id);
            }}
            className="p-1 rounded hover:bg-muted text-muted-foreground opacity-0 group-hover:opacity-100"
            title="上传文件"
          >
            <Upload className="w-3 h-3" />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleDeleteDirectory(dir.id);
            }}
            className="p-1 rounded hover:bg-red-100 dark:bg-red-950 text-red-500 opacity-0 group-hover:opacity-100"
            title="删除目录"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
        {isExpanded && hasChildren && (
          <div>{dir.children.map((child) => renderDirectoryNode(child, depth + 1))}</div>
        )}
      </div>
    );
  };

  const rebuildSteps = useMemo(() => {
    const stepMap = new Map(rebuildStatus?.steps.map((s) => [s.name, s]));
    return STEP_ORDER.map((name) => {
      const found = stepMap.get(name);
      return (
        found || {
          name,
          status: 'pending' as const,
        }
      );
    });
  }, [rebuildStatus]);

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex gap-2">
          <button
            onClick={() => openCreate(null)}
            className="flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:opacity-90"
          >
            <Plus className="w-4 h-4" />
            新建根目录
          </button>
          <button
            onClick={handleRebuild}
            disabled={!!rebuildTaskId && rebuildStatus?.status === 'running'}
            className="flex items-center gap-1.5 px-4 py-2 bg-card border border-border text-card-foreground text-sm font-medium rounded-md hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className="w-4 h-4" />
            {rebuildStatus?.status === 'running' ? '重建中...' : '重建索引'}
          </button>
          <Link
            href="/admin/kb/access"
            className="flex items-center gap-1.5 px-4 py-2 bg-card border border-border text-card-foreground text-sm font-medium rounded-md hover:bg-muted"
          >
            <Shield className="w-4 h-4" />
            权限审批
          </Link>
        </div>
      </div>

      {error && (
        <div className="p-3 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-900 rounded-md flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {rebuildStatus && (
        <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-medium text-card-foreground">
              索引重建任务：{rebuildStatus.task_id}
            </div>
            <div className="flex items-center gap-1.5">
              {rebuildStatus.status === 'running' && (
                <Clock className="w-4 h-4 text-blue-500" />
              )}
              {rebuildStatus.status === 'completed' && (
                <CheckCircle className="w-4 h-4 text-green-500" />
              )}
              {rebuildStatus.status === 'failed' && (
                <XCircle className="w-4 h-4 text-red-500" />
              )}
              <span
                className={`text-xs font-medium ${
                  rebuildStatus.status === 'completed'
                    ? 'text-green-600 dark:text-green-300'
                    : rebuildStatus.status === 'failed'
                    ? 'text-red-600 dark:text-red-300'
                    : 'text-blue-600 dark:text-blue-300'
                }`}
              >
                {rebuildStatus.status === 'running'
                  ? '执行中'
                  : rebuildStatus.status === 'completed'
                  ? '已完成'
                  : rebuildStatus.status === 'failed'
                  ? '失败'
                  : '等待中'}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
            {rebuildSteps.map((step) => (
              <div
                key={step.name}
                className={`text-xs px-2 py-1.5 rounded border ${
                  step.status === 'completed'
                    ? 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-900 text-green-700 dark:text-green-300'
                    : step.status === 'running'
                    ? 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300'
                    : step.status === 'failed'
                    ? 'bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-900 text-red-700 dark:text-red-300'
                    : 'bg-muted border-border text-muted-foreground'
                }`}
              >
                {STEP_LABELS[step.name] || step.name}
              </div>
            ))}
          </div>
          {rebuildStatus.error && (
            <p className="mt-2 text-xs text-red-600 dark:text-red-300">{rebuildStatus.error}</p>
          )}
        </div>
      )}

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Directory tree */}
        <div className="w-1/3 min-w-[260px] max-w-[360px] bg-card border border-border rounded-lg shadow-sm flex flex-col">
          <div className="px-4 py-3 border-b border-border font-medium text-card-foreground">
            目录树
          </div>
          <div className="flex-1 overflow-auto p-2">
            {loadingTree ? (
              <div className="p-4 text-center text-sm text-muted-foreground">加载中...</div>
            ) : tree.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground">
                暂无目录，点击上方「新建根目录」开始
              </div>
            ) : (
              tree.map((dir) => renderDirectoryNode(dir))
            )}
          </div>
        </div>

        {/* File list */}
        <div className="flex-1 bg-card border border-border rounded-lg shadow-sm flex flex-col min-w-0">
          <div className="px-5 py-3 border-b border-border flex items-center justify-between">
            <div className="font-medium text-card-foreground">
              {selectedDirectory ? selectedDirectory.name : '请选择目录'}
            </div>
            {selectedDirectory && (
              <button
                onClick={() => openUpload(selectedDirectory.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-blue-600 dark:text-blue-300 bg-blue-50 dark:bg-blue-950 rounded-md hover:bg-blue-100 dark:hover:bg-blue-900"
              >
                <Upload className="w-3.5 h-3.5" />
                上传文件
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto p-0">
            {selectedId === null ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                从左侧选择目录查看文件
              </div>
            ) : loadingFiles ? (
              <div className="p-8 text-center text-sm text-muted-foreground">加载中...</div>
            ) : files.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                该目录下暂无文件
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-5 py-3 text-left font-medium text-muted-foreground">文件名</th>
                    <th className="px-5 py-3 text-left font-medium text-muted-foreground">大小</th>
                    <th className="px-5 py-3 text-left font-medium text-muted-foreground">状态</th>
                    <th className="px-5 py-3 text-left font-medium text-muted-foreground">上传时间</th>
                    <th className="px-5 py-3 text-right font-medium text-muted-foreground">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {files.map((file) => (
                    <tr key={file.id} className="hover:bg-muted">
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <FileText className="w-4 h-4 text-muted-foreground" />
                          <span className="text-card-foreground truncate max-w-[240px]">
                            {file.original_name}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">{formatBytes(file.size)}</td>
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                            file.status === 'indexed'
                              ? 'bg-green-100 dark:bg-green-950 text-green-700 dark:text-green-300'
                              : file.status === 'failed'
                              ? 'bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300'
                              : file.status === 'indexing'
                              ? 'bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300'
                              : 'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300'
                          }`}
                        >
                          {file.status === 'indexed' && <CheckCircle className="w-3 h-3" />}
                          {file.status === 'failed' && <XCircle className="w-3 h-3" />}
                          {file.status === 'indexing' && <Loader2 className="w-3 h-3 animate-spin" />}
                          {file.status === 'indexed'
                            ? '已索引'
                            : file.status === 'failed'
                            ? '失败'
                            : file.status === 'indexing'
                            ? '索引中'
                            : '待索引'}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {formatIsoDate(file.created_at)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        {file.task_id && (
                          <button
                            onClick={() => openLog(file)}
                            className="inline-flex items-center gap-1 px-2 py-1 mr-2 text-xs font-medium text-blue-600 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-950 rounded-md"
                          >
                            <FileText className="w-3.5 h-3.5" />
                            查看日志
                          </button>
                        )}
                        <button
                          onClick={() => handleReindexFile(file)}
                          disabled={file.status === 'indexing'}
                          className="inline-flex items-center gap-1 px-2 py-1 mr-2 text-xs font-medium text-muted-foreground hover:bg-muted rounded-md disabled:opacity-50"
                        >
                          <Play className="w-3.5 h-3.5" />
                          重新索引
                        </button>
                        <button
                          onClick={() => handleDeleteFile(file.id)}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-red-600 dark:text-red-300 hover:bg-red-50 dark:bg-red-950 rounded-md"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* GraphRAG 配置卡片 */}
      {selectedId !== null && graphSchema && (
        <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
          <div className="px-5 py-3 bg-muted border-b border-border flex items-center justify-between">
            <div className="font-medium text-card-foreground flex items-center gap-2">
              <Network className="w-4 h-4 text-primary" />
              GraphRAG 配置
            </div>
            {selectedDirectory?.graphrag_enabled && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300">
                已启用意图
              </span>
            )}
          </div>
          <div className="p-5 space-y-5">
            {loadingGraphSchema ? (
              <div className="text-sm text-muted-foreground">加载配置中...</div>
            ) : (
              <>
                <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                  <label className="inline-flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={graphSchema.enabled}
                      onChange={(e) =>
                        setGraphSchema((prev) =>
                          prev ? { ...prev, enabled: e.target.checked } : prev
                        )
                      }
                      className="w-4 h-4 text-primary border-border rounded focus:ring-ring"
                    />
                    <span className="text-sm text-card-foreground">启用 GraphRAG</span>
                  </label>
                  <label className="inline-flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={graphSchema.shadow_mode}
                      onChange={(e) =>
                        setGraphSchema((prev) =>
                          prev ? { ...prev, shadow_mode: e.target.checked } : prev
                        )
                      }
                      className="w-4 h-4 text-primary border-border rounded focus:ring-ring"
                    />
                    <span className="text-sm text-card-foreground">Shadow Mode（仅记录差异，不影响答案）</span>
                  </label>
                  <div className="flex-1" />
                  <button
                    onClick={handleRecommendSchema}
                    disabled={recommending}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted disabled:opacity-50"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    {recommending ? '推荐中...' : '自动推荐 schema'}
                  </button>
                  <button
                    onClick={handleRebuildGraph}
                    disabled={graphTaskStatus?.status === 'running'}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${graphTaskStatus?.status === 'running' ? 'animate-spin' : ''}`} />
                    {graphTaskStatus?.status === 'running' ? '构建中...' : '重建图谱'}
                  </button>
                  <button
                    onClick={handleSaveGraphSchema}
                    disabled={schemaSaving}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                  >
                    <Save className="w-3.5 h-3.5" />
                    {schemaSaving ? '保存中...' : '保存配置'}
                  </button>
                </div>

                <div className="flex flex-col lg:flex-row gap-5">
                  <div className="flex-1 min-w-0 space-y-5">
                    <div>
                      <label className="block text-sm font-medium text-card-foreground mb-2">
                        实体类型（每行一个 JSON：{'{"name":"人员","description":"...","examples":["张三"]}'}
                      </label>
                      <textarea
                        value={graphSchema.entity_types
                          .map((et) => JSON.stringify(et))
                          .join('\n')}
                        onChange={(e) => {
                          const lines = e.target.value.split('\n').filter(Boolean);
                          const parsed: EntityType[] = [];
                          for (const line of lines) {
                            try {
                              parsed.push(JSON.parse(line));
                            } catch {
                              // 忽略解析失败的行
                            }
                          }
                          setGraphSchema((prev) =>
                            prev ? { ...prev, entity_types: parsed } : prev
                          );
                        }}
                        rows={6}
                        className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                        placeholder={`{"name":"人员","description":"公司员工或客户","examples":["张三"]}`}
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-card-foreground mb-2">
                        关系类型（每行一个 JSON：{'{"name":"汇报给","source_types":["人员"],"target_types":["人员"]}'}
                      </label>
                      <textarea
                        value={graphSchema.relation_types
                          .map((rt) => JSON.stringify(rt))
                          .join('\n')}
                        onChange={(e) => {
                          const lines = e.target.value.split('\n').filter(Boolean);
                          const parsed: RelationType[] = [];
                          for (const line of lines) {
                            try {
                              parsed.push(JSON.parse(line));
                            } catch {
                              // 忽略解析失败的行
                            }
                          }
                          setGraphSchema((prev) =>
                            prev ? { ...prev, relation_types: parsed } : prev
                          );
                        }}
                        rows={6}
                        className="w-full px-3 py-2 border border-border rounded-md text-sm bg-card text-card-foreground focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                        placeholder={`{"name":"汇报给","source_types":["人员"],"target_types":["人员"]}`}
                      />
                    </div>
                  </div>

                  <div className="lg:w-[45%] xl:w-1/2 min-h-[380px] bg-muted/30 border border-border rounded-lg p-3 flex flex-col">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-muted-foreground">
                        类型层图谱预览
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        点击节点或边查看详情
                      </span>
                    </div>
                    <div className="flex-1 min-h-[320px]">
                      <GraphSchemaViz
                        entity_types={graphSchema.entity_types}
                        relation_types={graphSchema.relation_types}
                        loading={recommending || loadingGraphSchema}
                        onNodeClick={(entity) => setSelectedSchemaItem({ type: 'entity', data: entity })}
                        onEdgeClick={(relation) => setSelectedSchemaItem({ type: 'relation', data: relation })}
                      />
                    </div>
                    {selectedSchemaItem && (
                      <div className="mt-3 p-3 bg-card border border-border rounded-md text-xs space-y-1">
                        <div className="font-medium text-card-foreground">
                          {selectedSchemaItem.type === 'entity' ? '实体类型' : '关系类型'}：{selectedSchemaItem.data.name}
                        </div>
                        {selectedSchemaItem.data.description && (
                          <div className="text-muted-foreground">{selectedSchemaItem.data.description}</div>
                        )}
                        {selectedSchemaItem.type === 'entity' && selectedSchemaItem.data.examples && selectedSchemaItem.data.examples.length > 0 && (
                          <div className="text-muted-foreground">示例：{selectedSchemaItem.data.examples.join('、')}</div>
                        )}
                        {selectedSchemaItem.type === 'relation' && (
                          <>
                            {selectedSchemaItem.data.source_types && selectedSchemaItem.data.source_types.length > 0 && (
                              <div className="text-muted-foreground">源类型：{selectedSchemaItem.data.source_types.join('、')}</div>
                            )}
                            {selectedSchemaItem.data.target_types && selectedSchemaItem.data.target_types.length > 0 && (
                              <div className="text-muted-foreground">目标类型：{selectedSchemaItem.data.target_types.join('、')}</div>
                            )}
                          </>
                        )}
                        <button
                          onClick={() => setSelectedSchemaItem(null)}
                          className="mt-1 text-muted-foreground hover:text-card-foreground underline"
                        >
                          清除选择
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {graphTaskStatus && (
                  <div className="border border-border rounded-md p-3 bg-muted">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm font-medium text-card-foreground">
                        图谱任务：{graphTaskStatus.task_id}
                      </div>
                      <span
                        className={`text-xs font-medium ${
                          graphTaskStatus.status === 'completed'
                            ? 'text-green-600 dark:text-green-300'
                            : graphTaskStatus.status === 'failed'
                            ? 'text-red-600 dark:text-red-300'
                            : 'text-blue-600 dark:text-blue-300'
                        }`}
                      >
                        {graphTaskStatus.status === 'running'
                          ? '执行中'
                          : graphTaskStatus.status === 'completed'
                          ? '已完成'
                          : graphTaskStatus.status === 'failed'
                          ? '失败'
                          : '等待中'}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {graphTaskStatus.steps.map((step) => (
                        <div
                          key={step.name}
                          className={`text-xs px-2 py-1 rounded border ${
                            step.status === 'completed'
                              ? 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-900 text-green-700 dark:text-green-300'
                              : step.status === 'running'
                              ? 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300'
                              : step.status === 'failed'
                              ? 'bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-900 text-red-700 dark:text-red-300'
                              : 'bg-card border-border text-muted-foreground'
                          }`}
                        >
                          {STEP_LABELS[step.name] || step.name}
                        </div>
                      ))}
                    </div>
                    {graphTaskStatus.error && (
                      <p className="mt-2 text-xs text-red-600 dark:text-red-300">
                        {graphTaskStatus.error}
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Create directory modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg shadow-lg w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-card-foreground">新建目录</h3>
              <button
                onClick={() => setShowCreate(false)}
                className="text-muted-foreground hover:text-muted-foreground"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">上级目录</label>
                <select
                  value={createParentId ?? ''}
                  onChange={(e) =>
                    setCreateParentId(e.target.value === '' ? null : Number(e.target.value))
                  }
                  className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">根目录</option>
                  {flattenDirectories(tree).map((d) => (
                    <option key={d.id} value={d.id}>
                      {'　'.repeat(d.depth)}{d.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">目录名称</label>
                <input
                  type="text"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  required
                  maxLength={100}
                  className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="例如：产品更新日志"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">描述（可选）</label>
                <textarea
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  maxLength={500}
                  rows={3}
                  className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="目录用途说明"
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <label className="inline-flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createGraphragEnabled}
                      onChange={(e) => setCreateGraphragEnabled(e.target.checked)}
                      className="w-4 h-4 text-primary border-border rounded focus:ring-ring"
                    />
                    <span className="text-sm text-card-foreground">启用 GraphRAG</span>
                  </label>
                  <div className="relative group">
                    <HelpCircle className="w-4 h-4 text-muted-foreground cursor-help" />
                    <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 hidden group-hover:block w-72 p-3 text-xs bg-card border border-border rounded-lg shadow-lg z-50">
                      <p className="font-medium text-card-foreground mb-1">适合场景</p>
                      <ul className="list-disc list-inside text-muted-foreground mb-2 space-y-0.5">
                        <li>组织架构、汇报关系文档</li>
                        <li>产品模块依赖、调用关系</li>
                        <li>故障根因与影响面分析</li>
                      </ul>
                      <p className="font-medium text-card-foreground mb-1">不适合场景</p>
                      <ul className="list-disc list-inside text-muted-foreground space-y-0.5">
                        <li>纯 FAQ 列表</li>
                        <li>彼此独立的短篇文章</li>
                      </ul>
                    </div>
                  </div>
                </div>
                {createGraphragEnabled && (
                  <p className="text-xs text-muted-foreground">
                    保存后可在知识库设置页配置 schema 并触发图谱构建。
                  </p>
                )}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creating || !createName.trim()}
                  className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                >
                  {creating ? '创建中...' : '创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Upload modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg shadow-lg w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-card-foreground">上传文件</h3>
              <button
                onClick={() => setShowUpload(false)}
                className="text-muted-foreground hover:text-muted-foreground"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">目标目录</label>
                <select
                  value={uploadDirId ?? ''}
                  onChange={(e) => setUploadDirId(Number(e.target.value))}
                  className="w-full px-3 py-2 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">请选择目录</option>
                  {flattenDirectories(tree).map((d) => (
                    <option key={d.id} value={d.id}>
                      {'　'.repeat(d.depth)}{d.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-card-foreground mb-1">选择文件</label>
                <input
                  type="file"
                  accept=".md,.json,.csv,.txt,.pdf,.docx,.xlsx"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  required
                  className="w-full text-sm text-muted-foreground file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-muted file:text-card-foreground hover:file:bg-muted-foreground/20"
                />
                <p className="mt-1 text-xs text-muted-foreground">支持 PDF（扫描件自动 OCR 识别）/ Word (.docx) / Excel (.xlsx) / Markdown / JSON / CSV / TXT</p>
                <p className="mt-1 text-xs text-muted-foreground">Word 页眉页脚不纳入索引；含公式的 Excel 请先在 Excel/WPS 中保存一次再上传</p>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowUpload(false)}
                  className="px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadFile || uploadDirId === null}
                  className="px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md hover:opacity-90 disabled:opacity-50"
                >
                  {uploading ? '上传中...' : '上传'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {logFile && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg shadow-lg w-full max-w-2xl max-h-[80vh] flex flex-col p-0">
            <div className="px-5 py-4 border-b border-border flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-card-foreground">{logFile.original_name} 索引日志</h3>
                <p className="text-xs text-muted-foreground mt-0.5">任务 ID: {logTaskId}</p>
              </div>
              <button
                onClick={() => setLogFile(null)}
                className="text-muted-foreground hover:text-muted-foreground"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-5 space-y-3">
              {logEvents.length === 0 && (
                <div className="text-sm text-muted-foreground text-center py-8">
                  {logConnected ? '等待日志...' : '正在连接日志流...'}
                </div>
              )}
              {logEvents.map((ev) => (
                <div
                  key={`${ev.step}-${ev.timestamp}`}
                  className={`flex items-start gap-3 text-sm p-3 rounded border ${
                    ev.status === 'completed'
                      ? 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-900'
                      : ev.status === 'failed'
                      ? 'bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-900'
                      : ev.status === 'running'
                      ? 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-900'
                      : 'bg-muted border-border'
                  }`}
                >
                  <div className="mt-0.5">
                    {ev.status === 'completed' && <CheckCircle className="w-4 h-4 text-green-600 dark:text-green-300" />}
                    {ev.status === 'failed' && <XCircle className="w-4 h-4 text-red-600 dark:text-red-300" />}
                    {ev.status === 'running' && <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-300 animate-spin" />}
                    {ev.status === 'pending' && <Clock className="w-4 h-4 text-muted-foreground" />}
                  </div>
                  <div className="flex-1">
                    <div className="font-medium text-card-foreground">
                      {STEP_LABELS[ev.step] || ev.step}
                    </div>
                    {ev.log && <div className="text-muted-foreground mt-0.5">{ev.log}</div>}
                    {ev.duration_ms !== undefined && (
                      <div className="text-xs text-muted-foreground mt-1">耗时 {ev.duration_ms} ms</div>
                    )}
                  </div>
                </div>
              ))}
              {logError && (
                <div className="p-3 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-900 rounded-md">
                  {logError}
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-border flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm">
                {logStatus === 'running' && <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-300 animate-spin" />}
                {logStatus === 'completed' && <CheckCircle className="w-4 h-4 text-green-600 dark:text-green-300" />}
                {logStatus === 'failed' && <XCircle className="w-4 h-4 text-red-600 dark:text-red-300" />}
                <span
                  className={`font-medium ${
                    logStatus === 'completed'
                      ? 'text-green-700 dark:text-green-300'
                      : logStatus === 'failed'
                      ? 'text-red-700 dark:text-red-300'
                      : 'text-blue-700 dark:text-blue-300'
                  }`}
                >
                  {logStatus === 'running'
                    ? '执行中'
                    : logStatus === 'completed'
                    ? '已完成'
                    : logStatus === 'failed'
                    ? '失败'
                    : '等待中'}
                </span>
                <span className="text-xs text-muted-foreground">
                  {logConnected ? '已连接' : '未连接'}
                </span>
              </div>
              <button
                onClick={() => setLogFile(null)}
                className="px-4 py-2 text-sm font-medium text-card-foreground bg-card border border-border rounded-md hover:bg-muted"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
