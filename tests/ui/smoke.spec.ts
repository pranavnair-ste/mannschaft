import { test, expect } from "@playwright/test";

test("landing page lists runs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("run-list")).toBeVisible();
  await expect(page.getByText("r-fixture-1")).toBeVisible();
});

test("run detail shows timeline with guide icon", async ({ page }) => {
  await page.goto("/runs/r-fixture-1");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("guide-icon").first()).toBeVisible();
});

test("branch button POSTs and succeeds", async ({ page }) => {
  await page.goto("/runs/r-fixture-1");
  const branchBtn = page.getByTestId("branch-s-1").first();
  await expect(branchBtn).toBeVisible();
  const [resp] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/runs/r-fixture-1/branch") && r.request().method() === "POST",
    ),
    branchBtn.click(),
  ]);
  expect([200, 409]).toContain(resp.status());
});

test("corpus health page renders gauge", async ({ page }) => {
  await page.goto("/corpus");
  await expect(page.getByTestId("corpus-gauge")).toBeVisible();
  await expect(page.getByTestId("corpus-pct")).toContainText("%");
});

test("specs page loads", async ({ page }) => {
  await page.goto("/specs");
  await expect(page.getByText("Prompt Shape · Specs")).toBeVisible();
});
