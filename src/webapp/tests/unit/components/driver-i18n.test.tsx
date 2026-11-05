import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DriverPortalPage from '@/app/driver/(tabs)/cases/page';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import { setLocaleCookie } from '@/lib/driver/locale';
import * as api from '@/lib/api-client';
import enMessages from '@/messages/en.json';
import viMessages from '@/messages/vi.json';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useParams: () => ({ caseId: 'case-test-101' }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
}));

vi.mock('@/lib/api-client', () => ({
  getDriverDisputeContext: vi.fn(),
  streamDriverChat: vi.fn(),
  sendDriverChat: vi.fn(),
  fetchDriverSession: vi.fn(),
  fetchDriverCases: vi.fn(),
}));

const mockContext = {
  case_id: 'case-test-101',
  driver_id: 'drv-999',
  driver_name: 'Nguyễn Văn A',
  trip_id: 'trip-777',
  violation_code: 'ERR-02',
  violation_title: 'Tài xế cố tình hủy chuyến để nhận phí hỗ trợ',
  alleged_time: '2026-09-26T08:30:00Z',
  alleged_location: 'Ngã tư Kim Mã - Liễu Giai, Ba Đình',
  dispute_deadline: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
  dispute_status: 'in_dispute',
  allowed_claim_types: ['traffic_gridlock', 'gps_issue', 'passenger_wait', 'breakdown'],
};

describe('Driver UI i18n & Locale Switch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getDriverDisputeContext).mockResolvedValue(mockContext);
    vi.mocked(api.fetchDriverCases).mockResolvedValue({
      items: [
        {
          case_id: 'case-alpha-1234',
          trip_id: 'trip-101',
          violation_code: 'ERR-01',
          violation_title: 'Chậm đón khách',
          description: 'Xe tiếp cận điểm đón chậm',
          alleged_time: '2026-09-26T08:30:00Z',
          status: 'open',
          dispute_status: 'not_disputed',
          source: 'system_detected',
          driver_id: 'drv-999',
          created_at: '2026-09-26T08:30:00Z',
        },
        {
          case_id: 'case-beta-5678',
          trip_id: 'trip-102',
          violation_code: 'ERR-999_UNKNOWN',
          violation_title: 'Sự cố chưa phân loại',
          description: 'Sự cố hệ thống chưa xác định',
          alleged_time: '2026-09-26T09:30:00Z',
          status: 'investigating',
          dispute_status: 'unknown_status_code',
          source: 'customer_reported',
          driver_id: 'drv-999',
          created_at: '2026-09-26T09:30:00Z',
        },
      ],
      total: 2,
    });
  });

  it('renders DriverPortalPage in default Vietnamese locale', async () => {
    render(<DriverPortalPage />);

    expect(await screen.findByText('Vụ việc của bạn')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Đang mở/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Đã xử lý/i })).toBeInTheDocument();

    expect(
      await screen.findByText('Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt')
    ).toBeInTheDocument();
    expect(screen.getByText('#1234')).toBeInTheDocument();
  });

  it('renders DriverPortalPage in English when locale is set to "en"', async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverPortalPage />
      </DriverI18nProvider>
    );

    expect(await screen.findByText('Your cases')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Resolved/i })).toBeInTheDocument();

    expect(
      await screen.findByText('Trip/order embezzlement: cancel then collect cash off-app')
    ).toBeInTheDocument();
    expect(screen.getByText('Not disputed')).toBeInTheDocument();
  });

  it('never displays raw unknown code on driver cards; uses generic fallback', async () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverPortalPage />
      </DriverI18nProvider>
    );

    await screen.findByText('Sự cố chưa phân loại');
    expect(screen.queryByText('ERR-999_UNKNOWN')).not.toBeInTheDocument();
    expect(screen.queryByText('unknown_status_code')).not.toBeInTheDocument();
    expect(screen.getByText('Cần xem xét')).toBeInTheDocument();
  });

  it('persists locale into NEXT_LOCALE cookie via setLocaleCookie', () => {
    setLocaleCookie('en');
    expect(document.cookie).toContain('NEXT_LOCALE=en');

    setLocaleCookie('vi');
    expect(document.cookie).toContain('NEXT_LOCALE=vi');
  });

  it('scans app/driver and components/driver for hard-coded Vietnamese diacritics outside messages and fails if found', () => {
    const viDiacriticsRegex = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]/;
    const baseDir = path.resolve(__dirname, '../../../');
    const targetDirs = [
      path.join(baseDir, 'app/driver'),
      path.join(baseDir, 'components/driver'),
    ];

    const violations: string[] = [];

    function scanDir(dirPath: string) {
      if (!fs.existsSync(dirPath)) return;
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dirPath, entry.name);
        if (entry.isDirectory()) {
          scanDir(fullPath);
        } else if (
          (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx')) &&
          !entry.name.endsWith('.test.ts') &&
          !entry.name.endsWith('.test.tsx')
        ) {
          const content = fs.readFileSync(fullPath, 'utf8');
          const lines = content.split('\n');
          lines.forEach((line, idx) => {
            if (viDiacriticsRegex.test(line)) {
              violations.push(`${path.relative(baseDir, fullPath)}:${idx + 1}: ${line.trim()}`);
            }
          });
        }
      }
    }

    targetDirs.forEach(scanDir);
    expect(violations).toEqual([]);
  });
});

