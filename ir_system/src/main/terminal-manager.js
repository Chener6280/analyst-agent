const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {randomUUID}=require('node:crypto');

class TerminalManager {
  constructor(send,pty=null) {this.send=send;this.pty=pty;this.sessions=new Map();}
  list(){return [...this.sessions.values()].map(s=>({id:s.id,title:s.title,cwd:s.cwd,running:s.running}));}
  create({cwd=os.homedir(),cols=100,rows=24}={}) {
    if(this.sessions.size>=8)throw new Error('terminal_limit');
    if(typeof cwd!=='string'||!path.isAbsolute(cwd)||!fs.statSync(cwd).isDirectory())throw new Error('invalid_terminal_directory');
    this.size(cols,rows);
    const pty=this.pty||require('node-pty');
    const shell=process.platform==='win32'?'powershell.exe':process.env.SHELL || '/bin/zsh';
    const args=process.platform==='win32'?['-NoLogo']:['-l'];
    const env={...process.env,TERM:'xterm-256color',COLORTERM:'truecolor'};
    // Shells launched by Electron must not inherit Electron's Node override.
    delete env.ELECTRON_RUN_AS_NODE;
    const processPty=pty.spawn(shell,args,{name:'xterm-256color',cwd,cols,rows,env});
    const s={id:randomUUID(),title:`${path.basename(shell)} ${this.sessions.size+1}`,cwd,running:true,buffer:'',seq:0,process:processPty};
    this.sessions.set(s.id,s);
    processPty.onData(data=>{s.buffer=(s.buffer+data).slice(-1024*1024);this.send({type:'data',id:s.id,seq:++s.seq,data});});
    processPty.onExit(({exitCode})=>{s.running=false;this.send({type:'exit',id:s.id,seq:++s.seq,exitCode});});
    return this.snapshot(s.id);
  }
  get(id){const s=this.sessions.get(id);if(!s)throw new Error('unknown_terminal');return s;}
  snapshot(id){const s=this.get(id);return {id:s.id,title:s.title,cwd:s.cwd,running:s.running,buffer:s.buffer,seq:s.seq};}
  size(cols,rows){if(!Number.isInteger(cols)||!Number.isInteger(rows)||cols<2||cols>500||rows<1||rows>300)throw new Error('invalid_terminal_size');}
  input(id,data){const s=this.get(id);if(typeof data!=='string'||data.length>65536)throw new Error('invalid_terminal_input');if(!s.running)throw new Error('terminal_exited');s.process.write(data);}
  resize(id,cols,rows){this.size(cols,rows);const s=this.get(id);if(s.running)s.process.resize(cols,rows);}
  rename(id,title){if(typeof title!=='string'||!title.trim()||title.length>80||/[\x00-\x1f]/.test(title))throw new Error('invalid_terminal_title');this.get(id).title=title.trim();return this.list();}
  close(id){const s=this.get(id);if(s.running){if(process.platform!=='win32'){try{process.kill(-s.process.pid,'SIGHUP');}catch{}}try{s.process.kill();}catch{}}this.sessions.delete(id);}
  closeAll(){for(const id of [...this.sessions.keys()])this.close(id);}
}
module.exports={TerminalManager};
