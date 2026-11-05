import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import * as api from '@/lib/api-client';
import { committedJudgment } from '../../fixtures/staged-adjudication';
vi.mock('@/components/map/maplibre-view', () => ({
 MapLibreView: ({ caseId }: { caseId?: string }) => <div data-testid="cockpit-map-boundary" data-case-id={caseId} />,
}));
vi.mock('@/lib/api-client', () => ({ fetchCases: vi.fn(), fetchCaseDetail: vi.fn(), fetchForensicBrief: vi.fn(), fetchCasePolicy: vi.fn(), fetchCurrentAnalyst: vi.fn(), fetchAgentSession: vi.fn(), claimCase: vi.fn(), releaseCase: vi.fn(), adjudicateCase: vi.fn(), recordCaseAction: vi.fn(), subscribeCaseStream: vi.fn(() => () => {}), streamPolicyChat: vi.fn(), getDisputeDossier: vi.fn(), delegateAnalystInquiry: vi.fn(), getCaseWorkflowTrace: vi.fn(), applyPrecedentProcedure: vi.fn() }));
const item = { id:'case-real', driver_name:'Driver persisted', vehicle_plate:'30A-45678', priority:'P1', priority_score:1, status:'ready', version:4 };
const detail = {
  case:item,
  trip:{},
  conversation:[{role:'driver' as const,text:'I am at the pickup',occurred_at:'2026-09-25T01:00:00Z'}],
  active_lease:{ analyst_id:'analyst-real', expires_at:'2099-01-01T00:00:00Z' },
  preliminary_judgment: committedJudgment(item.id, 'analyst-real'),
};
const openFinalization = () => fireEvent.click(screen.getByRole('tab', { name: /Complete/i }));
const openCustomer = async () => {
 await screen.findByRole('tabpanel', { name: /Overview/i });
 fireEvent.click(await screen.findByRole('tab', { name: /Customer/i }));
};
const openMaps = async () => {
 await screen.findByRole('tabpanel', { name: /Overview/i });
 fireEvent.click(await screen.findByRole('tab', { name: /Maps/i }));
};

it('retains the map but hides old detail and decisions while another case loads', async () => {
 const second = { ...item, id: 'case-second', driver_name: 'Second driver' };
 let resolveDetail!: (value: typeof detail) => void;
 vi.mocked(api.fetchCases).mockResolvedValue({items:[item,second],total:2,limit:50,offset:0});
 vi.mocked(api.fetchCaseDetail).mockImplementation((id) => id === second.id
  ? new Promise(resolve => { resolveDetail = resolve; }) : Promise.resolve(detail));
 render(<CockpitWorkspaceView />);
 await openMaps();
 const map = await screen.findByTestId('cockpit-map-boundary');
 await waitFor(() => expect(map).toBeVisible());
 expect(map).toHaveAttribute('data-case-id', item.id);
 fireEvent.click(screen.getByRole('button',{name:/#e-second/}));
 await waitFor(() => expect(api.fetchCaseDetail).toHaveBeenCalledWith(second.id));
 expect(screen.getByTestId('cockpit-map-boundary')).toBe(map);
 expect(map).not.toBeVisible();
 expect(screen.queryByRole('button',{name:'Send decision'})).not.toBeInTheDocument();
 expect(map).toHaveAttribute('data-case-id', item.id);
 await act(async () => resolveDetail({...detail,case:second}));
 await waitFor(() => expect(map).toBeVisible());
 expect(screen.getByTestId('cockpit-map-boundary')).toBe(map);
 expect(map).toHaveAttribute('data-case-id', second.id);
 openFinalization();
 expect(screen.getByRole('button',{name:'Approve conclusion'})).toBeVisible();
});

it('renders cached map detail while revalidating a previously loaded case', async () => {
 const second = { ...item, id: 'case-second', driver_name: 'Second driver' };
 const secondDetail = {...detail, case:second};
 let resolveRevalidation!: (value: typeof detail) => void;
 vi.mocked(api.fetchCases).mockResolvedValue({items:[item,second],total:2,limit:50,offset:0});
 vi.mocked(api.fetchCaseDetail)
  .mockResolvedValueOnce(detail)
  .mockResolvedValueOnce(secondDetail)
  .mockImplementationOnce(() => new Promise(resolve => { resolveRevalidation = resolve; }));
 render(<CockpitWorkspaceView />);
 await openMaps();
 const map = await screen.findByTestId('cockpit-map-boundary');
 await waitFor(() => expect(map).toHaveAttribute('data-case-id', item.id));
 fireEvent.click(screen.getByRole('button',{name:/#e-second/}));
 await waitFor(() => expect(map).toHaveAttribute('data-case-id', second.id));

 fireEvent.click(screen.getByRole('button',{name:/#ase-real/}));
 await waitFor(() => expect(api.fetchCaseDetail).toHaveBeenCalledTimes(3));
 expect(map).toBeVisible();
 expect(map).toHaveAttribute('data-case-id', item.id);

 await act(async () => resolveRevalidation(detail));
});

it('keeps selection and avoids queue reads for intermediate stream progress', async () => {
 const second = { ...item, id: 'case-second', driver_name: 'Second driver' };
 vi.mocked(api.fetchCases).mockResolvedValue({items:[item,second],total:2,limit:50,offset:0});
 vi.mocked(api.fetchCaseDetail).mockImplementation(async (id) => ({...detail,case:id === second.id ? second : item}));
 render(<CockpitWorkspaceView />);
 await openCustomer(); await screen.findByText('I am at the pickup');
 fireEvent.click(screen.getByRole('button',{name:/#e-second/}));
 await waitFor(() => expect(api.subscribeCaseStream).toHaveBeenLastCalledWith(second.id,expect.any(Function),expect.any(Function)));
 const stream = vi.mocked(api.subscribeCaseStream).mock.calls.at(-1)![1];
 const reads = vi.mocked(api.fetchCases).mock.calls.length;
 await act(async () => { stream({status:'features_extracted'} as any); });
 expect(api.fetchCases).toHaveBeenCalledTimes(reads);
 vi.mocked(api.fetchCases).mockRejectedValueOnce(new Error('ERR_NETWORK_CHANGED'));
 await act(async () => { stream({status:'ready'} as any); });
 expect(screen.getByRole('button',{name:/#e-second/})).toHaveAttribute('aria-pressed','true');
});

it('retains a selected case across a failed manual queue refresh and retry', async () => {
 const second = { ...item, id: 'case-second', driver_name: 'Second driver' };
 vi.mocked(api.fetchCases).mockResolvedValue({items:[item,second],total:2,limit:50,offset:0});
 vi.mocked(api.fetchCaseDetail).mockImplementation(async (id) => ({...detail,case:id === second.id ? second : item}));
 render(<CockpitWorkspaceView />);
 await openCustomer(); await screen.findByText('I am at the pickup');
 fireEvent.click(screen.getByRole('button',{name:/#e-second/}));
 vi.mocked(api.fetchCases).mockRejectedValueOnce(new Error('ERR_NETWORK_CHANGED'));
 fireEvent.click(screen.getByRole('button',{name:'Refresh cases'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('ERR_NETWORK_CHANGED');
 fireEvent.click(screen.getByRole('button',{name:'Retry'}));
 await waitFor(() => expect(screen.getByRole('button',{name:/#e-second/})).toHaveAttribute('aria-pressed','true'));
});
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.fetchCases).mockResolvedValue({items:[item],total:1,limit:50,offset:0}); vi.mocked(api.fetchCaseDetail).mockResolvedValue(detail); vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({id:'analyst-real',name:'Analyst',role:'analyst'}); vi.mocked(api.fetchAgentSession).mockResolvedValue({session_id:'session-empty',messages:[]}); vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any); vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any); });
describe('API cockpit', () => {
 it('shows loading without a seeded case before API resolves', () => {
  vi.mocked(api.fetchCases).mockReturnValue(new Promise(() => {})); render(<CockpitWorkspaceView />);
  expect(screen.getByText('Loading workspace')).toBeInTheDocument(); expect(screen.queryByText('#FC-8921')).not.toBeInTheDocument();
 });
 it('renders case detail before a delayed optional forensic brief resolves', async () => {
  let resolveBrief!: (brief: Awaited<ReturnType<typeof api.fetchForensicBrief>>) => void;
  vi.mocked(api.fetchForensicBrief).mockReturnValue(new Promise((resolve) => { resolveBrief = resolve; }));
  render(<CockpitWorkspaceView />);
  await openCustomer();
  expect(await screen.findByText('I am at the pickup')).toBeInTheDocument();
  openFinalization();
  const rationaleBox = await screen.findByLabelText('Decision rationale') as HTMLTextAreaElement;
  expect(rationaleBox.value).toBe('');
  expect(api.fetchForensicBrief).toHaveBeenCalledWith(item.id);
  await act(async () => resolveBrief({ case_id: item.id, generated_at: '2026-10-10T08:00:00Z', abnormalities: [], abnormality_count: 0, evidence_sources: [], summary_text: 'Brief arrives after the map detail.' }));
  await waitFor(() => expect(rationaleBox.value).toBe('Brief arrives after the map detail.'));
 });
 it('keeps case detail usable when the optional brief call throws synchronously', async () => {
  vi.mocked(api.fetchForensicBrief).mockImplementation(() => { throw new Error('Optional brief unavailable'); });
  render(<CockpitWorkspaceView />);
  await openCustomer();
  expect(await screen.findByText('I am at the pickup')).toBeInTheDocument();
  await waitFor(() => expect(api.fetchForensicBrief).toHaveBeenCalledWith(item.id));
  expect(screen.queryByText('Optional brief unavailable')).not.toBeInTheDocument();
 });
 it('shows empty queue and retryable API failures', async () => {
  vi.mocked(api.fetchCases).mockRejectedValueOnce(new Error('Unavailable')); render(<CockpitWorkspaceView />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');
  vi.mocked(api.fetchCases).mockResolvedValueOnce({items:[],total:0,limit:50,offset:0}); fireEvent.click(screen.getByRole('button',{name:'Retry'}));
  expect(await screen.findByText('No available cases')).toBeInTheDocument();
 });
 it('shows stored conversation and submits AGREE from send menu', async () => {
  const turnId = '018f2f4e-a000-7000-8000-000000000010';
  vi.mocked(api.fetchAgentSession).mockResolvedValue({session_id:'session-1',messages:[
   {id:'user-message',turn_id:turnId,role:'user',content:'Review the trip evidence',created_at:'2026-09-25T01:00:00Z'},
   {id:'assistant-message',turn_id:turnId,role:'assistant',content:'Evidence supports the policy finding.',created_at:'2026-09-25T01:00:03Z'},
  ]});
  vi.mocked(api.adjudicateCase).mockResolvedValue({case_id:item.id,outcome:'AGREE',status:'adjudicated',adjudicated_at:'',new_version:5}); render(<CockpitWorkspaceView />); await openCustomer();
  expect(await screen.findByText('Evidence supports the policy finding.')).toBeInTheDocument();
  openFinalization();
  fireEvent.change(screen.getByLabelText('Decision rationale'),{target:{value:'Confirmed against trip evidence'}});
  fireEvent.click(screen.getByRole('button',{name:'Approve conclusion'}));
  await waitFor(() => expect(api.adjudicateCase).toHaveBeenCalledWith(item.id,expect.objectContaining({outcome:'AGREE',analyst_id:'analyst-real',expected_case_version:4,agent_turn_id:turnId})));
 });
 it('pre-populates Decision rationale box with objective forensic_brief summary_text on case load', async () => {
  const briefSummary = 'Forensic Brief (Case case-real): 2 observed abnormalities: Stationary duration recorded at 240s (threshold >= 180s); Passenger cancelled trip.';
  vi.mocked(api.fetchCaseDetail).mockResolvedValueOnce({
   ...detail,
   forensic_brief: {
    case_id: item.id,
    trip_id: 'trip-1',
    driver_id: 'drv-1',
    category: 'intentional_dic',
    abnormalities: [
     { code: 'STATIONARY_STALL', field: 'stationary_duration_seconds', observed_value: 240, threshold_or_baseline: '>= 180s', description: 'Stationary duration recorded at 240s (threshold >= 180s).' }
    ],
    telemetry_summary: { sample_count: 8, stationary_duration_seconds: 240 },
    trip_context: { status: 'cancelled', cancel_actor: 'passenger' },
    guardrail_observations: [],
    summary_text: briefSummary,
   },
  } as any);
  render(<CockpitWorkspaceView />);
  await openCustomer();
  await screen.findByText('I am at the pickup');
  openFinalization();
  const rationaleBox = screen.getByLabelText('Decision rationale') as HTMLTextAreaElement;
  expect(rationaleBox.value).toBe(briefSummary);
 });
 it('restores the persisted case agent session without mock messages', async () => {
  vi.mocked(api.fetchAgentSession).mockResolvedValue({session_id:'session-1',messages:[
   {id:'message-1',turn_id:'turn-1',role:'user',content:'What happened on this trip?',created_at:'2026-09-25T01:00:00Z'},
   {id:'message-2',turn_id:'turn-1',role:'assistant',content:'The trip started at the recorded pickup.',created_at:'2026-09-25T01:00:03Z'},
  ]});
  render(<CockpitWorkspaceView />);
  expect(await screen.findByText('The trip started at the recorded pickup.')).toBeInTheDocument();
  expect(screen.getByText('What happened on this trip?')).toBeInTheDocument();
  expect(api.fetchAgentSession).toHaveBeenCalledWith(item.id);
  expect(screen.queryByText('AI Policy Copilot')).not.toBeInTheDocument();
  expect(screen.queryByText(/Verified Citations/)).not.toBeInTheDocument();
 });
 it('keeps network errors visible without claiming an offline success', async () => {
  vi.mocked(api.adjudicateCase).mockRejectedValue(new Error('Failed to fetch')); render(<CockpitWorkspaceView />); await openCustomer(); await screen.findByText('I am at the pickup'); openFinalization();
  fireEvent.change(screen.getByLabelText('Decision rationale'),{target:{value:'Evidence reviewed'}}); fireEvent.click(screen.getByRole('button',{name:'Dismiss'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch'); expect(screen.queryByText(/ngoại tuyến/)).not.toBeInTheDocument(); expect(screen.getAllByText('Driver persisted').length).toBeGreaterThan(0);
 });
});

it('submits Request More Evidence as evidence request', async () => {
 vi.mocked(api.recordCaseAction).mockResolvedValue({case_id:item.id,action_type:'REQUEST_EVIDENCE',status:'recorded',recorded_at:'',new_case_status:'waiting'});
 render(<CockpitWorkspaceView />); await openCustomer(); await screen.findByText('I am at the pickup'); openFinalization();
 fireEvent.change(screen.getByLabelText('Decision rationale'),{target:{value:'Need pickup recording'}});
 fireEvent.click(screen.getByRole('button',{name:'Request evidence'}));
 await waitFor(()=>expect(api.recordCaseAction).toHaveBeenCalledWith(item.id,expect.objectContaining({action_type:'REQUEST_EVIDENCE'})));
});
it('keeps queue membership authoritative in the API response', async () => {
 vi.mocked(api.fetchCases).mockResolvedValue({items:[],total:0,limit:50,offset:0});
 render(<CockpitWorkspaceView />); expect(await screen.findByText('No available cases')).toBeInTheDocument();
 expect(screen.queryByText('Driver persisted')).not.toBeInTheDocument();
});

it('renders tool calls with Vietnamese labels from tool-labels and collapsible summary in cockpit view', async () => {
  vi.mocked(api.fetchAgentSession).mockResolvedValueOnce({
    session_id: 'session-tools',
    messages: [
      {
        id: 'msg-tool-1',
        turn_id: '018f2f4e-a000-7000-8000-000000000010',
        role: 'assistant',
        content: 'Policy clause 5.2 applies.',
        created_at: '2026-10-10T08:00:00Z',
        parts: [
          {
            type: 'tool-invocation',
            toolName: 'get_forensic_brief',
            toolCallId: 'tc-1',
            state: 'result',
            output: {},
          },
          {
            type: 'tool-invocation',
            toolName: 'get_driver_history',
            toolCallId: 'tc-2',
            state: 'result',
            output: {},
          },
          {
            type: 'text',
            text: 'Policy clause 5.2 applies.',
          },
        ],
      } as any,
    ],
  });

  render(<CockpitWorkspaceView />);
  await openCustomer(); await screen.findByText('I am at the pickup');

  // Verify collapsed summary row "Đã dùng 2 công cụ"
  const trigger = await screen.findByRole('button', { name: /Đã dùng 2 công cụ/i });
  expect(trigger).toBeInTheDocument();

  // Click to expand
  fireEvent.click(trigger);

  // Verify Vietnamese labels from tool-labels
  expect(await screen.findByText('Đã tóm tắt vụ việc')).toBeInTheDocument();
  expect(screen.getByText('Đã tải lịch sử tài xế')).toBeInTheDocument();
  expect(screen.getByText('Policy clause 5.2 applies.')).toBeInTheDocument();
});

it.each(['Disagree', 'Agree'])('refreshes the active queue after committed %s even when detail reload fails', async (action) => {
 vi.mocked(api.adjudicateCase).mockResolvedValue({case_id:item.id,outcome:'DISAGREE',status:'adjudicated',adjudicated_at:'',new_version:5});
 render(<CockpitWorkspaceView />);
 await openCustomer(); await screen.findByText('I am at the pickup');
 vi.mocked(api.fetchCases).mockResolvedValue({items:[],total:0,limit:50,offset:0});
 vi.mocked(api.fetchCaseDetail).mockRejectedValue(new Error('Detail temporarily unavailable'));
 openFinalization(); fireEvent.change(screen.getByLabelText('Decision rationale'),{target:{value:'Evidence reviewed and dismissal confirmed'}});
 fireEvent.click(screen.getByRole('button',{name:action === 'Approve' ? 'Approve conclusion' : 'Dismiss'}));
 expect(await screen.findByText('No available cases')).toBeInTheDocument();
 expect(screen.queryByText('Driver persisted')).not.toBeInTheDocument();
});

it('focuses on initialCaseId parameter and fetches detail even if not head of queue', async () => {
  const targetItem = { ...item, id: 'case-url-target', driver_name: 'Target Driver' };
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [item], total: 1, limit: 50, offset: 0 });
  vi.mocked(api.fetchCaseDetail).mockImplementation(async (id) => ({
    ...detail,
    case: id === targetItem.id ? targetItem : item,
    conversation: [{ role: 'driver' as const, text: `Message for ${id}`, occurred_at: '2026-10-12T00:00:00Z' }],
  }));
  render(<CockpitWorkspaceView initialCaseId={targetItem.id} />);
  await openCustomer();
  expect(await screen.findByText(`Message for ${targetItem.id}`)).toBeInTheDocument();
});

it('allocates at least 70vh to center workspace on mobile and maintains desktop lg classes', async () => {
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [item], total: 1, limit: 50, offset: 0 });
  vi.mocked(api.fetchCaseDetail).mockResolvedValue(detail as any);
  const { container } = render(<CockpitWorkspaceView />);
  const triageSection = await screen.findByRole('region', { name: 'Triage queue' });
  expect(triageSection.classList.contains('shrink-0')).toBe(true);

  const workspaceSection = await screen.findByRole('region', { name: 'Case workspace' });
  expect(workspaceSection.className).toContain('min-h-[70vh]');
  expect(workspaceSection.className).toContain('lg:min-h-0');
  expect(workspaceSection.className).toContain('lg:h-full');
  expect(workspaceSection.className).toContain('min-w-0');
  expect(workspaceSection.classList.contains('shrink-0')).toBe(true);

});
