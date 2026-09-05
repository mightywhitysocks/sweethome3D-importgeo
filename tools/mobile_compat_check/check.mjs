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
 * argument, n'importe ou sur le disque) se charge sans erreur cote moteur
 * mobile.
 *
 * Usage : node check.mjs <chemin.sh3d> [--screenshot out.png]
 *
 * Sert les assets (viewer/, node_modules/) et le .sh3d cible via
 * `page.route()` (interception reseau Playwright) plutot qu'un serveur
 * HTTP maison : evite une table MIME et un garde anti-traversal a
 * reecrire soi-meme, et permet de servir un .sh3d situe n'importe ou
 * (pas seulement sous ce depot).
 */
import { chromium } from "playwright";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TOOL_DIR = HERE;
const FAKE_ORIGIN = "https://mobile-compat-check.invalid";
const WAIT_MS = 15000;

const MIME = { ".html": "text/html", ".js": "text/javascript" };

/** Sert TOOL_DIR (viewer/, node_modules/) sous FAKE_ORIGIN, et `sh3dPath`
 * sous un nom d'URL fixe -- quel que soit son emplacement reel sur disque. */
function installRoutes(page, sh3dPath) {
  return page.route(`${FAKE_ORIGIN}/**`, async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/__target.sh3d") {
      return route.fulfill({ path: sh3dPath, contentType: "application/octet-stream" });
    }
    const rel = pathname === "/" ? "viewer/index.html" : pathname.slice(1);
    const filePath = path.join(TOOL_DIR, rel);
    if (path.relative(TOOL_DIR, filePath).startsWith("..")) {
      return route.fulfill({ status: 403, body: "forbidden" });
    }
    try {
      const data = await readFile(filePath);
      return route.fulfill({ body: data, contentType: MIME[path.extname(filePath)] });
    } catch {
      return route.fulfill({ status: 404, body: "not found: " + rel });
    }
  });
}

async function main() {
  const args = process.argv.slice(2);
  const sh3dPath = path.resolve(args[0] || "");
  if (!sh3dPath || !existsSync(sh3dPath)) {
    console.error("Usage: node check.mjs <chemin.sh3d> [--screenshot out.png]");
    process.exit(2);
  }
  const shotIdx = args.indexOf("--screenshot");
  const screenshotPath = shotIdx >= 0 ? path.resolve(args[shotIdx + 1]) : null;

  const browser = await chromium.launch();
  let ok = false;
  let chk = null;
  let errors = [];
  try {
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    const pageErrors = [];
    page.on("pageerror", (err) => pageErrors.push(String(err)));

    await installRoutes(page, sh3dPath);
    await page.goto(`${FAKE_ORIGIN}/viewer/index.html?url=${encodeURIComponent("/__target.sh3d")}`);
    await page
      .waitForFunction(() => window.__chk.calledBack || window.__chk.errors.length > 0,
                        null, { timeout: WAIT_MS })
      .catch(() => {}); // laisse passer un vrai timeout comme cas d'echec (chk.calledBack restera false)

    chk = await page.evaluate(() => window.__chk);
    if (screenshotPath) {
      await page.screenshot({ path: screenshotPath });
    }
    errors = [...consoleErrors, ...pageErrors, ...(chk?.errors || []), ...(chk?.pageerrors || [])];
    ok = Boolean(chk?.calledBack) && errors.length === 0;
  } finally {
    await browser.close();
  }

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
