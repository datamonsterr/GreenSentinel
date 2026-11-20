import React from 'react';

export type VehicleKind = 'car' | 'motorbike' | 'unknown';

export function vehicleKind(value?: string | null): VehicleKind {
  switch (value?.trim().toLowerCase()) {
    case 'car':
    case 'green sm car':
      return 'car';
    case 'bike':
    case 'motorbike':
    case 'green sm bike':
      return 'motorbike';
    default:
      return 'unknown';
  }
}

export type CheckpointRole = 'initial' | 'pickup' | 'destination' | 'driver';

// Lucide geometry from the approved checkpoint preview; never interpolate source data.
const glyphs = {
  'circle': '<circle cx="12" cy="12" r="10" fill="#ffffff"/>',
  'user-round': '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  'flag': '<path d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528"/>',
  'car': '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
  'motorbike': '<path d="m18 14-1-3"/><path d="m3 9 6 2a2 2 0 0 1 2-2h2a2 2 0 0 1 1.99 1.81"/><path d="M8 17h3a1 1 0 0 0 1-1 6 6 0 0 1 6-6 1 1 0 0 0 1-1v-.75A5 5 0 0 0 17 5"/><circle cx="19" cy="17" r="3"/><circle cx="5" cy="17" r="3"/>',
  'circle-help': '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
} as const;

const colors = {
  surface: '#ffffff',
  start: '#16273b',
  primary: '#22a45d',
  destination: '#7b3ed6',
  unknown: '#5a6b78',
} as const;

function presentation(role: CheckpointRole, vehicleType?: string | null) {
  switch (role) {
    case 'initial': return { glyph: 'circle', label: 'Điểm bắt đầu', color: colors.start } as const;
    case 'pickup': return { glyph: 'user-round', label: 'Điểm đón khách', color: colors.primary } as const;
    case 'destination': return { glyph: 'flag', label: 'Điểm đến', color: colors.destination } as const;
    case 'driver': {
      switch (vehicleKind(vehicleType)) {
        case 'car': return { glyph: 'car', label: 'Tài xế, ô tô', color: colors.primary } as const;
        case 'motorbike': return { glyph: 'motorbike', label: 'Tài xế, xe máy', color: colors.primary } as const;
        default: return { glyph: 'circle-help', label: 'Tài xế, chưa rõ loại phương tiện', color: colors.unknown } as const;
      }
    }
    default: throw new Error('Unsupported checkpoint role');
  }
}

function artwork(role: CheckpointRole, vehicleType?: string | null, timeline = false) {
  const { glyph, label, color } = presentation(role, vehicleType);
  const driver = role === 'driver';
  const size = timeline ? 20 : driver ? 28 : 24;
  const glyphSize = timeline ? 14 : driver ? 20 : role === 'initial' ? 12 : 16;
  const center = size / 2;
  const inset = (size - glyphSize) / 2;
  const unknown = glyph === 'circle-help';
  const carrier = driver
    ? `<rect x="0.5" y="0.5" width="${size - 1}" height="${size - 1}" rx="${timeline ? 4 : 6}" fill="${unknown ? colors.surface : color}" stroke="${color}"${unknown ? ' stroke-dasharray="2 2"' : ''}/>`
    : role === 'initial' ? '' : `<circle cx="${center}" cy="${center}" r="${center - 0.5}" fill="${colors.surface}" stroke="${color}"/>`;
  const markup = `${carrier}<svg x="${inset}" y="${inset}" width="${glyphSize}" height="${glyphSize}" viewBox="0 0 24 24" fill="none" stroke="${driver && !unknown ? colors.surface : color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-${glyph}" aria-hidden="true" focusable="false">${glyphs[glyph]}</svg>`;
  return { size, label, markup, icon: driver ? vehicleKind(vehicleType) : role };
}

export interface CheckpointIconProps {
  role: CheckpointRole;
  vehicleType?: string | null;
  timeline?: boolean;
}

/** Complete centered carrier for a MapLibre DOM marker. All markup comes from static roles. */
export function markerSvg(role: CheckpointRole, vehicleType?: string | null): string {
  const { size, label, markup, icon } = artwork(role, vehicleType);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" data-icon="${icon}" role="img" aria-label="${label}" focusable="false" style="flex-shrink: 0; display: block;">${markup}</svg>`;
}

export function CheckpointIcon({ role, vehicleType, timeline = false }: CheckpointIconProps) {
  const { size, label, markup, icon } = artwork(role, vehicleType, timeline);
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox={`0 0 ${size} ${size}`}
      data-icon={icon} role="img" aria-label={timeline ? undefined : label} aria-hidden={timeline || undefined}
      focusable="false" style={{ flexShrink: 0, display: 'block' }}
      dangerouslySetInnerHTML={{ __html: markup }} />
  );
}
