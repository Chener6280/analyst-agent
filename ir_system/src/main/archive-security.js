const fs = require("node:fs");
const path = require("node:path");

function validatedAssetPath(archiveRoot, candidate) {
  const root = fs.realpathSync(archiveRoot);
  const resolved = fs.realpathSync(candidate);
  const relative = path.relative(root, resolved).split(path.sep).join("/");
  if (!/^(?:(?:zsxq_web|incoming\/v1)\/)?objects\/[0-9a-f]{2}\/[0-9a-f]{64}$/.test(relative) || !fs.statSync(resolved).isFile()) {
    throw new Error("归档原件路径不在允许范围内");
  }
  return resolved;
}

module.exports = { validatedAssetPath };
