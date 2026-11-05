import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CheckpointIcon, markerSvg, vehicleKind } from '@/components/map/checkpoint-icon';

describe('vehicleKind', () => {
  it('normalizes only the recorded vehicle allowlist', () => {
    for (const value of ['car', ' CAR ', 'Green SM Car']) expect(vehicleKind(value)).toBe('car');
    for (const value of ['bike', ' BIKE ', 'motorbike', ' MOTORBIKE ', 'Green SM Bike']) expect(vehicleKind(value)).toBe('motorbike');
    for (const value of [null, undefined, '', ' ', 'car bike', 'Express', 'Delivery', 'racecar', 'Green SM Car Plus']) {
      expect(vehicleKind(value)).toBe('unknown');
    }
  });
});

describe('markerSvg', () => {
  it('provides a complete SVG carrier matching React map output for every role and vehicle', () => {
    for (const role of ['initial', 'pickup', 'destination', 'driver'] as const) {
      for (const vehicleType of ['car', 'bike', undefined]) {
        const markup = markerSvg(role, vehicleType);
        const parsed = new DOMParser().parseFromString(markup, 'image/svg+xml');
        expect(parsed.querySelector('parsererror')).toBeNull();
        const svg = parsed.documentElement;
        expect(svg.namespaceURI).toBe('http://www.w3.org/2000/svg');
        expect(svg.tagName).toBe('svg');
        const { container, unmount } = render(<CheckpointIcon role={role} vehicleType={vehicleType} />);
        const host = document.createElement('div');
        host.innerHTML = markup;
        expect(host.firstElementChild?.outerHTML).toBe(container.firstElementChild?.outerHTML);
        unmount();
      }
    }
  });

  it('keeps unsupported source values neutral and never inserts them into markup', () => {
    const hostile = '\"><script>alert(1)</script><svg onload="alert(1)">';
    for (const value of [hostile, 'car bike', 'Express', null, undefined]) {
      const markup = markerSvg('driver', value);
      expect(markup).not.toContain('<script');
      expect(markup).not.toContain('onload');
      expect(markup).toContain('lucide-circle-help');
      expect(markup).not.toContain('lucide-car');
      expect(markup).toContain('stroke-dasharray="2 2"');
      expect(markup).toContain('chưa rõ loại phương tiện');
    }
    expect(() => markerSvg(hostile as 'driver')).toThrow('Unsupported checkpoint role');
  });
});

describe('CheckpointIcon', () => {
  it('keeps all timeline glyphs at 14px inside a 20px decorative carrier', () => {
    for (const role of ['initial', 'pickup', 'destination', 'driver'] as const) {
      for (const vehicleType of ['car', 'bike', undefined]) {
        const { container, unmount } = render(<CheckpointIcon role={role} vehicleType={vehicleType} timeline />);
        const icon = container.firstElementChild;
        expect(icon).toHaveAttribute('width', '20');
        expect(icon).toHaveAttribute('height', '20');
        expect(icon).toHaveAttribute('aria-hidden', 'true');
        expect(icon?.querySelector('svg')).toHaveAttribute('width', '14');
        expect(icon?.querySelector('svg')).toHaveAttribute('height', '14');
        unmount();
      }
    }
  });

  it('renders distinct named circle, person, flag, car, motorbike and unknown glyphs at fixed sizes', () => {
    const cases = [
      ['initial', undefined, 'Điểm bắt đầu', 24, 12, 'circle'],
      ['pickup', undefined, 'Điểm đón khách', 24, 16, 'user-round'],
      ['destination', undefined, 'Điểm đến', 24, 16, 'flag'],
      ['driver', 'car', 'Tài xế, ô tô', 28, 20, 'car'],
      ['driver', 'Green SM Bike', 'Tài xế, xe máy', 28, 20, 'motorbike'],
      ['driver', null, 'Tài xế, chưa rõ loại phương tiện', 28, 20, 'circle-help'],
    ] as const;
    const shapes = new Set<string>();
    for (const [role, vehicleType, name, size, glyphSize, glyphName] of cases) {
      const { unmount } = render(<CheckpointIcon role={role} vehicleType={vehicleType} />);
      const icon = screen.getByRole('img', { name });
      expect(icon).toHaveAttribute('width', String(size));
      expect(icon).toHaveAttribute('height', String(size));
      expect(icon).toHaveAttribute('data-icon', role === 'driver' ? vehicleType === null ? 'unknown' : vehicleType === 'car' ? 'car' : 'motorbike' : role);
      const glyph = icon.querySelector('svg');
      expect(glyph).toHaveAttribute('width', String(glyphSize));
      expect(glyph).toHaveAttribute('height', String(glyphSize));
      expect(glyph).toHaveAttribute('viewBox', '0 0 24 24');
      expect(glyph).toHaveClass(`lucide-${glyphName}`);
      shapes.add(glyph!.innerHTML);
      if (role === 'initial') expect(glyph?.querySelector('circle')).toHaveAttribute('fill', '#ffffff');
      if (role === 'driver' && vehicleType === null) {
        expect(icon.querySelector('rect')).toHaveAttribute('fill', '#ffffff');
        expect(icon.querySelector('rect')).toHaveAttribute('stroke-dasharray', '2 2');
      }
      unmount();
    }
    expect(shapes.size).toBe(6);
  });
});
