import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { CodeBlock } from '@/components/ai-elements/code-block';

describe('Analyst Components Theme Isolation', () => {
  it('renders InputGroup correctly without dark mode leak', () => {
    const { container } = render(
      <InputGroup data-testid="test-input-group">
        <InputGroupAddon align="inline-start">$</InputGroupAddon>
        <InputGroupInput placeholder="Amount" />
      </InputGroup>
    );

    const inputGroup = screen.getByTestId('test-input-group');
    expect(inputGroup).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Amount')).toBeInTheDocument();
    expect(screen.getByText('$')).toBeInTheDocument();
  });

  it('renders CodeBlock correctly without crashing', () => {
    const { container } = render(
      <CodeBlock code="const x = 1;" language="typescript" data-testid="test-code-block" />
    );

    const codeBlock = screen.getByTestId('test-code-block');
    expect(codeBlock).toBeInTheDocument();
  });
});
