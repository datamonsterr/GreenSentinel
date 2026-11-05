import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MapLibreView } from '@/components/map/maplibre-view';

const start = Date.parse('2026-09-24T00:00:00Z');
const route = [[105, 21], [105.001, 21], [105.001, 21.001]];

function sample(second: number, coordinates: number[], speed = 0) {
  return {
    recorded_at: new Date(start + second * 1000).toISOString(),
    position: { coordinates }, speed_mps: speed, leg: 'pickup',
  };
}

function driverPosition() {
  const marker = screen.getByTestId('driver-vehicle-marker');
  return [Number(marker.getAttribute('data-longitude')), Number(marker.getAttribute('data-latitude'))];
}

afterEach(() => vi.useRealTimers());

describe('recorded road playback', () => {
  it('uses distinct normalized checkpoint and vehicle icons', () => {
    render(<MapLibreView vehicleType="Green SM Bike"
      driverInitialLocation={{ longitude: 105, latitude: 21 }}
      customerLocation={{ longitude: 105.001, latitude: 21 }}
      destinationLocation={{ longitude: 105.001, latitude: 21.001 }}
      telemetrySamples={[sample(0, route[0]), sample(20, route[2])]} />);
    expect(screen.getByTestId('driver-initial-marker').querySelector('svg')).toHaveAttribute('data-icon', 'initial');
    expect(screen.getByTestId('customer-pickup-marker').querySelector('svg')).toHaveAttribute('data-icon', 'pickup');
    expect(screen.getByTestId('destination-marker').querySelector('svg')).toHaveAttribute('data-icon', 'destination');
    expect(screen.getByTestId('driver-vehicle-marker').querySelector('svg')).toHaveAttribute('data-icon', 'motorbike');
    expect(screen.getByTestId('driver-vehicle-marker').querySelector('svg')).toHaveAttribute('width', '28');
  });

  it('moves along the bend between GPS fixes rather than jumping to a future fix', () => {
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: route } }}
      telemetrySamples={[sample(0, route[0]), sample(20, route[2], 7.6)]} />);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '10' } });
    const [longitude, latitude] = driverPosition();
    expect(longitude).toBeCloseTo(105.001, 5);
    expect(latitude).toBeLessThan(21.0001);
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute('data-playback-mode', 'interpolated');
  });

  it('does not display the next observed position before its timestamp', () => {
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: route } }}
      telemetrySamples={[sample(0, route[0]), sample(20, route[2], 7.6)]} />);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '16' } });
    const [longitude, latitude] = driverPosition();
    expect(longitude).toBeCloseTo(105.001, 5);
    expect(latitude).toBeGreaterThan(21.0005);
    expect(latitude).toBeLessThan(21.001);
  });

  it('holds the last known fix during dropout and leaves speed unavailable', () => {
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: route } }}
      telemetrySamples={[sample(0, route[0], 7.6), sample(60, route[2], 7.6)]}
      missingnessAlerts={[{ alert_id: 'dropout-1', start_time: new Date(start).toISOString(), end_time: new Date(start + 60_000).toISOString(), gap_duration_s: 60, reason: 'GPS observations omitted', severity: 'warning' }]} />);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '40' } });
    expect(driverPosition()).toEqual(route[0]);
    expect(screen.getByTestId('driver-vehicle-marker')).toHaveAttribute('data-playback-mode', 'gap');
    expect(screen.queryByTestId('speedometer-readout')).not.toBeInTheDocument();
  });

  it('retains observed fixes when their intervening route is unavailable', () => {
    render(<MapLibreView telemetrySamples={[sample(0, route[0]), sample(60, route[2])]} />);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '60' } });
    expect(screen.getAllByTestId('observed-gps-fix')).toHaveLength(2);
    expect(screen.getByTestId('driver-trajectory').querySelector('path')).toBeNull();
  });

  it('marks dense checkpoints at their exact time without adding buttons or popovers', () => {
    const timestamp = (second: number) => new Date(start + second * 1000).toISOString();
    render(<MapLibreView telemetrySamples={[sample(0, route[0]), sample(20, route[2])]} timelineMilestones={[
      { id: 'a', type: 'start_match', timestamp: timestamp(0), title: 'Điểm bắt đầu' },
      { id: 'b', type: 'pickup', timestamp: timestamp(0.043), title: 'Điểm đón khách' },
    ] as any} />);
    const marks = screen.getByTestId('timeline-checkpoint-marks');
    expect(marks.querySelector('button, details, summary')).toBeNull();
    const pickup = screen.getByTestId('milestone-pickup');
    expect(pickup.tagName).toBe('SPAN');
    expect(pickup).toHaveAccessibleName(/Điểm đón khách/);
    expect(pickup.style.left).toBe('0.215%');
    expect(screen.getByTestId('milestone-start_match').style.left).toBe('0%');
    expect(screen.getByTestId('trip-timeline-bar').querySelectorAll('button')).toHaveLength(1);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '0.043' } });
    expect((screen.getByTestId('timeline-scrubber-slider') as HTMLInputElement).value).toBe('0.043');
  });

  it('plays at one recorded second per wall-clock second for a long trip', () => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: route } }}
      telemetrySamples={[sample(0, route[0]), sample(2400, route[2], 7.6)]} />);
    fireEvent.click(screen.getByRole('button', { name: /Replay/ }));
    act(() => vi.advanceTimersByTime(1050));
    expect(Number((screen.getByTestId('timeline-scrubber-slider') as HTMLInputElement).value)).toBeCloseTo(1.05, 1);
    expect(screen.getByTestId('active-timeline-status')).toHaveTextContent('00:00:01');
  });
});
