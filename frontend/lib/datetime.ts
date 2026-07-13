/**
 * 统一时间格式化工具，所有显示时间均按 Asia/Shanghai 时区处理。
 * 后端统一存 UTC ISO 字符串，前端负责按用户所在业务时区展示。
 */

const TIME_ZONE = 'Asia/Shanghai';

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  try {
    // 后端存的是 UTC，但 isoformat() 不带 Z；没有时区偏移的 ISO 字符串按 UTC 解析
    const normalized =
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
        ? value + 'Z'
        : value;
    const d = new Date(normalized);
    if (Number.isNaN(d.getTime())) return null;
    return d;
  } catch {
    return null;
  }
}

export function formatTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return '';
  return date.toLocaleTimeString('zh-CN', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatTimeSeconds(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return '';
  return date.toLocaleTimeString('zh-CN', {
    timeZone: TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatDate(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return '';
  return date.toLocaleDateString('zh-CN', {
    timeZone: TIME_ZONE,
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return '';
  return date.toLocaleString('zh-CN', {
    timeZone: TIME_ZONE,
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * 表格里常用的 YYYY-MM-DD HH:mm 格式（上海时区）。
 */
export function formatIsoDate(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return '-';
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`;
}

/**
 * 判断给定时间是否为上海时区的“今天”。
 */
export function isToday(value: string | Date | null | undefined): boolean {
  const date = toDate(value);
  if (!date) return false;
  const d = new Intl.DateTimeFormat('zh-CN', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).format(date);
  const n = new Intl.DateTimeFormat('zh-CN', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).format(new Date());
  return d === n;
}

/**
 * 聊天侧边栏：今天显示时间，其它显示日期。
 */
export function formatChatDateLabel(value: string | Date | null | undefined): string {
  if (isToday(value)) {
    return formatTime(value);
  }
  return formatDate(value);
}
