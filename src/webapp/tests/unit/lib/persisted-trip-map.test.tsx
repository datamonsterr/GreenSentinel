import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MapLibreView } from '@/components/map/maplibre-view';

const samples = [
  { recorded_at: '2026-09-24T00:00:00Z', position: { coordinates: [105, 21] }, speed_mps: 5 },
  { recorded_at: '2026-09-24T00:01:00Z', position: { coordinates: [105.01, 21.01] }, speed_mps: 0, anomaly_type: 'stall' },
  { recorded_at: '2026-09-24T00:02:00Z', position: { coordinates: [105.02, 21.02] }, speed_mps: 8 },
];
const route = {
  pickup_route: { coordinates: [[105, 21], [105.005, 21], [105.01, 21.01]] },
  destination_route: { coordinates: [[105.01, 21.01], [105.015, 21.01], [105.02, 21.02]] },
};

describe('persisted trip map', () => {
  it('does not fabricate routes, drivers, anomalies or traffic without data', () => {
    render(<MapLibreView />);
    expect(screen.queryByTestId('driver-vehicle-marker')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pickup-route')).not.toBeInTheDocument();
    expect(screen.queryByTestId('traffic-corroboration-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stall-point-indicator')).not.toBeInTheDocument();
    expect(screen.getByText(/No trip data/)).toBeInTheDocument();
  });
  it('scrubs timestamped samples even when latest driver location is provided', () => {
    render(<MapLibreView telemetrySamples={[samples[2], samples[0], samples[1]]}
      driverLocation={{ longitude: 105.02, latitude: 21.02 }} />);
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute('data-longitude', '105');
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '60' } });
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute('data-longitude', '105.01');
    expect(screen.getByTestId('speedometer-readout')).toHaveTextContent('0.0 km/h');
    expect(screen.getByTestId('timeline-end-time')).toHaveTextContent('00:02:00');
  });
  it('renders both persisted road legs and timestamped anomaly checkpoints', () => {
    render(<MapLibreView telemetrySamples={samples} routeGeometry={route} />);
    expect(screen.getByTestId('pickup-route').querySelector('path')?.getAttribute('d')).toMatch(/^M/);
    expect(screen.getByTestId('destination-route')).toBeInTheDocument();
    const anomaly = screen.getByTestId('milestone-stall_anomaly');
    expect(anomaly).toHaveAttribute('role', 'img');
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '60' } });
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute('data-longitude', '105.01');
  });
  it('restricts the displayed breadcrumb path to the selected time range', () => {
    render(<MapLibreView telemetrySamples={samples} routeGeometry={route} />);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '120' } });
    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute('data-point-count', '3');
    fireEvent.change(screen.getByLabelText('Start time range'), { target: { value: '60' } });
    expect(screen.getByTestId('driver-trajectory')).toHaveAttribute('data-point-count', '2');
  });
  it('uses actual projected coordinates in the fallback and never invents missing route geometry', () => {
    render(<MapLibreView telemetrySamples={samples} />);
    expect(screen.queryByTestId('pickup-route')).not.toBeInTheDocument();
    expect(screen.getByText(/No route/)).toBeInTheDocument();
    const first = screen.getByTestId('driver-vehicle-marker').getAttribute('transform');
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '120' } });
    expect(screen.getByTestId('driver-vehicle-marker').getAttribute('transform')).not.toBe(first);
  });
});

it('does not invent straight routes between known trip markers', () => {
  render(<MapLibreView driverInitialLocation={{longitude:105,latitude:21}} customerLocation={{longitude:105.01,latitude:21.01}} destinationLocation={{longitude:105.02,latitude:21.02}} />);
  expect(screen.queryByTestId('pickup-route')).not.toBeInTheDocument();
  expect(screen.queryByTestId('destination-route')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Center whole trip'})).toBeEnabled();
});
