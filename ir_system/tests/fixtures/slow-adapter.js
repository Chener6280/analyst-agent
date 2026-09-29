// 测试桩：扮演 provider 适配器，延迟 1.5s 后返回合法协议响应。
let buffer = "";
process.stdin.on("data", chunk => { buffer += chunk; });
process.stdin.on("end", () => {
  setTimeout(() => {
    process.stdout.write(JSON.stringify({ protocol: "ir-system-provider/v1", ok: true, result: { slow: true } }));
  }, 1500);
});
