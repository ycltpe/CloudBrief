interface CardSkeletonProps {
  variant?: 'stats' | 'scores' | 'tasks' | 'graph-rag' | 'health';
}

export function CardSkeleton({ variant = 'stats' }: CardSkeletonProps) {
  if (variant === 'stats') {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="bg-card p-5 rounded-lg border border-border shadow-sm"
          >
            <div className="h-4 w-24 bg-muted rounded animate-pulse mb-4" />
            <div className="h-8 w-16 bg-muted rounded animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === 'scores') {
    return (
      <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
        <div className="h-4 w-40 bg-muted rounded animate-pulse mb-4" />
        <div className="grid grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="p-4 rounded-lg border border-border bg-muted">
              <div className="h-3 w-24 bg-muted-foreground/20 rounded animate-pulse mb-2" />
              <div className="h-7 w-12 bg-muted-foreground/20 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (variant === 'tasks') {
    return (
      <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
        <div className="h-4 w-40 bg-muted rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted"
            >
              <div className="space-y-2">
                <div className="h-3 w-32 bg-muted-foreground/20 rounded animate-pulse" />
                <div className="h-3 w-20 bg-muted-foreground/20 rounded animate-pulse" />
              </div>
              <div className="h-5 w-16 bg-muted-foreground/20 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (variant === 'graph-rag') {
    return (
      <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
        <div className="h-4 w-32 bg-muted rounded animate-pulse mb-4" />
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 rounded-lg border border-border bg-muted">
              <div className="h-3 w-24 bg-muted-foreground/20 rounded animate-pulse mb-2" />
              <div className="h-7 w-12 bg-muted-foreground/20 rounded animate-pulse" />
            </div>
            <div className="p-4 rounded-lg border border-border bg-muted">
              <div className="h-3 w-24 bg-muted-foreground/20 rounded animate-pulse mb-2" />
              <div className="h-7 w-16 bg-muted-foreground/20 rounded animate-pulse" />
            </div>
          </div>
          <div className="p-4 rounded-lg border border-border bg-muted">
            <div className="h-3 w-28 bg-muted-foreground/20 rounded animate-pulse mb-2" />
            <div className="h-4 w-40 bg-muted-foreground/20 rounded animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  // health
  return (
    <div className="bg-card p-6 rounded-lg border border-border shadow-sm">
      <div className="h-4 w-24 bg-muted rounded animate-pulse mb-4" />
      <div className="space-y-4">
        <div className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted">
          <div className="h-4 w-20 bg-muted-foreground/20 rounded animate-pulse" />
          <div className="h-5 w-16 bg-muted-foreground/20 rounded animate-pulse" />
        </div>
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted"
            >
              <div className="space-y-2">
                <div className="h-3 w-24 bg-muted-foreground/20 rounded animate-pulse" />
                <div className="h-3 w-16 bg-muted-foreground/20 rounded animate-pulse" />
              </div>
              <div className="h-5 w-14 bg-muted-foreground/20 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
