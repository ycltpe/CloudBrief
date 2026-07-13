import type { Metadata } from 'next'
import { ThemeProvider } from './providers'
import './globals.css'

export const metadata: Metadata = {
  title: 'CloudBrief 支持副驾',
  description: 'Enterprise RAG 内部知识问答系统',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  )
}
