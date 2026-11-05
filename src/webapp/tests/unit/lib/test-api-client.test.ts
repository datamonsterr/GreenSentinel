import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import {
  cancelTestRun,
  controlTestRun,
  fetchTestPresets,
  fetchTestRunOverview,
  fetchTestRuns,
  setTestApiTokenProvider,
  updateTestRunTitle,
} from '@/lib/testApiClient';

const ORG = 'run-123';

function mockJson(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => mockJson({}));
  vi.stubGlobal('fetch', fetchMock);
  setTestApiTokenProvider(async () => 'session-token');
});

afterEach(() => {
  vi.unstubAllGlobals();
  setTestApiTokenProvider(null);
});

function lastCall() {
  return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

test('fetchTestRuns lists org history through the test boundary', async () => {
  fetchMock.mockResolvedValueOnce(mockJson([{ id: ORG, title: 'Trip', status: 'COMPLETED' }]));
  const rows = await fetchTestRuns(10);
  expect(rows[0].id).toBe(ORG);
  const [url, init] = lastCall();
  expect(url).toContain('/runs?limit=10');
  expect((init.headers as Headers).get('X-Test-Context')).toBe('true');
  expect((init.headers as Headers).get('Authorization')).toBe('Bearer session-token');
});

test('updateTestRunTitle issues a PATCH with the new title', async () => {
  fetchMock.mockResolvedValueOnce(mockJson({ id: ORG, title: 'Renamed' }));
  const run = await updateTestRunTitle(ORG, 'Renamed');
  expect(run.title).toBe('Renamed');
  const [url, init] = lastCall();
  expect(url).toContain(`/runs/${ORG}`);
  expect(init.method).toBe('PATCH');
  expect(JSON.parse(init.body as string)).toEqual({ title: 'Renamed' });
});

test('fetchTestRunOverview reads recorded pipeline evidence', async () => {
  fetchMock.mockResolvedValueOnce(
    mockJson({ run_id: ORG, trips_input: 1, trips_processed: 1, trips_classified: 0, classification_counts: {}, stages: [] })
  );
  const overview = await fetchTestRunOverview(ORG);
  expect(overview.trips_input).toBe(1);
  expect(lastCall()[0]).toContain(`/runs/${ORG}/overview`);
});

test('cancelTestRun sends the canonical actor and trimmed reason', async () => {
  fetchMock.mockResolvedValueOnce(mockJson({ status: 'accepted', command: 'CANCEL' }));
  await cancelTestRun(ORG, 'passenger', '  Customer changed plan  ');
  const [url, init] = lastCall();
  expect(url).toContain(`/runs/${ORG}/controls`);
  expect(init.method).toBe('POST');
  expect(JSON.parse(init.body as string)).toEqual({
    command: 'CANCEL',
    payload: { actor: 'passenger', reason: 'Customer changed plan' },
  });
});

test('cancelTestRun refuses a blank reason before any request', async () => {
  await expect(cancelTestRun(ORG, 'driver', '   ')).rejects.toThrow(/reason is required/i);
  expect(fetchMock).not.toHaveBeenCalled();
});

test('controlTestRun posts pause and resume commands', async () => {
  fetchMock.mockResolvedValue(mockJson({ status: 'accepted', command: 'PAUSE' }));
  await controlTestRun(ORG, 'PAUSE');
  expect(JSON.parse(lastCall()[1].body as string)).toEqual({ command: 'PAUSE', payload: {} });
});

test('fetchTestPresets returns the published library with availability', async () => {
  fetchMock.mockResolvedValueOnce(
    mockJson({
      presets: [{ id: 'default', title: 'Default', available: true, sample_trips: [] }],
      source: { revision: '914a3656' },
    })
  );
  const library = await fetchTestPresets(3);
  expect(library.presets[0].id).toBe('default');
  expect(lastCall()[0]).toContain('/presets?sample_limit=3');
});

test('testAuthorizedHeaders awaits deferred token provider registration before sending request', async () => {
  setTestApiTokenProvider(null);
  fetchMock.mockResolvedValueOnce(mockJson({ ok: true }));

  // Simulate late registration of token provider (e.g. Clerk loading race)
  setTimeout(() => {
    setTestApiTokenProvider(async () => 'late-registered-token');
  }, 50);

  await fetchTestPresets(1);
  const [, init] = lastCall();
  expect((init.headers as Headers).get('Authorization')).toBe('Bearer late-registered-token');
});
