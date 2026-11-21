import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WorkflowStepperView } from '@/components/cockpit/workflow-stepper';
import { CaseStatusChip } from '@/components/cockpit/case-status-chip';
import { caseStatusLabel, caseStatusTone } from '@/lib/status-tone';
import type { CaseWorkflow } from '@/lib/case-workflow-client';

const ALL = ['ingested', 'processing', 'ready', 'in_review', 'evidence_requested', 'driver_disputed', 'pending_analyst_review',
  'escalated', 'resolved', 'suspended', 'report_issued', 'report_confirmed', 'need_ops_dir_approved', 'need_mkp_dir_approved',
  'completed', 'auto_dismissed', 'dismissed', 'closed', 'processing_failed'];

describe('shared case status mapping', () => {
  it('labels every status in both locales (no raw key leaks)', () => {
    for (const s of ALL) {
      expect(caseStatusLabel(s, 'vi')).not.toBe(s);
      expect(caseStatusLabel(s, 'en')).not.toBe(s);
    }
  });
  it('tone follows the workflow stage', () => {
    expect(caseStatusTone('evidence_requested')).toBe('t-amber');
    expect(caseStatusTone('driver_disputed')).toBe('t-cyan');
    expect(caseStatusTone('pending_analyst_review')).toBe('t-cyan');
    expect(caseStatusTone('report_issued')).toBe('t-purple');
    expect(caseStatusTone('need_mkp_dir_approved')).toBe('t-orange');
    expect(caseStatusTone('completed')).toBe('t-green');
    expect(caseStatusTone('auto_dismissed')).toBe('t-grey');
    expect(caseStatusTone('processing_failed')).toBe('t-red');
  });
  it('chip renders label with the tone class and no palette classes', () => {
    render(<CaseStatusChip status="evidence_requested" locale="vi" />);
    const el = screen.getByText(caseStatusLabel('evidence_requested', 'vi'));
    expect(el.className).toMatch(/t-amber/);
    expect(el.className).not.toMatch(/(emerald|red|amber|sky|violet)-\d/);
  });
});

const wf = (over: Partial<CaseWorkflow>): CaseWorkflow => ({
  status: 'in_review', closed: false, actions: [],
  steps: ['NEED_TO_EXPLAIN', 'UNDER_REVIEW', 'REVIEWED'].map((key, i) => ({
    key, label: key, actor_role: 'KSGL', state: i === 0 ? 'skipped' : i === 1 ? 'current' : 'pending', completed_at: null,
  })),
  next: { actor_role: 'KSGL', text: 'x' }, ...over,
});

describe('stepper skipped state + status chip', () => {
  it('renders skipped step distinctly, without a check mark or timestamp', () => {
    const { container } = render(<WorkflowStepperView workflow={wf({})} locale="vi" />);
    const el = container.querySelector('[data-step="NEED_TO_EXPLAIN"]')!;
    expect(el.getAttribute('data-state')).toBe('skipped');
    expect(el.textContent).not.toContain('✓');
    expect(el.textContent).toMatch(/Không áp dụng/);
  });
  it('shows the same status chip as the queue', () => {
    render(<WorkflowStepperView workflow={wf({ status: 'driver_disputed' })} locale="vi" />);
    const chip = screen.getByTestId('workflow-status-chip');
    expect(chip.textContent).toBe(caseStatusLabel('driver_disputed', 'vi'));
    expect(chip.className).toContain(caseStatusTone('driver_disputed'));
  });
  it('closed case shows closed banner and grey chip', () => {
    render(<WorkflowStepperView workflow={wf({ status: 'auto_dismissed', closed: true, next: null })} locale="en" />);
    expect(screen.getByText(/Case closed/)).toBeInTheDocument();
    expect(screen.getByTestId('workflow-status-chip').className).toContain('t-grey');
    expect(screen.queryByTestId('workflow-next')).toBeNull();
  });
});
