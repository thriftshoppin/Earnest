// Local, read-only visualization. Audio capture is isolated from the playback bridge.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const readline = require('readline');
const ROOT = path.resolve(__dirname, '..');
const PACKS = path.join(path.dirname(ROOT), 'lipscan-packs');
const requested = process.argv[2] || 'Speakers (7.1 Surround Sound)';
const port = Number(process.argv[3] || 8774);
let last = null, error = null;
const monitor = spawn(path.join(__dirname,'EarnestMonitor.exe'), [requested], { cwd: __dirname, windowsHide:true });
monitor.on('error', e => error = e.message);
monitor.stderr.on('data', s => { error = String(s).slice(0,1000); });
monitor.on('exit', code => { if (code !== 0 && !error) error = 'Audio monitor exited: ' + code; });
readline.createInterface({input:monitor.stdout}).on('line', line => { try { last={...JSON.parse(line), observed_at:Date.now()}; error=null; } catch {} });
const staticFiles = new Map([
  ['/', ['index.html','text/html; charset=utf-8']],
  ['/app.js',['app.bundle.js','text/javascript; charset=utf-8']],
]);
const server=http.createServer((req,res)=>{
  const host=(req.headers.host||'').toLowerCase();
  if(!['127.0.0.1:'+port,'localhost:'+port].includes(host)){res.writeHead(403);res.end('Forbidden');return;}
  const u=new URL(req.url,'http://127.0.0.1:'+port);
  res.setHeader('X-Content-Type-Options','nosniff');
  if(req.method!=='GET'){res.writeHead(405);res.end();return;}
  if(u.pathname==='/room-studio'){
    const editorPort=Number(process.env.EARNEST_EDITOR_PORT || 8775);
    if(!Number.isInteger(editorPort) || editorPort < 1 || editorPort > 65535){res.writeHead(503);res.end('Room Studio unavailable');return;}
    res.writeHead(302,{Location:'http://127.0.0.1:'+editorPort+'/'});res.end();return;
  }
  if(u.pathname==='/api/state'){
    res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify({endpoint:requested,last,error,connected:!!last && Date.now()-last.observed_at<1500}));return;
  }
  if(u.pathname==='/api/room'){
    res.setHeader('Content-Type','application/json');
    fs.createReadStream(path.join(ROOT,'inbox','rooms','Union-Stairs.room.json')).on('error',()=>res.destroy()).pipe(res);return;
  }
  const m=u.pathname.match(/^\/model\/(v_male|v_female)\/(head|eyes|eyebrows|teeth)\.glb$/);
  if(m){ const bundled=path.join(__dirname,'models',m[1],m[2]+'.glb');const file=fs.existsSync(bundled)?bundled:path.join(PACKS,m[1],m[2]+'.glb');res.setHeader('Content-Type','model/gltf-binary');fs.createReadStream(file).on('error',()=>{if(!res.headersSent)res.writeHead(404);res.end()}).pipe(res);return; }
  let item=staticFiles.get(u.pathname);
  if(!item){res.writeHead(404);res.end('Not found');return;}
  res.setHeader('Content-Type',item[1]);fs.createReadStream(path.join(__dirname,item[0])).on('error',()=>{if(!res.headersSent)res.writeHead(404);res.end()}).pipe(res);
});
server.on('error',e=>{console.error('Viewer server: '+e.message);monitor.kill();process.exitCode=1});
server.listen(port,'127.0.0.1',()=>console.log('EARNEST LIVE VIEW: http://127.0.0.1:'+port+'\nREAD-ONLY LOOPBACK: '+requested+'\nPress Ctrl+C to stop.'));
function stop(){ monitor.kill();server.close(); }
process.on('SIGINT',stop);process.on('SIGTERM',stop);process.on('exit',()=>monitor.kill());
