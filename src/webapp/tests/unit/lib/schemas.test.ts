import { describe, it, expect } from "vitest";
import {
  mockDriverExplanationEvent,
  mockPassengerCancelEvent,
  mockAiAssessmentEvent,
  mockTelemetryEvents,
  primaryAdjudicationCase,
} from "@/tests/fixtures/mock-data";
import { DomainEvent, TelemetryEvent } from "@/types/schemas";

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DATE_REGEX =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

describe("Domain Event Schema Compliance (domain-event.schema.json)", () => {
  const events: DomainEvent[] = [
    mockDriverExplanationEvent,
    mockPassengerCancelEvent,
    mockAiAssessmentEvent,
  ];

  events.forEach((evt) => {
    it(`should validate required fields and types for event ${evt.event_type}`, () => {
      expect(evt.schema_version).toBe(1);
      expect(evt.event_id).toMatch(UUID_REGEX);
      expect(evt.aggregate_id).toMatch(UUID_REGEX);
      expect(evt.correlation_id).toMatch(UUID_REGEX);
      expect(evt.occurred_at).toMatch(ISO_DATE_REGEX);
      expect(evt.aggregate_version).toBeGreaterThanOrEqual(1);

      expect([
        "trip.requested",
        "assignment.offered",
        "assignment.accepted",
        "traffic.observed",
        "passenger.cancelled",
        "passenger.feedback_submitted",
        "driver.explanation_submitted",
        "case.evidence_updated",
        "assessment.completed",
        "case.ready",
        "case.adjudicated",
        "sanction.approved",
      ]).toContain(evt.event_type);

      expect(["trip", "assignment", "case", "assessment", "sanction"]).toContain(
        evt.aggregate_type
      );

      expect(["passenger", "driver", "analyst", "service", "simulator"]).toContain(
        evt.actor.type
      );
      expect(evt.actor.id.length).toBeGreaterThanOrEqual(1);
      expect(evt.payload).toBeTypeOf("object");
    });
  });
});

describe("Telemetry Event Schema Compliance (telemetry-event.schema.json)", () => {
  mockTelemetryEvents.forEach((tEvt: TelemetryEvent) => {
    it(`should validate telemetry event sequence ${tEvt.sequence}`, () => {
      expect(tEvt.schema_version).toBe(1);
      expect(tEvt.event_id).toMatch(UUID_REGEX);
      expect(tEvt.trip_id).toMatch(UUID_REGEX);
      expect(tEvt.assignment_id).toMatch(UUID_REGEX);
      expect(tEvt.driver_id).toMatch(UUID_REGEX);
      expect(tEvt.correlation_id).toMatch(UUID_REGEX);
      expect(tEvt.occurred_at).toMatch(ISO_DATE_REGEX);
      expect(tEvt.sequence).toBeGreaterThanOrEqual(0);

      expect([
        "telemetry.observed",
        "driver.app_crashed",
        "driver.network_changed",
      ]).toContain(tEvt.event_type);

      const payload = tEvt.payload;
      expect(["foreground", "background", "crashed", "unknown"]).toContain(
        payload.app_state
      );
      expect(["online", "offline", "degraded", "unknown"]).toContain(
        payload.network_state
      );
      expect([
        "valid",
        "jitter",
        "unavailable",
        "mock_reported",
        "unknown",
      ]).toContain(payload.gps_state);

      if (payload.position) {
        expect(payload.position.latitude).toBeGreaterThanOrEqual(-90);
        expect(payload.position.latitude).toBeLessThanOrEqual(90);
        expect(payload.position.longitude).toBeGreaterThanOrEqual(-180);
        expect(payload.position.longitude).toBeLessThanOrEqual(180);
        if (payload.position.accuracy_m !== null) {
          expect(payload.position.accuracy_m).toBeGreaterThanOrEqual(0);
        }
      }
    });
  });
});

describe("Adjudication Case Invariants", () => {
  it("should have consistent trip and driver references between case and events", () => {
    expect(primaryAdjudicationCase.trip_id).toBe(
      mockPassengerCancelEvent.aggregate_id
    );
    expect(primaryAdjudicationCase.dispute.driver_explanation).toBeDefined();
    expect(primaryAdjudicationCase.dispute.passenger_cancel).toBeDefined();
    expect(primaryAdjudicationCase.telemetry_points.length).toBeGreaterThan(0);
    expect(primaryAdjudicationCase.ai_assessment?.payload.confidence_pct).toBe(92);
  });
});
