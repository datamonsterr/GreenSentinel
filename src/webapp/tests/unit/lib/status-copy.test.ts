import { describe, it, expect } from 'vitest';
import viMessages from '@/messages/vi.json';
import {
  formatShortCaseId,
  getStatusCopy,
  getDisputeStatusCopy,
  getCaseStatusCopy,
  getViolationCopy,
} from '@/lib/driver/status-copy';

describe('Driver status-copy module', () => {
  describe('formatShortCaseId', () => {
    it('strips common prefixes and formats last 4 alphanumeric characters uppercase', () => {
      expect(formatShortCaseId('case-test-101')).toBe('#T101');
      expect(formatShortCaseId('52af66c8ce0b4c62')).toBe('#4C62');
      expect(formatShortCaseId('c8e0b4c6-2')).toBe('#4C62');
      expect(formatShortCaseId('CASE_1234_ABCD')).toBe('#ABCD');
    });

    it('handles already prefixed "#" without duplicating "#"', () => {
      expect(formatShortCaseId('#case-101')).toBe('#101');
      expect(formatShortCaseId('#52af')).toBe('#52AF');
    });

    it('handles uppercase and lowercase strings properly', () => {
      expect(formatShortCaseId('err-02')).toBe('#RR02');
      expect(formatShortCaseId('vietnam')).toBe('#TNAM');
    });

    it('handles short or empty inputs gracefully', () => {
      expect(formatShortCaseId('ab')).toBe('#AB');
      expect(formatShortCaseId('')).toBe('#----');
      expect(formatShortCaseId(null)).toBe('#----');
      expect(formatShortCaseId(undefined)).toBe('#----');
    });

    it('produces different codes for distinct case IDs', () => {
      const code1 = formatShortCaseId('case-alpha-1234');
      const code2 = formatShortCaseId('case-beta-5678');
      expect(code1).not.toBe(code2);
      expect(code1).toBe('#1234');
      expect(code2).toBe('#5678');
    });

    it('formats a real UUIDv7 case id using the last 4 alphanumeric characters (deliberate: avoids collisions, not a unique digest)', () => {
      // Deliberate design: last-4 is a human-scannable short code, not a
      // collision-free identifier. Full disambiguation is via case_id/case_code.
      expect(formatShortCaseId('018f2f4e-a000-7000-8000-000000001234')).toBe('#1234');
    });
  });

  describe('getStatusCopy - known dispute statuses', () => {
    it('maps "not_disputed" to plain language in vi and en', () => {
      const vi = getDisputeStatusCopy('not_disputed', 'vi');
      expect(vi.label).toBe('Chưa khiếu nại');
      expect(vi.explanation).toBeTruthy();

      const en = getDisputeStatusCopy('not_disputed', 'en');
      expect(en.label).toBe('Not disputed');
      expect(en.explanation).toBeTruthy();
    });

    it('maps "in_dispute" / "driver_disputed"', () => {
      const vi = getDisputeStatusCopy('in_dispute', 'vi');
      expect(vi.label).toBe('Đang đối soát');
      const en = getDisputeStatusCopy('in_dispute', 'en');
      expect(en.label).toBe('In dispute');
    });

    it('maps "auto_dismissed" and "AUTO_DISMISSED"', () => {
      const viLower = getDisputeStatusCopy('auto_dismissed', 'vi');
      const viUpper = getDisputeStatusCopy('AUTO_DISMISSED', 'vi');
      expect(viLower.label).toBe('Miễn trừ tự động');
      expect(viUpper.label).toBe('Miễn trừ tự động');

      const en = getDisputeStatusCopy('auto_dismissed', 'en');
      expect(en.label).toBe('Auto dismissed');
    });

    it('maps "escalated" and "pending_analyst_review"', () => {
      const viEscalated = getDisputeStatusCopy('escalated', 'vi');
      expect(viEscalated.label).toBe('Chuyển chuyên viên');
      const enEscalated = getDisputeStatusCopy('escalated', 'en');
      expect(enEscalated.label).toBe('Escalated');

      const viPending = getDisputeStatusCopy('pending_analyst_review', 'vi');
      expect(viPending.label).toBe('Chờ chuyên viên');
      expect(viPending.explanation).toBeTruthy();
      const enPending = getDisputeStatusCopy('pending_analyst_review', 'en');
      expect(enPending.label).toBe('Pending review');
      expect(enPending.explanation).toBeTruthy();
    });

    it('maps "resolved"', () => {
      const vi = getDisputeStatusCopy('resolved', 'vi');
      expect(vi.label).toBe('Đã giải quyết');
      const en = getDisputeStatusCopy('resolved', 'en');
      expect(en.label).toBe('Resolved');
    });

    it('maps "closed"', () => {
      const vi = getDisputeStatusCopy('closed', 'vi');
      expect(vi.label).toBe('Đã đóng');
      const en = getDisputeStatusCopy('closed', 'en');
      expect(en.label).toBe('Closed');
    });

    it('maps "expired"', () => {
      const vi = getDisputeStatusCopy('expired', 'vi');
      expect(vi.label).toBe('Hết hạn');
      const en = getDisputeStatusCopy('expired', 'en');
      expect(en.label).toBe('Expired');
    });
  });

  describe('getStatusCopy - known violation codes', () => {
    it('maps ERR-01, ERR-02, ERR-03 in vi and en', () => {
      const err01Vi = getViolationCopy('ERR-01', 'vi');
      expect(err01Vi.label).toBe('Chậm trễ đón khách');
      expect(err01Vi.explanation).toBeTruthy();

      const err01En = getViolationCopy('ERR-01', 'en');
      expect(err01En.label).toBe('Pickup delay');
      expect(err01En.explanation).toBeTruthy();

      const err02Vi = getViolationCopy('ERR-02', 'vi');
      expect(err02Vi.label).toBe('Hủy chuyến bất thường');
      const err02En = getViolationCopy('ERR-02', 'en');
      expect(err02En.label).toBe('Irregular cancellation');

      const err03Vi = getViolationCopy('ERR-03', 'vi');
      expect(err03Vi.label).toBe('Bất thường định vị GPS');
      const err03En = getViolationCopy('ERR-03', 'en');
      expect(err03En.label).toBe('GPS anomaly');
    });

    it('maps ERR-04, ERR-05 and DIC with exact labels differing from fallback', () => {
      const fallbackVi = getStatusCopy(null, 'vi').label;
      const fallbackEn = getStatusCopy(null, 'en').label;

      const err04Vi = getViolationCopy('ERR-04', 'vi');
      expect(err04Vi.label).toBe('Gián đoạn viễn thông');
      expect(err04Vi.label).not.toBe(fallbackVi);

      const err04En = getViolationCopy('ERR-04', 'en');
      expect(err04En.label).toBe('Telemetry disconnect');
      expect(err04En.label).not.toBe(fallbackEn);

      const err05Vi = getViolationCopy('ERR-05', 'vi');
      expect(err05Vi.label).toBe('Sai lệch lộ trình');
      expect(err05Vi.label).not.toBe(fallbackVi);

      const err05En = getViolationCopy('ERR-05', 'en');
      expect(err05En.label).toBe('Route deviation');
      expect(err05En.label).not.toBe(fallbackEn);

      const dicVi = getViolationCopy('DIC', 'vi');
      expect(dicVi.label).toBe('Hủy chuyến chủ đích');
      expect(dicVi.label).not.toBe(fallbackVi);

      const dicEn = getViolationCopy('DIC', 'en');
      expect(dicEn.label).toBe('Driver cancellation');
      expect(dicEn.label).not.toBe(fallbackEn);
    });

    it('iterates every known code in both vi and en without returning fallback', () => {
      const locales: ('vi' | 'en')[] = ['vi', 'en'];

      for (const loc of locales) {
        const fallbackLabel = getStatusCopy(null, loc).label;

        for (const code of Object.keys(viMessages.status.dispute)) {
          const res = getDisputeStatusCopy(code, loc);
          expect(res.label).toBeTruthy();
          expect(res.label).not.toBe(fallbackLabel);
          expect(res.explanation).toBeTruthy();
          expect(res.labelKey).toBe(`status.dispute.${code}.label`);
        }

        for (const code of Object.keys(viMessages.status.case)) {
          const res = getCaseStatusCopy(code, loc);
          expect(res.label).toBeTruthy();
          expect(res.label).not.toBe(fallbackLabel);
          expect(res.explanation).toBeTruthy();
          expect(res.labelKey).toBe(`status.case.${code}.label`);
        }

        for (const code of Object.keys(viMessages.status.violation)) {
          const res = getViolationCopy(code, loc);
          expect(res.label).toBeTruthy();
          expect(res.label).not.toBe(fallbackLabel);
          expect(res.explanation).toBeTruthy();
          expect(res.labelKey).toBe(`status.violation.${code}.label`);
        }
      }
    });

    it('is case-insensitive for violation codes', () => {
      expect(getViolationCopy('err-01', 'vi').label).toBe('Chậm trễ đón khách');
      expect(getViolationCopy('err-02', 'en').label).toBe('Irregular cancellation');
    });
  });

  describe('getStatusCopy - generic fallback for unknown codes', () => {
    it('never leaks raw unknown codes in label or explanation', () => {
      const unknownCodes = [
        'ERR-999',
        'SECRET_INTERNAL_CODE_123',
        'MALICIOUS_UUID_84920491',
        'random_garbage_status',
        'AUTO_BAN',
      ];

      for (const code of unknownCodes) {
        const vi = getStatusCopy(code, 'vi');
        expect(vi.label).not.toContain(code);
        expect(vi.explanation).not.toContain(code);
        expect(vi.label).toBe('Cần xem xét');
        expect(vi.explanation).toBe('Hồ sơ đang trong quy trình đối soát và xử lý.');

        const en = getStatusCopy(code, 'en');
        expect(en.label).not.toContain(code);
        expect(en.explanation).not.toContain(code);
        expect(en.label).toBe('Under review');
        expect(en.explanation).toBe('This case is currently being reviewed and processed.');
      }
    });

    it('handles null, undefined, and empty string safely', () => {
      const viNull = getStatusCopy(null, 'vi');
      expect(viNull.label).toBe('Cần xem xét');
      expect(viNull.explanation).toBe('Hồ sơ đang trong quy trình đối soát và xử lý.');

      const enUndef = getStatusCopy(undefined, 'en');
      expect(enUndef.label).toBe('Under review');

      const viEmpty = getStatusCopy('', 'vi');
      expect(viEmpty.label).toBe('Cần xem xét');
    });
  });
});
