'use client';

import Chat from '@/components/Chat';
import { authFetch } from '@/lib/auth';

export default function AdminChatPage() {
  return (
    <div className="h-full">
      <Chat
        fetcher={authFetch}
        showHeader={false}
        className="flex flex-row h-[calc(100vh-7rem)] bg-card border border-border rounded-lg shadow-sm overflow-hidden"
      />
    </div>
  );
}
