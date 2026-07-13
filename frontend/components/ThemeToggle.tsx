'use client';

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { Moon, Sun } from 'lucide-react';

interface ThemeToggleProps {
  className?: string;
}

export default function ThemeToggle({ className }: ThemeToggleProps) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <button
        type="button"
        aria-label="切换主题"
        className={`inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring ${className ?? ''}`}
      >
        <span className="h-5 w-5" />
      </button>
    );
  }

  const isDark = resolvedTheme === 'dark';
  const nextTheme = theme === 'system' ? (isDark ? 'light' : 'dark') : theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      onClick={() => setTheme(nextTheme)}
      aria-label={isDark ? '切换到明亮模式' : '切换到暗黑模式'}
      title={isDark ? '切换到明亮模式' : '切换到暗黑模式'}
      className={`inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring ${className ?? ''}`}
    >
      {isDark ? (
        <Sun className="h-5 w-5" aria-hidden="true" />
      ) : (
        <Moon className="h-5 w-5" aria-hidden="true" />
      )}
    </button>
  );
}
