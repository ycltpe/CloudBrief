export interface User {
  id: number;
  username: string;
  role: 'admin' | 'qa' | 'user';
  created_at?: string | null;
}

export interface Citation {
  chunk_id: string;
  source_title: string;
  source_type: string;
  updated_at: string;
  content_summary: string;
}

export interface Source {
  chunk_id: string;
  title: string;
  type: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  sources?: Source[];
  is_refusal?: boolean;
  is_stale?: boolean;
  status?: string;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  citations: Citation[];
  is_refusal: boolean;
  is_stale: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  preview: string | null;
  updated_at: string | null;
}

export interface IndexStep {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  log?: string;
  created_at: string;
}

export interface IndexTaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  steps: IndexStep[];
  error?: string;
}

export interface EvalResultOut {
  id: number;
  question: string;
  answer?: string | null;
  ground_truth?: string | null;
  contexts_json: string;
  ragas_scores_json: string;
  reasoning_json: string;
  human_score?: number | null;
  human_note?: string | null;
  is_adopted: boolean;
  is_modified: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminEvalContext {
  chunk_id: string;
  source_title: string;
  source_type: string;
  content: string;
  updated_at?: string | null;
}

export interface AdminEvalResult {
  id: number;
  question: string;
  answer?: string | null;
  ground_truth?: string | null;
  contexts: AdminEvalContext[];
  ragas_scores: Record<string, number | string | null>;
  reasoning: Record<string, string>;
  human_score?: number | null;
  human_note?: string | null;
  is_adopted: boolean;
  is_modified: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminEvalListResponse {
  total: number;
  items: AdminEvalResult[];
}

export type KbAccessStatus = 'pending' | 'approved' | 'rejected';

export interface KbAccessRequest {
  id: number;
  kb_id: string;
  user_id: number;
  username?: string | null;
  status: KbAccessStatus;
  created_by?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface KbAccessListResponse {
  total: number;
  items: KbAccessRequest[];
}

export interface KbDirectory {
  id: number;
  name: string;
  description?: string | null;
  parent_id?: number | null;
  file_count: number;
  graphrag_enabled: boolean;
  children: KbDirectory[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface KbFile {
  id: number;
  directory_id: number;
  original_name: string;
  stored_name: string;
  size: number;
  mime_type?: string | null;
  status: 'uploaded' | 'indexing' | 'indexed' | 'failed';
  task_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DashboardIndexStatus {
  is_ready: boolean;
  active_collection?: string | null;
  bm25_index_path?: string | null;
  last_task_status: string;
  last_task_updated_at?: string | null;
}

export interface DashboardEvalScores {
  context_precision?: number | null;
  context_recall?: number | null;
  faithfulness?: number | null;
  answer_relevancy?: number | null;
}

export interface DashboardRecentTask {
  task_id: string;
  status: string;
  created_at?: string | null;
}

export interface DashboardGraphRagStatus {
  enabled_kb_count: number;
  total_kb_count: number;
  last_build_at?: string | null;
  last_build_entities?: number | null;
  last_build_relations?: number | null;
  last_build_error?: string | null;
  avg_query_duration_ms?: number | null;
}

export type DependencyStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface DashboardDependencyStatus {
  name: string;
  status: DependencyStatus;
  latency_ms?: number | null;
  message?: string | null;
}

export interface DashboardSystemHealth {
  status: DependencyStatus;
  dependencies: DashboardDependencyStatus[];
  checked_at?: string | null;
}

export interface AdminDashboardResponse {
  user_count: number;
  conversation_count_today: number;
  index_status: DashboardIndexStatus;
  latest_eval_scores: DashboardEvalScores;
  recent_tasks: DashboardRecentTask[];
  graph_rag_status: DashboardGraphRagStatus;
  system_health: DashboardSystemHealth;
}

export interface DashboardStatsResponse {
  user_count: number;
  conversation_count_today: number;
  index_status: DashboardIndexStatus;
  latest_eval_scores: DashboardEvalScores;
}

export interface DashboardEvalScoresResponse {
  latest_eval_scores: DashboardEvalScores;
}

export interface DashboardRecentTasksResponse {
  recent_tasks: DashboardRecentTask[];
}

export interface DashboardGraphRagResponse {
  graph_rag_status: DashboardGraphRagStatus;
}

export interface DashboardSystemHealthResponse {
  system_health: DashboardSystemHealth;
}
