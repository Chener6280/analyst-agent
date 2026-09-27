const fs=require('node:fs');
const path=require('node:path');
if(process.platform!=='win32'){
  const root=path.dirname(require.resolve('node-pty/package.json'));
  for(const relative of [`prebuilds/${process.platform}-${process.arch}/spawn-helper`,'build/Release/spawn-helper']){
    const file=path.join(root,relative);if(fs.existsSync(file))fs.chmodSync(file,0o755);
  }
}
