import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MapLibreView } from '@/components/map/maplibre-view';

const telemetry = [
  { occurred_at: '2026-09-24T00:00:00Z', position: { coordinates: [105, 21] }, speed_mps: 5 },
  { occurred_at: '2026-09-24T00:01:00Z', position: { coordinates: [105.01, 21] }, speed_mps: 0, anomaly_type: 'stall' },
  { occurred_at: '2026-09-24T00:02:00Z', position: { coordinates: [105.01, 21.01] }, speed_mps: 8 },
];

describe('map coordinate evidence', () => {
  it('never creates missing points, traffic or routes from layer toggles', () => {
    render(<MapLibreView initialRoute initialTraffic initialBreadcrumbs initialHotspots />);
    for (const id of ['driver-initial-marker', 'driver-vehicle-marker', 'customer-pickup-marker', 'destination-marker', 'pickup-route', 'driver-trajectory', 'hotspot-indicator', 'traffic-layer']) {
      expect(screen.queryByTestId(id)).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/210s Stall/)).not.toBeInTheDocument();
    expect(screen.queryByText(/32 km\/h/)).not.toBeInTheDocument();
  });
  it('preserves recorded fixes, leaves GPS gaps disconnected, clips milestones and scrubs occurred_at speed', () => {
    render(<MapLibreView telemetrySamples={telemetry} driverBreadcrumbs={[[0, 0], [1, 1]]} />);
    expect(screen.getByTestId("active-timeline-status")).not.toHaveTextContent("stall");
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '120' } });
    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute('data-point-count', '3');
    expect(screen.getByTestId('driver-trajectory').querySelector('path')).toBeNull();
    expect(screen.getByTestId('speedometer-readout')).toHaveTextContent('28.8 km/h');
    const anomaly = screen.getByTestId('anomaly-telemetry-1');
    expect(anomaly).toHaveAttribute('data-longitude', '105.01');
    expect(anomaly).toHaveAttribute('data-latitude', '21');
    expect(anomaly).toHaveAttribute('data-timestamp', telemetry[1].occurred_at);
    fireEvent.change(screen.getByLabelText('Start time range'), { target: { value: '61' } });
    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute('data-point-count', '1');
    expect(screen.getByTestId("timeline-start-time")).toHaveTextContent("00:01:01");
    expect(screen.queryByTestId('milestone-stall_anomaly')).not.toBeInTheDocument();
    expect(screen.queryByTestId('anomaly-telemetry-1')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('End time range'), { target: { value: '90' } });
    expect(screen.getByTestId('timeline-scrubber-slider')).toHaveAttribute('max', '90');
    expect(screen.getByTestId("timeline-end-time")).toHaveTextContent("00:01:30");
  });
});
