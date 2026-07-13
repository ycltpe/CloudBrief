'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { useTheme } from 'next-themes';
import { Loader2, Network } from 'lucide-react';

export interface GraphEntityType {
  name: string;
  description?: string;
  examples?: string[];
}

export interface GraphRelationType {
  name: string;
  description?: string;
  source_types?: string[];
  target_types?: string[];
}

interface GraphSchemaVizProps {
  entity_types: GraphEntityType[];
  relation_types: GraphRelationType[];
  onNodeClick?: (entity: GraphEntityType) => void;
  onEdgeClick?: (relation: GraphRelationType) => void;
  loading?: boolean;
  className?: string;
}

const ENTITY_PALETTE = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#8b5cf6', // violet
  '#f43f5e', // rose
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#6366f1', // indigo
];

function stringHash(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function pickColor(name: string): string {
  return ENTITY_PALETTE[stringHash(name) % ENTITY_PALETTE.length];
}

function readCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function buildElements(
  entity_types: GraphEntityType[],
  relation_types: GraphRelationType[],
): cytoscape.ElementDefinition[] {
  const entityMap = new Map<string, GraphEntityType>();
  for (const et of entity_types) {
    if (!et.name) continue;
    entityMap.set(et.name, et);
  }

  const referencedTypes = new Set<string>();
  const edgeTuples: Array<{
    source: string;
    target: string;
    relation: GraphRelationType;
    key: string;
  }> = [];

  for (const rt of relation_types) {
    if (!rt.name) continue;
    const sources = rt.source_types?.filter(Boolean) ?? [];
    const targets = rt.target_types?.filter(Boolean) ?? [];
    if (sources.length === 0 || targets.length === 0) continue;

    for (const source of sources) {
      for (const target of targets) {
        referencedTypes.add(source);
        referencedTypes.add(target);
        const key = `${source}::${rt.name}::${target}`;
        if (edgeTuples.some((e) => e.key === key)) continue;
        edgeTuples.push({ source, target, relation: rt, key });
      }
    }
  }

  const connectedTypes = new Set<string>();
  for (const e of edgeTuples) {
    connectedTypes.add(e.source);
    connectedTypes.add(e.target);
  }

  const elements: cytoscape.ElementDefinition[] = [];

  // Known entity types
  entityMap.forEach((et, name) => {
    elements.push({
      data: {
        id: name,
        label: name,
        color: pickColor(name),
        entity: et,
        isolated: !connectedTypes.has(name),
      },
    });
  });

  // Referenced but missing entity types (schema inconsistency)
  referencedTypes.forEach((name) => {
    if (entityMap.has(name)) return;
    elements.push({
      data: {
        id: name,
        label: `${name} (未定义)`,
        color: '#94a3b8',
        entity: { name, description: '该类型被关系引用，但在实体类型中未定义' },
        isolated: false,
        missing: true,
      },
    });
  });

  // Edges
  for (const e of edgeTuples) {
    elements.push({
      data: {
        id: e.key,
        source: e.source,
        target: e.target,
        label: e.relation.name,
        relation: e.relation,
      },
    });
  }

  return elements;
}

export default function GraphSchemaViz({
  entity_types,
  relation_types,
  onNodeClick,
  onEdgeClick,
  loading,
  className = '',
}: GraphSchemaVizProps) {
  const { resolvedTheme } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const onNodeClickRef = useRef(onNodeClick);
  const onEdgeClickRef = useRef(onEdgeClick);
  const [isReady, setIsReady] = useState(false);

  const elements = useMemo(
    () => buildElements(entity_types, relation_types),
    [entity_types, relation_types],
  );

  const hasData = entity_types.length > 0;

  // Keep callback refs up to date without re-binding cytoscape events.
  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    onEdgeClickRef.current = onEdgeClick;
  }, [onEdgeClick]);

  // Initialize cytoscape instance once.
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: [],
      minZoom: 0.3,
      maxZoom: 2.5,
      wheelSensitivity: 0.25,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      autoungrabify: true,
    });

    cy.on('tap', 'node', (evt) => {
      const target = evt.target as unknown as cytoscape.NodeSingular;
      const entity = target.data('entity') as GraphEntityType | undefined;
      if (entity && onNodeClickRef.current) onNodeClickRef.current(entity);
    });

    cy.on('tap', 'edge', (evt) => {
      const target = evt.target as unknown as cytoscape.EdgeSingular;
      const relation = target.data('relation') as GraphRelationType | undefined;
      if (relation && onEdgeClickRef.current) onEdgeClickRef.current(relation);
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        cy.elements().unselect();
      }
    });

    cyRef.current = cy;
    setIsReady(true);

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // Update elements when data changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !isReady) return;

    cy.elements().remove();
    if (elements.length > 0) {
      cy.add(elements);
      cy.layout({
        name: 'breadthfirst',
        directed: true,
        padding: 16,
        spacingFactor: 1.2,
        animate: true,
        animationDuration: 250,
        fit: true,
      }).run();
    }
  }, [elements, isReady]);

  // Update stylesheet when theme changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !isReady) return;

    const isDark = resolvedTheme === 'dark';
    const foreground = readCssVar('--foreground', isDark ? '#f8fafc' : '#0f172a');
    const border = readCssVar('--border', isDark ? '#1e293b' : '#e2e8f0');
    const primary = readCssVar('--primary', isDark ? '#3b82f6' : '#2563eb');
    const mutedForeground = readCssVar('--muted-foreground', isDark ? '#94a3b8' : '#64748b');
    const background = readCssVar('--background', isDark ? '#020617' : '#f8fafc');

    cy.style()
      .clear()
      .fromJson([
        {
          selector: 'core',
          style: {
            'active-bg-color': primary,
            'selection-box-border-color': primary,
            'selection-box-color': primary,
          },
        },
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            label: 'data(label)',
            color: foreground,
            'font-size': '12px',
            'font-weight': '500',
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'text-max-width': '90px',
            width: '40px',
            height: '40px',
            'border-width': 2,
            'border-color': border,
            'border-opacity': 1,
            'transition-property': 'background-color, border-color, border-width',
            'transition-duration': '0.2s',
          },
        },
        {
          selector: 'node[missing]',
          style: {
            'background-color': '#94a3b8',
            'border-style': 'dashed',
            'border-color': mutedForeground,
            'font-size': '10px',
          },
        },
        {
          selector: 'node[isolated]',
          style: {
            'border-style': 'dashed',
            'border-color': mutedForeground,
            'background-opacity': 0.65,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 3,
            'border-color': primary,
          },
        },
        {
          selector: 'edge',
          style: {
            width: 2,
            'line-color': border,
            'target-arrow-color': border,
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': '10px',
            'font-weight': '500',
            color: mutedForeground,
            'text-background-color': background,
            'text-background-opacity': 1,
            'text-background-shape': 'roundrectangle',
            'text-background-padding': '3px',
          },
        },
        {
          selector: 'edge:selected',
          style: {
            'line-color': primary,
            'target-arrow-color': primary,
            'source-arrow-color': primary,
            width: 3,
          },
        },
      ])
      .update();
  }, [resolvedTheme, isReady]);

  const showOverlay = loading || !hasData;

  return (
    <div className={`relative w-full h-full min-h-[280px] ${className}`}>
      <div ref={containerRef} className="absolute inset-0" />

      {showOverlay && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/80 backdrop-blur-sm z-10">
          {loading ? (
            <>
              <Loader2 className="w-6 h-6 text-primary animate-spin mb-2" />
              <span className="text-sm text-muted-foreground">推荐 schema 中...</span>
            </>
          ) : (
            <>
              <Network className="w-8 h-8 text-muted-foreground mb-2" />
              <span className="text-sm text-muted-foreground">暂无 schema 数据</span>
              <span className="text-xs text-muted-foreground mt-1">
                点击「自动推荐 schema」生成类型层图谱
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
