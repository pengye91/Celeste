/**
 * Tests for package.json scripts.
 *
 * Regression: `next build` ran React in whatever NODE_ENV the caller's
 * shell exported. A polluted shell (e.g. an agent/dev tool that exports
 * NODE_ENV=development globally) made `next build` run React in dev mode
 * during static prerendering, which crashed on the generated
 * `/_global-error` route with "Cannot read properties of null
 * (reading 'useContext')". The production Dockerfile already set
 * NODE_ENV=production, but a bare `npm run build` outside Docker was not
 * robust. The build script now forces NODE_ENV=production inline so the
 * caller's environment cannot break a production build.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

interface PackageJson {
  scripts: Record<string, string>;
}

function readPackage(): PackageJson {
  return JSON.parse(
    readFileSync(resolve(__dirname, "package.json"), "utf8"),
  ) as PackageJson;
}

describe("package.json scripts", () => {
  it("the build script forces NODE_ENV=production", () => {
    const pkg = readPackage();
    const build = pkg.scripts.build;
    expect(build, "package.json must define a build script").toBeDefined();
    // The inline assignment overrides any NODE_ENV exported in the caller's
    // shell, so a polluted environment can't break a production build.
    expect(
      build,
      "build script must start with `NODE_ENV=production` so it is robust " +
        "to a polluted caller environment",
    ).toMatch(/^NODE_ENV=production\s+next build\b/);
  });

  it("the build script still runs next build", () => {
    const pkg = readPackage();
    expect(pkg.scripts.build).toContain("next build");
  });
});
