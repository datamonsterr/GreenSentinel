import { describe, it, expect } from 'vitest';
import {
  getLocalizedChatErrorMessage,
} from '@/lib/driver/chat-errors';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';

describe('chat-errors (F1)', () => {
  const tVi = (key: string) => (viMessages.driver.chat as any)[key] || key;
  const tEn = (key: string) => (enMessages.driver.chat as any)[key] || key;

  it('maps 404 error from chat-transport to localized text for vi and en', () => {
    const err = new Error('Driver chat stream failed with status 404');
    expect(getLocalizedChatErrorMessage(err, tVi)).toBe(
      'Không tìm thấy vụ việc hoặc bạn không có quyền xem vụ việc này'
    );
    expect(getLocalizedChatErrorMessage(err, tEn)).toBe(
      'This case was not found or you do not have access'
    );
  });

  it('maps 403 error to same 404/403 localized text', () => {
    const err = new Error('Driver chat stream failed with status 403');
    expect(getLocalizedChatErrorMessage(err, tVi)).toBe(
      'Không tìm thấy vụ việc hoặc bạn không có quyền xem vụ việc này'
    );
    expect(getLocalizedChatErrorMessage(err, tEn)).toBe(
      'This case was not found or you do not have access'
    );
  });

  it('maps 401 session expired error to localized text', () => {
    const err = new Error('Driver chat stream failed with status 401');
    expect(getLocalizedChatErrorMessage(err, tVi)).toBe(
      'Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại'
    );
    expect(getLocalizedChatErrorMessage(err, tEn)).toBe(
      'Session expired, please sign in again'
    );
  });

  it('maps 5xx status codes to assistant unavailable message', () => {
    const err500 = new Error('Driver chat stream failed with status 500');
    expect(getLocalizedChatErrorMessage(err500, tVi)).toBe(
      'Không kết nối được trợ lý, vui lòng thử lại'
    );
    expect(getLocalizedChatErrorMessage(err500, tEn)).toBe(
      'Could not reach the assistant, please try again'
    );

    const err502 = new Error('Driver chat stream failed with status 502');
    expect(getLocalizedChatErrorMessage(err502, tVi)).toBe(
      'Không kết nối được trợ lý, vui lòng thử lại'
    );
  });

  it('maps network errors or arbitrary developer English to assistant unavailable message without leaking English or status codes', () => {
    const networkErr = new TypeError('Failed to fetch');
    expect(getLocalizedChatErrorMessage(networkErr, tVi)).toBe(
      'Không kết nối được trợ lý, vui lòng thử lại'
    );
    expect(getLocalizedChatErrorMessage(networkErr, tEn)).toBe(
      'Could not reach the assistant, please try again'
    );

    const streamErr = new Error('Stream ended without a terminal event');
    expect(getLocalizedChatErrorMessage(streamErr, tVi)).toBe(
      'Không kết nối được trợ lý, vui lòng thử lại'
    );

    const emptyErr = new Error('Empty SSE stream');
    expect(getLocalizedChatErrorMessage(emptyErr, tVi)).toBe(
      'Không kết nối được trợ lý, vui lòng thử lại'
    );
  });

  it('never contains status code or English technical string in Vietnamese output', () => {
    const err = new Error('Driver chat stream failed with status 404');
    const msg = getLocalizedChatErrorMessage(err, tVi);
    expect(msg).not.toMatch(/404/);
    expect(msg).not.toMatch(/stream/i);
    expect(msg).not.toMatch(/failed/i);
  });
});
