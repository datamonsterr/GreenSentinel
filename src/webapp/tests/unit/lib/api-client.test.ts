import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchCases,
  fetchCaseDetail,
  claimCase,
  releaseCase,
  recordCaseAction,
  adjudicateCase,
  streamCaseProgress,
  streamPolicyChat,
  triggerSimulation,
  chatWithAgent,
  getApiHealth,
  getApiBaseUrl,
  setApiTokenProvider,
  getDriverDisputeContext,
  sendDriverChat,
  streamDriverChat,
  delegateAnalystInquiry,
  getDisputeDossier,
} from "@/lib/api-client";
import {
  CaseProgressEvent,
  PolicyCitationEvent,
} from "@/types/schemas";

function createSseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;

  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index++;
      } else {
        controller.close();
      }
    },
  });
}

describe("api-client", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    setApiTokenProvider(null);
  });

  it("sends a fresh Clerk session token on JSON and SSE requests", async () => {
    const tokenProvider = vi.fn().mockResolvedValueOnce("session-one").mockResolvedValueOnce("session-two");
    setApiTokenProvider(tokenProvider);
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [], total: 0 }) })
      .mockResolvedValueOnce({ ok: true, body: createSseStream([]) });

    await fetchCases();
    streamCaseProgress("case-1", () => undefined);
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].headers.get("Authorization")).toBe("Bearer session-one");
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls[1][1].headers.get("Authorization")).toBe("Bearer session-two");
    expect(tokenProvider).toHaveBeenCalledTimes(2);
  });

  it("resolves default API base URL", () => {
    expect(getApiBaseUrl()).toBe("");
  });

  describe("fetchCases", () => {
    it("fetches cases with query parameters", async () => {
      const mockResponse = {
        items: [
          {
            id: "case-001",
            status: "OPEN",
            priority: "P0",
            priority_score: 98,
            version: 1,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const res = await fetchCases("OPEN", "P0", 50, 0);

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases?status=OPEN&priority=P0&limit=50&offset=0",
        expect.objectContaining({ method: "GET" })
      );
      expect(res).toEqual(mockResponse);
    });

    it("fetches cases with options object", async () => {
      const mockResponse = { items: [], total: 0, limit: 10, offset: 5 };
      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const res = await fetchCases({ status: "ESCALATED", limit: 10, offset: 5 });

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases?status=ESCALATED&limit=10&offset=5",
        expect.objectContaining({ method: "GET" })
      );
      expect(res.total).toBe(0);
    });

    it("throws detailed error when response is not ok", async () => {
      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({ detail: "Database connection failed" }),
      });

      await expect(fetchCases()).rejects.toThrow("API Error 500: Database connection failed");
    });
  });

  describe("fetchCaseDetail", () => {
    it("fetches case detail for given case id", async () => {
      const mockDetail = {
        case: { id: "case-8921", status: "UNDER_REVIEW", priority: "P0", priority_score: 92, version: 1 },
        trip: { fare_amount_vnd: 340000, driver_name: "Nguyễn Văn A" },
        telemetry_samples: [],
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockDetail,
      });

      const res = await fetchCaseDetail("case-8921");

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-8921",
        expect.objectContaining({ method: "GET" })
      );
      expect(res.case.id).toBe("case-8921");
      expect(res.trip?.driver_name).toBe("Nguyễn Văn A");
    });
  });

  describe("claimCase", () => {
    it("sends claim request with positional arguments", async () => {
      const mockClaimRes = {
        case_id: "case-8921",
        analyst_id: "analyst-01",
        lease_expires_at: "2026-09-22T08:30:00Z",
        status: "CLAIMED",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockClaimRes,
      });

      const res = await claimCase("case-8921", "analyst-01", 600);

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-8921/claim",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ analyst_id: "analyst-01", lease_duration_seconds: 600 }),
        })
      );
      expect(res.status).toBe("CLAIMED");
    });

    it("sends claim request with object payload", async () => {
      const mockClaimRes = {
        case_id: "case-8921",
        analyst_id: "analyst-02",
        lease_expires_at: "2026-09-22T08:35:00Z",
        status: "CLAIMED",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockClaimRes,
      });

      const res = await claimCase("case-8921", { analyst_id: "analyst-02", lease_duration_seconds: 300 });

      expect(res.analyst_id).toBe("analyst-02");
    });
  });

  describe("releaseCase", () => {
    it("sends release request with positional arguments", async () => {
      const mockReleaseRes = {
        case_id: "case-8921",
        status: "RELEASED",
        analyst_id: "analyst-01",
        released_at: "2026-09-22T08:35:00Z",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockReleaseRes,
      });

      const res = await releaseCase("case-8921", "analyst-01", "analyst", false);

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-8921/release",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ analyst_id: "analyst-01", role: "analyst", force: false }),
        })
      );
      expect(res.status).toBe("RELEASED");
      expect(res.analyst_id).toBe("analyst-01");
    });

    it("sends release request with object payload", async () => {
      const mockReleaseRes = {
        case_id: "case-8921",
        status: "RELEASED",
        analyst_id: "admin-01",
        released_at: "2026-09-22T08:35:00Z",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockReleaseRes,
      });

      const res = await releaseCase("case-8921", { analyst_id: "admin-01", role: "admin", force: true });

      expect(res.analyst_id).toBe("admin-01");
    });
  });

  describe("recordCaseAction", () => {
    it("records analyst action", async () => {
      const mockActionRes = {
        case_id: "case-8921",
        action_type: "REQUEST_EVIDENCE",
        status: "RECORDED",
        recorded_at: "2026-09-22T08:15:00Z",
        new_case_status: "PENDING_EVIDENCE",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockActionRes,
      });

      const res = await recordCaseAction("case-8921", {
        action_type: "REQUEST_EVIDENCE",
        analyst_id: "analyst-01",
        notes: "Requesting additional OBD logs",
      });

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-8921/actions",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            action_type: "REQUEST_EVIDENCE",
            analyst_id: "analyst-01",
            notes: "Requesting additional OBD logs",
          }),
        })
      );
      expect(res.new_case_status).toBe("PENDING_EVIDENCE");
    });
  });

  describe("adjudicateCase", () => {
    it("submits case adjudication", async () => {
      const mockAdjRes = {
        case_id: "case-8921",
        outcome: "AGREE",
        status: "ADJUDICATED",
        sanction_applied: null,
        adjudicated_at: "2026-09-22T08:20:00Z",
        new_version: 2,
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockAdjRes,
      });

      const res = await adjudicateCase("case-8921", {
        outcome: "AGREE",
        analyst_id: "analyst-01",
        rationale: "Vi phạm cố ý đỗ chờ ép hủy theo Điều 14.2",
        expected_case_version: 1,
      });

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-8921/adjudicate",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            outcome: "AGREE",
            analyst_id: "analyst-01",
            rationale: "Vi phạm cố ý đỗ chờ ép hủy theo Điều 14.2",
            expected_case_version: 1,
          }),
        })
      );
      expect(res.new_version).toBe(2);
    });
  });

  describe("streamCaseProgress", () => {
    it("streams case progress events through SSE", async () => {
      const events: CaseProgressEvent[] = [];
      const ssePayload = [
        `event: case_progress\ndata: {"case_id":"c1","status":"telemetry_ingested","progress":20,"message":"Telemetry aligned","timestamp":"2026-09-22T08:00:00Z"}\n\n`,
        `event: case_progress\ndata: {"case_id":"c1","status":"ready","progress":100,"message":"Case ready","timestamp":"2026-09-22T08:00:05Z"}\n\n`,
      ];

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        body: createSseStream(ssePayload),
      });

      await new Promise<void>((resolve) => {
        streamCaseProgress(
          "c1",
          (data) => {
            events.push(data);
            if (events.length === 2) {
              resolve();
            }
          },
          (err) => {
            throw err;
          }
        );
      });

      expect(events).toHaveLength(2);
      expect(events[0].progress).toBe(20);
      expect(events[1].status).toBe("ready");
    });
  });

  describe("streamPolicyChat", () => {
    it("streams delta and citation events and signals done", async () => {
      const citations: PolicyCitationEvent[] = [];
      let fullText = "";
      let isDone = false;
      let doneCount = 0;

      const ssePayload = [
        `event: citation\ndata: {"source":"GreenSM Policy 2026","section":"Điều 14.2","content":"Quy chế xử phạt"}\n\n`,
        `event: text_delta\ndata: {"delta":"Căn cứ "}\n\n`,
        `event: text_delta\ndata: {"delta":"Điều 14.2"}\n\n`,
        `event: done\ndata: {"status":"completed"}\n\n`,
      ];

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        body: createSseStream(ssePayload),
      });

      await new Promise<void>((resolve) => {
        streamPolicyChat(
          {
            query: "Điều 14.2 thế nào?",
            case_id: "018f2f4e-a000-7000-8000-000000000001",
            turn_id: "018f2f4e-a000-7000-8000-000000000010",
          },
          (delta) => {
            fullText += delta;
          },
          (citation) => {
            citations.push(citation);
          },
          () => {
            isDone = true;
            doneCount += 1;
            resolve();
          }
        );
      });

      expect(citations).toHaveLength(1);
      expect(citations[0].section).toBe("Điều 14.2");
      expect(fullText).toBe("Căn cứ Điều 14.2");
      expect(isDone).toBe(true);
      expect(doneCount).toBe(1);
    });

    it("recovers from 401 Invalid Clerk session by refreshing token with skipCache and retrying", async () => {
      const tokenProvider = vi
        .fn()
        .mockResolvedValueOnce("expired-token")
        .mockResolvedValueOnce("fresh-token");
      setApiTokenProvider(tokenProvider);

      let fullText = "";
      let isDone = false;

      const ssePayload = [
        `event: text_delta\ndata: {"delta":"Refreshed stream response"}\n\n`,
        `event: done\ndata: {"status":"completed"}\n\n`,
      ];

      // First call fails with 401, retry succeeds with 200 SSE
      global.fetch = vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          statusText: "Unauthorized",
          json: async () => ({ detail: "Invalid Clerk session" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          body: createSseStream(ssePayload),
        });

      await new Promise<void>((resolve, reject) => {
        streamPolicyChat(
          {
            query: "Tin nhắn mới sau khi hết hạn phiên",
            case_id: "018f2f4e-a000-7000-8000-000000000001",
            turn_id: "018f2f4e-a000-7000-8000-000000000002",
          },
          (delta) => {
            fullText += delta;
          },
          undefined,
          () => {
            isDone = true;
            resolve();
          },
          (err) => reject(err)
        );
      });

      expect(fullText).toBe("Refreshed stream response");
      expect(isDone).toBe(true);
      // tokenProvider called first time, then second time with { skipCache: true }
      expect(tokenProvider).toHaveBeenCalledTimes(2);
      expect(tokenProvider).toHaveBeenNthCalledWith(2, { skipCache: true });
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it("completes a multi-turn conversation of 5 messages even when token expires during conversation", async () => {
      let tokenCounter = 0;
      const tokenProvider = vi.fn().mockImplementation(async (opts?: { skipCache?: boolean }) => {
        tokenCounter++;
        return `token-${tokenCounter}`;
      });
      setApiTokenProvider(tokenProvider);

      const conversationMessages = [
        "Xin chào trợ lý",
        "Tóm tắt vụ việc này",
        "Có bằng chứng nào bất thường không?",
        "Tài xế đã giải trình gì?",
        "Kết luận và đề xuất xử lý",
      ];

      // Mock fetch: on message 2, the first attempt returns 401, then retries and succeeds.
      // Other messages succeed on first attempt.
      const mockFetch = vi.fn();
      for (let i = 0; i < conversationMessages.length; i++) {
        if (i === 1) {
          // Message 2: 401 first, then 200
          mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 401,
            json: async () => ({ detail: "Invalid Clerk session" }),
          });
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            body: createSseStream([
              `event: text_delta\ndata: {"delta":"Trả lời ${i + 1}"}\n\n`,
              `event: done\ndata: {"status":"completed"}\n\n`,
            ]),
          });
        } else {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            body: createSseStream([
              `event: text_delta\ndata: {"delta":"Trả lời ${i + 1}"}\n\n`,
              `event: done\ndata: {"status":"completed"}\n\n`,
            ]),
          });
        }
      }
      global.fetch = mockFetch;

      const receivedAnswers: string[] = [];

      for (let i = 0; i < conversationMessages.length; i++) {
        let answer = "";
        await new Promise<void>((resolve, reject) => {
          streamPolicyChat(
            {
              query: conversationMessages[i],
              case_id: "018f2f4e-a000-7000-8000-000000000001",
              turn_id: `018f2f4e-a000-7000-8000-00000000000${i + 1}`,
            },
            (delta) => {
              answer += delta;
            },
            undefined,
            () => {
              receivedAnswers.push(answer);
              resolve();
            },
            (err) => reject(err)
          );
        });
      }

      expect(receivedAnswers).toHaveLength(5);
      expect(receivedAnswers).toEqual([
        "Trả lời 1",
        "Trả lời 2",
        "Trả lời 3",
        "Trả lời 4",
        "Trả lời 5",
      ]);
    });
  });

  describe("triggerSimulation", () => {
    it("triggers simulation scenario", async () => {
      const mockSimRes = {
        scenario: "gps_drift",
        case_id: "case-sim-101",
        status: "RUNNING",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockSimRes,
      });

      const res = await triggerSimulation("gps_drift", "analyst-01", 42);

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/simulations/gps_drift",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ analyst_id: "analyst-01", seed: 42 }),
        })
      );
      expect(res.case_id).toBe("case-sim-101");
    });
  });

  describe("chatWithAgent & getApiHealth", () => {
    it("calls legacy /api/v1/chat agent", async () => {
      const mockChatRes = {
        response: "Agent answer",
        analysis: "Internal step-by-step reasoning",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockChatRes,
      });

      const res = await chatWithAgent("Phân tích case");
      expect(res.response).toBe("Agent answer");
      expect(res.analysis).toBe("Internal step-by-step reasoning");
    });

    it("fetches API health status", async () => {
      const mockHealth = {
        status: "ok",
        env: "development",
        database: "connected",
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockHealth,
      });

      const res = await getApiHealth();
      expect(res.status).toBe("ok");
      expect(res.database).toBe("connected");
    });
  });

  describe("Driver Dispute & Cockpit A2A Methods", () => {
    it("fetches driver dispute context with driver_id header & query param", async () => {
      const mockContext = {
        case_id: "case-999",
        driver_id: "drv-123",
        driver_name: "Nguyễn Văn A",
        trip_id: "trip-001",
        violation_code: "ERR-02",
        violation_title: "Tài xế cố tình hủy chuyến",
        alleged_time: "2026-09-26T08:00:00Z",
        alleged_location: "Hà Nội",
        dispute_deadline: "2026-09-28T08:00:00Z",
        dispute_status: "not_disputed",
        allowed_claim_types: ["traffic_gridlock"],
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockContext,
      });

      const res = await getDriverDisputeContext("case-999", "drv-123");
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/driver/cases/case-999/dispute?driver_id=drv-123",
        expect.objectContaining({
          method: "GET",
          headers: expect.any(Headers),
        })
      );
      expect(res.case_id).toBe("case-999");
      expect(res.driver_name).toBe("Nguyễn Văn A");
    });

    it("sends driver chat statement", async () => {
      const mockChatRes = {
        case_id: "case-999",
        driver_id: "drv-123",
        reply: "Giải trình đã được tiếp nhận.",
        dispute_status: "in_dispute",
        is_auto_dismissed: false,
        exoneration_receipt: null,
        needs_analyst_review: true,
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockChatRes,
      });

      const res = await sendDriverChat("case-999", {
        case_id: "case-999",
        driver_id: "drv-123",
        message: "Xe bị thủng lốp",
        claim_type: "breakdown",
      });

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/driver/cases/case-999/chat",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            case_id: "case-999",
            driver_id: "drv-123",
            message: "Xe bị thủng lốp",
            claim_type: "breakdown",
          }),
        })
      );
      expect(res.dispute_status).toBe("in_dispute");
    });

    it("streams driver chat and resolves with completion event", async () => {
      const sseChunks = [
        'event: token\ndata: {"token":"Kẹt "}\n\n',
        'event: token\ndata: {"token":"xe "}\n\n',
        'event: done\ndata: {"case_id":"case-999","driver_id":"drv-123","reply":"Kẹt xe nghiêm trọng","dispute_status":"auto_dismissed","is_auto_dismissed":true,"exoneration_receipt":{"reason":"Lưu lượng cao"},"needs_analyst_review":false}\n\n',
      ];

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        body: createSseStream(sseChunks),
      });

      const tokens: string[] = [];
      const res = await streamDriverChat("case-999", "Bị kẹt xe", "traffic_gridlock", (token) => {
        tokens.push(token);
      });

      expect(tokens).toEqual(["Kẹt ", "xe "]);
      expect(res.is_auto_dismissed).toBe(true);
      expect(res.reply).toBe("Kẹt xe nghiêm trọng");
      expect(res.dispute_status).toBe("auto_dismissed");
    });

    it("delegates analyst inquiry to driver agent", async () => {
      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: "delegated", case_id: "case-999" }),
      });

      const res = await delegateAnalystInquiry("case-999", {
        case_id: "case-999",
        analyst_id: "analyst-001",
        instruction: "Vui lòng cung cấp hình ảnh",
      });

      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-999/delegate-inquiry",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            case_id: "case-999",
            analyst_id: "analyst-001",
            instruction: "Vui lòng cung cấp hình ảnh",
          }),
        })
      );
      expect(res.status).toBe("delegated");
    });

    it("fetches dispute dossier for a case", async () => {
      const mockDossier = {
        case_id: "case-999",
        driver_id: "drv-123",
        driver_name: "Nguyễn Văn A",
        dispute_status: "in_dispute",
        driver_statement: "Tắc đường",
        claim_type: "traffic_gridlock",
        traffic_corroboration: { ratio: 2.5 },
        precedent_score: 0.88,
        recommended_action: "Review",
        transcript: [],
      };

      global.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        json: async () => mockDossier,
      });

      const res = await getDisputeDossier("case-999");
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/v1/cases/case-999/dispute-dossier",
        expect.objectContaining({ method: "GET" })
      );
      expect(res.precedent_score).toBe(0.88);
      expect(res.recommended_action).toBe("Review");
    });
  });
});
