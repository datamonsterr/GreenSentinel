import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { requestJson as unboundedRequestJson, setApiTokenProvider } from '@/lib/api-client';

const requestJson = (url: string, options?: RequestInit) => unboundedRequestJson(url, options, 15_000);
const never = () => new Promise<never>(() => {});
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

describe('JSON request deadline', () => {
  beforeEach(() => { vi.useFakeTimers(); setApiTokenProvider(null); });
  afterEach(() => { setApiTokenProvider(null); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it.each(['token', 'fetch', 'body', 'refresh'] as const)('settles a stalled %s within the deadline', async (stage) => {
    const fetchMock = vi.fn().mockResolvedValue(response({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    if (stage === 'token') setApiTokenProvider(never);
    if (stage === 'fetch') fetchMock.mockImplementation(never);
    if (stage === 'body') fetchMock.mockResolvedValue({ ok: true, status: 200, json: never });
    if (stage === 'refresh') {
      setApiTokenProvider(vi.fn().mockResolvedValueOnce('token').mockImplementation(never));
      fetchMock.mockResolvedValue(response({}, 401));
    }
    let failure: unknown;
    void requestJson('/actions').catch(error => { failure = error; });
    await vi.advanceTimersByTimeAsync(15_000);
    expect(failure).toMatchObject({ name: 'TimeoutError' });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('keeps its deadline when a caller supplies a signal', async () => {
    const external = new AbortController();
    const fetchMock = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(never);
    vi.stubGlobal('fetch', fetchMock);
    let failure: unknown;
    void requestJson('/actions', { signal: external.signal }).catch(error => { failure = error; });
    await vi.advanceTimersByTimeAsync(15_000);
    expect(failure).toMatchObject({ name: 'TimeoutError' });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(external.signal.aborted).toBe(false);
  });

  it('honors caller cancellation and removes its listener and timer', async () => {
    const external = new AbortController();
    const remove = vi.spyOn(external.signal, 'removeEventListener');
    vi.stubGlobal('fetch', vi.fn(never));
    const request = requestJson('/actions', { signal: external.signal });
    const result = expect(request).rejects.toMatchObject({ name: 'AbortError' });
    external.abort();
    await result;
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not send a mutation when authentication resolves after timeout', async () => {
    let resolveToken!: (token: string) => void;
    setApiTokenProvider(() => new Promise(resolve => { resolveToken = resolve; }));
    const fetchMock = vi.fn().mockResolvedValue(response({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    let failure: unknown;
    void requestJson('/actions', { method: 'POST' }).catch(error => { failure = error; });
    await vi.advanceTimersByTimeAsync(15_000);
    resolveToken('late-token');
    await vi.advanceTimersByTimeAsync(0);
    expect(failure).toMatchObject({ name: 'TimeoutError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('preserves HTTP error details and clears successful request timers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ detail: 'Claim expired' }, 409)).mockResolvedValueOnce(response({ id: 'saved' })));
    await expect(requestJson('/actions')).rejects.toThrow('API Error 409: Claim expired');
    await expect(requestJson('/actions')).resolves.toEqual({ id: 'saved' });
    expect(vi.getTimerCount()).toBe(0);
  });
});
