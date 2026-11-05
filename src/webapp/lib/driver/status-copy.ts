import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';
import { DEFAULT_LOCALE, type Locale, resolveLocale } from './locale';

export interface StatusCopyResult {
  label: string;
  explanation: string;
  labelKey: string;
  explanationKey: string;
}

const MESSAGES: Record<Locale, typeof viMessages> = {
  vi: viMessages,
  en: enMessages,
};

/**
 * Format a case ID to a human-friendly short identifier.
 * Strips common prefixes (case-, CASE_), takes last 4 alphanumeric chars uppercase.
 * Example: 'case-test-101' -> '#T101', 'case-alpha-1234' -> '#1234'
 */
export function formatShortCaseId(caseId?: string | null): string {
  if (!caseId) return '#----';
  const withoutHash = caseId.replace(/^#+/, '').trim();
  if (!withoutHash) return '#----';
  const stripped = withoutHash.replace(/^(case[-_]|CASE[-_])/i, '');
  const alphanum = stripped.replace(/[^a-zA-Z0-9]/g, '');
  if (!alphanum) return '#----';
  const last4 = alphanum.slice(-4).toUpperCase();
  return '#' + last4;
}


function normalizeKey(code?: string | null): string {
  if (!code) return '';
  return code.trim().toLowerCase().replace(/[-]/g, '_');
}

/**
 * Returns localized status copy for dispute statuses.
 */
export function getDisputeStatusCopy(
  code?: string | null,
  locale?: string | null
): StatusCopyResult {
  const currentLocale = resolveLocale(locale);
  const messages = MESSAGES[currentLocale].status;
  const key = normalizeKey(code);

  const disputeMap = messages.dispute as Record<string, { label: string; explanation: string } | undefined>;
  const found = disputeMap[key];

  if (found) {
    return {
      label: found.label,
      explanation: found.explanation,
      labelKey: `status.dispute.${key}.label`,
      explanationKey: `status.dispute.${key}.explanation`,
    };
  }

  return {
    label: messages.fallback.label,
    explanation: messages.fallback.explanation,
    labelKey: 'status.fallback.label',
    explanationKey: 'status.fallback.explanation',
  };
}

/**
 * Returns localized status copy for case statuses.
 */
export function getCaseStatusCopy(
  code?: string | null,
  locale?: string | null
): StatusCopyResult {
  const currentLocale = resolveLocale(locale);
  const messages = MESSAGES[currentLocale].status;
  const key = normalizeKey(code);

  const caseMap = messages.case as Record<string, { label: string; explanation: string } | undefined>;
  const found = caseMap[key];

  if (found) {
    return {
      label: found.label,
      explanation: found.explanation,
      labelKey: `status.case.${key}.label`,
      explanationKey: `status.case.${key}.explanation`,
    };
  }

  return {
    label: messages.fallback.label,
    explanation: messages.fallback.explanation,
    labelKey: 'status.fallback.label',
    explanationKey: 'status.fallback.explanation',
  };
}

/**
 * Returns localized status copy for trip history statuses (completed, cancelled, flagged, ...).
 */
export function getTripStatusCopy(
  code?: string | null,
  locale?: string | null
): StatusCopyResult {
  const currentLocale = resolveLocale(locale);
  const messages = MESSAGES[currentLocale].status;
  const key = normalizeKey(code);

  const tripMap = messages.trip as Record<string, { label: string; explanation: string } | undefined>;
  const found = tripMap?.[key];

  if (found) {
    return {
      label: found.label,
      explanation: found.explanation,
      labelKey: `status.trip.${key}.label`,
      explanationKey: `status.trip.${key}.explanation`,
    };
  }

  return {
    label: messages.fallback.label,
    explanation: messages.fallback.explanation,
    labelKey: 'status.fallback.label',
    explanationKey: 'status.fallback.explanation',
  };
}

/**
 * Returns localized status copy for violation codes (e.g. ERR-01..05, DIC, etc).
 */
export function getViolationCopy(
  code?: string | null,
  locale?: string | null
): StatusCopyResult {
  const currentLocale = resolveLocale(locale);
  const messages = MESSAGES[currentLocale].status;
  const key = normalizeKey(code);

  const violationMap = messages.violation as Record<string, { label: string; explanation: string } | undefined>;
  const found = violationMap[key];

  if (found) {
    return {
      label: found.label,
      explanation: found.explanation,
      labelKey: `status.violation.${key}.label`,
      explanationKey: `status.violation.${key}.explanation`,
    };
  }

  return {
    label: messages.fallback.label,
    explanation: messages.fallback.explanation,
    labelKey: 'status.fallback.label',
    explanationKey: 'status.fallback.explanation',
  };
}

/**
 * General status copy resolver that inspects dispute statuses, violation codes, and case statuses.
 * Guaranteed to NEVER leak raw code in fallback.
 */
export function getStatusCopy(
  code?: string | null,
  locale?: string | null,
  type?: 'dispute_status' | 'status' | 'violation_code'
): StatusCopyResult {
  if (type === 'dispute_status') return getDisputeStatusCopy(code, locale);
  if (type === 'status') return getCaseStatusCopy(code, locale);
  if (type === 'violation_code') return getViolationCopy(code, locale);

  if (!code) {
    const currentLocale = resolveLocale(locale);
    const messages = MESSAGES[currentLocale].status;
    return {
      label: messages.fallback.label,
      explanation: messages.fallback.explanation,
      labelKey: 'status.fallback.label',
      explanationKey: 'status.fallback.explanation',
    };
  }

  // Auto-detect among maps
  const dispute = getDisputeStatusCopy(code, locale);
  if (dispute.labelKey !== 'status.fallback.label') return dispute;

  const violation = getViolationCopy(code, locale);
  if (violation.labelKey !== 'status.fallback.label') return violation;

  const caseStatus = getCaseStatusCopy(code, locale);
  if (caseStatus.labelKey !== 'status.fallback.label') return caseStatus;

  const currentLocale = resolveLocale(locale);
  const messages = MESSAGES[currentLocale].status;
  return {
    label: messages.fallback.label,
    explanation: messages.fallback.explanation,
    labelKey: 'status.fallback.label',
    explanationKey: 'status.fallback.explanation',
  };
}

export {
  getViolationTitle,
  stripTrailingParenthetical,
  isRawViolationCode,
  VIOLATION_TITLE_MAP,
} from './violation-copy';

