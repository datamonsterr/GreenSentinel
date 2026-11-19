/** Case queue: expand/collapse (URL-persisted) + filter state → backend query / client filters. */
import type { Locale } from '@/lib/locale';

export type Availability = 'available' | 'mine' | 'all';

export interface QueueFilters {
  statuses: string[];
  priority: string;
  category: string;
  assignee: string;
  from: string; // yyyy-mm-dd
  to: string;
  search: string;
  availability: Availability;
}

export const EMPTY_FILTERS: QueueFilters = {
  statuses: [], priority: '', category: '', assignee: '', from: '', to: '', search: '', availability: 'available',
};

export const EXPAND_PARAM = 'queue';
export const EXPAND_VALUE = 'expanded';

export function isQueueExpanded(search: string): boolean {
  return new URLSearchParams(search).get(EXPAND_PARAM) === EXPAND_VALUE;
}

/** Returns the new query string (without "?") with the expand flag set/cleared; other params kept. */
export function withQueueExpanded(search: string, expanded: boolean): string {
  const params = new URLSearchParams(search);
  if (expanded) params.set(EXPAND_PARAM, EXPAND_VALUE);
  else params.delete(EXPAND_PARAM);
  return params.toString();
}

/** Params sent to GET /cases. Status/priority/category/assignee/date filter client-side so chip counts stay stable. */
export function toFetchParams(f: QueueFilters): { availability: Availability; search?: string } {
  const search = f.search.trim();
  return { availability: f.availability, search: search || undefined };
}

export interface QueueRow {
  id: string;
  severity: string;
  status?: string;
  category?: string | null;
  assignedAnalystName?: string | null;
  openedAt?: string | null;
}

const dayStart = (d: string) => Date.parse(`${d}T00:00:00`);
const dayEnd = (d: string) => Date.parse(`${d}T23:59:59.999`);

/** `skip` omits one facet so its chip counts reflect the other filters. */
export function applyFilters<T extends QueueRow>(rows: T[], f: QueueFilters, skip?: 'statuses'): T[] {
  return rows.filter(r => {
    if (skip !== 'statuses' && f.statuses.length && !f.statuses.includes((r.status ?? '').toLowerCase())) return false;
    if (f.priority && r.severity !== f.priority) return false;
    if (f.category && (r.category ?? '') !== f.category) return false;
    if (f.assignee && (r.assignedAnalystName ?? '') !== f.assignee) return false;
    if (f.from || f.to) {
      const t = r.openedAt ? Date.parse(r.openedAt) : NaN;
      if (Number.isNaN(t)) return false;
      if (f.from && t < dayStart(f.from)) return false;
      if (f.to && t > dayEnd(f.to)) return false;
    }
    return true;
  });
}

export function statusCounts(rows: QueueRow[], f: QueueFilters): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of applyFilters(rows, f, 'statuses')) {
    const s = (r.status ?? '').toLowerCase();
    if (s) out[s] = (out[s] ?? 0) + 1;
  }
  return out;
}

/** Facets beyond availability/search that narrow the list; drives the popover badge. */
export function activeFilterCount(f: QueueFilters): number {
  return (f.statuses.length ? 1 : 0) + [f.priority, f.category, f.assignee].filter(Boolean).length + (f.from || f.to ? 1 : 0);
}

export function distinct(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((v): v is string => Boolean(v)))].sort();
}

export const QUEUE_STATUSES = ['ready', 'in_review', 'escalated', 'evidence_requested', 'driver_disputed', 'pending_analyst_review'] as const;

export const queueText: Record<Locale, Record<string, string>> = {
  en: {
    expand: 'Expand case list', collapse: 'Collapse case list', filters: 'Filters', clear: 'Clear filters',
    priority: 'Priority', category: 'Category', assignee: 'Assignee', from: 'From', to: 'To', all: 'All',
    id: 'Case', driver: 'Driver', plate: 'Plate', status: 'Status', opened: 'Opened', action: 'Action',
    allCases: 'All cases', unassigned: 'Unassigned', date: 'Date',
    ready: 'Ready', in_review: 'In review', escalated: 'Escalated', evidence_requested: 'Evidence requested',
    driver_disputed: 'Disputed', pending_analyst_review: 'Pending review',
  },
  vi: {
    expand: 'Mở rộng danh sách vụ việc', collapse: 'Thu gọn danh sách vụ việc', filters: 'Bộ lọc', clear: 'Xoá bộ lọc',
    priority: 'Ưu tiên', category: 'Loại vi phạm', assignee: 'Người phụ trách', from: 'Từ', to: 'Đến', all: 'Tất cả',
    id: 'Mã vụ việc', driver: 'Tài xế', plate: 'Biển số', status: 'Trạng thái', opened: 'Thời gian mở', action: 'Thao tác',
    allCases: 'Tất cả vụ việc', unassigned: 'Chưa phân công', date: 'Ngày',
    ready: 'Sẵn sàng', in_review: 'Đang thẩm định', escalated: 'Đã chuyển cấp', evidence_requested: 'Chờ bằng chứng',
    driver_disputed: 'Tài xế khiếu nại', pending_analyst_review: 'Chờ thẩm định',
  },
};
