import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8001';

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));

  // 前端消费逻辑按 SSE 设计，必须显式声明流式
  const payload = {
    ...body,
    stream: true,
  };

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };

  // 透传认证信息：Bearer Token 或 Cookie
  const authHeader = request.headers.get('authorization');
  if (authHeader) {
    headers.Authorization = authHeader;
  }
  const cookieHeader = request.headers.get('cookie');
  if (cookieHeader) {
    headers.Cookie = cookieHeader;
  }

  const backendRes = await fetch(`${BACKEND_URL}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  if (!backendRes.ok) {
    const text = await backendRes.text().catch(() => '请求失败');
    return NextResponse.json(
      { detail: text },
      { status: backendRes.status }
    );
  }

  if (!backendRes.body) {
    return NextResponse.json(
      { detail: '后端未返回可读取的响应流' },
      { status: 502 }
    );
  }

  return new Response(backendRes.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
