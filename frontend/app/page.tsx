import Chat from '@/components/Chat'
import IndexRebuildPanel from '@/components/IndexRebuildPanel'
import ThemeToggle from '@/components/ThemeToggle'

export default function Home() {
  return (
    <div className="min-h-screen p-4 md:p-6 bg-background">
      <header className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-semibold text-card-foreground">CloudBrief 支持副驾</h1>
          <p className="text-sm text-muted-foreground">Enterprise RAG 内部知识问答系统</p>
        </div>
        <ThemeToggle />
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-1">
          <IndexRebuildPanel />
        </div>
        <div className="lg:col-span-3">
          <Chat />
        </div>
      </div>
    </div>
  )
}
