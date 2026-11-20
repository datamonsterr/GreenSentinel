import type { Locale } from './locale';

/** GSM tone chip classes (defined in globals.css). Use: <span className={`gs-tone ${statusTone('amber')}`}>. */
export type Tone = 'amber' | 'cyan' | 'purple' | 'green' | 'orange' | 'brown' | 'grey' | 'red' | 'blue';

export const statusTone = (tone: Tone): string => `t-${tone}`;

/**
 * Case status -> tone. Single source for queue, header, Complete tab and the workflow stepper chip.
 * Tone follows workflow stage: amber = needs driver/analyst action, cyan = in review, purple = report,
 * orange = escalated/awaiting approval, green = confirmed/completed, red = failed, grey = closed.
 */
const CASE_STATUS_TONE: Record<string, Tone> = {
  pending: 'amber', open: 'amber', new: 'amber', ingested: 'amber', ready: 'amber', evidence_requested: 'amber',
  processing: 'cyan', in_review: 'cyan', reviewing: 'cyan', assigned: 'cyan', driver_disputed: 'cyan', pending_analyst_review: 'cyan',
  awaiting_driver: 'purple', awaiting_response: 'purple', escalated: 'orange',
  resolved: 'cyan', suspended: 'cyan', driver_confirmed_resolution: 'cyan', pending_driver_confirmation: 'amber', closed: 'grey', auto_dismissed: 'grey', dismissed: 'grey',
  report_issued: 'purple', report_confirmed: 'green', need_ops_dir_approved: 'orange', need_mkp_dir_approved: 'orange',
  completed: 'green', confirmed: 'red', rejected: 'grey', processing_failed: 'red',
};
export const caseStatusTone = (status?: string | null): string =>
  statusTone(CASE_STATUS_TONE[(status ?? '').toLowerCase()] ?? 'grey');

const CASE_STATUS_LABEL: Record<Locale, Record<string, string>> = {
  vi: {
    ingested: 'Mới tiếp nhận', processing: 'Đang xử lý dữ liệu', ready: 'Sẵn sàng', in_review: 'Đang thẩm định',
    evidence_requested: 'Chờ tài xế giải trình', pending_driver_confirmation: 'Chờ tài xế xác nhận', driver_confirmed_resolution: 'Tài xế đã xác nhận', driver_disputed: 'Tài xế đã giải trình', pending_analyst_review: 'Chờ thẩm định',
    escalated: 'Đã chuyển cấp', resolved: 'Đã thẩm định', suspended: 'Đình chỉ', report_issued: 'Đã phát hành biên bản',
    report_confirmed: 'Depot đã xác nhận', need_ops_dir_approved: 'Chờ OPS DIR duyệt', need_mkp_dir_approved: 'Chờ MKP DIR duyệt',
    completed: 'Hoàn tất', auto_dismissed: 'Tự động đóng', dismissed: 'Đã bác bỏ', closed: 'Đã đóng', processing_failed: 'Xử lý lỗi',
  },
  en: {
    ingested: 'Ingested', processing: 'Processing', ready: 'Ready', in_review: 'In review',
    evidence_requested: 'Awaiting driver explanation', pending_driver_confirmation: 'Awaiting driver confirmation', driver_confirmed_resolution: 'Driver confirmed', driver_disputed: 'Driver explained', pending_analyst_review: 'Pending review',
    escalated: 'Escalated', resolved: 'Reviewed', suspended: 'Suspended', report_issued: 'Report issued',
    report_confirmed: 'Depot confirmed', need_ops_dir_approved: 'Awaiting OPS DIR', need_mkp_dir_approved: 'Awaiting MKP DIR',
    completed: 'Completed', auto_dismissed: 'Auto-dismissed', dismissed: 'Dismissed', closed: 'Closed', processing_failed: 'Processing failed',
  },
};
export const caseStatusLabel = (status: string | null | undefined, locale: Locale): string =>
  CASE_STATUS_LABEL[locale][(status ?? '').toLowerCase()] ?? status ?? '—';
