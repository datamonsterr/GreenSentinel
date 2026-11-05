import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MapLibreView } from '@/components/map/maplibre-view';
import manifest from '../../../../../tests/fixtures/road_telemetry/normal_trip.json';

type Manifest = typeof manifest;

const dropoutBefore = manifest.ingest_events[4];
const dropoutAfter = manifest.ingest_events[10];
const dropoutGapSeconds = Math.round(
  (Date.parse(dropoutAfter.occurred_at) - Date.parse(dropoutBefore.occurred_at)) / 1000,
);

function toMapProps(source: Manifest) {
  return {
    routeGeometry: Object.fromEntries(source.route_snapshots.map((snapshot) => [
      `${snapshot.leg}_route`, snapshot.route_geojson,
    ])),
    telemetrySamples: source.ingest_events.map((event) => ({
      recorded_at: event.occurred_at,
      position: {
        // Producer payload is latitude/longitude; MapLibreView consumes GeoJSON order.
        coordinates: [event.payload.position.longitude, event.payload.position.latitude],
      },
      speed_mps: event.payload.speed_mps,
      bearing_deg: event.payload.bearing_deg,
      leg: event.leg,
    })),
  };
}

describe('normal road telemetry consumer contract', () => {
  it('preserves both route legs, event time/speed, and transforms producer coordinates to GeoJSON', () => {
    const props = toMapProps(manifest);
    const first = manifest.ingest_events[0];
    const firstSample = props.telemetrySamples[0];

    expect(props.routeGeometry.pickup_route.coordinates).toEqual(
      manifest.route_snapshots.find((snapshot) => snapshot.leg === 'pickup')?.route_geojson.coordinates,
    );
    expect(props.routeGeometry.destination_route.coordinates).toEqual(
      manifest.route_snapshots.find((snapshot) => snapshot.leg === 'destination')?.route_geojson.coordinates,
    );
    expect(firstSample).toMatchObject({
      recorded_at: first.occurred_at,
      speed_mps: first.payload.speed_mps,
      leg: 'pickup',
      position: { coordinates: [first.payload.position.longitude, first.payload.position.latitude] },
    });

    render(<MapLibreView {...props} />);

    expect(screen.getByTestId('pickup-route')).toBeInTheDocument();
    expect(screen.getByTestId('destination-route')).toBeInTheDocument();
    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute(
      'data-point-count',
      '1',
    );
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute(
      'data-longitude',
      String(first.payload.position.longitude),
    );
  });

  it('scrubs the canonical timeline using recorded timestamps and speed', () => {
    const props = toMapProps(manifest);
    render(<MapLibreView {...props} />);
    const scrubber = screen.getByTestId('timeline-scrubber-slider');
    const secondEvent = manifest.ingest_events[1];
    const elapsed = (Date.parse(secondEvent.occurred_at) - Date.parse(manifest.ingest_events[0].occurred_at)) / 1000;

    fireEvent.change(scrubber, { target: { value: String(elapsed) } });

    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute('data-point-count', '2');
    expect(screen.getByTestId('speedometer-readout')).toHaveTextContent(
      `${(secondEvent.payload.speed_mps * 3.6).toFixed(1)} km/h`,
    );
    expect(screen.getByTestId('timeline-start-time')).toHaveTextContent(
      manifest.ingest_events[0].occurred_at.slice(11, 19),
    );
  });

  it('renders supported route and telemetry missingness evidence without fabricating geometry', () => {
    const props = toMapProps(manifest);
    render(
      <MapLibreView
        {...props}
        routeGeometry={{ pickup_route: props.routeGeometry.pickup_route }}
        missingnessAlerts={[{
          alert_id: 'dropout-1',
          start_time: dropoutBefore.occurred_at,
          end_time: dropoutAfter.occurred_at,
          gap_duration_s: dropoutGapSeconds,
          reason: 'canonical dropout: omitted normal event indices 5..9',
          severity: 'warning',
        }]}
      />,
    );

    expect(screen.getByTestId('data-missingness-alert-banner')).toHaveTextContent(`${dropoutGapSeconds}s`);
    expect(screen.getByTestId('pickup-route')).toBeInTheDocument();
    expect(screen.queryByTestId('destination-route')).not.toBeInTheDocument();
  });
});
