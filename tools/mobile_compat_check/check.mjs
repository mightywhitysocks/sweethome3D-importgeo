#!/usr/bin/env node
/**
 * check.mjs : charge un fichier .sh3d dans le vrai moteur JS eTeks
 * (SweetHome3DJS, celui de Sweet Home 3D Online -- l'appli mobile declare
 * officiellement partager la meme compatibilite de format) via Chromium
 * headless, et rapporte succes/echec explicite.
 *
 * Outil autonome (cf. README.md de ce dossier) : ne touche jamais au
 * pipeline principal ni a data/, sert uniquement a verifier qu'un .sh3d
 * donne (celui de la fixture synthetique, ou un vrai Plan 3D.sh3d passe en
 * argument) se charge sans erreur cote moteur mobile.
 *
 * Usage : node check.mjs <chemin.sh3d> [--timeout-ms 15000] [--screenshot out.png]
 */
import { chromium } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".sh3d": "application/octet-stream", ".sh3x": "application/octet-stream",
  ".png": "image/png", ".json": "application/json",
};

function serveStatic(root) {
  return http.createServer(async (req, res) => {
    try {
      const urlPath = decodeURIComponent(new URL(req.url, "http://x").pathname);
      const filePath = path.join(root, urlPath);
      if (!filePath.startsWith(root)) { res.writeHead(403); res.end(); return; }
      const data = await readFile(filePath);
      const ext = path.extname(filePath);
      res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
      res.end(data);
    } catch (e) {
      res.writeHead(404);
      res.end("not found: " + e.message);
    }
  });
}

async function main() {
  const args = process.argv.slice(2);
  const sh3dPath = path.resolve(args[0] || "");
  if (!sh3dPath || !existsSync(sh3dPath)) {
    console.error("Usage: node check.mjs <chemin.sh3d> [--timeout-ms N] [--screenshot out.png]");
    process.exit(2);
  }
  const timeoutMsIdx = args.indexOf("--timeout-ms");
  const timeoutMs = timeoutMsIdx >= 0 ? Number(args[timeoutMsIdx + 1]) : 15000;
  const shotIdx = args.indexOf("--screenshot");
  const screenshotPath = shotIdx >= 0 ? path.resolve(args[shotIdx + 1]) : null;

  if (!sh3dPath.startsWith(REPO_ROOT)) {
    console.error("Le .sh3d doit se trouver sous le depot (" + REPO_ROOT + ") pour etre servi.");
    process.exit(2);
  }
  const sh3dUrlPath = "/" + path.relative(REPO_ROOT, sh3dPath).split(path.sep).join("/");

  const server = serveStatic(REPO_ROOT);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;

  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  const pageUrl =
    `http://127.0.0.1:${port}/tools/mobile_compat_check/viewer/index.html` +
    `?url=${encodeURIComponent(sh3dUrlPath)}`;
  await page.goto(pageUrl);
  await page.waitForTimeout(timeoutMs);

  const chk = await page.evaluate(() => window.__chk);

  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath });
  }

  await browser.close();
  server.close();

  const errors = [...consoleErrors, ...pageErrors, ...(chk?.errors || []), ...(chk?.pageerrors || [])];
  const ok = chk?.calledBack && errors.length === 0;

  console.log(JSON.stringify({
    sh3d: sh3dPath,
    ok,
    progress: chk?.progress ?? null,
    calledBack: chk?.calledBack ?? false,
    errors,
    screenshot: screenshotPath,
  }, null, 2));

  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error("check.mjs: erreur inattendue:", e);
  process.exit(2);
});
