const http = require("node:http");
const { randomBytes, timingSafeEqual } = require("node:crypto");

// Loopback-only, per-invocation capability. It cannot create grants or change settings.
async function createAgentBroker(manager, grantId, { maxCalls = 12, lifetimeMs = 180000 } = {}) {
  const grant = manager.store.state.grants[grantId];
  if (!grant || grant.revoked || grant.expires < Date.now()) throw new Error("invalid_grant");
  const token = randomBytes(32).toString("hex");
  let calls = 0;
  const expires = Date.now() + lifetimeMs;
  const server = http.createServer((req, res) => {
    function send(code, data) { res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(data)); }
    const auth = req.headers.authorization || "";
    const expected = `Bearer ${token}`;
    if (req.headers.origin || req.method !== "POST" || req.url !== "/tool" || Buffer.byteLength(auth) !== Buffer.byteLength(expected) || !timingSafeEqual(Buffer.from(auth), Buffer.from(expected))) return send(403, { error: "forbidden" });
    if (Date.now() > expires || ++calls > maxCalls) return send(429, { error: "agent_budget_exhausted" });
    let body = "";
    req.on("data", chunk => { body += chunk; if (body.length > 2048) req.destroy(); });
    req.on("end", () => {
      try {
        const input = JSON.parse(body);
        if (!input || Object.keys(input).some(k => !["tool", "arguments"].includes(k)) || !input.arguments || typeof input.arguments !== "object" || Array.isArray(input.arguments) || Object.keys(input.arguments).length) throw new Error("invalid_tool_arguments");
        const actions = {
          sync_start: () => manager.start(grantId),
          sync_status: () => manager.report(grant.jobId),
          sync_report: () => manager.report(grant.jobId),
          sync_stop: () => manager.stop(grant.jobId),
        };
        if (!Object.hasOwn(actions, input.tool)) throw new Error("tool_not_allowed");
        if (grant.readOnly && !["sync_status", "sync_report"].includes(input.tool)) throw new Error("read_only_grant");
        send(200, actions[input.tool]());
      } catch (e) { send(400, { error: /^[a-z_]{1,80}$/.test(e.message) ? e.message : "tool_rejected" }); }
    });
  });
  server.requestTimeout = 5000;
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const timer = setTimeout(() => server.close(), lifetimeMs); timer.unref?.();
  return { url: `http://127.0.0.1:${server.address().port}/tool`, token,
    close() { clearTimeout(timer); server.closeAllConnections?.(); server.close(); } };
}
module.exports = { createAgentBroker };
