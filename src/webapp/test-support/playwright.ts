// Resolve the installed browser framework from the webapp package.
import { test as base } from "@playwright/test";
export * from "@playwright/test";

// Fixture browser suites do not depend on live third-party basemap assets.
export const test = base.extend({
  page: async ({ page }, provide) => {
    await page.route("**/styles/liberty", route => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: "test-background", type: "background", paint: { "background-color": "#f8fafc" } }],
    } }));
    await provide(page);
  },
});
