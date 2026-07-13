export interface User {
  id: number;
  username: string;
  role: 'admin' | 'qa' | 'user';
  created_at?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export async function register(username: string, password: string, role: string = 'user') {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || '注册失败');
  }
  return res.json() as Promise<User>;
}

export async function login(username: string, password: string) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || '登录失败');
  }
  const data = (await res.json()) as LoginResponse;
  localStorage.setItem('access_token', data.access_token);
  return data;
}

export async function logout() {
  localStorage.removeItem('access_token');
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

export async function getCurrentUser(): Promise<User | null> {
  const token = getToken();
  if (!token) return null;
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: 'include',
  });
  if (!res.ok) {
    localStorage.removeItem('access_token');
    return null;
  }
  return res.json() as Promise<User>;
}

export async function authFetch(input: string | URL, init?: RequestInit) {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return fetch(input, {
    ...init,
    headers,
    credentials: 'include',
  });
}
