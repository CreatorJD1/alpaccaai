// We test ONLY the pure logic in lib/ with ts-jest (node env) — no React Native
// runtime needed, so the math suite runs fast and clean in CI or on a laptop.
// (Component/screen testing, if added later, would use jest-expo's preset.)
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/__tests__/**/*.test.ts"],
};
