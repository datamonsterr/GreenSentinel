import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { LocaleProvider, useLocale } from '@/lib/locale';
import { OverviewTab } from '@/components/adjudication/overview-tab';
import { WorkflowTab } from '@/components/adjudication/workflow-tab';

afterEach(() => { cleanup(); localStorage.clear(); });
function LanguageSwitch() {
  const { setLocale } = useLocale();
  return <button onClick={() => setLocale('vi')}>Switch Vietnamese</button>;
}
const detail: any = {
  case: { id: 'repair' },
  preliminary_judgment: { id: 'saved', case_id: 'repair' },
  forensic_brief: { summary_text: 'Original evidence remains unchanged.', motivation_assessment: {
    natural_vietnamese_narrative: 'MODEL INTENT ESTIMATE', economic_incentive_reward: 10000,
  } },
};
describe('workspace locale and reveal boundaries', () => {
  it('keeps model intent out of Overview after saved judgment and language changes', () => {
    render(<LocaleProvider><LanguageSwitch /><OverviewTab caseDetail={detail} /></LocaleProvider>);
    expect(screen.getByRole('heading', { name: 'Motivation' })).toBeVisible();
    expect(screen.queryByText('MODEL INTENT ESTIMATE')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Switch Vietnamese' }));
    expect(screen.getByRole('heading', { name: 'Động cơ' })).toBeVisible();
    expect(screen.getByText('Original evidence remains unchanged.')).toBeVisible();
    expect(screen.queryByText('MODEL INTENT ESTIMATE')).not.toBeInTheDocument();
  });
  it('localizes revealed workflow accessibility labels while preserving evidence and edited draft', () => {
    render(<LocaleProvider><LanguageSwitch /><WorkflowTab caseDetail={detail} aiRevealed caseWorkflowTrace={{ ai_result: { classification: 'MODEL_RAW_CLASS', confidence: 0.91 } } as any} /></LocaleProvider>);
    expect(screen.getByRole('region', { name: 'AI results' })).toHaveTextContent('MODEL_RAW_CLASS');
    fireEvent.change(screen.getByRole('textbox', { name: 'Workflow draft' }), { target: { value: 'Analyst wording unchanged' } });
    fireEvent.click(screen.getByRole('button', { name: 'Switch Vietnamese' }));
    expect(screen.getByRole('region', { name: 'Kết quả AI' })).toHaveTextContent('MODEL_RAW_CLASS');
    expect(screen.getByRole('textbox', { name: 'Bản nháp quy trình' })).toHaveValue('Analyst wording unchanged');
    expect(screen.queryByRole('region', { name: 'AI results' })).not.toBeInTheDocument();
  });
});
