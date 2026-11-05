import { describe, it, expect } from "vitest";
import { parseEntityHref } from "@/lib/copilot/entity-links";

describe("parseEntityHref (copilot entity link parser)", () => {
  describe("case:// scheme", () => {
    it("parses valid case href", () => {
      expect(parseEntityHref("case://018f2f4e-a000-7000-8000-000000000001")).toEqual({
        type: "case",
        id: "018f2f4e-a000-7000-8000-000000000001",
      });
    });

    it("parses alphanumeric and hyphenated case ids", () => {
      expect(parseEntityHref("case://CASE-123-ABC")).toEqual({
        type: "case",
        id: "CASE-123-ABC",
      });
    });

    it("returns null on missing case id", () => {
      expect(parseEntityHref("case://")).toBeNull();
      expect(parseEntityHref("case:///")).toBeNull();
    });
  });

  describe("driver:// scheme", () => {
    it("parses valid driver href", () => {
      expect(parseEntityHref("driver://drv_98765")).toEqual({
        type: "driver",
        id: "drv_98765",
      });
    });

    it("returns null on missing driver id", () => {
      expect(parseEntityHref("driver://")).toBeNull();
      expect(parseEntityHref("driver:///")).toBeNull();
    });
  });

  describe("trip:// scheme", () => {
    it("parses trip with encoded pickup and destination", () => {
      const href = "trip://trip-789?pickup=H%C3%A0%20N%E1%BB%99i&dest=H%E1%BA%A3i%20Ph%C3%B2ng";
      const result = parseEntityHref(href);
      expect(result).toEqual({
        type: "trip",
        id: "trip-789",
        pickup: "Hà Nội",
        dest: "Hải Phòng",
      });
    });

    it("parses trip with empty pickup and dest params", () => {
      const href = "trip://trip-789?pickup=&dest=";
      const result = parseEntityHref(href);
      expect(result).toEqual({
        type: "trip",
        id: "trip-789",
        pickup: "",
        dest: "",
      });
    });

    it("parses trip without query params", () => {
      const result = parseEntityHref("trip://trip-789");
      expect(result).toEqual({
        type: "trip",
        id: "trip-789",
      });
    });

    it("returns null on missing trip id", () => {
      expect(parseEntityHref("trip://?pickup=A&dest=B")).toBeNull();
      expect(parseEntityHref("trip://")).toBeNull();
    });

    it("returns null on malformed percent encoding in trip params", () => {
      expect(parseEntityHref("trip://trip-123?pickup=%E0%B8%&dest=ok")).toBeNull();
    });
  });

  describe("policy:// scheme", () => {
    it("parses policy citation link like policy://c1", () => {
      const result = parseEntityHref("policy://c1");
      expect(result).toEqual({
        type: "policy",
        id: "c1",
        citationId: "c1",
      });
    });

    it("parses multi-digit policy citation link like policy://c12", () => {
      const result = parseEntityHref("policy://c12");
      expect(result).toEqual({
        type: "policy",
        id: "c12",
        citationId: "c12",
      });
    });

    it("returns null on missing policy id", () => {
      expect(parseEntityHref("policy://")).toBeNull();
    });
  });

  describe("malformed or unsupported hrefs", () => {
    it("returns null for non-entity protocols and strings", () => {
      expect(parseEntityHref("https://example.com")).toBeNull();
      expect(parseEntityHref("mailto:test@example.com")).toBeNull();
      expect(parseEntityHref("javascript:alert(1)")).toBeNull();
      expect(parseEntityHref("random_string")).toBeNull();
      expect(parseEntityHref("")).toBeNull();
      expect(parseEntityHref(null as any)).toBeNull();
      expect(parseEntityHref(undefined as any)).toBeNull();
    });
  });
});
