import { describe, expect, it } from 'vitest';
import { caseStatusTone, statusTone } from './status-tone';

describe('status-tone', () => {
  it('maps tones to reference classes', () => {
    expect(statusTone('amber')).toBe('t-amber');
    expect(caseStatusTone('in_review')).toBe('t-cyan');
    expect(caseStatusTone('weird')).toBe('t-grey');
    expect(caseStatusTone(null)).toBe('t-grey');
  });
});
