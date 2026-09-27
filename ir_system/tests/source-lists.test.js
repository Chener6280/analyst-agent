const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {SourceLists}=require('../adapters/source_lists/store');
const {main}=require('../adapters/source_lists/cli');
const fixture=()=>fs.mkdtempSync(path.join(os.tmpdir(),'ir-lists-'));
test('older six-source lists gain an empty Xiaoe list without changing existing files',()=>{
 const dir=fixture(),s=new SourceLists(dir),legacy=s.read();
 delete legacy.sources.xiaoe;legacy.sources.wechat=[{name:'既有公众号'}];legacy.revision=4;
 const original=JSON.stringify(legacy);fs.writeFileSync(s.file,original);
 assert.deepEqual(s.read().sources.xiaoe,[]);assert.equal(fs.readFileSync(s.file,'utf8'),original);
 assert.equal(s.read().revision,4);
 main(['add','--data-dir',dir,'--source','xiaoe','--name','示例店铺','--revision','4']);
 assert.deepEqual(s.read().sources.wechat,legacy.sources.wechat);assert.equal(s.read().sources.xiaoe.length,1);
 const invalid=s.read();invalid.sources.xiaoe=null;fs.writeFileSync(s.file,JSON.stringify(invalid));
 assert.equal(s.view().status,'error');
});
test('local lists are independent, versioned, backed up and preserve unrelated sources',()=>{
 const dir=fixture(),s=new SourceLists(dir),args=['--data-dir',dir,'--source','wechat'];
 assert.equal(fs.existsSync(s.file),false);assert.equal(main(['list',...args]).entries.length,0);
 main(['add',...args,'--name','示例 & <公众号>','--revision','0','--ghid','gh_example']);
 assert.throws(()=>main(['add',...args,'--name','第二个','--revision','0']),/changed/);
 assert.throws(()=>main(['add',...args,'--name','示例 & <公众号>','--revision','1']),/exists/);
 main(['add','--data-dir',dir,'--source','web','--name','网站示例','--revision','1']);
 main(['remove',...args,'--name','示例 & <公众号>','--revision','2']);
 assert.deepEqual(s.read().sources.wechat,[]);assert.equal(s.read().sources.web.length,1);
 assert.equal(fs.readdirSync(path.join(dir,'source-list-backups')).length,2);
 assert.equal(fs.existsSync(s.file+'.lock'),false);
});
test('import merges without overwriting identifiers, source is unchanged, duplicate identifiers rejected',()=>{
 const dir=fixture(),file=path.join(dir,'input.json'),s=new SourceLists(dir);
 const input=JSON.stringify([{name:'甲',ghid:'gh_a'},{name:'乙'}]);fs.writeFileSync(file,input);
 const args=['import-wechat','--data-dir',dir,'--source','wechat','--file',file];
 assert.equal(main([...args,'--revision','0']).count,2);
 assert.equal(main([...args,'--revision','1']).count,2);assert.equal(fs.readFileSync(file,'utf8'),input);
 assert.throws(()=>s.change('wechat',2,r=>[...r,{name:'丙',ghid:'gh_a'}]),/duplicate/);
 fs.writeFileSync(file,JSON.stringify([{name:'甲',ghid:'gh_b'}]));
 assert.throws(()=>main([...args,'--revision','2']),/conflicting/);assert.equal(s.read().revision,2);
});
test('corruption, existing locks, unknown sources and invalid revisions fail closed',()=>{
 const dir=fixture(),s=new SourceLists(dir);
 assert.throws(()=>s.change('ima',0,()=>[]),/unsupported/);
 assert.throws(()=>main(['add','--data-dir',dir,'--source','wechat','--name','甲']),/revision/);
 fs.writeFileSync(s.file,'corrupt');assert.equal(s.view().status,'error');
 assert.throws(()=>s.change('wechat',0,()=>[]));assert.equal(fs.readFileSync(s.file,'utf8'),'corrupt');
 fs.writeFileSync(s.file+'.lock','other owner');assert.throws(()=>s.change('wechat',0,()=>[]),/busy/);
 assert.equal(fs.readFileSync(s.file+'.lock','utf8'),'other owner');
});
