import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkflowStepperView } from '@/components/cockpit/workflow-stepper';
import { roleStyle, actorStyle } from '@/lib/role-style';
import { caseStatusTone } from '@/lib/status-tone';
import type { CaseWorkflow } from '@/lib/case-workflow-client';

const KEYS = [['NEED_TO_EXPLAIN', 'TX'], ['UNDER_REVIEW', 'KSGL'], ['REVIEWED', 'KSGL'], ['REPORT_ISSUED', 'System'],
  ['REPORT_CONFIRMED', 'KSCL'], ['NEED_OPS_DIR_APPROVED', 'OPS_DIR'], ['NEED_MKP_DIR_APPROVED', 'MKP_DIR'], ['COMPLETED', 'System']];
const wf = (cur: number, actions: string[] = []): CaseWorkflow => ({
  status: 'report_issued', closed: false, actions,
  steps: KEYS.map(([key, actor_role], i) => ({
    key, label: key, actor_role, state: i < cur ? 'done' : i === cur ? 'current' : 'pending',
    completed_at: i < cur ? '2026-01-02T03:04:00Z' : null,
  })),
  next: { actor_role: 'KSCL', text: 'Depot (KSCL) xác nhận biên bản' },
});

describe('WorkflowStepperView', () => {
  it('renders done/current/pending, timestamps and next-action callout', () => {
    const { container } = render(<WorkflowStepperView workflow={wf(3)} locale="vi" />);
    const state = (k: string) => container.querySelector(`[data-step="${k}"]`)?.getAttribute('data-state');
    expect(state('REVIEWED')).toBe('done');
    expect(state('REPORT_ISSUED')).toBe('current');
    expect(state('COMPLETED')).toBe('pending');
    expect(container.querySelectorAll('[aria-current="step"]')).toHaveLength(1);
    expect(screen.getByTestId('workflow-next')).toHaveTextContent(/Bước tiếp theo:\s*KSCL\s*— Depot \(KSCL\) xác nhận biên bản/);
    expect(container.querySelector('[data-step="REVIEWED"]')?.textContent).toMatch(/\d/);
  });

  it('shows Admin as the actor of the MKP DIR step', () => {
    const { container } = render(<WorkflowStepperView workflow={wf(6)} locale="vi" />);
    const step = container.querySelector('[data-step="NEED_MKP_DIR_APPROVED"]')!;
    expect(step).toHaveTextContent('MKP_DIR');
    expect(step).toHaveTextContent('Admin');
    expect(step.querySelector('[title="Admin"]')).not.toBeNull();
  });
  it('shows action button only when backend allows it', () => {
    const onAction = vi.fn();
    const { rerender } = render(<WorkflowStepperView workflow={wf(3)} locale="en" onAction={onAction} />);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<WorkflowStepperView workflow={wf(3, ['confirm-report'])} locale="en" onAction={onAction} />);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm report' }));
    expect(onAction).toHaveBeenCalledWith('confirm-report');
  });
});

describe('role style + status tone', () => {
  it('uses reference badge labels and colours', () => {
    expect(roleStyle('reviewer')).toMatchObject({ label: 'KSCL', bg: '#fbe9d6', fg: '#c8791e' });
    expect(roleStyle('ops_director')).toMatchObject({ label: 'OPS_DIR', fg: '#3b6fd6' });
    expect(roleStyle('marketplace_director')).toMatchObject({ label: 'MKP_DIR', bg: '#fde4e4' });
    expect(actorStyle('KSCL').label).toBe('KSCL');
    expect(actorStyle('System').label).toBe('System');
  });
  it('maps new statuses', () => {
    expect(caseStatusTone('report_issued')).toBe('t-purple');
    expect(caseStatusTone('need_ops_dir_approved')).toBe('t-orange');
    expect(caseStatusTone('completed')).toBe('t-green');
  });
});
