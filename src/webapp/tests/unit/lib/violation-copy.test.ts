import { describe, it, expect } from 'vitest';
import {
  getViolationTitle,
  stripTrailingParenthetical,
  isRawViolationCode,
} from '@/lib/driver/violation-copy';

describe('violation-copy (F4)', () => {
  it('maps known violation codes to localized titles for vi and en', () => {
    expect(getViolationTitle({ code: 'ERR-01', locale: 'vi' })).toBe(
      'Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt'
    );
    expect(getViolationTitle({ code: 'ERR-01', locale: 'en' })).toBe(
      'Trip/order embezzlement: cancel then collect cash off-app'
    );
    expect(getViolationTitle({ code: 'ERR-02', locale: 'vi' })).toBe(
      'Lái xe lệch tuyến, kéo dài hoặc di chuyển sai hướng để khách hủy chuyến'
    );
    expect(getViolationTitle({ code: 'ERR-02', locale: 'en' })).toBe(
      'Route deviation / stall-to-cancel'
    );
    expect(getViolationTitle({ code: 'ERR-03', locale: 'vi' })).toBe(
      'Khai thác khuyến mãi qua đặt chuyến giả hoặc gaming chính sách'
    );
    expect(getViolationTitle({ code: 'ERR-03', locale: 'en' })).toBe(
      'Incentive/policy exploitation via fake trips'
    );
    expect(getViolationTitle({ code: 'ERR-04', locale: 'vi' })).toBe(
      'Chuyến đi ảo/ma: không có hành trình vật lý thực tế'
    );
    expect(getViolationTitle({ code: 'ERR-04', locale: 'en' })).toBe(
      'Phantom trip with no physical journey'
    );
    expect(getViolationTitle({ code: 'ERR-05', locale: 'vi' })).toBe(
      'GPS giả hoặc thao túng công nghệ vị trí'
    );
    expect(getViolationTitle({ code: 'ERR-05', locale: 'en' })).toBe(
      'Fake GPS / technological manipulation'
    );
  });

  it('handles lowercase or underscore in violation code', () => {
    expect(getViolationTitle({ code: 'err_01', locale: 'vi' })).toBe(
      'Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt'
    );
    expect(getViolationTitle({ code: 'err-05', locale: 'en' })).toBe(
      'Fake GPS / technological manipulation'
    );
  });

  it('falls back to violation_title when code is unknown or missing, stripping trailing parenthetical', () => {
    expect(
      getViolationTitle({
        code: 'UNKNOWN_99',
        title: 'Chậm đón khách (Pickup delay)',
        locale: 'vi',
      })
    ).toBe('Chậm đón khách');

    expect(
      getViolationTitle({
        title: 'Lái xe lệch tuyến (Route deviation / stall-to-cancel)',
        locale: 'vi',
      })
    ).toBe('Lái xe lệch tuyến');

    expect(
      getViolationTitle({
        title: 'Khách khiếu nại thái độ',
        locale: 'vi',
      })
    ).toBe('Khách khiếu nại thái độ');
  });

  it('never shows raw code in fallback', () => {
    expect(
      getViolationTitle({
        code: 'UNKNOWN_99',
        title: 'ERR-09',
        locale: 'vi',
      })
    ).toBe('Nghi vấn vi phạm chỉ số vận hành');

    expect(
      getViolationTitle({
        code: 'UNKNOWN_99',
        title: 'ERR-09',
        locale: 'en',
      })
    ).toBe('Suspected violation');

    expect(
      getViolationTitle({
        title: 'ERR_99',
        locale: 'vi',
      })
    ).toBe('Nghi vấn vi phạm chỉ số vận hành');
  });

  it('stripTrailingParenthetical helper strips trailing English parenthetical properly', () => {
    expect(stripTrailingParenthetical('Chậm đón khách (Pickup delay)')).toBe('Chậm đón khách');
    expect(stripTrailingParenthetical('Hủy chuyến (Driver cancelled)')).toBe('Hủy chuyến');
    expect(stripTrailingParenthetical('Normal title without paren')).toBe('Normal title without paren');
    expect(stripTrailingParenthetical(null)).toBe('');
  });

  it('isRawViolationCode detects codes correctly', () => {
    expect(isRawViolationCode('ERR-01')).toBe(true);
    expect(isRawViolationCode('err_05')).toBe(true);
    expect(isRawViolationCode('DIC')).toBe(true);
    expect(isRawViolationCode('Chậm đón khách')).toBe(false);
  });
});
