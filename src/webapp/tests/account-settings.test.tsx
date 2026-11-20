import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { expect, it, vi, beforeEach } from 'vitest';
import { AccountSettingsModal } from '@/components/account/account-settings-modal';
import WorkplacePage from '@/app/workplace/page';
import * as api from '@/lib/api-client';

vi.mock('@clerk/nextjs', () => {
  const UserButtonMock = Object.assign(
    ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="mock-user-button">
        UserButton
        {children}
      </div>
    ),
    {
      MenuItems: ({ children }: { children?: React.ReactNode }) => (
        <div data-testid="mock-user-button-menu-items">{children}</div>
      ),
      Action: ({ label, onClick }: { label: string; onClick?: () => void }) => (
        <button type="button" onClick={onClick} aria-label={label}>
          {label}
        </button>
      ),
    }
  );
  return {
    useAuth: () => ({ getToken: async () => 'test-token', isLoaded: true }),
    OrganizationSwitcher: ({ hidePersonal }: { hidePersonal?: boolean }) => (
      <div data-testid="mock-organization-switcher">OrganizationSwitcher</div>
    ),
    UserButton: UserButtonMock,
  };
});

describe('Account Settings & RBAC UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, 'fetchCases').mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.spyOn(api, 'fetchCurrentAnalyst').mockResolvedValue({
      id: 'analyst-001',
      name: 'Lê Minh Tuấn',
      role: 'fraud_analyst', roles: ["fraud_analyst"],
    });
  });

  it('renders AccountSettingsModal with user details, role capabilities, and updates display name', async () => {
    vi.spyOn(api, 'fetchAccountSettings').mockResolvedValue({
      id: 'user-001',
      display_name: 'Lê Minh Tuấn',
      email: 'tuan@vinuni.edu.vn',
      roles: ['fraud_analyst'],
      primary_role: 'fraud_analyst',
      organization_id: 'org-001',
      driver_id: null,
    });
    const updateNameSpy = vi.spyOn(api, 'updateAccountSettings').mockResolvedValue({
      id: 'user-001',
      display_name: 'Lê Minh Tuấn (Senior)',
      roles: ['fraud_analyst'],
      primary_role: 'fraud_analyst',
      organization_id: 'org-001',
      driver_id: null,
    });

    const onClose = vi.fn();
    render(<AccountSettingsModal isOpen={true} onClose={onClose} />);

    expect(await screen.findByText('Account Settings & Permissions')).toBeInTheDocument();
    expect(screen.getByText('Lê Minh Tuấn')).toBeInTheDocument();
    expect(screen.getByText('Fraud Analyst (Adjudication)')).toBeInTheDocument();
    expect(screen.getByText('Role Capabilities')).toBeInTheDocument();

    // Update display name
    const input = screen.getByLabelText('Display Name');
    fireEvent.change(input, { target: { value: 'Lê Minh Tuấn (Senior)' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Name' }));

    await waitFor(() => expect(updateNameSpy).toHaveBeenCalledWith({ display_name: 'Lê Minh Tuấn (Senior)' }));
    expect(await screen.findByText(/Profile name updated successfully/i)).toBeInTheDocument();

    // Close modal
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('does not render team role modification dropdown in AccountSettingsModal as roles are managed in Clerk', async () => {
    vi.spyOn(api, 'fetchAccountSettings').mockResolvedValue({
      id: 'admin-001',
      display_name: 'Nguyen Admin',
      email: 'admin@vinuni.edu.vn',
      roles: ['admin'],
      primary_role: 'admin',
      organization_id: 'org-001',
      driver_id: null,
    });

    render(<AccountSettingsModal isOpen={true} onClose={vi.fn()} />);

    expect(await screen.findByText('Account Settings & Permissions')).toBeInTheDocument();
    expect(screen.getByText('Nguyen Admin')).toBeInTheDocument();
    expect(screen.queryByText('Team Role Management (Manager Only)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Select role for/i)).not.toBeInTheDocument();
  });

  it('verifies WorkplacePage renders OrganizationSwitcher and UserButton without custom role settings modal', async () => {
    render(<WorkplacePage />);

    // Redundant LT avatar should not exist
    expect(screen.queryByText('LT')).not.toBeInTheDocument();
    expect(screen.queryByTitle(/FA-8492/i)).not.toBeInTheDocument();

    // Standalone Settings button should not exist
    expect(screen.queryByRole('button', { name: 'Open Account Settings' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Settings' })).not.toBeInTheDocument();

    // Clerk OrganizationSwitcher and UserButton are rendered
    expect(screen.getByTestId('mock-organization-switcher')).toBeInTheDocument();
    expect(screen.getByTestId('mock-user-button')).toBeInTheDocument();

    // AccountSettingsModal is not invoked in WorkplacePage
    expect(screen.queryByText('Account Settings & Permissions')).not.toBeInTheDocument();
  });
});
