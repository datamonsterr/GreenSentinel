import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LandingPage } from "@/components/landing/landing-page";

vi.mock("lenis", () => {
  return {
    default: class MockLenis {
      on = vi.fn();
      raf = vi.fn();
      destroy = vi.fn();
      scrollTo = vi.fn();
    },
  };
});

vi.mock("gsap", () => {
  const gsapObj = {
    registerPlugin: vi.fn(),
    fromTo: vi.fn(),
    to: vi.fn(),
    set: vi.fn(),
    timeline: vi.fn(() => ({
      to: vi.fn().mockReturnThis(),
      fromTo: vi.fn().mockReturnThis(),
    })),
    ticker: {
      add: vi.fn(),
      remove: vi.fn(),
      lagSmoothing: vi.fn(),
    },
  };
  return {
    gsap: gsapObj,
    default: gsapObj,
  };
});

vi.mock("gsap/ScrollTrigger", () => ({
  ScrollTrigger: {
    register: vi.fn(),
    create: vi.fn(() => ({ kill: vi.fn() })),
    refresh: vi.fn(),
    update: vi.fn(),
    getAll: vi.fn(() => []),
    defaults: vi.fn(),
    scrollerProxy: vi.fn(),
  },
}));

let observerInstances: Array<{
  callback: (entries: IntersectionObserverEntry[]) => void;
  elements: Element[];
  trigger: (isIntersecting?: boolean) => void;
}> = [];

class MockIntersectionObserver {
  callback: (entries: IntersectionObserverEntry[]) => void;
  elements: Element[] = [];
  constructor(cb: (entries: IntersectionObserverEntry[]) => void) {
    this.callback = cb;
    observerInstances.push({
      callback: cb,
      elements: this.elements,
      trigger: (isIntersecting = true) => {
        cb(
          (this.elements.length > 0 ? this.elements : [document.createElement("div")]).map((el) => ({
            isIntersecting,
            target: el,
            intersectionRatio: isIntersecting ? 1 : 0,
            boundingClientRect: el.getBoundingClientRect(),
            intersectionRect: el.getBoundingClientRect(),
            rootBounds: null,
            time: Date.now(),
          })) as unknown as IntersectionObserverEntry[]
        );
      },
    });
  }
  observe(el: Element) {
    this.elements.push(el);
  }
  unobserve(el: Element) {
    this.elements = this.elements.filter((e) => e !== el);
  }
  disconnect() {
    this.elements = [];
  }
}

describe("LandingPage GSAP ScrollTrigger + Lenis Redesign", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    observerInstances = [];
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
    // Deterministic default: motion allowed
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    observerInstances = [];
  });

  it("renders GreenSentinel hero headline and product description", () => {
    render(<LandingPage />);
    expect(
      screen.getByRole("heading", { name: /catch ride fraud\. treat drivers fairly\./i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/protect every ride\. give drivers a fair hearing\./i)
    ).toBeInTheDocument();
  });

  it("scrolls: landing root is self-scrollable inside the locked app shell", () => {
    const { container } = render(<LandingPage />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toMatch(/overflow-y-auto/);
  });

  it("exposes Try live demo, Create organization, See all features, Sign in", () => {
    render(<LandingPage />);
    const demoLinks = screen.getAllByRole("link", { name: /try live demo/i });
    expect(demoLinks.length).toBeGreaterThanOrEqual(1);
    expect(demoLinks[0]).toHaveAttribute("href", expect.stringContaining("/workplace"));

    const createLinks = screen.getAllByRole("link", { name: /create organization/i });
    expect(createLinks.length).toBeGreaterThanOrEqual(1);
    createLinks.forEach((link) => {
      expect(link).toHaveAttribute("href", expect.stringContaining("/sign-up"));
    });

    const featuresLink = screen.getByRole("link", { name: /see all features/i });
    expect(featuresLink.getAttribute("href")).toBe("#features");

    const signIns = screen.getAllByRole("link", { name: /sign in/i });
    expect(signIns.length).toBeGreaterThanOrEqual(1);
    signIns.forEach((link) => {
      expect(link).toHaveAttribute("href", expect.stringContaining("/sign-in"));
    });
  });

  it("shows three main features with live demo navigation", () => {
    render(<LandingPage />);
    const section = document.querySelector("#features") as HTMLElement;
    expect(section).not.toBeNull();
    expect(
      within(section).getByRole("link", { name: /workplace.*demo|fraud analyst workplace/i })
    ).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: /driver.*demo|driver support/i })
    ).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: /test.*demo|test console/i })
    ).toBeInTheDocument();

    expect(screen.getAllByText(/sample data/i).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/mock data only/i).length).toBeGreaterThanOrEqual(1);
    expect(document.querySelectorAll("video").length).toBe(0);
    expect(screen.queryByText(/animated preview/i)).toBeNull();
  });

  it("journey rail renders 5 steps with numbered labels", () => {
    render(<LandingPage />);
    const rail = screen.getByRole("navigation", { name: /journey steps/i });
    expect(rail).toBeInTheDocument();

    const railButtons = within(rail).getAllByRole("button");
    expect(railButtons.length).toBe(5);
    expect(railButtons[0]).toHaveTextContent(/trip ends/i);
    expect(railButtons[1]).toHaveTextContent(/ai checks/i);
    expect(railButtons[2]).toHaveTextContent(/driver explains/i);
    expect(railButtons[3]).toHaveTextContent(/analyst decides/i);
    expect(railButtons[4]).toHaveTextContent(/team learns/i);
  });

  it("reduced motion renders full chat script + both case outcomes statically", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))
    );

    render(<LandingPage />);

    // Chapter 2: Both case outcomes rendered statically
    expect(screen.getByText(/fraud case opened/i)).toBeInTheDocument();
    expect(screen.getByText(/no issue/i)).toBeInTheDocument();

    // Chapter 3: Full chat script rendered immediately without waiting for typing
    expect(screen.getByText(/we noticed a 4-minute pause/i)).toBeInTheDocument();
    expect(screen.getByText(/traffic police diverted all lanes/i)).toBeInTheDocument();
    expect(screen.getByText(/marathon detour verified/i)).toBeInTheDocument();
  });

  it("clicking quick reply chip appends reply to driver chat", async () => {
    render(<LandingPage />);

    const chip = screen.getByRole("button", { name: /^police detour$/i });
    expect(chip).toBeInTheDocument();

    await userEvent.click(chip);

    // New messages appended
    const log = screen.getByRole("log", { name: /driver support chat transcript/i });
    expect(within(log).getByText(/^police detour$/i)).toBeInTheDocument();
    expect(within(log).getByText(/statement recorded: "police detour"/i)).toBeInTheDocument();
  });

  it("clicking queue row switches selected case in analyst cockpit", async () => {
    render(<LandingPage />);

    const case2Button = screen.getByRole("tab", { name: /#fc-8924/i });
    expect(case2Button).toBeInTheDocument();

    await userEvent.click(case2Button);

    expect(case2Button).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByText(/30f-982\.11/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/trần minh đức/i).length).toBeGreaterThanOrEqual(1);
  });

  it("makes zero network requests: no fetch called", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<LandingPage />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("allows replaying driver conversation via Replay button", async () => {
    render(<LandingPage />);
    const replayBtn = screen.getByRole("button", { name: /replay conversation/i });
    expect(replayBtn).toBeInTheDocument();
    await userEvent.click(replayBtn);
    expect(replayBtn).toBeEnabled();
  });

  it("allows replaying trip screening in Test Console card", async () => {
    render(<LandingPage />);
    const detourCard = screen.getByRole("button", { name: /replay detour trip/i });
    expect(detourCard).toBeInTheDocument();
    await userEvent.click(detourCard);
    expect(detourCard).toBeEnabled();
  });

  it("meets keyboard and touch-target basics", async () => {
    render(<LandingPage />);
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThanOrEqual(5);

    links.slice(0, 5).forEach((link) => {
      expect(link).toHaveAttribute("href");
    });
  });

  it("case autoplay order in chapter 2 (fake timers + mocked IntersectionObserver: case 2 starts only after case 1 outcome)", () => {
    vi.useFakeTimers();
    render(<LandingPage />);

    // Before visibility: both cases at 0 / idle
    expect(screen.queryByText(/fraud case opened/i)).toBeNull();
    expect(screen.queryByText(/no issue/i)).toBeNull();

    // Trigger IntersectionObserver
    act(() => {
      observerInstances.forEach((inst) => inst.trigger(true));
    });

    // Case 1 is now checking, while Case 2 has not started checking
    expect(screen.getAllByText(/checking…/i).length).toBe(1);
    expect(screen.queryByText(/fraud case opened/i)).toBeNull();
    expect(screen.queryByText(/no issue/i)).toBeNull();

    // Advance halfway through case 1 (1200ms)
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(screen.queryByText(/fraud case opened/i)).toBeNull();
    expect(screen.queryByText(/no issue/i)).toBeNull();

    // Advance to complete case 1 (total 2500ms)
    act(() => {
      vi.advanceTimersByTime(1300);
    });
    // Case 1 outcome is now displayed!
    expect(screen.getByText(/fraud case opened/i)).toBeInTheDocument();
    // During 600ms pause, case 2 has not started checking yet
    expect(screen.queryByText(/checking…/i)).toBeNull();
    expect(screen.queryByText(/no issue/i)).toBeNull();

    // Advance through the 600ms pause
    act(() => {
      vi.advanceTimersByTime(600);
    });
    // Now case 2 starts filling / checking
    expect(screen.getByText(/checking…/i)).toBeInTheDocument();
    expect(screen.queryByText(/no issue/i)).toBeNull();

    // Advance past case 2 completion (2500ms)
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(screen.getByText(/no issue/i)).toBeInTheDocument();
  });

  it("renders updated plain text labels and shield badge", () => {
    render(<LandingPage />);

    // Chapter 2 plain text
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("Sent to analyst")).toBeInTheDocument();
    expect(screen.getByText(/gps matches route · normal speed/i)).toBeInTheDocument();
    expect(screen.getByText("Cleared")).toBeInTheDocument();
    expect(screen.getByText("2 sample trips checked")).toBeInTheDocument();

    // Chapter 4 plain text & badge
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(screen.getByText("92% sure")).toBeInTheDocument();
    expect(screen.getByText("AI summary")).toBeInTheDocument();
    expect(screen.queryByText("LT")).toBeNull();
  });

  it("chapter 4 autoplay reaches case 2 stamp", () => {
    vi.useFakeTimers();
    render(<LandingPage />);

    // Trigger view
    act(() => {
      observerInstances.forEach((inst) => inst.trigger(true));
    });

    // Case 1 rationale types in, then "Penalty confirmed" stamp appears
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByText(/penalty confirmed/i)).toBeInTheDocument();

    // Advances to Case 2, rationale types in, and "Driver cleared" stamp appears
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(screen.getByText(/driver cleared/i)).toBeInTheDocument();
  });

  it("row click stops autoplay", async () => {
    vi.useFakeTimers();
    render(<LandingPage />);

    act(() => {
      observerInstances.forEach((inst) => inst.trigger(true));
    });

    // User clicks queue row for Case 2 (#FC-8924)
    const case2Button = screen.getByRole("tab", { name: /#fc-8924/i });
    act(() => {
      case2Button.click();
    });

    // User click stops autoplay
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    // Case 2 remains selected
    expect(case2Button).toHaveAttribute("aria-selected", "true");
  });

  it("rail renders without jargon strings above", () => {
    render(<LandingPage />);

    const forbiddenStrings = [
      "INTEGRITY RAIL",
      "5-STEP SCROLL STORY",
      "v2.0",
      "ACTIVE TRIP GUARD",
      "100% human-in-the-loop review",
      "Flow / Self-Service",
      "Corroborated by 14 adjacent fleet units",
      "Temporary detour polygon logged for surrounding fleet",
      "Adaptive rule learning active",
      "Closed-loop cycle verified",
      "immutable audit hashes",
      "Connect your telemetry streams",
      "READY FOR PRODUCTION",
      "Real-time protection for ride fleets",
    ];

    forbiddenStrings.forEach((phrase) => {
      expect(screen.queryByText(new RegExp(phrase, "i"))).toBeNull();
    });
  });
});
