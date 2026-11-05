import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import userEvent from "@testing-library/user-event";
import { LocaleProvider, useLocale } from "@/lib/locale";

function Controls() {
  const { locale, setLocale } = useLocale();
  return <><output aria-label="Locale">{locale}</output><button onClick={() => setLocale("vi")}>Vietnamese</button><button onClick={() => setLocale("en")}>English</button></>;
}

beforeEach(() => { localStorage.clear(); document.documentElement.lang = "en"; });
afterEach(() => { vi.restoreAllMocks(); });

test("switching locale persists the choice and updates document language", async () => {
  render(<LocaleProvider><Controls /></LocaleProvider>);
  expect(screen.getByLabelText("Locale")).toHaveTextContent("en");
  await userEvent.click(screen.getByRole("button", { name: "Vietnamese" }));
  expect(screen.getByLabelText("Locale")).toHaveTextContent("vi");
  expect(localStorage.getItem("greensentinel.locale")).toBe("vi");
  expect(document.documentElement.lang).toBe("vi");
});

test("restores a saved Vietnamese choice after an English server render without hydration errors", async () => {
  localStorage.setItem("greensentinel.locale", "vi");
  const tree = <LocaleProvider><Controls /></LocaleProvider>;
  const container = document.createElement("div");
  container.innerHTML = renderToString(tree);
  expect(container.querySelector("output")).toHaveTextContent("en");
  const onRecoverableError = vi.fn();
  let root: ReturnType<typeof hydrateRoot>;
  await act(async () => { root = hydrateRoot(container, tree, { onRecoverableError }); });
  expect(container.querySelector("output")).toHaveTextContent("vi");
  expect(localStorage.getItem("greensentinel.locale")).toBe("vi");
  expect(document.documentElement.lang).toBe("vi");
  expect(onRecoverableError).not.toHaveBeenCalled();
  await act(async () => { root.unmount(); });
});

test.each([null, "fr", "VI", "", '{"locale":"vi"}'])("uses English for missing or invalid saved value %s", (saved) => {
  if (saved !== null) localStorage.setItem("greensentinel.locale", saved);
  render(<LocaleProvider><Controls /></LocaleProvider>);
  expect(screen.getByLabelText("Locale")).toHaveTextContent("en");
  expect(document.documentElement.lang).toBe("en");
});

test("storage read and write failures do not prevent switching in either direction", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Full", "QuotaExceededError"); });
  render(<LocaleProvider><Controls /></LocaleProvider>);
  expect(screen.getByLabelText("Locale")).toHaveTextContent("en");
  await userEvent.click(screen.getByRole("button", { name: "Vietnamese" }));
  expect(screen.getByLabelText("Locale")).toHaveTextContent("vi");
  expect(document.documentElement.lang).toBe("vi");
  await userEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByLabelText("Locale")).toHaveTextContent("en");
  expect(document.documentElement.lang).toBe("en");
});

test("isolated consumers have a safe English fallback with a harmless setter", async () => {
  render(<Controls />);
  await userEvent.click(screen.getByRole("button", { name: "Vietnamese" }));
  expect(screen.getByLabelText("Locale")).toHaveTextContent("en");
  expect(localStorage.getItem("greensentinel.locale")).toBeNull();
});

test("a new provider restores the choice after unmounting", async () => {
  const view = render(<LocaleProvider><Controls /></LocaleProvider>);
  await userEvent.click(screen.getByRole("button", { name: "Vietnamese" }));
  view.unmount();
  render(<LocaleProvider><Controls /></LocaleProvider>);
  expect(screen.getByLabelText("Locale")).toHaveTextContent("vi");
});
