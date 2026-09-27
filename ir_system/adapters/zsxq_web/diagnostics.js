"use strict";

// Keep the exception's first line and code locations, never browser call logs,
// headers, response bodies, cookies or signed download URLs.
function sanitizeDiagnostic(value) {
  return String(value || "")
    .replace(/https?:\/\/[^\s"'<>]+/gi, "[url]")
    .replace(/\b(?:cookie|authorization|set-cookie)\s*[:=].*/gi, "[credentials redacted]")
    .replace(/\b(?:token|access_token|password|secret|signature)\s*[=:]\s*[^\s,;}]+/gi, "[secret redacted]")
    .replace(/\bBearer\s+[^\s]+/gi, "Bearer [redacted]");
}

function errorDiagnostic(error) {
  return {
    name: /^[A-Za-z0-9_]+$/.test(error?.name || "") ? error.name : "Error",
    message: sanitizeDiagnostic(String(error?.message || error).split(/\r?\n/)[0]).slice(0, 500),
    stack: String(error?.stack || "").split(/\r?\n/)
      .filter((line) => /^\s+at /.test(line)).slice(0, 8).map(sanitizeDiagnostic),
  };
}

module.exports = { errorDiagnostic };
