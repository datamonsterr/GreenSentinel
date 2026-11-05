import { beforeEach, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  SignOutButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import OnboardingPage from "../../../app/onboarding/page";

beforeEach(() => {
  vi.unstubAllEnvs();
});

test("onboarding explains pending provisioning without auth calls", () => {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "");
  render(<OnboardingPage />);
  expect(screen.getByRole("heading", { name: /pending setup/i })).toBeInTheDocument();
  expect(screen.getByText(/no organization or role is assigned/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /back to home/i })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: /switch account/i })).toHaveAttribute("href", "/sign-in");
});

test("keyed switch account clears session via sign-out button", () => {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test");
  render(<OnboardingPage />);
  expect(screen.getByRole("button", { name: /switch account/i })).toBeInTheDocument();
});
