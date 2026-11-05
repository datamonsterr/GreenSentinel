import { describe, it, expect } from 'vitest';
import { isResolvedCase } from '@/lib/driver/case-segments';

describe('isResolvedCase', () => {
  it('treats status "closed" as resolved', () => {
    expect(isResolvedCase({ status: 'closed', dispute_status: 'not_disputed' })).toBe(true);
  });

  it('treats dispute_status "resolved" as resolved', () => {
    expect(isResolvedCase({ status: 'open', dispute_status: 'resolved' })).toBe(true);
  });

  it('treats dispute_status "upheld" as resolved', () => {
    expect(isResolvedCase({ status: 'open', dispute_status: 'upheld' })).toBe(true);
  });

  it('treats dispute_status "auto_dismissed" as resolved', () => {
    expect(isResolvedCase({ status: 'open', dispute_status: 'auto_dismissed' })).toBe(true);
  });

  it('treats dispute_status "dismissed" as resolved', () => {
    expect(isResolvedCase({ status: 'open', dispute_status: 'dismissed' })).toBe(true);
  });

  it('treats open/not_disputed cases as not resolved', () => {
    expect(isResolvedCase({ status: 'open', dispute_status: 'not_disputed' })).toBe(false);
  });

  it('treats in_dispute / escalated / pending_review as not resolved', () => {
    expect(isResolvedCase({ status: 'investigating', dispute_status: 'in_dispute' })).toBe(false);
    expect(isResolvedCase({ status: 'open', dispute_status: 'escalated' })).toBe(false);
    expect(isResolvedCase({ status: 'open', dispute_status: 'pending_analyst_review' })).toBe(false);
  });
});
