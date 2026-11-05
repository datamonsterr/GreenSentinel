import { describe, expect, it } from 'vitest';
import { createPlaybackTrack, distanceMeters, playbackAt, playbackTrail, type Coordinate } from '@/lib/telemetry-playback';

const route: Coordinate[] = [[105, 21], [105.001, 21], [105.001, 21.001]];
const sample = (_time: number, coordinates: Coordinate) => ({ _time, position: { coordinates }, speed_mps: 7.6 });

describe('road playback geometry and evidence boundaries', () => {
  it('uses the recorded leg when another route offers a shorter shortcut', () => {
    const pickup: Coordinate[] = [[105, 21], [105.0005, 21.0005], [105.001, 21]];
    const destination: Coordinate[] = [[105, 21], [105.001, 21]];
    const track = createPlaybackTrack([
      { ...sample(0, pickup[0]), leg: 'pickup' },
      { ...sample(20000, pickup[2]), leg: 'pickup' },
    ], [pickup, destination]);
    expect(playbackAt(track, 10000)?.coordinate[1]).toBeGreaterThan(21.0004);
  });

  it('does not confuse simultaneous observations with a telemetry gap', () => {
    const track = createPlaybackTrack([sample(0, route[0]), sample(0, route[1]), sample(10000, route[2])], [route]);
    expect(track.intervals[0].mode).toBe('unmatched');
    expect(playbackAt(track, 0)?.coordinate).toEqual(route[1]);
  });

  it('uses the next recorded leg when the first observation has no leg', () => {
    const pickup: Coordinate[] = [[105, 21], [105.001, 21]];
    const destination: Coordinate[] = [[105, 21], [105.0005, 21.0005], [105.001, 21]];
    const track = createPlaybackTrack([
      sample(0, destination[0]),
      { ...sample(20000, destination[2]), leg: 'destination' },
    ], [pickup, destination]);
    expect(playbackAt(track, 10000)?.coordinate[1]).toBeGreaterThan(21.0004);
  });

  it('retains exact observations and never exposes one before the first fix', () => {
    const track = createPlaybackTrack([sample(1000, route[0]), sample(21000, route[2])], [route]);
    expect(playbackAt(track, 999)).toBeUndefined();
    expect(playbackAt(track, 1000)).toMatchObject({ coordinate: route[0], mode: 'observed', speedMps: 7.6 });
    expect(playbackAt(track, 21000)).toMatchObject({ coordinate: route[2], mode: 'observed', speedMps: 7.6 });
  });

  it('keeps movement bounded and the trail attached along a corner', () => {
    const track = createPlaybackTrack([sample(0, route[0]), sample(20000, route[2])], [route]);
    for (let t = 100; t < 20000; t += 100) {
      const previous = playbackAt(track, t - 100)!, current = playbackAt(track, t)!;
      expect(distanceMeters(previous.coordinate, current.coordinate)).toBeLessThan(1.2);
      expect(Math.min(Math.abs(current.coordinate[1] - 21), Math.abs(current.coordinate[0] - 105.001))).toBeLessThan(0.000001);
      expect(playbackTrail(track, t, 0).at(-1)?.at(-1)).toEqual(current.coordinate);
    }
    expect(playbackTrail(track, 20000, 0)[0]).toContainEqual(route[1]);
  });

  it('does not snap off-route fixes or join their unknown trajectory', () => {
    const a: Coordinate = [105, 21.002], b: Coordinate = [105.001, 21.003];
    const track = createPlaybackTrack([sample(0, a), sample(10000, b)], [route]);
    expect(playbackAt(track, 9000)).toMatchObject({ coordinate: a, mode: 'unmatched' });
    expect(playbackAt(track, 9000)?.speedMps).toBeUndefined();
    expect(playbackAt(track, 10000)?.coordinate).toEqual(b);
    expect(playbackTrail(track, 10000, 0)).toEqual([]);
  });

  it('breaks the trail across an omitted interval and resumes at the next fix', () => {
    const track = createPlaybackTrack([sample(0, route[0]), sample(10000, route[1]), sample(70000, route[1]), sample(80000, route[2])], [route]);
    expect(playbackAt(track, 40000)).toMatchObject({ coordinate: route[1], mode: 'gap' });
    expect(playbackTrail(track, 80000, 0)).toHaveLength(2);
    expect(playbackAt(track, 70000)?.mode).toBe('observed');
    expect(playbackAt(track, 75000)?.mode).toBe('interpolated');
  });

  it('holds implausible road travel rather than animating a teleport', () => {
    const track = createPlaybackTrack([sample(0, route[0]), sample(1000, route[2])], [route]);
    expect(playbackAt(track, 500)).toMatchObject({ coordinate: route[0], mode: 'unmatched' });
  });

  it('keeps a stationary driver stationary with zero estimated speed', () => {
    const track = createPlaybackTrack([sample(0, route[1]), sample(10000, route[1])], [route]);
    expect(playbackAt(track, 5000)).toMatchObject({ coordinate: route[1], speedMps: 0 });
  });

  it('clips the trail to a fractional range boundary without joining earlier points', () => {
    const track = createPlaybackTrack([sample(0, route[0]), sample(20000, route[2])], [route]);
    const trail = playbackTrail(track, 16000, 12000);
    expect(trail[0][0]).toEqual(playbackAt(track, 12000)?.coordinate);
    expect(trail[0].at(-1)).toEqual(playbackAt(track, 16000)?.coordinate);
    expect(trail[0]).not.toContainEqual(route[0]);
  });
});




describe('missingness gap limits and malformed input handling', () => {
  it('holds the last valid fix through a terminal persisted missingness gap', () => {
    const t0 = Date.parse("2026-09-22T08:10:00Z");
    const track = createPlaybackTrack(
      [sample(t0, route[0])],
      [route],
      [{ start_time: "2026-09-22T08:10:00Z", end_time: "2026-09-22T08:10:10Z" }],
    );

    expect(playbackAt(track, t0)).toMatchObject({ coordinate: route[0], mode: 'observed', speedMps: 7.6 });
    expect(playbackAt(track, t0 + 5000)).toMatchObject({ coordinate: route[0], mode: 'gap' });
    expect(playbackAt(track, t0 + 5000)?.speedMps).toBeUndefined();
    expect(playbackAt(track, t0 + 10000)).toMatchObject({ coordinate: route[0], mode: 'gap' });
  });

  it('ends a terminal missingness gap at the next exact valid fix', () => {
    const t0 = Date.parse("2026-09-22T08:10:00Z");
    const t10 = t0 + 10000;
    const track = createPlaybackTrack(
      [sample(t0, route[0]), sample(t10, route[1])],
      [route],
      [{ start_time: "2026-09-22T08:10:00Z", end_time: "2026-09-22T08:10:10Z" }],
    );

    expect(playbackAt(track, t0 + 5000)).toMatchObject({ coordinate: route[0], mode: 'gap' });
    expect(playbackAt(track, t10)).toMatchObject({ coordinate: route[1], mode: 'observed', speedMps: 7.6 });
  });

  it('interpolates at exactly 30.000s but generates a gap at 30.001s', () => {
    const track30 = createPlaybackTrack([sample(0, route[0]), sample(30000, route[1])], [route]);
    expect(track30.intervals[0].mode).toBe('interpolated');

    const track30001 = createPlaybackTrack([sample(0, route[0]), sample(30001, route[1])], [route]);
    expect(track30001.intervals[0].mode).toBe('gap');
  });

  it('does not fabricate a gap from a malformed explicit timestamp', () => {
    // Gap start time after end time (malformed)
    const gap1 = { start_time: "2026-09-22T08:10:10Z", end_time: "2026-09-22T08:10:05Z", gap_duration_s: 5, alert_id: "1", reason: "test", severity: "warning" as const };
    const track = createPlaybackTrack([sample(Date.parse("2026-09-22T08:10:00Z"), route[0]), sample(Date.parse("2026-09-22T08:10:20Z"), route[1])], [route], [gap1]);
    expect(track.intervals[0].mode).toBe('interpolated'); // NOT gap

    // Gap missing or invalid timestamp
    const gap2 = { start_time: "invalid", end_time: "invalid", gap_duration_s: 5, alert_id: "2", reason: "test", severity: "warning" as const };
    const track2 = createPlaybackTrack([sample(Date.parse("2026-09-22T08:10:00Z"), route[0]), sample(Date.parse("2026-09-22T08:10:20Z"), route[1])], [route], [gap2]);
    expect(track2.intervals[0].mode).toBe('interpolated'); // NOT gap
  });

  it('ignores zero-duration explicit gap leaving route-aligned playback interpolated and trail connected', () => {
    const t0 = Date.parse("2026-09-22T08:10:00Z");
    const t20 = Date.parse("2026-09-22T08:10:20Z");
    const zeroGap = {
      start_time: "2026-09-22T08:10:10Z",
      end_time: "2026-09-22T08:10:10Z",
      gap_duration_s: 0,
      alert_id: "zero-gap-1",
      reason: "zero duration test",
      severity: "warning" as const,
    };
    const track = createPlaybackTrack(
      [sample(t0, route[0]), sample(t20, route[1])],
      [route],
      [zeroGap],
    );

    // 20s interval must remain interpolated
    expect(track.intervals[0].mode).toBe('interpolated');

    // Source fixes unaffected
    const atStart = playbackAt(track, t0);
    const atEnd = playbackAt(track, t20);
    expect(atStart?.mode).toBe('observed');
    expect(atStart?.coordinate).toEqual(route[0]);
    expect(atEnd?.mode).toBe('observed');
    expect(atEnd?.coordinate).toEqual(route[1]);

    // Interpolated midpoint along route
    const atMid = playbackAt(track, t0 + 10000);
    expect(atMid?.mode).toBe('interpolated');

    // Trail remains connected across the interval
    const trail = playbackTrail(track, t20, t0);
    expect(trail).toHaveLength(1);
    expect(trail[0][0]).toEqual(route[0]);
    expect(trail[0].at(-1)).toEqual(route[1]);
  });
});
