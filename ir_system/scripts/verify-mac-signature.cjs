// Fail closed on a malformed local build; this does not grant OS permissions.
const {execFileSync,spawnSync}=require('node:child_process');
const path=require('node:path');
module.exports=async context=>{
 if(context.electronPlatformName!=='darwin')return;
 const app=path.join(context.appOutDir,context.packager.appInfo.productFilename+'.app');
 execFileSync('/usr/bin/codesign',['--verify','--deep','--strict',app],{stdio:'pipe'});
 const id=execFileSync('/usr/libexec/PlistBuddy',['-c','Print :CFBundleIdentifier',path.join(app,'Contents/Info.plist')],{encoding:'utf8'}).trim();
 if(id!=='com.irsystem.desktop')throw new Error('Unexpected macOS application identity');
 const signed=spawnSync('/usr/bin/codesign',['-dv','--verbose=2',app],{encoding:'utf8'});
 if(signed.status!==0||!/^Identifier=com\.irsystem\.desktop$/m.test(signed.stderr)||/Info\.plist=not bound/.test(signed.stderr))throw new Error('macOS code identity is not bound to IR System');
};
