import { describe, it, expect } from 'vitest';
import {
  EMPTY_FILTERS, activeFilterCount, applyFilters, isQueueExpanded, statusCounts, toFetchParams, withQueueExpanded,
  type QueueFilters, type QueueRow,
} from '@/lib/case-queue';

const rows: QueueRow[] = [
  { id: 'a', severity: 'P0', status: 'ready', category: 'ERR-01', assignedAnalystName: null, openedAt: '2026-11-10T08:00:00' },
  { id: 'b', severity: 'P1', status: 'in_review', category: 'ERR-02', assignedAnalystName: 'Hà', openedAt: '2026-11-15T08:00:00' },
  { id: 'c', severity: 'P1', status: 'ready', category: 'ERR-01', assignedAnalystName: 'Hà', openedAt: '2026-11-18T23:00:00' },
];
const f = (p: Partial<QueueFilters>): QueueFilters => ({ ...EMPTY_FILTERS, ...p });

describe('expand state in URL', () => {
  it('reads the flag', () => {
    expect(isQueueExpanded('?queue=expanded&caseId=1')).toBe(true);
    expect(isQueueExpanded('?caseId=1')).toBe(false);
  });
  it('sets and clears the flag keeping other params', () => {
    expect(withQueueExpanded('caseId=1', true)).toBe('caseId=1&queue=expanded');
    expect(withQueueExpanded('caseId=1&queue=expanded', false)).toBe('caseId=1');
    expect(withQueueExpanded('', false)).toBe('');
  });
});

describe('filter → backend query', () => {
  it('sends only availability and trimmed search', () => {
    expect(toFetchParams(f({ search: '  29A ', availability: 'mine', priority: 'P0' }))).toEqual({ availability: 'mine', search: '29A' });
    expect(toFetchParams(EMPTY_FILTERS)).toEqual({ availability: 'available' });
  });
});

describe('client filters', () => {
  it('filters by status, priority, category, assignee', () => {
    expect(applyFilters(rows, f({ statuses: ['ready'] })).map(r => r.id)).toEqual(['a', 'c']);
    expect(applyFilters(rows, f({ priority: 'P1', category: 'ERR-01' })).map(r => r.id)).toEqual(['c']);
    expect(applyFilters(rows, f({ assignee: 'Hà' })).map(r => r.id)).toEqual(['b', 'c']);
  });
  it('date range is inclusive of whole end day', () => {
    expect(applyFilters(rows, f({ from: '2026-11-15', to: '2026-11-18' })).map(r => r.id)).toEqual(['b', 'c']);
    expect(applyFilters(rows, f({ to: '2026-11-10' })).map(r => r.id)).toEqual(['a']);
  });
  it('status counts ignore the status facet but respect others', () => {
    expect(statusCounts(rows, f({ statuses: ['ready'] }))).toEqual({ ready: 2, in_review: 1 });
    expect(statusCounts(rows, f({ priority: 'P1' }))).toEqual({ in_review: 1, ready: 1 });
  });
  it('counts active facets', () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    expect(activeFilterCount(f({ statuses: ['ready', 'escalated'], priority: 'P0', from: '2026-11-01', search: 'x' }))).toBe(3);
  });
});
