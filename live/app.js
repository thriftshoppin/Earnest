import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const $=id=>document.getElementById(id),view=$('view');
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x0d191d);view.prepend(renderer.domElement);
const scene=new THREE.Scene();const camera=new THREE.PerspectiveCamera(35,1,.01,100);camera.position.set(3.9,3.0,5.8);
const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,.75,0);controls.enableDamping=true;controls.minDistance=2;controls.maxDistance=16;
scene.add(new THREE.HemisphereLight(0xd5f7ee,0x152729,2.2));
const light=new THREE.DirectionalLight(0xffffff,2.1);light.position.set(2,5,4);scene.add(light);
const rim=new THREE.DirectionalLight(0x79d0b4,1.4);rim.position.set(-3,2,-4);scene.add(rim);
const grid=new THREE.GridHelper(10,20,0x35534c,0x263b39);grid.position.y=-.36;scene.add(grid);
const ring=new THREE.Mesh(new THREE.RingGeometry(.85,.86,96),new THREE.MeshBasicMaterial({color:0x7dd8ac,transparent:true,opacity:.65,side:THREE.DoubleSide}));ring.rotation.x=-Math.PI/2;ring.position.y=-.34;scene.add(ring);
// Concentric rings encode octave-band energy as color and brightness. Their
// positions are decorative, not measurements of incoming sound direction.
const energyRings=[],palette=[0x718cf0,0x6bb4e6,0x68d3cd,0x9be4af,0xd8d785,0xe9af76,0xe98385];
for(let i=0;i<7;i++){
  const radius=1.02+i*.19,points=[];
  for(let k=0;k<=160;k++){const a=k*Math.PI*2/160;points.push(new THREE.Vector3(Math.cos(a)*radius,0,Math.sin(a)*radius));}
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:palette[i],transparent:true,opacity:.12}));
  line.position.y=-.30+i*.015;scene.add(line);energyRings.push(line);
}
const earGlows=[];
for(const side of [-1,1]){const glow=new THREE.Mesh(new THREE.SphereGeometry(.42,24,18),new THREE.MeshBasicMaterial({color:side<0?0x6abbe3:0xebb77a,transparent:true,opacity:.07,depthWrite:false}));glow.position.set(side*.8,.8,0);scene.add(glow);earGlows.push(glow)}
const loader=new GLTFLoader();let head=null,loadSerial=0,room=null,live=null;const nodes=[];
async function loadModel(which){
  const id=++loadSerial;$('modelStatus').textContent='Loading local LipScan head…';
  try{
    const gltf=await loader.loadAsync('/model/'+which+'/head.glb');if(id!==loadSerial)return;
    const model=gltf.scene;model.updateMatrixWorld(true);
    model.traverse(o=>{if(o.isMesh){o.frustumCulled=false;o.material=new THREE.MeshStandardMaterial({color:0xc4c6bb,roughness:.72,metalness:.03,side:THREE.DoubleSide});}});
    const box=new THREE.Box3().setFromObject(model),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
    let scale=1.65/Math.max(size.x,size.y,size.z);const group=new THREE.Group();model.position.sub(center);model.scale.setScalar(scale);model.position.multiplyScalar(scale);group.add(model);group.position.y=.67;
    if(head)scene.remove(head);head=group;scene.add(head);$('modelStatus').textContent='LipScan base head loaded locally';
  }catch(e){if(id===loadSerial)$('modelStatus').textContent='Unable to load head: '+e.message;}
}
$('model').addEventListener('change',()=>loadModel($('model').value));loadModel('v_male');
function setRoom(r){
  room=r;for(const n of nodes){scene.remove(n.group)}nodes.length=0;
  const listener=r.receivers[0];if(!listener)return;
  for(const s of r.sources){const group=new THREE.Group();let dx=s.position[0]-listener.position[0],dy=s.position[1]-listener.position[1],dz=s.position[2]-listener.position[2];group.position.set(-dy,Math.max(.05,.67+dz),-dx);
    const sphere=new THREE.Mesh(new THREE.SphereGeometry(.105,18,12),new THREE.MeshBasicMaterial({color:0xabe8c5}));group.add(sphere);
    const halo=new THREE.Mesh(new THREE.SphereGeometry(.18,18,12),new THREE.MeshBasicMaterial({color:0x86dfad,transparent:true,opacity:.12,depthWrite:false}));group.add(halo);
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(),new THREE.Vector3(-group.position.x,.67-group.position.y,-group.position.z)]),new THREE.LineBasicMaterial({color:0x4c7465,transparent:true,opacity:.36}));group.add(line);
    const c=document.createElement('canvas');c.width=128;c.height=48;const ctx=c.getContext('2d');ctx.font='bold 26px Segoe UI';ctx.fillStyle='#cceade';ctx.textAlign='center';ctx.fillText(s.id,64,32);
    const label=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthWrite:false}));label.position.y=.32;label.scale.set(.6,.23,1);group.add(label);scene.add(group);nodes.push({id:s.id,group,halo});
  }
}
fetch('/api/room').then(r=>{if(!r.ok)throw Error('Room is unavailable');return r.json()}).then(setRoom).catch(e=>$('error').textContent=e.message);
const bars=$('bars');for(let i=0;i<7;i++)bars.appendChild(document.createElement('i'));
const db=v=>v>1e-8?Math.max(-80,20*Math.log10(v)):-80;const text=v=>v<=-79.9?'−∞':v.toFixed(1)+' dBFS';
async function update(){try{const d=await fetch('/api/state',{cache:'no-store'}).then(r=>r.json());$('endpoint').textContent=d.endpoint;$('error').textContent=d.error||'';
  $('status').textContent=d.connected?'●  LIVE / READ-ONLY':'○  NO AUDIO DATA';$('status').style.color=d.connected?'#9ee0b7':'#ebc584';live=d.connected?d.last:null;
  const rms=live?.rms||[0,0];for(let i=0;i<2;i++){let key=i?'right':'left',v=db(rms[i]);$(key).textContent=live?text(v):'—';$(key+'Bar').style.width=(live?Math.max(0,(v+60)/60)*100:0)+'%'}
  $('correlation').textContent=live?live.correlation.toFixed(2):'—';$('width').textContent=live&&live.mid>1e-7?(live.side/live.mid).toFixed(2):'—';
  [...bars.children].forEach((b,i)=>b.style.height=(live?Math.max(2,Math.min(100,(db(live.bands[i])+80)/80*100)):2)+'%');
 }catch(e){live=null;$('status').textContent='○  VIEWER DISCONNECTED';$('error').textContent=e.message}setTimeout(update,125)}update();
new ResizeObserver(()=>{let r=view.getBoundingClientRect();renderer.setSize(r.width,r.height,false);camera.aspect=r.width/Math.max(1,r.height);camera.updateProjectionMatrix()}).observe(view);
function frame(){requestAnimationFrame(frame);controls.update();for(const n of nodes){let i=n.id==='FL'?0:n.id==='FR'?1:-1;let v=i>=0&&live?Math.min(1,live.rms[i]*5):0;n.halo.scale.setScalar(1+v);n.halo.material.opacity=i>=0?.1+v*.4:.08}energyRings.forEach((line,i)=>{let v=live?Math.max(0,Math.min(1,(db(live.bands[i])+72)/72)):0;line.material.opacity=.12+.83*v;line.scale.setScalar(1+v*.07)});earGlows.forEach((glow,i)=>{let v=live?Math.min(1,live.rms[i]*4):0;glow.scale.setScalar(1+v*.7);glow.material.opacity=.04+v*.25});renderer.render(scene,camera)}frame();
