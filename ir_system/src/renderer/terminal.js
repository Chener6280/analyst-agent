(() => {
  let host,active=null,cwd=null,unlisten,observer;
  const sessions=new Map();
  const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const report=e=>{const el=host?.querySelector('.dc-terminal-notice');if(el)el.textContent=String(e.message||e);};
  function renderTabs(){
    if(!host?.isConnected)return;
    host.querySelector('.dc-terminal-sessions').innerHTML=[...sessions.values()].map(s=>`<span class="dc-terminal-tab ${s.id===active?'active':''}"><button data-terminal-select="${s.id}" title="${esc(s.cwd)}">›_ ${esc(s.title)}${s.running?'':' · 已退出'}</button><button data-terminal-rename="${s.id}" aria-label="重命名 ${esc(s.title)}">✎</button><button data-terminal-close="${s.id}" aria-label="关闭 ${esc(s.title)}">×</button></span>`).join('');
    for(const s of sessions.values())s.element.hidden=s.id!==active;
    host.querySelector('.dc-terminal-empty').hidden=sessions.size>0;
    const s=sessions.get(active);if(s){requestAnimationFrame(()=>{s.fit.fit();s.term.focus();});}
  }
  function event(e){const s=sessions.get(e.id);if(!s || e.seq<=s.seq)return;s.seq=e.seq;if(e.type==='data')s.term.write(e.data);else if(e.type==='exit'){s.running=false;s.term.writeln(`\r\n[进程已退出：${e.exitCode}]`);renderTabs();}}
  async function attach(snapshot){
    const s={...snapshot};s.element=document.createElement('div');s.element.className='dc-terminal-view';host.querySelector('.dc-terminal-views').append(s.element);
    s.term=new Terminal({fontSize:12,fontFamily:'Menlo, Consolas, monospace',cursorBlink:true,scrollback:5000,theme:{background:'#080e15',foreground:'#c4d0dd'},allowProposedApi:true});
    s.fit=new FitAddon.FitAddon();s.term.loadAddon(s.fit);s.term.open(s.element);
    // No terminal-controlled clipboard, hyperlink launch or shell integration.
    s.term.parser.registerOscHandler(52,()=>true);
    s.term.onData(data=>window.irSystem.terminalInput(s.id,data).catch(report));
    s.term.onResize(({cols,rows})=>window.irSystem.terminalResize(s.id,cols,rows).catch(report));
    sessions.set(s.id,s);active=s.id;s.term.write(s.buffer||'');
    // Subscribe before snapshot and deduplicate sequence numbers on restoration.
    const current=await window.irSystem.terminalSnapshot(s.id);
    if(current.seq>s.seq){s.term.reset();s.term.write(current.buffer);s.seq=current.seq;s.running=current.running;}
    renderTabs();
  }
  window.mountIRTerminals=async target=>{
    for(const s of sessions.values())s.term.dispose();sessions.clear();unlisten?.();observer?.disconnect();host=target;active=null;
    host.innerHTML=`<div class="dc-terminal-toolbar"><div class="dc-terminal-sessions"></div><button data-terminal-new title="新增终端">＋</button><button data-terminal-directory>工作目录…</button></div><p class="dc-terminal-notice">本地交互式终端。自行输入 pi、kimi 或其他命令；不会自动启动模型。终端命令不受同步预算限制。</p><div class="dc-terminal-views"><div class="dc-terminal-empty">点击 ＋ 新建终端。可同时打开多个标签，分别运行不同 CLI。</div></div>`;
    unlisten=window.irSystem.onTerminalEvent(event);
    for(const s of await window.irSystem.terminalList())await attach(await window.irSystem.terminalSnapshot(s.id));
    observer=new ResizeObserver(()=>{const s=sessions.get(active);if(s&&!host.hidden)s.fit.fit();});observer.observe(host);
  };
  window.fitIRTerminal=()=>{const s=sessions.get(active);if(s)requestAnimationFrame(()=>s.fit.fit());};
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b||!host?.contains(b))return;
    try{
      if(b.hasAttribute('data-terminal-new')){const s=await window.irSystem.terminalCreate(cwd?{cwd}:{});if(!s.cancelled)await attach(s);}
      if(b.hasAttribute('data-terminal-directory')){const next=await window.irSystem.terminalChooseDirectory();if(next){cwd=next;report(`新终端工作目录：${next}。已有会话不变。`);}}
      if(b.hasAttribute('data-terminal-select')){active=b.dataset.terminalSelect;renderTabs();}
      if(b.hasAttribute('data-terminal-close')){const id=b.dataset.terminalClose,r=await window.irSystem.terminalClose(id);if(r.closed){const s=sessions.get(id);s.term.dispose();s.element.remove();sessions.delete(id);active=[...sessions.keys()].at(-1);renderTabs();}}
      if(b.hasAttribute('data-terminal-rename')){
        const s=sessions.get(b.dataset.terminalRename), input=document.createElement('input');input.value=s.title;input.maxLength=80;input.className='dc-terminal-rename';b.parentElement.replaceChildren(input);input.focus();input.select();
        input.addEventListener('keydown',async ev=>{if(ev.key==='Escape')renderTabs();if(ev.key==='Enter'){try{await window.irSystem.terminalRename(s.id,input.value);s.title=input.value.trim();renderTabs();}catch(err){report(err);}}});input.addEventListener('blur',renderTabs,{once:true});
      }
    }catch(err){report(err);}
  });
})();
