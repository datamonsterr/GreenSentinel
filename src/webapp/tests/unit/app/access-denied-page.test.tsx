import { beforeEach, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  SignOutButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { AccessDeniedCard } from "../../../app/access-denied/access-denied-card";

beforeEach(() => {
  vi.unstubAllEnvs();
});

test("driver role: back link points to /driver, keyless switch account is a link", () => {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "");
  render(<AccessDeniedCard role="driver" />);
  expect(screen.getByRole("heading", { name: /not available for your account/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /back to driver view/i })).toHaveAttribute("href", "/driver");
  expect(screen.getByRole("link", { name: /switch account/i })).toHaveAttribute("href", "/sign-in");
});

test("analyst role: back link points to /workspace", () => {
  render(<AccessDeniedCard role="analyst" />);
  expect(screen.getByRole("link", { name: /back to analyst view/i })).toHaveAttribute("href", "/workspace");
});

test("admin role: back link points to /organization", () => {
  render(<AccessDeniedCard role="admin" />);
  expect(screen.getByRole("link", { name: /back to admin view/i })).toHaveAttribute("href", "/organization");
});

test("unknown/missing role falls back to home", () => {
  render(<AccessDeniedCard role={null} />);
  expect(screen.getByRole("link", { name: /back to home/i })).toHaveAttribute("href", "/");
});

test("keyed switch account renders a sign-out button, not a link", () => {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test");
  render(<AccessDeniedCard role="driver" />);
  expect(screen.getByRole("button", { name: /switch account/i })).toBeInTheDocument();
});
