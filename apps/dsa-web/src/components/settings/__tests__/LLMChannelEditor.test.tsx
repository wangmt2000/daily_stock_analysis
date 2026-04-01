import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LLMChannelEditor } from '../LLMChannelEditor';

vi.mock('../../../api/systemConfig', () => ({
  systemConfigApi: {
    update: vi.fn(),
    testLLMChannel: vi.fn(),
  },
}));

describe('LLMChannelEditor', () => {
  it('renders API Key input with controlled visibility', async () => {
    render(
      <LLMChannelEditor
        items={[
          { key: 'LLM_CHANNELS', value: 'openai' },
          { key: 'LLM_OPENAI_PROTOCOL', value: 'openai' },
          { key: 'LLM_OPENAI_BASE_URL', value: 'https://api.openai.com/v1' },
          { key: 'LLM_OPENAI_ENABLED', value: 'true' },
          { key: 'LLM_OPENAI_API_KEY', value: 'secret-key' },
          { key: 'LLM_OPENAI_MODELS', value: 'gpt-4o-mini' },
        ]}
        configVersion="v1"
        maskToken="******"
        onSaved={() => {}}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /OpenAI 官方/i }));

    const input = await screen.findByLabelText('API Key');
    expect(input).toHaveAttribute('type', 'password');

    fireEvent.click(screen.getByRole('button', { name: '显示内容' }));
    expect(input).toHaveAttribute('type', 'text');
  });

  it('keeps minimax-prefixed models in runtime selections', () => {
    render(
      <LLMChannelEditor
        items={[
          { key: 'LLM_CHANNELS', value: 'openai' },
          { key: 'LLM_OPENAI_PROTOCOL', value: 'openai' },
          { key: 'LLM_OPENAI_BASE_URL', value: 'https://api.example.com/v1' },
          { key: 'LLM_OPENAI_ENABLED', value: 'true' },
          { key: 'LLM_OPENAI_API_KEY', value: 'secret-key' },
          { key: 'LLM_OPENAI_MODELS', value: 'minimax/MiniMax-M1' },
        ]}
        configVersion="v1"
        maskToken="******"
        onSaved={() => {}}
      />
    );

    const primaryModelSelect = screen.getByRole('combobox', { name: '主模型' });
    const agentModelSelect = screen.getByRole('combobox', { name: 'Agent 主模型' });
    const visionModelSelect = screen.getByRole('combobox', { name: 'Vision 模型' });

    expect(within(primaryModelSelect).getByRole('option', { name: 'minimax/MiniMax-M1' })).toBeInTheDocument();
    expect(within(agentModelSelect).getByRole('option', { name: 'minimax/MiniMax-M1' })).toBeInTheDocument();
    expect(within(visionModelSelect).getByRole('option', { name: 'minimax/MiniMax-M1' })).toBeInTheDocument();
  });
});
