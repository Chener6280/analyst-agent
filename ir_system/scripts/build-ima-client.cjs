// Build the fixed, auditable native helper for the target macOS architecture.
const {execFileSync}=require('node:child_process');
const path=require('node:path');
module.exports=async context=>{
 if(context.electronPlatformName!=='darwin')return;
 const arch={1:'x86_64',3:'arm64'}[context.arch];
 if(!arch)throw new Error('Unsupported IMA accessibility helper architecture');
 const root=context.appDir||path.resolve(__dirname,'..');
 execFileSync('/usr/bin/xcrun',['swiftc',path.join(root,'adapters/ima_client/bridge.swift'),
  '-target',arch+'-apple-macosx12.0','-o',path.join(root,'adapters/ima_client/ima-accessibility'),
  '-framework','Cocoa','-framework','ApplicationServices'],{stdio:'inherit'});
};
