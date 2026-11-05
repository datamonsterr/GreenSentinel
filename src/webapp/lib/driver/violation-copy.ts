/**
 * Frontend copy dictionary and formatting for driver violation titles (F4).
 * Mirrors src/services/driver_dispute_service.py VIOLATION_TITLE_MAP / VIOLATION_TITLE_MAP_EN.
 */

import type { Locale } from './locale';
import { resolveLocale } from './locale';

export const VIOLATION_TITLE_MAP: Record<'vi' | 'en', Record<string, string>> = {
  vi: {
    'ERR-01': 'Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt',
    'ERR-02': 'Lái xe lệch tuyến, kéo dài hoặc di chuyển sai hướng để khách hủy chuyến',
    'ERR-03': 'Khai thác khuyến mãi qua đặt chuyến giả hoặc gaming chính sách',
    'ERR-04': 'Chuyến đi ảo/ma: không có hành trình vật lý thực tế',
    'ERR-05': 'GPS giả hoặc thao túng công nghệ vị trí',
  },
  en: {
    'ERR-01': 'Trip/order embezzlement: cancel then collect cash off-app',
    'ERR-02': 'Route deviation / stall-to-cancel',
    'ERR-03': 'Incentive/policy exploitation via fake trips',
    'ERR-04': 'Phantom trip with no physical journey',
    'ERR-05': 'Fake GPS / technological manipulation',
  },
};

export const DEFAULT_VIOLATION_TITLE: Record<'vi' | 'en', string> = {
  vi: 'Nghi vấn vi phạm chỉ số vận hành',
  en: 'Suspected violation',
};

export function normalizeViolationCode(code?: string | null): string {
  if (!code) return '';
  return code.trim().toUpperCase().replace(/_/g, '-');
}

export function stripTrailingParenthetical(title?: string | null): string {
  if (!title) return '';
  return title.replace(/\s*\([A-Za-z0-9\s/_\-:,.'"]+\)\s*$/, '').trim();
}

export function isRawViolationCode(str?: string | null): boolean {
  if (!str) return true;
  const trimmed = str.trim();
  return /^(ERR[-_]?\d+|DIC|NO[-_]?VIOLATION|AUTO[-_]?DISMISSED|CASE[-_]?[A-Z0-9]+)$/i.test(trimmed);
}

export function getViolationTitle(options: {
  code?: string | null;
  title?: string | null;
  locale?: string | null;
}): string {
  const currentLocale: 'vi' | 'en' = resolveLocale(options.locale);
  const normalizedCode = normalizeViolationCode(options.code);

  const mappedTitle = VIOLATION_TITLE_MAP[currentLocale]?.[normalizedCode];
  if (mappedTitle) {
    return mappedTitle;
  }

  const cleanedTitle = stripTrailingParenthetical(options.title);
  if (cleanedTitle && !isRawViolationCode(cleanedTitle)) {
    return cleanedTitle;
  }

  return DEFAULT_VIOLATION_TITLE[currentLocale];
}
