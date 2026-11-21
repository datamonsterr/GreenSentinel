/**
 * Sprint 3 Playwright UAT spec for issue #197
 *
 * Covers FEAT-S3-01 through FEAT-S3-07.
 * Path: src/webapp/tests/e2e/sprint3-workflow.spec.ts
 */

import { test, expect } from "../../test-support/playwright";
import { installApiFixtures } from "../../../../tests/e2e/browser/api-fixtures";

test.describe("Sprint 3 multi-persona workflow", () => {
  test.describe("Analyst Persona (/workplace)", () => {
    test.beforeEach(async ({ page }) => {
      await installApiFixtures(page);
      await page.goto("/workplace");

      const caseButton = page
        .getByRole("region", { name: "Triage queue" })
        .locator("button[aria-pressed]")
        .first();
      await expect(caseButton).toBeVisible();
      await caseButton.click();
    });

    test("FEAT-S3-01: Forensic Brief and Copilot show consistent motivation assessment", async ({ page }) => {
      // Model intent stays out of Overview even with a saved judgment; the
      // recorded narrative lives behind the Complete reveal gate after the
      // workspace reveal-boundary change.
      const overview = page.getByRole("tabpanel", { name: "Overview", exact: true });
      const motivation = overview.locator("section").filter({
        has: page.getByRole("heading", { name: "Motivation", exact: true }),
      });
      // Structured, versioned motivation assessment (unsaved rule draft) replaces the "Not assessed" placeholder.
      await expect(motivation.getByTestId("motivation-card").getByText("Subsidy / surge")).toBeVisible();
      await expect(motivation.getByText("Not saved")).toBeVisible();
      await expect(motivation.getByText(/Not assessed/i)).toHaveCount(0);
      await expect(overview.getByText(/tài xế có thể kéo dài hành trình/i)).toHaveCount(0);

      await page.getByRole("button", { name: "Claim", exact: true }).click();
      await page.getByRole("tab", { name: "Complete", exact: true }).click();
      const results = page.getByRole("region", { name: "AI results", exact: true });
      await expect(results.getByText(/Dữ liệu cho thấy tài xế có thể kéo dài hành trình để hưởng thêm 25\.000 đồng/i)).toBeVisible();
      await expect(results.getByText(/25[.,\s]000\s*₫/)).toBeVisible();

      const copilotInput = page.getByPlaceholder("Ask Agents about this case…");
      await copilotInput.fill("Tóm tắt động cơ và hành vi của tài xế");
      await copilotInput.press("Enter");
      const copilotPanel = page.locator("#panel-ai-copilot");
      await expect(copilotPanel.getByText(/tài xế có thể kéo dài hành trình để hưởng thêm 25\.000 đồng/i)).toBeVisible();
      await expect(copilotPanel.getByText(/Lợi ích tăng thêm ước tính: 25\.000 ₫/i)).toBeVisible();
    });

    test.fixme("FEAT-S3-02: Copilot drawer shows traffic tool call badges", async ({ page }) => {
      const copilotInput = page.getByPlaceholder("Ask Agents about this case…");
      await copilotInput.fill("Kiểm tra tình trạng kẹt xe trên đoạn đường này");
      await copilotInput.press("Enter");
      await expect(page.getByLabel(/Tool fetch_corridor_historical_traffic/)).toBeVisible();
      await expect(page.getByLabel(/Tool query_traffic_incident_feed/)).toBeVisible();
    });

    test.fixme(
      "FEAT-S3-03: Center Panel has document upload dropzone and document list",
      async ({ page }) => {
        await expect(page.getByRole("region", { name: /Uploaded Documents/i })).toBeVisible();
        await expect(page.getByRole("button", { name: /Upload/i })).toBeVisible();
      }
    );

    test(
      "FEAT-S3-04: Conversation tab is read-only and Copilot has dual tabs",
      async ({ page }) => {
        await page.getByRole("tab", { name: "Customer", exact: true }).click();
        const conversation = page.getByRole("region", { name: "Driver–customer conversation" });
        await expect(conversation.getByRole("textbox")).toHaveCount(0);
        await expect(conversation.getByText(/^\d+ turns?$/)).toBeVisible();
        await expect(conversation.getByRole("status", { name: "Conversation summary" })).toBeVisible();

        const agentPanels = page.getByRole("tablist", { name: "Agent panels" });
        await expect(agentPanels.getByRole("tab", { name: /Analyst Copilot|AI Copilot|Trợ lý/i })).toBeVisible();
        await expect(agentPanels.getByRole("tab", { name: "Driver", exact: true })).toBeVisible();
      }
    );
  });

  test.describe("Tester Persona (/test)", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/test");
      await page.waitForLoadState("domcontentloaded");
    });

    test.fixme(
      'FEAT-S3-07: /test dashboard has "Run E2E Lifecycle Demo" button and live stepper',
      async ({ page }) => {
        await expect(page.getByRole("button", { name: /Run E2E Lifecycle Demo/i })).toBeVisible();
        await page.getByRole("button", { name: /Run E2E Lifecycle Demo/i }).click();
        await expect(page.getByText(/Telemetry Ingestion/i)).toBeVisible();
        await expect(page.getByText(/Adjudication/i)).toBeVisible();
      }
    );
  });
});
