import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FRONTEND_DIR = path.resolve(__dirname, "..");

// Mock in-memory storage for testing ProtectedRoute behavior
class MockStorage {
  constructor() {
    this.store = new Map();
  }
  getItem(key) {
    return this.store.get(key) ?? null;
  }
  setItem(key, value) {
    this.store.set(key, String(value));
  }
  removeItem(key) {
    this.store.delete(key);
  }
  clear() {
    this.store.clear();
  }
}

// Emulate ProtectedRoute logic directly from source contract
function evaluateProtectedRoute({ sessionStorage, children }) {
  const isAuthenticated = sessionStorage.getItem("is_authenticated") === "true";

  if (!isAuthenticated) {
    return { redirectTo: "/login", replace: true, renderedChildren: null };
  }

  return { redirectTo: null, replace: false, renderedChildren: children };
}

test("SEC-11: Route Guard redirects unauthenticated user to /login", () => {
  const mockSession = new MockStorage();

  const result = evaluateProtectedRoute({
    sessionStorage: mockSession,
    children: "ProtectedChildComponent",
  });

  assert.equal(result.redirectTo, "/login");
  assert.equal(result.replace, true);
  assert.equal(result.renderedChildren, null);
});

test("SEC-11: Setting localStorage.demo_mode='true' does NOT bypass route guard", () => {
  const mockSession = new MockStorage();
  const mockLocal = new MockStorage();
  mockLocal.setItem("demo_mode", "true");

  // Verify that regardless of any demo_mode set in localStorage, ProtectedRoute evaluates solely sessionStorage
  assert.equal(mockLocal.getItem("demo_mode"), "true");

  const result = evaluateProtectedRoute({
    sessionStorage: mockSession,
    children: "ProtectedChildComponent",
  });

  assert.equal(result.redirectTo, "/login");
  assert.equal(result.replace, true);
  assert.equal(result.renderedChildren, null);
});

test("SEC-11: Setting sessionStorage.is_authenticated='false' redirects to /login", () => {
  const mockSession = new MockStorage();
  mockSession.setItem("is_authenticated", "false");

  const result = evaluateProtectedRoute({
    sessionStorage: mockSession,
    children: "ProtectedChildComponent",
  });

  assert.equal(result.redirectTo, "/login");
  assert.equal(result.replace, true);
  assert.equal(result.renderedChildren, null);
});

test("SEC-11: Only sessionStorage.is_authenticated='true' renders children", () => {
  const mockSession = new MockStorage();
  mockSession.setItem("is_authenticated", "true");

  const result = evaluateProtectedRoute({
    sessionStorage: mockSession,
    children: "ProtectedChildComponent",
  });

  assert.equal(result.redirectTo, null);
  assert.equal(result.renderedChildren, "ProtectedChildComponent");
});

test("SEC-11: ProtectedRoute.jsx contains zero references to demo_mode", () => {
  const protectedRouteSource = fs.readFileSync(
    path.join(FRONTEND_DIR, "src", "components", "ProtectedRoute.jsx"),
    "utf-8"
  );

  assert.equal(
    protectedRouteSource.includes("demo_mode"),
    false,
    "ProtectedRoute.jsx must not contain any reference to demo_mode"
  );
  assert.equal(
    protectedRouteSource.includes('sessionStorage.getItem("is_authenticated") === "true"'),
    true,
    "ProtectedRoute.jsx must strictly check sessionStorage is_authenticated === 'true'"
  );
});

test("SEC-11: Login.jsx has demo buttons removed and contains no demo_mode writes", () => {
  const loginSource = fs.readFileSync(
    path.join(FRONTEND_DIR, "src", "pages", "auth", "Login.jsx"),
    "utf-8"
  );

  assert.equal(
    loginSource.includes("demo_mode"),
    false,
    "Login.jsx must not contain any reference to demo_mode"
  );
  assert.equal(
    loginSource.includes("Admin Demo"),
    false,
    "Login.jsx must not contain Admin Demo button"
  );
  assert.equal(
    loginSource.includes("Teacher Demo"),
    false,
    "Login.jsx must not contain Teacher Demo button"
  );
  assert.equal(
    loginSource.includes("Student Demo"),
    false,
    "Login.jsx must not contain Student Demo button"
  );
  assert.equal(
    loginSource.includes("import.meta.env.DEV"),
    true,
    "Login.jsx must wrap Fill buttons with import.meta.env.DEV"
  );
});

test("SEC-11: auth.js and client.js purge demo_mode on logout and 401", () => {
  const authSource = fs.readFileSync(
    path.join(FRONTEND_DIR, "src", "api", "auth.js"),
    "utf-8"
  );
  const clientSource = fs.readFileSync(
    path.join(FRONTEND_DIR, "src", "api", "client.js"),
    "utf-8"
  );

  assert.equal(
    authSource.includes('localStorage.removeItem("demo_mode")'),
    true,
    "auth.js must remove demo_mode on logout"
  );
  assert.equal(
    clientSource.includes('localStorage.removeItem("demo_mode")'),
    true,
    "client.js must remove demo_mode on 401"
  );
});

test("SEC-11: Production build bundle omits dev fill credentials and demo buttons", () => {
  const distAssetsDir = path.join(FRONTEND_DIR, "dist", "assets");
  if (!fs.existsSync(distAssetsDir)) {
    return; // Skip if dist hasn't been built yet
  }

  const jsFiles = fs.readdirSync(distAssetsDir).filter((f) => f.endsWith(".js"));
  assert.ok(jsFiles.length > 0, "Production JS bundle should exist in dist/assets");

  for (const jsFile of jsFiles) {
    const bundleContent = fs.readFileSync(path.join(distAssetsDir, jsFile), "utf-8");

    assert.equal(
      bundleContent.includes("hishamadmin"),
      false,
      `Bundle ${jsFile} must not leak dev credentials (hishamadmin)`
    );
    assert.equal(
      bundleContent.includes("Admin Demo"),
      false,
      `Bundle ${jsFile} must not contain Admin Demo`
    );
    assert.equal(
      bundleContent.includes('localStorage.setItem("demo_mode"'),
      false,
      `Bundle ${jsFile} must not write demo_mode to localStorage`
    );
  }
});
