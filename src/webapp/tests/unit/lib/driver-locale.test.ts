import { describe, it, expect } from 'vitest';
import {
  DEFAULT_LOCALE,
  SUPPORTED_LOCALES,
  LOCALE_COOKIE_NAME,
  resolveLocale,
} from '@/lib/driver/locale';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';

describe('Driver locale module', () => {
  it('defines default locale as "vi" and supported locales as ["vi", "en"]', () => {
    expect(DEFAULT_LOCALE).toBe('vi');
    expect(SUPPORTED_LOCALES).toEqual(['vi', 'en']);
    expect(LOCALE_COOKIE_NAME).toBe('NEXT_LOCALE');
  });

  it('resolves valid locales properly', () => {
    expect(resolveLocale('vi')).toBe('vi');
    expect(resolveLocale('en')).toBe('en');
  });

  it('defaults to "vi" when locale cookie is missing or invalid', () => {
    expect(resolveLocale(undefined)).toBe('vi');
    expect(resolveLocale(null)).toBe('vi');
    expect(resolveLocale('')).toBe('vi');
    expect(resolveLocale('fr')).toBe('vi');
    expect(resolveLocale('zh-CN')).toBe('vi');
    expect(resolveLocale('unknown')).toBe('vi');
  });

  describe('messages integrity (vi.json and en.json)', () => {
    it('has identical top-level keys in vi.json and en.json', () => {
      const viKeys = Object.keys(viMessages).sort();
      const enKeys = Object.keys(enMessages).sort();
      expect(viKeys).toEqual(enKeys);
    });

    it('contains driver, status, and common sections in both translation files', () => {
      expect((viMessages as any).driver).toBeDefined();
      expect((enMessages as any).driver).toBeDefined();
      expect((viMessages as any).status).toBeDefined();
      expect((enMessages as any).status).toBeDefined();
    });

    it('contains all required driver translation keys', () => {
      const viDriver = (viMessages as any).driver;
      const enDriver = (enMessages as any).driver;

      expect(viDriver.portalTitle).toBe('Danh sách phiên vụ việc');
      expect(enDriver.portalTitle).toBe('Dispute Sessions');

      expect(viDriver.allCases).toBe('Tất cả');
      expect(enDriver.allCases).toBe('All');

      expect(viDriver.activeCases).toBe('Đang xử lý');
      expect(enDriver.activeCases).toBe('Active');

      expect(viDriver.resolvedCases).toBe('Đã giải quyết');
      expect(enDriver.resolvedCases).toBe('Resolved');
    });

    it('maintains recursive key parity between vi.json and en.json and has no empty values', () => {
      function flattenKeys(obj: Record<string, any>, prefix = ''): Record<string, string> {
        const result: Record<string, string> = {};
        for (const [key, value] of Object.entries(obj)) {
          const fullKey = prefix ? `${prefix}.${key}` : key;
          if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
            Object.assign(result, flattenKeys(value, fullKey));
          } else {
            result[fullKey] = String(value ?? '');
          }
        }
        return result;
      }

      const viFlat = flattenKeys(viMessages);
      const enFlat = flattenKeys(enMessages);

      const viKeys = Object.keys(viFlat).sort();
      const enKeys = Object.keys(enFlat).sort();

      expect(viKeys).toEqual(enKeys);

      for (const [key, val] of Object.entries(viFlat)) {
        expect(val.trim(), `vi key "${key}" should not be empty`).not.toBe('');
      }

      for (const [key, val] of Object.entries(enFlat)) {
        expect(val.trim(), `en key "${key}" should not be empty`).not.toBe('');
      }
    });
  });
});


describe('driver time zone', () => {
  it('pins next-intl to Vietnam time so server and client markup match', async () => {
    const { DRIVER_TIME_ZONE } = await import('@/lib/driver/locale');
    expect(DRIVER_TIME_ZONE).toBe('Asia/Ho_Chi_Minh');
  });
});
