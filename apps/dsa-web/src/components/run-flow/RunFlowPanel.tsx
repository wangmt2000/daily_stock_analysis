import type React from 'react';
import { useMemo, useState } from 'react';
import { AlertCircle, RefreshCw, Workflow } from 'lucide-react';
import { Button, EmptyState, InlineAlert } from '../common';
import { useRunFlowSnapshot } from '../../hooks/useRunFlowSnapshot';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { RunFlowNode, RunFlowSnapshotSource } from '../../types/runFlow';
import { RunFlowEventList } from './RunFlowEventList';
import { RunFlowGraph } from './RunFlowGraph';
import { RunFlowNodeDetails } from './RunFlowNodeDetails';
import { RunFlowSummaryBar } from './RunFlowSummaryBar';

interface RunFlowPanelProps {
  source: RunFlowSnapshotSource | null;
  title?: string;
}

export const RunFlowPanel: React.FC<RunFlowPanelProps> = ({ source, title }) => {
  const { t } = useUiLanguage();
  const { snapshot, isLoading, error, refetch } = useRunFlowSnapshot({
    source,
    enabled: Boolean(source),
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null | false>(null);
  const defaultNodeId = useMemo(() => {
    if (!snapshot?.nodes.length) {
      return null;
    }

    const notable = snapshot.nodes.find((node) => (
      node.status === 'failed'
      || node.status === 'fallback'
      || node.status === 'degraded'
      || node.status === 'running'
      || node.status === 'cancel_requested'
    ));
    return notable?.id || snapshot.nodes[0].id;
  }, [snapshot]);
  const resolvedSelectedNodeId = useMemo(() => {
    if (selectedNodeId === false) {
      return null;
    }
    if (selectedNodeId && snapshot?.nodes.some((node) => node.id === selectedNodeId)) {
      return selectedNodeId;
    }
    return defaultNodeId;
  }, [defaultNodeId, selectedNodeId, snapshot]);
  const selectedNode = useMemo(
    () => snapshot?.nodes.find((node) => node.id === resolvedSelectedNodeId) || null,
    [resolvedSelectedNodeId, snapshot],
  );

  const selectNode = (node: RunFlowNode) => setSelectedNodeId(node.id);
  const selectNodeById = (nodeId: string) => {
    if (snapshot?.nodes.some((node) => node.id === nodeId)) {
      setSelectedNodeId(nodeId);
    }
  };

  if (isLoading && !snapshot) {
    return (
      <div className="flex min-h-[22rem] flex-col items-center justify-center text-center" data-testid="run-flow-panel-loading">
        <div className="home-spinner h-10 w-10 animate-spin border-[3px]" aria-hidden="true" />
        <h3 className="mt-4 text-base font-semibold text-foreground">{t('runFlow.loadingTitle')}</h3>
        <p className="mt-2 max-w-sm text-sm text-secondary-text">{t('runFlow.loadingDescription')}</p>
      </div>
    );
  }

  if (error && !snapshot) {
    return (
      <div className="space-y-4" data-testid="run-flow-panel-error">
        <InlineAlert
          variant="danger"
          title={error.title || t('runFlow.errorTitle')}
          message={error.message}
          className="rounded-xl px-3 py-2 text-sm shadow-none"
        />
        <Button type="button" variant="secondary" size="sm" onClick={() => void refetch()}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {t('runFlow.retry')}
        </Button>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <EmptyState
        title={t('runFlow.emptyTitle')}
        description={t('runFlow.emptyDescription')}
        icon={<Workflow className="h-6 w-6" aria-hidden="true" />}
        className="border-dashed"
      />
    );
  }

  const hasDetails = snapshot.nodes.length > 0 || snapshot.events.length > 0;

  return (
    <div className="space-y-3" data-testid="run-flow-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="label-uppercase">{t('runFlow.eyebrow')}</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-foreground">
            {title || t('runFlow.title')}
          </h2>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          isLoading={isLoading}
          loadingText={t('runFlow.refreshing')}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {t('runFlow.refresh')}
        </Button>
      </div>

      <RunFlowSummaryBar snapshot={snapshot} />

      {!hasDetails ? (
        <EmptyState
          title={t('runFlow.emptySnapshotTitle')}
          description={t('runFlow.emptySnapshotDescription')}
          icon={<AlertCircle className="h-6 w-6" aria-hidden="true" />}
          className="border-dashed"
        />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="min-w-0 space-y-3">
            <RunFlowGraph
              lanes={snapshot.lanes}
              nodes={snapshot.nodes}
              edges={snapshot.edges}
              selectedNodeId={resolvedSelectedNodeId}
              onSelectNode={selectNode}
            />
            <RunFlowNodeDetails node={selectedNode} onClose={() => setSelectedNodeId(false)} />
          </div>
          <div className="min-h-[20rem] 2xl:max-h-[calc(100vh-18rem)]">
            <RunFlowEventList
              events={snapshot.events}
              selectedNodeId={resolvedSelectedNodeId}
              onSelectNode={selectNodeById}
            />
          </div>
        </div>
      )}
    </div>
  );
};
