const assert = require("node:assert/strict");
const test = require("node:test");
const { errorDiagnostic } = require("../adapters/zsxq_web/diagnostics");

test("exceptions keep actionable code locations without signed URLs or browser call logs", () => {
  const error = new Error("page.goto: Navigation failed https://files.example/doc?token=private123\nCall log:\nAuthorization: Bearer hidden456\nbody: private content");
  error.stack = `${error.message}\n    at topicMetadata (/app/archive.js:25:10)\n    at async runJob (/app/archive.js:80:7)`;
  const diagnostic = errorDiagnostic(error);
  assert.match(diagnostic.message, /Navigation failed/);
  assert.equal(diagnostic.stack.length, 2);
  const serialized = JSON.stringify(diagnostic);
  for (const secret of ["private123", "hidden456", "private content", "files.example"]) assert.equal(serialized.includes(secret), false);
});
