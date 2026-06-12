import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from '../../../api/analysis';
import { historyApi } from '../../../api/history';
import type { RunFlowSnapshot } from '../../../types/runFlow';
import { RunFlowPanel } from '../RunFlowPanel';

vi.mock('../../../api/analysis', () => ({
  analysisApi: {
    getTaskFlow: vi.fn(),
  },
}));

vi.mock('../../../api/history', () => ({
  historyApi: {
    getRecordFlow: vi.fn(),
  },
}));

const snapshot: RunFlowSnapshot = {
  taskId: 'task-1',
  traceId: 'trace-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  status: 'degraded',
  generatedAt: '2026-06-08T08:00:00Z',
  summary: {
    elapsedMs: 3250,
    failedAttempts: 1,
    fallbackCount: 1,
    model: 'DeepSeek',
    dataSourceCount: 2,
    eventCount: 3,
  },
  lanes: [
    { id: 'entry', label: '入口', order: 1 },
    { id: 'data_source', label: '数据来源', order: 2 },
    { id: 'analysis', label: '分析引擎', order: 3 },
    { id: 'artifact', label: '产物', order: 4 },
  ],
  nodes: [
    {
      id: 'request',
      lane: 'entry',
      kind: 'entry',
      label: '用户请求',
      status: 'success',
      message: '任务请求已创建',
    },
    {
      id: 'news',
      lane: 'data_source',
      kind: 'data_source',
      label: '新闻舆情',
      provider: 'AkShare',
      status: 'fallback',
      durationMs: 1200,
      attempts: 2,
      recordCount: 8,
      message: '主数据源失败后降级成功',
      metadata: {
        fallbackFrom: 'Tushare',
        fallbackTo: 'AkShare',
      },
    },
    {
      id: 'llm',
      lane: 'analysis',
      kind: 'model',
      label: 'LLM 生成',
      provider: 'DeepSeek',
      status: 'success',
      durationMs: 1800,
    },
  ],
  edges: [
    {
      id: 'request-news',
      from: 'request',
      to: 'news',
      kind: 'control',
      status: 'success',
      label: '调度',
    },
    {
      id: 'news-llm',
      from: 'news',
      to: 'llm',
      kind: 'fallback',
      status: 'fallback',
      label: '降级输入',
    },
  ],
  events: [
    {
      id: 'evt-1',
      timestamp: '2026-06-08T08:00:01Z',
      severity: 'info',
      type: 'task_created',
      nodeId: 'request',
      title: '任务创建',
    },
    {
      id: 'evt-2',
      timestamp: '2026-06-08T08:00:02Z',
      severity: 'warning',
      type: 'provider_fallback',
      nodeId: 'news',
      title: '新闻数据源降级',
      message: '重试后切换数据源',
    },
  ],
};

describe('RunFlowPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state while the snapshot request is pending', () => {
    vi.mocked(analysisApi.getTaskFlow).mockReturnValue(new Promise(() => undefined));

    render(<RunFlowPanel source={{ type: 'task', taskId: 'task-1' }} />);

    expect(screen.getByTestId('run-flow-panel-loading')).toBeInTheDocument();
    expect(screen.getByText('正在加载运行流')).toBeInTheDocument();
  });

  it('renders an error state and reload action when the request fails', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockRejectedValue({
      response: {
        status: 404,
        data: { message: '运行流不存在' },
      },
    });

    render(<RunFlowPanel source={{ type: 'task', taskId: 'missing-task' }} />);

    expect(await screen.findByTestId('run-flow-panel-error')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  });

  it('renders an empty snapshot state when there are no nodes or events', async () => {
    vi.mocked(historyApi.getRecordFlow).mockResolvedValue({
      ...snapshot,
      nodes: [],
      edges: [],
      events: [],
      summary: { ...snapshot.summary, eventCount: 0 },
    });

    render(<RunFlowPanel source={{ type: 'history', recordId: 1 }} />);

    expect(await screen.findByText('暂无运行流细节')).toBeInTheDocument();
    expect(historyApi.getRecordFlow).toHaveBeenCalledWith(1);
  });

  it('renders a successful graph, event stream, and selectable node details', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    render(<RunFlowPanel source={{ type: 'task', taskId: 'task-1' }} title="贵州茅台运行流" />);

    expect(await screen.findByTestId('run-flow-panel')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台运行流')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-graph')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-events')).toBeInTheDocument();
    expect(await screen.findByTestId('run-flow-node-details')).toHaveTextContent('新闻舆情');

    fireEvent.click(screen.getByRole('button', { name: 'LLM 生成 节点，状态 成功' }));

    expect(screen.getByTestId('run-flow-node-details')).toHaveTextContent('LLM 生成');
    expect(screen.getByTestId('run-flow-node-details')).toHaveTextContent('DeepSeek');
  });

  it('does not update state after a pending request is cleaned up', async () => {
    let resolveSnapshot: (value: RunFlowSnapshot) => void = () => undefined;
    vi.mocked(analysisApi.getTaskFlow).mockReturnValue(new Promise((resolve) => {
      resolveSnapshot = resolve;
    }));

    const { unmount } = render(<RunFlowPanel source={{ type: 'task', taskId: 'task-1' }} />);
    unmount();

    await act(async () => {
      resolveSnapshot(snapshot);
    });

    expect(analysisApi.getTaskFlow).toHaveBeenCalledWith('task-1');
  });
});
