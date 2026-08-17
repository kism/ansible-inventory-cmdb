#!/usr/bin/env node
// Loads every @font-face rule in zy.css in a real browser, so a woff2 that is missing,
// corrupt, or never regenerated after a weight was added to zy.css fails the build.
// Usage: npm run check_fonts   (needs: npx playwright install --with-deps chromium)

import { spawn } from "node:child_process";
import { chromium } from "playwright";

const PORT = 5101;
const BASE = `http://127.0.0.1:${PORT}`;
// The package dir is the server root so zy.css's absolute /static/... urls resolve.
const ROOT = new URL("../src/ansibleinventorycmdb", import.meta.url).pathname;

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1", "-d", ROOT], {
  stdio: "ignore",
});

try {
  for (let attempt = 0; ; attempt++) {
    try {
      await fetch(BASE);
      break;
    } catch (error) {
      if (attempt === 50) throw error;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(BASE, { waitUntil: "load" });
    await page.addStyleTag({ url: "/static/zy.css" });

    const results = await page.evaluate(async () => {
      const specs = [];
      for (const sheet of document.styleSheets) {
        for (const rule of sheet.cssRules) {
          if (rule instanceof CSSFontFaceRule) {
            specs.push(`${rule.style.fontStyle} ${rule.style.fontWeight} 16px ${rule.style.fontFamily}`);
          }
        }
      }
      const out = [];
      for (const spec of specs) {
        try {
          await document.fonts.load(spec);
          out.push({ spec, checked: document.fonts.check(spec) });
        } catch (error) {
          out.push({ spec, checked: false, error: String(error) });
        }
      }
      return out;
    });

    for (const result of results) {
      console.log(`[${result.checked ? "OK" : "FAILED"}] ${result.spec}${result.error ? ` -- ${result.error}` : ""}`);
    }

    const failures = results.filter((result) => !result.checked);
    if (results.length === 0) {
      console.error("No @font-face rules found, zy.css did not load");
      process.exit(1);
    }
    if (failures.length > 0) {
      console.error(`${failures.length}/${results.length} font(s) failed to load`);
      process.exit(1);
    }
    console.log(`All ${results.length} fonts loaded successfully`);
  } finally {
    await browser.close();
  }
} finally {
  server.kill();
}
