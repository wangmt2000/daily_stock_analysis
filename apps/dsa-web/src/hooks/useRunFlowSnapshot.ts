import { useCallback, useEffect, useMemo, useState } from 'react';
import { analysisApi } from '../api/analysis';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import type { RunFlowSnapshot, RunFlowSnapshotSource } from '../types/runFlow';

interface UseRunFlowSnapshotOptions {
  source?: RunFlowSnapshotSource | null;
  enabled?: boolean;
}

interface UseRunFlowSnapshotResult {
  snapshot: RunFlowSnapshot | null;
  isLoading: boolean;
  error: ParsedApiError | null;
  refetch: () => Promise<void>;
}

type RunFlowRequestState = {
  requestKey: string;
  snapshot: RunFlowSnapshot | null;
  error: ParsedApiError | null;
};

const getSourceKey = (source?: RunFlowSnapshotSource | null): string => {
  if (!source) {
    return 'none';
  }
  return source.type === 'task'
    ? `task:${source.taskId}`
    : `history:${source.recordId}`;
};

const isUsableSource = (source?: RunFlowSnapshotSource | null): source is RunFlowSnapshotSource => {
  if (!source) {
    return false;
  }
  if (source.type === 'task') {
    return Boolean(source.taskId.trim());
  }
  return Number.isFinite(source.recordId);
};

export function useRunFlowSnapshot({
  source,
  enabled = true,
}: UseRunFlowSnapshotOptions): UseRunFlowSnapshotResult {
  const [requestState, setRequestState] = useState<RunFlowRequestState>({
    requestKey: 'none',
    snapshot: null,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const sourceKey = useMemo(() => getSourceKey(source), [source]);
  const sourceType = source?.type;
  const taskId = source?.type === 'task' ? source.taskId : '';
  const recordId = source?.type === 'history' ? source.recordId : null;
  const requestKey = `${sourceKey}:${reloadToken}`;
  const shouldLoad = enabled && isUsableSource(source);

  const refetch = useCallback(async () => {
    setReloadToken((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!shouldLoad || !sourceType) {
      return undefined;
    }

    let active = true;

    const request = sourceType === 'task'
      ? analysisApi.getTaskFlow(taskId)
      : historyApi.getRecordFlow(recordId ?? 0);

    request
      .then((result) => {
        if (active) {
          setRequestState({
            requestKey,
            snapshot: result,
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setRequestState({
            requestKey,
            snapshot: null,
            error: getParsedApiError(err),
          });
        }
      });

    return () => {
      active = false;
    };
  }, [recordId, requestKey, shouldLoad, sourceType, taskId]);

  const hasFreshState = shouldLoad && requestState.requestKey === requestKey;

  return {
    snapshot: hasFreshState ? requestState.snapshot : null,
    isLoading: shouldLoad && !hasFreshState,
    error: hasFreshState ? requestState.error : null,
    refetch,
  };
}
