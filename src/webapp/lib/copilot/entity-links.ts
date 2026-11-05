/**
 * Entity link parser for copilot markdown links.
 * Supports:
 * - case://<case_id>
 * - driver://<driver_id>
 * - trip://<trip_id>?pickup=<urlenc>&dest=<urlenc>
 * - policy://<citation_id> (e.g. policy://c1)
 */

export interface CaseEntityLink {
  type: "case";
  id: string;
}

export interface DriverEntityLink {
  type: "driver";
  id: string;
}

export interface TripEntityLink {
  type: "trip";
  id: string;
  pickup?: string;
  dest?: string;
}

export interface PolicyEntityLink {
  type: "policy";
  id: string;
  citationId?: string;
}

export type EntityLink =
  | CaseEntityLink
  | DriverEntityLink
  | TripEntityLink
  | PolicyEntityLink;

export function parseEntityHref(href: unknown): EntityLink | null {
  if (typeof href !== "string" || !href) {
    return null;
  }

  // 1. case://<id>
  const caseMatch = href.match(/^case:\/\/([^/?#]+)$/);
  if (caseMatch) {
    const id = caseMatch[1].trim();
    return id ? { type: "case", id } : null;
  }

  // 2. driver://<id>
  const driverMatch = href.match(/^driver:\/\/([^/?#]+)$/);
  if (driverMatch) {
    const id = driverMatch[1].trim();
    return id ? { type: "driver", id } : null;
  }

  // 3. trip://<trip_id>[?pickup=...&dest=...]
  const tripMatch = href.match(/^trip:\/\/([^/?#]+)(?:\?(.*))?$/);
  if (tripMatch) {
    const id = tripMatch[1].trim();
    if (!id) return null;

    const queryString = tripMatch[2];
    if (queryString === undefined) {
      return { type: "trip", id };
    }

    try {
      const searchParams = new URLSearchParams(queryString);
      const rawPickup = searchParams.get("pickup");
      const rawDest = searchParams.get("dest");

      const result: TripEntityLink = {
        type: "trip",
        id,
      };

      if (rawPickup !== null) {
        result.pickup = decodeURIComponent(rawPickup);
      }
      if (rawDest !== null) {
        result.dest = decodeURIComponent(rawDest);
      }

      return result;
    } catch {
      // Malformed percent-encoding
      return null;
    }
  }

  // 4. policy://cN or policy://<citation_id>
  const policyMatch = href.match(/^policy:\/\/([^/?#]+)$/);
  if (policyMatch) {
    const id = policyMatch[1].trim();
    if (!id) return null;
    return {
      type: "policy",
      id,
      citationId: id,
    };
  }

  return null;
}
