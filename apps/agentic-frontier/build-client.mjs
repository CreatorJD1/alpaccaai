import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const appRoot = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(appRoot, "web", "src");
const outputPath = path.join(appRoot, "web", "index.html");

const result = await build({
  entryPoints: [path.join(sourceRoot, "main.js")],
  bundle: true,
  charset: "utf8",
  define: { "process.env.NODE_ENV": '"production"' },
  format: "iife",
  legalComments: "none",
  minify: true,
  platform: "browser",
  target: ["chrome110", "edge110", "firefox115", "safari16.4"],
  write: false,
});

const [template, css] = await Promise.all([
  readFile(path.join(sourceRoot, "index.template.html"), "utf8"),
  readFile(path.join(sourceRoot, "styles.css"), "utf8"),
]);

const javascript = Buffer.from(result.outputFiles[0].contents)
  .toString("utf8")
  .replaceAll("</script", "<\\/script");
const document = template
  .replace("/* APP_CSS */", css.replaceAll("</style", "<\\/style"))
  .replace("/* APP_JAVASCRIPT */", javascript);

await writeFile(outputPath, document, "utf8");
console.log(`Built ${path.relative(appRoot, outputPath)} (${Buffer.byteLength(document).toLocaleString()} bytes)`);
