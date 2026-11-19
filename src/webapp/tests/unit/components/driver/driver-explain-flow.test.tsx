import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';
import { DriverExplainFlow } from '@/components/driver/chat/driver-explain-flow';
import { countByPhase, getTicketPhase, getTicketStep } from '@/lib/driver/tickets';

function setup(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  const onClose = vi.fn();
  render(
    <DriverI18nProvider locale="vi" messages={viMessages}>
      <DriverExplainFlow caseTitle="GPS giả" onClose={onClose} onSubmit={onSubmit} />
    </DriverI18nProvider>
  );
  return { onSubmit, onClose };
}

describe('DriverExplainFlow', () => {
  it('blocks step 1 without a reason, then validates min length, then submits', async () => {
    const { onSubmit } = setup();
    fireEvent.click(screen.getByTestId('explain-next'));
    expect(screen.getByTestId('explain-error')).toHaveTextContent('Vui lòng chọn một lý do');

    fireEvent.click(screen.getByTestId('explain-reason-Tech'));
    fireEvent.click(screen.getByTestId('explain-next'));

    fireEvent.change(screen.getByTestId('explain-detail'), { target: { value: 'ngắn' } });
    fireEvent.click(screen.getByTestId('explain-next'));
    expect(screen.getByTestId('explain-error')).toHaveTextContent('ít nhất 20 ký tự');

    fireEvent.change(screen.getByTestId('explain-detail'), {
      target: { value: 'GPS bị lỗi suốt buổi chiều hôm đó' },
    });
    fireEvent.click(screen.getByTestId('explain-next'));
    fireEvent.click(screen.getByTestId('explain-next')); // evidence optional
    expect(screen.getByTestId('explain-review')).toHaveTextContent('Lỗi GPS hoặc ứng dụng');

    fireEvent.click(screen.getByTestId('explain-submit'));
    await waitFor(() => expect(screen.getByTestId('driver-explain-done')).toBeInTheDocument());
    expect(onSubmit).toHaveBeenCalledWith(expect.stringContaining('GPS bị lỗi suốt buổi chiều'));
  });

  it('shows a plain error when sending fails', async () => {
    setup(vi.fn().mockRejectedValue(new Error('x')));
    fireEvent.click(screen.getByTestId('explain-reason-Other'));
    fireEvent.click(screen.getByTestId('explain-next'));
    fireEvent.change(screen.getByTestId('explain-detail'), {
      target: { value: 'Mô tả đủ dài để vượt ngưỡng tối thiểu' },
    });
    fireEvent.click(screen.getByTestId('explain-next'));
    fireEvent.click(screen.getByTestId('explain-next'));
    fireEvent.click(screen.getByTestId('explain-submit'));
    expect(await screen.findByTestId('explain-send-error')).toHaveTextContent('Không gửi được');
  });
});

describe('ticket phases', () => {
  it('classifies open / pending / closed and counts', () => {
    const items = [
      { dispute_status: 'pending_analyst_review' },
      { dispute_status: 'upheld' },
      { status: 'closed' },
      { status: 'open', dispute_status: 'not_disputed' },
    ];
    expect(getTicketPhase(items[0])).toBe('pending');
    expect(getTicketPhase(items[1])).toBe('closed');
    expect(getTicketStep(items[3])).toBe(2);
    expect(countByPhase(items)).toEqual({ all: 4, open: 1, pending: 1, closed: 2 });
  });
});
