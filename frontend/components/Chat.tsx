'use client';

import { useEffect, useRef, useState } from 'react';
import { User, Bot, Send, Square, Paperclip, Sparkles, FileText, Workflow, Database, BookOpen, ChevronDown } from 'lucide-react';
import AnswerWithCitations from './AnswerWithCitations';
import CitationSources from './CitationSources';
import InlineMarkdown from './InlineMarkdown';
import { formatChatDateLabel } from '@/lib/datetime';
import { ChatMessage, ConversationSummary } from '@/lib/types';

interface KbInfo {
  kb_id: string;
  name: string;
  description?: string;
}

type Fetcher = (input: string | URL, init?: RequestInit) => Promise<Response>;

interface ChatProps {
  fetcher?: Fetcher;
  className?: string;
  showHeader?: boolean;
}

const defaultContainerClass =
  'flex flex-row h-[calc(100vh-2rem)] max-w-6xl mx-auto bg-card border border-border rounded-lg shadow-sm overflow-hidden';
const defaultFetcher: Fetcher = fetch;

const starterQuestions = [
  { icon: Sparkles, text: 'CloudBrief 支持哪些知识库格式？' },
  { icon: FileText, text: '如何排查索引构建失败？' },
  { icon: Workflow, text: '检索流程是怎么工作的？' },
  { icon: Database, text: '如何更新已有文档的索引？' },
];

export default function Chat({
  fetcher = defaultFetcher,
  className,
  showHeader = true,
}: ChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [kbList, setKbList] = useState<KbInfo[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string>('');
  const [kbDropdownOpen, setKbDropdownOpen] = useState(false);
  const kbDropdownRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 加载会话列表
  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetcher('/api/conversations');
        if (!res.ok) return;
        const data: ConversationSummary[] = await res.json();
        setConversations(data);
      } catch {
        // 忽略列表加载错误，保持右侧可用
      }
    };
    load();
  }, [fetcher]);

  // 加载用户可访问知识库列表
  useEffect(() => {
    const loadKbList = async () => {
      try {
        const res = await fetcher('/api/kb-access/accessible');
        if (!res.ok) return;
        const data: { items: KbInfo[] } = await res.json();
        setKbList(data.items || []);
      } catch {
        // 忽略加载错误
      }
    };
    loadKbList();
  }, [fetcher]);

  // 加载选中会话的历史
  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      setConversationId(null);
      return;
    }
    const load = async () => {
      try {
        const res = await fetcher(`/api/chat/${activeId}`);
        if (!res.ok) return;
        const data = await res.json();
        setConversationId(data.conversation_id);
        setMessages(
          (data.messages || []).map((m: any) => ({
            role: m.role,
            content: m.content,
            citations: m.citations || [],
            is_refusal: m.is_refusal,
          }))
        );
      } catch {
        // 忽略历史加载错误
      }
    };
    load();
  }, [activeId, fetcher]);

  // 新消息时自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 点击外部关闭知识库下拉框
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (kbDropdownRef.current && !kbDropdownRef.current.contains(event.target as Node)) {
        setKbDropdownOpen(false);
      }
    };
    if (kbDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [kbDropdownOpen]);

  // 输入变化时自动调整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const refreshConversations = async () => {
    try {
      const res = await fetcher('/api/conversations');
      if (!res.ok) return;
      const data: ConversationSummary[] = await res.json();
      setConversations(data);
    } catch {
      // 忽略刷新错误
    }
  };

  const stopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  const sendMessageWithText = async (text: string) => {
    if (!text || loading) return;
    const question = text;
    setInput('');
    setStreamError(null);

    const userMsg: ChatMessage = { role: 'user', content: question };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    // 先放入 assistant 占位消息，边收流边追加
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', citations: [], status: '已收到，我先查一下知识库…' },
    ]);

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    let finalConversationId: string | null = null;

    try {
      const res = await fetcher('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          conversation_id: activeId,
          question,
          ...(selectedKbId ? { kb_ids: [selectedKbId] } : {}),
        }),
        signal: abortController.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error?.message || '请求失败');
      }

      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error('无法读取响应流');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const lines = part.split('\n');
          let eventType = '';
          let data = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7);
            } else if (line.startsWith('data: ')) {
              data += line.slice(6);
            }
          }
          if (!eventType || !data) continue;

          const payload = JSON.parse(data);

          if (eventType === 'chunk') {
            finalConversationId = payload.conversation_id ?? finalConversationId;
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (next[idx]?.role === 'assistant') {
                next[idx] = {
                  ...next[idx],
                  content: next[idx].content + (payload.content || ''),
                  status: undefined,
                };
              }
              return next;
            });
          } else if (eventType === 'status') {
            finalConversationId = payload.conversation_id ?? finalConversationId;
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (next[idx]?.role === 'assistant' && !next[idx].content) {
                next[idx] = {
                  ...next[idx],
                  status: payload.message || next[idx].status,
                };
              }
              return next;
            });
          } else if (eventType === 'citations') {
            finalConversationId = payload.conversation_id ?? finalConversationId;
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (next[idx]?.role === 'assistant') {
                next[idx] = {
                  ...next[idx],
                  citations: payload.citations || [],
                  is_refusal: payload.is_refusal,
                  is_stale: payload.is_stale,
                  status: undefined,
                };
              }
              return next;
            });
          } else if (eventType === 'sources') {
            finalConversationId = payload.conversation_id ?? finalConversationId;
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (next[idx]?.role === 'assistant') {
                next[idx] = {
                  ...next[idx],
                  sources: payload.sources || [],
                };
              }
              return next;
            });
          } else if (eventType === 'done') {
            finalConversationId = payload.conversation_id ?? finalConversationId;
          } else if (eventType === 'error') {
            throw new Error(payload.message || '生成失败');
          }
        }
      }

      if (finalConversationId) {
        setConversationId(finalConversationId);
        setActiveId(finalConversationId);
        await refreshConversations();
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setStreamError('生成已中断');
        setMessages((prev) => {
          const next = [...prev];
          const idx = next.length - 1;
          if (next[idx]?.role === 'assistant') {
            next[idx] = {
              ...next[idx],
              content:
                next[idx].content || '生成已中断，点击下方的“重试”按钮继续。',
              is_refusal: true,
            };
          }
          return next;
        });
      } else {
        setStreamError(err.message || '请求失败');
        setMessages((prev) => {
          const next = [...prev];
          const idx = next.length - 1;
          if (next[idx]?.role === 'assistant') {
            next[idx] = {
              ...next[idx],
              content: err.message || '请求失败，请稍后重试。',
              is_refusal: true,
            };
          }
          return next;
        });
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  const sendMessage = () => {
    sendMessageWithText(input.trim());
  };

  const retryLastMessage = () => {
    const lastUserMsg = [...messages].reverse().find((m) => m.role === 'user');
    if (!lastUserMsg) return;
    // 移除因中断或失败产生的最后一条 assistant 消息
    setMessages((prev) => {
      const next = [...prev];
      while (next.length && next[next.length - 1].role === 'assistant') {
        next.pop();
      }
      return next;
    });
    setStreamError(null);
    sendMessageWithText(lastUserMsg.content);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const startNewConversation = () => {
    setActiveId(null);
    setConversationId(null);
    setMessages([]);
    setInput('');
    setStreamError(null);
    setEditingId(null);
    setEditValue('');
    stopStreaming();
  };

  const startEditing = (conv: ConversationSummary) => {
    setEditingId(conv.id);
    setEditValue(conv.title || '');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditValue('');
  };

  const saveTitle = async (conversationId: string) => {
    const title = editValue.trim();
    if (!title) {
      cancelEditing();
      return;
    }
    try {
      const res = await fetcher(`/api/conversations/${conversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || '保存失败');
      }
      await refreshConversations();
      cancelEditing();
    } catch (err: any) {
      // 可以在这里加 toast；暂时静默保留编辑态让用户重试
      console.error('保存标题失败', err);
    }
  };

  const handleEditKeyDown = (e: React.KeyboardEvent, conversationId: string) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveTitle(conversationId);
    } else if (e.key === 'Escape') {
      cancelEditing();
    }
  };

  const isEmpty = messages.length === 0 && !loading;

  return (
    <div className={className || defaultContainerClass}>
      {/* 左侧会话列表 */}
      <aside className="w-72 flex flex-col border-r bg-muted shrink-0">
        <div className="p-3 border-b bg-muted">
          <button
            onClick={startNewConversation}
            className="w-full flex items-center justify-center gap-1 px-3 py-2 text-sm font-medium text-primary bg-card border border-border rounded hover:bg-muted transition-colors"
          >
            <span>+</span>
            <span>新对话</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {conversations.map((conv) => {
            const isActive = activeId === conv.id;
            return (
              <div
                key={conv.id}
                onClick={() => setActiveId(conv.id)}
                className={`group relative w-full text-left px-3 py-2.5 rounded-md text-sm transition-colors cursor-pointer ${
                  isActive ? 'bg-card shadow-sm' : 'hover:bg-muted'
                }`}
              >
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-1 bg-primary rounded-r" />
                )}
                <div className="flex items-center justify-between gap-2">
                  {editingId === conv.id ? (
                    <input
                      autoFocus
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={() => saveTitle(conv.id)}
                      onKeyDown={(e) => handleEditKeyDown(e, conv.id)}
                      className="flex-1 text-sm px-1.5 py-0.5 border rounded focus:outline-none focus:ring-2 focus:ring-ring"
                      maxLength={50}
                    />
                  ) : (
                    <>
                      <span className="font-medium text-card-foreground truncate flex-1">
                        {conv.title || '新对话'}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditing(conv);
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-muted-foreground shrink-0"
                        title="编辑标题"
                      >
                        ✏️
                      </button>
                    </>
                  )}
                  <span className="text-xs text-muted-foreground shrink-0">
                    {formatChatDateLabel(conv.updated_at)}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground truncate mt-0.5 pr-4">
                  {conv.preview || '暂无消息'}
                </div>
              </div>
            );
          })}
          {conversations.length === 0 && (
            <div className="px-3 py-6 text-xs text-muted-foreground text-center">
              暂无历史会话
            </div>
          )}
        </div>
      </aside>

      {/* 右侧聊天窗口 */}
      <div className="flex flex-col flex-1 min-w-0 bg-chat-bg">
        {showHeader && (
          <div className="p-4 border-b border-border bg-card">
            <h1 className="text-lg font-semibold text-card-foreground">CloudBrief 支持副驾</h1>
            <p className="text-sm text-muted-foreground">基于知识库的 Enterprise RAG 问答助手</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {isEmpty && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
                <Bot className="w-6 h-6 text-primary" />
              </div>
              <h2 className="text-lg font-semibold text-card-foreground mb-1">
                有什么可以帮你的？
              </h2>
              <p className="text-sm text-muted-foreground mb-6">
                基于企业内部知识库，为你提供精准、可溯源的答案
              </p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              {/* Avatar */}
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground border border-border'
                }`}
              >
                {msg.role === 'user' ? (
                  <User className="w-4 h-4" />
                ) : (
                  <Bot className="w-4 h-4" />
                )}
              </div>

              {/* Message bubble */}
              <div
                className={`flex flex-col max-w-[85%] ${
                  msg.role === 'user' ? 'items-end' : 'items-start'
                }`}
              >
                <div
                  className={`relative px-4 py-3 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground rounded-2xl rounded-tr-sm'
                      : msg.is_refusal
                      ? 'bg-muted text-card-foreground rounded-2xl rounded-tl-sm'
                      : 'bg-muted text-card-foreground border border-border rounded-2xl rounded-tl-sm'
                  }`}
                >
                  {msg.role === 'assistant' ? (
                    <>
                      {!msg.content && msg.status ? (
                        <div
                          className="flex items-center gap-2 text-muted-foreground italic"
                          aria-live="polite"
                        >
                          <span className="inline-block w-2 h-2 bg-primary rounded-full animate-pulse" />
                          <span>{msg.status}</span>
                        </div>
                      ) : !msg.content ? (
                        <div className="text-muted-foreground">
                          {msg.is_refusal
                            ? '未在知识库中检索到与问题直接相关的内容，请尝试换种问法或联系管理员补充资料。'
                            : '抱歉，没有生成任何内容。'}
                        </div>
                      ) : (
                        <div className="relative inline">
                          <AnswerWithCitations answer={msg.content} citations={msg.citations || []} />
                          {loading && idx === messages.length - 1 && (
                            <span
                              className="inline-block w-[2px] h-[1em] bg-primary ml-0.5 align-middle animate-pulse"
                              aria-hidden="true"
                            />
                          )}
                        </div>
                      )}
                      {msg.content && msg.citations && msg.citations.length > 0 && (
                        <CitationSources citations={msg.citations} />
                      )}
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {msg.sources.map((s, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md bg-primary/10 text-primary"
                              title={s.chunk_id}
                            >
                              <BookOpen className="w-3 h-3" />
                              {s.title}
                            </span>
                          ))}
                        </div>
                      )}
                      {msg.is_stale && (
                        <div className="flex items-center gap-1.5 mt-3 text-xs text-yellow-800 bg-yellow-100 px-2.5 py-1.5 rounded-md dark:bg-yellow-950 dark:text-yellow-200">
                          <span>⚠️</span>
                          <span>该答案依据的来源较旧，请核对最新产品版本。</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <InlineMarkdown text={msg.content} />
                  )}
                </div>
              </div>
            </div>
          ))}

          {streamError && (
            <div className="flex justify-center">
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-yellow-900 bg-yellow-100 border border-yellow-200 rounded-md dark:bg-yellow-950 dark:text-yellow-200 dark:border-yellow-900">
                <span>⚠️ {streamError}</span>
                <button
                  onClick={retryLastMessage}
                  className="font-medium text-primary hover:opacity-80 underline"
                >
                  重试
                </button>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 快捷问题 */}
        {isEmpty && !loading && (
          <div className="px-4 pb-4 bg-card">
            <p className="text-sm text-muted-foreground mb-3 text-center">你可以这样问我：</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-2xl mx-auto">
              {starterQuestions.map((q, i) => {
                const Icon = q.icon;
                return (
                  <button
                    key={i}
                    onClick={() => sendMessageWithText(q.text)}
                    className="flex items-center gap-2 px-4 py-2 rounded-full border border-border text-sm text-muted-foreground bg-card hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
                  >
                    <Icon className="w-4 h-4" />
                    {q.text}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 输入区 */}
        <div className="border-t border-border bg-card p-4">
          {/* 知识库选择器 */}
          {kbList.length > 0 && (
            <div className="max-w-4xl mx-auto mb-2 flex items-center gap-2">
              <span className="text-xs text-muted-foreground">知识库：</span>
              <div className="relative" ref={kbDropdownRef}>
                <button
                  type="button"
                  onClick={() => setKbDropdownOpen((open) => !open)}
                  className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border border-border bg-card text-card-foreground hover:bg-muted transition-colors"
                >
                  <Database className="w-3 h-3" />
                  <span>{selectedKbId ? kbList.find((k) => k.kb_id === selectedKbId)?.name || '默认' : '默认（全部）'}</span>
                  <ChevronDown className={`w-3 h-3 transition-transform ${kbDropdownOpen ? 'rotate-180' : ''}`} />
                </button>
                {kbDropdownOpen && (
                  <div className="absolute bottom-full left-0 mb-1 w-48 rounded-md border border-border bg-popover shadow-md z-10">
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedKbId('');
                        setKbDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-xs hover:bg-muted transition-colors ${
                        selectedKbId === '' ? 'bg-primary/10 text-primary' : 'text-card-foreground'
                      }`}
                    >
                      默认（全部）
                    </button>
                    {kbList.map((kb) => (
                      <button
                        key={kb.kb_id}
                        type="button"
                        onClick={() => {
                          setSelectedKbId(kb.kb_id);
                          setKbDropdownOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2 text-xs hover:bg-muted transition-colors ${
                          selectedKbId === kb.kb_id ? 'bg-primary/10 text-primary' : 'text-card-foreground'
                        }`}
                      >
                        {kb.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="flex items-end gap-2 max-w-4xl mx-auto">
            <button
              className="p-2 rounded-lg text-muted-foreground hover:text-card-foreground hover:bg-muted transition-colors flex-shrink-0"
              title="上传文件（即将支持）"
              disabled
            >
              <Paperclip className="w-5 h-5" />
            </button>

            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入问题，例如：报表导出后无法打开怎么办？"
                disabled={loading}
                rows={1}
                className="w-full resize-none rounded-xl border border-border bg-card px-4 py-3 pr-12 text-sm text-card-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent disabled:bg-muted min-h-[44px] max-h-[200px]"
              />
            </div>

            {loading ? (
              <button
                onClick={stopStreaming}
                className="p-2.5 rounded-xl bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/50 transition-colors flex-shrink-0"
                title="停止生成"
              >
                <Square className="w-5 h-5 fill-current" />
              </button>
            ) : (
              <button
                onClick={sendMessage}
                disabled={!input.trim()}
                className="p-2.5 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                title="发送"
              >
                <Send className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
