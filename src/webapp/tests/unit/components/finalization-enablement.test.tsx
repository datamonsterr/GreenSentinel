import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { FinalizationTab } from '@/components/adjudication/finalization-tab';
import type { CaseDetailResponse } from '@/types/schemas';

const mockCaseDetailWithoutJudgment: CaseDetailResponse = {
  case: {
    id: 'case-test-573',
    status: 'in_review',
    priority: 'P1',
    priority_score: 80,
    version: 1,
  },
  active_lease: {
    analyst_id: 'analyst-123',
    expires_at: '2099-01-01T00:00:00Z',
  },
  assessment: {
    id: 'assessment-123',
    category: 'ERR-02',
    confidence: 0.85,
    reason_codes: ['stop_too_long'],
  },
  preliminary_judgment: null,
};

describe('FinalizationTab enablement & accessible hints (#573 Item 3)', () => {
  it('shows why Approve and Dismiss are disabled and keeps judgment save control reachable', () => {
    const onSaveJudgment = vi.fn();
    const onChoice = vi.fn();
    const onDecision = vi.fn();

    render(
      <FinalizationTab
        caseDetail={mockCaseDetailWithoutJudgment}
        isActive={true}
        canWrite={true}
        busy={false}
        choice=""
        onChoice={onChoice}
        note=""
        onNote={vi.fn()}
        savingJudgment={false}
        onSaveJudgment={onSaveJudgment}
        rationale="Detailed decision rationale with more than 10 characters"
        onRationale={vi.fn()}
        onDecision={onDecision}
        delta=""
      />
    );

    // 1. Approve conclusion and Dismiss must be disabled because independent judgment is not saved
    const approveBtn = screen.getByRole('button', { name: /Approve conclusion|Chấp thuận kết luận/i });
    const dismissBtn = screen.getByRole('button', { name: /Dismiss|Bác bỏ/i });

    expect(approveBtn).toBeDisabled();
    expect(dismissBtn).toBeDisabled();

    // 2. UI must show accessible hint explaining why Approve and Dismiss are disabled
    const hint = screen.getByRole('status', { name: /judgment|phán đoán/i });
    expect(hint).toBeVisible();
    expect(hint.textContent).toMatch(/judgment|phán đoán/i);

    // 3. Buttons must have accessible description or title explaining why they are disabled
    expect(approveBtn.getAttribute('title')).toMatch(/judgment|phán đoán/i);
    expect(dismissBtn.getAttribute('title')).toMatch(/judgment|phán đoán/i);

    // 4. The required step (save judgment) must be directly reachable from the Complete tab
    const reachTrigger = screen.getAllByRole('button', { name: /Save judgment|View AI|Lưu phán đoán|Xem kết quả AI/i })[0];
    expect(reachTrigger).toBeVisible();
    fireEvent.click(reachTrigger);

    const radioGroup = screen.getByRole('radiogroup', { name: /phán đoán|judgment/i });
    expect(radioGroup).toBeVisible();
    const saveButton = screen.getByRole('button', { name: /Save judgment & view AI|Lưu phán đoán và xem AI/i });
    expect(saveButton).toBeVisible();
  });
});
