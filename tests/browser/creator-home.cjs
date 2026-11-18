/* Owner entry, including the independent shortcuts while the week's data is slow. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.TCE_PLAYWRIGHT_MODULE || "playwright");
const assets = path.resolve(__dirname, "../../src/tce/api");

(async () => {
  const browser = await chromium.launch({ channel: process.env.TCE_BROWSER_CHANNEL || undefined });
  try {
    for (const prefix of ["", "/tce"]) {
      const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
      let mode = "pending", releaseWeek, extras = 0;
      const waiting = new Promise(resolve => { releaseWeek = resolve; });
      await page.route("**/*", async route => {
        const url = new URL(route.request().url());
        const urlPath = url.pathname.slice(prefix.length);
        if (urlPath === "/api/v1/editorial/today") {
          if (mode === "pending") await waiting;
          if (mode === "error") return route.fulfill({ status: 400, json: { detail: "Week unavailable" } });
          return route.fulfill({ json: { week: { primary: [] }, attention: {}, next_action: {} } });
        }
        if (urlPath.startsWith("/api/")) {
          extras++;
          return route.fulfill({ json: {} });
        }
        const file = urlPath === "/today" ? "workspace.html" : urlPath.slice(1);
        if (!["workspace.html", "workspace.js", "workspace.css", "talk-voice.css", "talk-voice.js", "recording-resume.js", "take-reward.js"].includes(file)) return route.abort();
        return route.fulfill({ body: fs.readFileSync(path.join(assets, file)), contentType: file.endsWith(".html") ? "text/html" : file.endsWith(".css") ? "text/css" : "text/javascript" });
      });
      await page.goto("https://test.invalid" + prefix + "/today", { waitUntil: "domcontentloaded" });
      const solo = page.getByRole("link", { name: "Record without a script" });
      const book = page.getByRole("link", { name: "Review my book" });
      assert.equal(await solo.getAttribute("href"), prefix + "/record/solo");
      assert.equal(await book.getAttribute("href"), prefix + "/book");
      releaseWeek();
      await page.locator(".creator-primary").waitFor();
      assert.equal(await page.locator(".creator-primary").getAttribute("href"), prefix + "/record/solo");
      assert.equal(extras, 0);
      await page.getByText("Production details", { exact: true }).click();
      await page.locator(".counts").waitFor();
      assert.equal(extras, 3);
      mode = "error";
      await page.reload();
      await page.getByRole("button", { name: "Try again" }).waitFor();
      assert.ok(await solo.isVisible() && await book.isVisible());
      mode = "ok";
      await page.getByRole("button", { name: "Try again" }).click();
      await page.locator(".creator-primary").waitFor();
      await page.close();
    }
    console.log("Creator home passed at both mounts, including slow, empty, failed and recovered weeks.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
