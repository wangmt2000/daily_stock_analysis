import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RunFlowEdge, RunFlowLane, RunFlowNode } from '../../../types/runFlow';
import { RunFlowGraph } from '../RunFlowGraph';

const lanes: RunFlowLane[] = [
  { id: 'entry', label: '入口', order: 1 },
  { id: 'data_source', label: '数据来源', order: 2 },
  { id: 'analysis', label: '分析引擎', order: 3 },
];

const nodes: RunFlowNode[] = [
  {
    id: 'request',
    lane: 'entry',
    kind: 'entry',
    label: '用户请求',
    status: 'success',
  },
  {
    id: 'news',
    lane: 'data_source',
    kind: 'data_source',
    label: '新闻舆情',
    status: 'fallback',
    provider: 'AkShare',
  },
];

const edges: RunFlowEdge[] = [
  {
    id: 'request-news',
    from: 'request',
    to: 'news',
    kind: 'fallback',
    status: 'fallback',
    label: '降级输入',
  },
];

describe('RunFlowGraph', () => {
  it('renders auto-layered lanes, edge legend labels, and clickable nodes', () => {
    const onSelectNode = vi.fn();
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={nodes}
        edges={edges}
        onSelectNode={onSelectNode}
      />,
    );

    expect(screen.getByText('入口')).toBeInTheDocument();
    expect(screen.getByText('数据来源')).toBeInTheDocument();
    expect(screen.getByText('降级')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新闻舆情 节点，状态 Fallback' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '新闻舆情 节点，状态 Fallback' }));

    expect(onSelectNode).toHaveBeenCalledWith(expect.objectContaining({ id: 'news' }));
  });

  it('distributes fan-out edge anchors instead of routing every line through the node center', () => {
    const fanOutNodes: RunFlowNode[] = [
      {
        id: 'request',
        lane: 'entry',
        kind: 'entry',
        label: '用户请求',
        status: 'success',
      },
      {
        id: 'daily',
        lane: 'data_source',
        kind: 'data_source',
        label: '日线K线',
        status: 'success',
      },
      {
        id: 'quote',
        lane: 'data_source',
        kind: 'data_source',
        label: '实时行情',
        status: 'success',
      },
      {
        id: 'llm',
        lane: 'analysis',
        kind: 'model',
        label: 'LLM 生成',
        status: 'success',
      },
    ];
    const fanOutEdges: RunFlowEdge[] = [
      {
        id: 'request-daily',
        from: 'request',
        to: 'daily',
        kind: 'control',
        status: 'success',
      },
      {
        id: 'request-quote',
        from: 'request',
        to: 'quote',
        kind: 'control',
        status: 'success',
      },
      {
        id: 'daily-llm',
        from: 'daily',
        to: 'llm',
        kind: 'data',
        status: 'success',
      },
      {
        id: 'quote-llm',
        from: 'quote',
        to: 'llm',
        kind: 'data',
        status: 'success',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={fanOutNodes}
        edges={fanOutEdges}
      />,
    );

    const pathData = Array.from(container.querySelectorAll('svg g path'))
      .map((path) => path.getAttribute('d') || '');
    const fanOutStartYs = pathData
      .slice(0, 2)
      .map((path) => Number(path.match(/^M\s+\S+\s+(\S+)/)?.[1]));

    expect(new Set(fanOutStartYs).size).toBe(2);
    expect(screen.getByTestId('run-flow-node-daily')).toHaveAttribute('data-layout-row');
    expect(screen.getByTestId('run-flow-node-quote')).toHaveAttribute('data-layout-row');
  });

  it('routes same-lane vertical edges from card bottom to the next card top', () => {
    const verticalNodes: RunFlowNode[] = [
      {
        id: 'daily',
        lane: 'data_source',
        kind: 'data_source',
        label: '日线K线',
        status: 'success',
      },
      {
        id: 'quote',
        lane: 'data_source',
        kind: 'data_source',
        label: '实时行情',
        status: 'success',
      },
    ];
    const verticalEdges: RunFlowEdge[] = [
      {
        id: 'daily-quote',
        from: 'daily',
        to: 'quote',
        kind: 'control',
        status: 'success',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={verticalNodes}
        edges={verticalEdges}
      />,
    );

    const pathData = container.querySelector('svg g path')?.getAttribute('d') || '';
    const pathNumbers = pathData.match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
    const [startX, startY, curveStartX, , curveEndX, , endX, endY] = pathNumbers;
    const dailyNode = screen.getByTestId('run-flow-node-daily');
    const quoteNode = screen.getByTestId('run-flow-node-quote');
    const dailyBottom = parseFloat(dailyNode.style.top) + parseFloat(dailyNode.style.minHeight);
    const quoteTop = parseFloat(quoteNode.style.top);

    expect(startX).toBe(endX);
    expect(curveStartX).toBe(startX);
    expect(curveEndX).toBe(endX);
    expect(startY).toBeLessThan(endY);
    expect(startY).toBe(dailyBottom);
    expect(endY).toBe(quoteTop);
  });
});
