import type React from 'react';
import { Info, X } from 'lucide-react';
import { Badge, Button, StatusDot } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { RunFlowNode } from '../../types/runFlow';
import {
  formatDateTime,
  formatDuration,
  formatMetadataValue,
  getRunFlowNodeKindLabel,
  getRunFlowStatusLabel,
  RUN_FLOW_STATUS_STYLE,
} from './utils';

interface RunFlowNodeDetailsProps {
  node?: RunFlowNode | null;
  onClose?: () => void;
}

export const RunFlowNodeDetails: React.FC<RunFlowNodeDetailsProps> = ({ node, onClose }) => {
  const { language, t } = useUiLanguage();

  if (!node) {
    return (
      <aside className="home-subpanel p-4 text-sm text-secondary-text" data-testid="run-flow-node-details-empty">
        <div className="flex items-center gap-2">
          <Info className="h-4 w-4 text-cyan" aria-hidden="true" />
          {t('runFlow.nodeDetails.empty')}
        </div>
      </aside>
    );
  }

  const style = RUN_FLOW_STATUS_STYLE[node.status] || RUN_FLOW_STATUS_STYLE.unknown;
  const metadata = Object.entries(node.metadata || {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
  const detailRows = [
    [t('runFlow.nodeDetails.kind'), getRunFlowNodeKindLabel(node.kind, t)],
    [t('runFlow.nodeDetails.provider'), node.provider || t('runFlow.valueUnavailable')],
    [t('runFlow.nodeDetails.duration'), formatDuration(node.durationMs, t)],
    [t('runFlow.nodeDetails.attempts'), node.attempts ? String(node.attempts) : t('runFlow.valueUnavailable')],
    [t('runFlow.nodeDetails.recordCount'), typeof node.recordCount === 'number' ? String(node.recordCount) : t('runFlow.valueUnavailable')],
    [t('runFlow.nodeDetails.startedAt'), formatDateTime(node.startedAt, language, t)],
    [t('runFlow.nodeDetails.endedAt'), formatDateTime(node.endedAt, language, t)],
  ];

  return (
    <aside className="home-subpanel p-4" data-testid="run-flow-node-details">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-uppercase">{t('runFlow.nodeDetails.title')}</p>
          <h3 className="mt-1 truncate text-base font-semibold text-foreground">{node.label}</h3>
          {node.message ? (
            <p className="mt-2 text-sm leading-6 text-secondary-text">{node.message}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={style.badge} className="gap-1.5 shadow-none">
            <StatusDot tone={style.tone} pulse={style.pulse} className="h-1.5 w-1.5" />
            {getRunFlowStatusLabel(node.status, t)}
          </Badge>
          {onClose ? (
            <Button
              type="button"
              variant="ghost"
              size="xsm"
              onClick={onClose}
              aria-label={t('runFlow.nodeDetails.close')}
              className="h-7 w-7 px-0"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        {detailRows.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
            <dt className="text-xs text-muted-text">{label}</dt>
            <dd className="mt-1 break-words text-foreground">{value}</dd>
          </div>
        ))}
      </dl>

      {metadata.length > 0 ? (
        <div className="mt-4">
          <p className="label-uppercase">{t('runFlow.nodeDetails.metadata')}</p>
          <dl className="mt-2 grid grid-cols-1 gap-2 text-sm">
            {metadata.map(([key, value]) => (
              <div key={key} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                <dt className="font-mono text-xs text-muted-text">{key}</dt>
                <dd className="mt-1 break-words text-foreground">{formatMetadataValue(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </aside>
  );
};
