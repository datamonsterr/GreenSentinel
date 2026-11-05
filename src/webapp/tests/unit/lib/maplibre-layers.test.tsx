import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { MapLibreView } from '@/components/map/maplibre-view';

const map = vi.hoisted(() => ({
  sources: new Map<string, any>(), layers: new Map<string, any>(),
  addSource: vi.fn(function(id: string, source: any) { map.sources.set(id, { ...source, setData(data: any) { this.data = data; } }); }),
  addLayer: vi.fn(function(layer: any) { map.layers.set(layer.id, layer); }),
  getSource: (id: string) => map.sources.get(id), getLayer: (id: string) => map.layers.get(id),
  on: vi.fn((event: string, callback: () => void) => { if (event === 'load') queueMicrotask(callback); }),
  resize: vi.fn(), triggerRepaint: vi.fn(), remove: vi.fn(), setStyle: vi.fn(), setLayoutProperty: vi.fn(), setPaintProperty: vi.fn(), fitBounds: vi.fn(),
}));
vi.mock('maplibre-gl', () => ({ setWorkerUrl: vi.fn(), Map: class { constructor() { return map; } }, Marker: class {
  setLngLat() { return this; } addTo() { return this; } remove() {}
} }));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); map.sources.clear(); map.layers.clear(); });

describe('MapLibre recorded layers', () => {
  it('loads both road legs and updates recorded geometry when range changes', async () => {
    vi.stubGlobal('WebGLRenderingContext', class {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as any);
    const pickup = [[105, 21], [105.001, 21]];
    const destination = [[105.001, 21], [105.001, 21.001]];
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: pickup }, destination_route: { coordinates: destination } }} telemetrySamples={[
      { recorded_at: '2026-09-24T00:00:00Z', position: { coordinates: [105, 21] } },
      { recorded_at: '2026-09-24T00:00:10Z', position: { coordinates: [105.001, 21] }, anomaly_type: 'stall' },
      { recorded_at: '2026-09-24T00:00:20Z', position: { coordinates: [105.001, 21.001] } },
    ]} />);
    await waitFor(() => expect(map.getSource('pickup-route-source')).toBeDefined());
    expect(map.getSource('pickup-route-source').data.geometry.coordinates).toEqual(pickup);
    expect(map.getSource('destination-route-source').data.geometry.coordinates).toEqual(destination);
    map.fitBounds.mockClear();
    fireEvent.click(screen.getByRole('button', {name:'Center whole trip'}));
    expect(map.fitBounds).toHaveBeenCalledWith([[105,21],[105.001,21.001]],expect.objectContaining({padding:48}));
    expect(map.getLayer('pickup-route-line').paint['line-color']).not.toBe(map.getLayer('destination-route-line').paint['line-color']);
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '20' } });
    expect(map.getSource('driver-trajectory-source').data.geometry.coordinates).toHaveLength(3);
    fireEvent.change(screen.getByLabelText('Start time range'), { target: { value: '11' } });
    expect(map.getSource('driver-trajectory-source').data.geometry.coordinates[0][1]).toBeGreaterThan(21);
    expect(map.getSource('trip-points-source').data.features.some((p: any) => p.properties.kind === 'anomaly')).toBe(false);
  });

  it('keeps the camera steady while playback changes and includes off-route observations', async () => {
    vi.stubGlobal('WebGLRenderingContext', class {});
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as any);
    render(<MapLibreView routeGeometry={{ pickup_route: { coordinates: [[105, 21], [105.001, 21]] } }} telemetrySamples={[
      { recorded_at: '2026-09-24T00:00:00Z', position: { coordinates: [105, 21] } },
      { recorded_at: '2026-09-24T00:00:10Z', position: { coordinates: [105.002, 21.001] } },
    ]} />);
    await waitFor(() => expect(map.getSource('trip-points-source')).toBeDefined());
    const pickupUpdate = vi.spyOn(map.getSource('pickup-route-source'), 'setData');
    expect(map.fitBounds).toHaveBeenCalledWith([[105, 21], [105.002, 21.001]], expect.objectContaining({ duration: 0 }));
    map.fitBounds.mockClear();
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '5' } });
    fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '10' } });
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(pickupUpdate).not.toHaveBeenCalled();
  });
});
