import { Type } from "@sinclair/typebox";

// Loaded explicitly with all other extensions, skills and context discovery off.
// Broker credentials remain in this trusted extension, never in model arguments.
export default function (pi: any) {
  const descriptions: Record<string, string> = {
    sync_start: "Start the already user-authorized IR System job. Idempotent. No scope changes.",
    sync_status: "Read this authorized job's redacted progress. Do not poll repeatedly.",
    sync_report: "Read authoritative redacted result counts. Coverage complete is not implied.",
    sync_stop: "Safely stop this job when the user requested it. Never delete data.",
  };
  for (const [name, description] of Object.entries(descriptions)) {
    pi.registerTool({ name, label: name, description, parameters: Type.Object({}, { additionalProperties: false }),
      async execute(_id: string, args: Record<string, unknown>, signal: AbortSignal) {
        if (Object.keys(args).length) throw new Error("invalid_tool_arguments");
        const endpoint = process.env.IR_SYSTEM_SYNC_URL || "";
        if (!/^http:\/\/127\.0\.0\.1:\d+\/tool$/.test(endpoint)) throw new Error("invalid_sync_broker");
        const response = await fetch(endpoint, { method: "POST", redirect: "error", signal,
          headers: { Authorization: `Bearer ${process.env.IR_SYSTEM_SYNC_TOKEN || ""}`, "Content-Type": "application/json" },
          body: JSON.stringify({ tool: name, arguments: {} }) });
        const result = await response.json();
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: {}, isError: !response.ok };
      },
    });
  }
  pi.on("session_start", (_event: any, ctx: any) => {
    pi.setActiveTools(Object.keys(descriptions));
    if (process.env.IR_SYSTEM_SYNC_SELFTEST === "1") ctx.ui.notify(JSON.stringify({ irSyncSelfTest: pi.getActiveTools() }), "info");
  });
  let turns = 0;
  pi.on("turn_end", (_event: any, ctx: any) => { if (++turns >= 4) ctx.abort(); });
}
