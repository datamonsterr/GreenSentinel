'use client';

import React from 'react';

export const mockDriverUser = {
  id: 'user_e2e_driver_an',
  fullName: 'Nguyen Van An',
  primaryEmailAddress: { emailAddress: 'an.nguyen@greensm.vn' },
  imageUrl: '',
};

export function useUser() {
  return {
    user: mockDriverUser,
    isLoaded: true,
    isSignedIn: true,
  };
}

export function useClerk() {
  return {
    signOut: async (cb?: () => void) => {
      if (typeof cb === 'function') {
        cb();
      }
    },
    openUserProfile: () => {},
  };
}

export function useAuth() {
  return {
    isLoaded: true,
    isSignedIn: true,
    userId: 'user_e2e_driver_an',
    sessionId: 'sess_e2e_test',
    orgId: 'org_test',
    orgRole: 'org:driver',
    getToken: async () => 'mock-jwt-token',
  };
}

export const ClerkProvider = ({ children }: { children: React.ReactNode }) => <>{children}</>;
export const SignIn = () => <div data-testid="clerk-sign-in">Sign In</div>;
export const SignUp = () => <div data-testid="clerk-sign-up">Sign Up</div>;
export const SignOutButton = ({ children }: { children: React.ReactNode }) => <button>{children}</button>;
export const UserButton = () => <div data-testid="clerk-user-button">User Button</div>;
export const OrganizationSwitcher = () => <div data-testid="clerk-org-switcher">Org Switcher</div>;
