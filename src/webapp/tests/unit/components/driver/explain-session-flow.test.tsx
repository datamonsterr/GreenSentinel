import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';
import { ApiError } from '@/lib/api-client';
import { DriverExplainFlow } from '@/components/driver/chat/driver-explain-flow';
import type { ExplainView } from '@/lib/driver-explain-client';

const client = vi.hoisted(() => ({
  get: vi.fn(),
  start: vi.fn(),
  saveDraft: vi.fn(),
  submit: vi.fn(),
  answer: vi.fn(),
  end: vi.fn(),
  editSummary: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock('@/lib/driver-explain-client', async (orig) => {
  const actual = await orig<typeof import('@/lib/driver-explain-client')>();
  return { ...actual, driverExplainClient: client };
});

const FIELDS = [
  { id: 'pickup_time', label: { vi: 'Giờ đón khách', en: 'Pickup time' }, type: 'time', required: true },
  { id: 'pickup_place', label: { vi: 'Bạn đón khách ở đâu?', en: 'Where?' }, type: 'location', required: true },
  { id: 'fare', label: { vi: 'Số tiền', en: 'Amount' }, type: 'amount', required: false },
  { id: 'kind', label: { vi: 'Loại', en: 'Kind' }, type: 'choice', required: false, options: [{ value: 'a', label: { vi: 'Phương án A', en: 'Option A' } }] },
  { id: 'tech_ticket', label: { vi: 'Mã ticket', en: 'Ticket' }, type: 'ticket', required: false },
  { id: 'evidence_photo', label: { vi: 'Ảnh', en: 'Photo' }, type: 'photo', required: false },
] as ExplainView['form']['fields'];

function view(over: Partial<ExplainView> = {}): ExplainView {
  return {
    session_id: 's1', state: 'draft', ui_status: 'form', mode: 'agent', reason: 'RealTrip',
    form: { form_version: 'RealTrip.1', has_question_set: true, fields: FIELDS, answers: {} },
    messages: [], current_question: null, waiting_for_help: false, can_end: false, summary: null,
    edits_left: 0, status_text: null, idle_timeout_minutes: 30, ...over,
  };
}

function setup(locale: 'vi' | 'en' = 'vi', onClose = vi.fn()) {
  render(
    <DriverI18nProvider locale={locale} messages={locale === 'vi' ? viMessages : enMessages}>
      <DriverExplainFlow caseId="c1" caseTitle="GPS giả" onClose={onClose} onSubmit={vi.fn().mockResolvedValue(undefined)} />
    </DriverI18nProvider>
  );
  return { onClose };
}

beforeEach(() => {
  Object.values(client).forEach((f) => f.mockReset());
});

describe('DriverExplainFlow v2 session', () => {
  it('resumes an existing agent session and renders typed fields with required marks', async () => {
    client.get.mockResolvedValue(view());
    setup();
    expect(await screen.findByTestId('explain-v2-form')).toBeInTheDocument();
    expect(screen.getByTestId('explain-field-pickup_time')).toHaveTextContent('Giờ đón khách');
    expect(screen.getByTestId('explain-field-pickup_time')).toHaveTextContent('*');
    expect(screen.getByTestId('explain-field-fare')).not.toHaveTextContent('*');
    expect(screen.getByTestId('explain-input-pickup_time')).toHaveAttribute('type', 'time');
    expect(screen.getByTestId('explain-input-kind').tagName).toBe('SELECT');
    expect(screen.getByTestId('explain-input-fare')).toHaveAttribute('inputmode', 'numeric');
  });

  it('renders English labels with the en locale', async () => {
    client.get.mockResolvedValue(view());
    setup('en');
    expect(await screen.findByTestId('explain-field-pickup_time')).toHaveTextContent('Pickup time');
  });

  it('autosaves draft answers after typing', async () => {
    client.get.mockResolvedValue(view());
    client.saveDraft.mockResolvedValue(view());
    setup();
    fireEvent.change(await screen.findByTestId('explain-input-pickup_place'), { target: { value: 'Cổng chợ X' } });
    await waitFor(() => expect(client.saveDraft).toHaveBeenCalledWith('c1', expect.objectContaining({ pickup_place: 'Cổng chợ X' })), { timeout: 3000 });
  });

  it('highlights missing and invalid fields from a 422', async () => {
    client.get.mockResolvedValue(view());
    client.submit.mockRejectedValue(
      new ApiError(422, JSON.stringify({ code: 'form_invalid', missing: ['pickup_time'], invalid: [{ field: 'fare', code: 'invalid_amount' }] }))
    );
    setup();
    fireEvent.change(await screen.findByTestId('explain-input-fare'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByTestId('explain-v2-submit'));
    await waitFor(() => expect(screen.getByTestId('explain-field-pickup_time')).toHaveAttribute('data-invalid', 'true'));
    expect(screen.getByTestId('explain-field-pickup_time')).toHaveTextContent('Vui lòng điền mục này');
    expect(screen.getByTestId('explain-field-fare')).toHaveTextContent('Số tiền không hợp lệ');
    expect(screen.getByTestId('explain-field-pickup_place')).not.toHaveAttribute('data-invalid');
  });

  it('shows the checking state, then moves to chat when the session advances', async () => {
    client.get
      .mockResolvedValueOnce(view())
      .mockResolvedValue(view({ state: 'asking', ui_status: 'chat', current_question: { seq: 3, text: 'Khách xuống lúc mấy giờ?' }, can_end: true, messages: [{ seq: 3, role: 'agent', text: 'Khách xuống lúc mấy giờ?' }] }));
    client.submit.mockResolvedValue(view({ state: 'investigating', ui_status: 'checking', status_text: { vi: 'Đang kiểm tra giải trình', en: 'Checking' } }));
    setup();
    fireEvent.change(await screen.findByTestId('explain-input-pickup_time'), { target: { value: '14:05' } });
    fireEvent.change(screen.getByTestId('explain-input-pickup_place'), { target: { value: 'X' } });
    fireEvent.click(screen.getByTestId('explain-v2-submit'));
    expect(await screen.findByTestId('explain-v2-checking')).toHaveTextContent('Đang kiểm tra giải trình');
    expect(await screen.findByTestId('explain-v2-chat', {}, { timeout: 6000 })).toBeInTheDocument();
  });

  it('chat: sends an answer, offers Kết thúc when can_end', async () => {
    const chat = view({ state: 'asking', ui_status: 'chat', current_question: { seq: 3, text: 'Khách xuống lúc mấy giờ?' }, can_end: true, messages: [{ seq: 3, role: 'agent', text: 'Khách xuống lúc mấy giờ?' }] });
    client.get.mockResolvedValue(chat);
    client.answer.mockResolvedValue(view({ ...chat, current_question: { seq: 5, text: 'Câu tiếp?' } }));
    client.end.mockResolvedValue(view({ state: 'summary', ui_status: 'summary', summary: 'Tóm tắt A', edits_left: 2 }));
    setup();
    expect(await screen.findByTestId('explain-v2-question')).toHaveTextContent('Khách xuống lúc mấy giờ?');
    fireEvent.change(screen.getByTestId('explain-v2-answer'), { target: { value: '14:30' } });
    fireEvent.click(screen.getByTestId('explain-v2-send'));
    await waitFor(() => expect(client.answer).toHaveBeenCalledWith('c1', '14:30', [], undefined));
    expect(await screen.findByText('Câu tiếp?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('explain-v2-end'));
    expect(await screen.findByTestId('explain-v2-summary')).toHaveTextContent('Tóm tắt A');
  });

  it('chat: waiting for help disables answering', async () => {
    client.get.mockResolvedValue(view({ state: 'asking', ui_status: 'chat', waiting_for_help: true, can_end: true, current_question: { seq: 3, text: 'Q?' }, messages: [] }));
    setup();
    expect(await screen.findByTestId('explain-v2-waiting')).toBeInTheDocument();
    expect(screen.queryByTestId('explain-v2-send')).not.toBeInTheDocument();
    expect(screen.getByTestId('explain-v2-end')).toBeInTheDocument();
  });

  it('summary: edit shows edits_left, confirm submits, then submitted state', async () => {
    const sum = view({ state: 'summary', ui_status: 'summary', summary: 'Bản tóm tắt', edits_left: 2 });
    client.get.mockResolvedValue(sum);
    client.editSummary.mockResolvedValue(view({ ...sum, summary: 'Bản sửa', edits_left: 1 }));
    client.confirm.mockResolvedValue(view({ state: 'submitted', ui_status: 'submitted', summary: 'Bản sửa', status_text: { vi: 'Đã gửi giải trình, VH sẽ phản hồi', en: 'Sent' } }));
    setup();
    expect(await screen.findByTestId('explain-v2-summary')).toHaveTextContent('Còn 2 lần sửa');
    fireEvent.click(screen.getByTestId('explain-v2-edit'));
    fireEvent.change(screen.getByTestId('explain-v2-edit-text'), { target: { value: 'Bản sửa' } });
    fireEvent.click(screen.getByTestId('explain-v2-edit-save'));
    await waitFor(() => expect(client.editSummary).toHaveBeenCalledWith('c1', 'Bản sửa'));
    expect(await screen.findByTestId('explain-v2-summary')).toHaveTextContent('Còn 1 lần sửa');
    fireEvent.click(screen.getByTestId('explain-v2-confirm'));
    expect(await screen.findByTestId('explain-v2-submitted')).toHaveTextContent('Đã gửi giải trình');
  });

  it('summary: no edit button when edits_left is 0', async () => {
    client.get.mockResolvedValue(view({ state: 'summary', ui_status: 'summary', summary: 'S', edits_left: 0 }));
    setup();
    await screen.findByTestId('explain-v2-summary');
    expect(screen.queryByTestId('explain-v2-edit')).not.toBeInTheDocument();
  });
});

describe('DriverExplainFlow legacy fallback with caseId', () => {
  it('falls back to the legacy wizard when there is no session and start reports mode=fallback', async () => {
    client.get.mockRejectedValue(new ApiError(404, 'Explanation session not found'));
    client.start.mockResolvedValue(view({ mode: 'fallback' }));
    setup();
    fireEvent.click(await screen.findByTestId('explain-reason-Tech'));
    fireEvent.click(screen.getByTestId('explain-next'));
    await waitFor(() => expect(client.start).toHaveBeenCalledWith('c1', 'Tech'));
    expect(await screen.findByTestId('explain-detail')).toBeInTheDocument();
  });

  it('falls back to legacy when start errors', async () => {
    client.get.mockRejectedValue(new ApiError(404, 'x'));
    client.start.mockRejectedValue(new ApiError(500, 'boom'));
    setup();
    fireEvent.click(await screen.findByTestId('explain-reason-Other'));
    fireEvent.click(screen.getByTestId('explain-next'));
    expect(await screen.findByTestId('explain-detail')).toBeInTheDocument();
  });

  it('enters the dynamic form when start returns mode=agent', async () => {
    client.get.mockRejectedValue(new ApiError(404, 'x'));
    client.start.mockResolvedValue(view());
    setup();
    fireEvent.click(await screen.findByTestId('explain-reason-RealTrip'));
    fireEvent.click(screen.getByTestId('explain-next'));
    expect(await screen.findByTestId('explain-v2-form')).toBeInTheDocument();
  });

  it('keeps legacy when the existing session is fallback mode', async () => {
    client.get.mockResolvedValue(view({ mode: 'fallback' }));
    setup();
    expect(await screen.findByTestId('explain-reason-Tech')).toBeInTheDocument();
  });
});
