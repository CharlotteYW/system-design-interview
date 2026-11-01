const $ = id => document.getElementById(id);
const enc = new TextEncoder();
const dec = new TextDecoder();
const tokens = {};
let who = localStorage.getItem("drive-demo-user") || "lee";
let sse, online = true, busyPull = false, paused = false, lastUpload, lastDownload;
const storeHashes = new Map();
const faultNames = {db_down:"Metadata unavailable", capacity_exhausted:"Reject new work", worker_paused:"Pause outbox worker", drop_completion_reply:"Lose next completion reply", drop_hints:"Drop live hints", crash_after_job_claim:"Crash after next job claim"};
const database = new Promise((resolve,reject) => {
  const req = indexedDB.open("drive-study-v1",1);
  req.onupgradeneeded = () => ["jobs","settings","files","pending"].forEach(s => req.result.createObjectStore(s,{keyPath:"id"}));
  req.onsuccess = () => resolve(req.result); req.onerror=()=>reject(req.error);
});
async function read(store,id){const db=await database;return new Promise((resolve,reject)=>{const q=db.transaction(store).objectStore(store).get(id);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});}
async function write(store,value){const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction(store,"readwrite");tx.objectStore(store).put(value);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function all(store){const db=await database;return new Promise((resolve,reject)=>{const q=db.transaction(store).objectStore(store).getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});}
async function clearLocal(){const db=await database;await Promise.all(["jobs","settings","files","pending"].map(s=>new Promise((resolve,reject)=>{const tx=db.transaction(s,"readwrite");tx.objectStore(s).clear();tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);})));lastUpload=lastDownload=null;}
function escape(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function toast(s,error=false){$("toast").textContent=s;$("toast").className=error?"error":"";$("toast").style.display="block";clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$("toast").style.display="none",6500);}
function visible(value){return JSON.parse(JSON.stringify(value,(k,v)=>{if(k==="accessToken")return "[mock session redacted]";if(typeof v==="string"&&v.includes("?ticket="))return v.split("?ticket=")[0]+"?ticket=[scoped credential]";return v;}));}
function trace(method,path,body,status,result){const el=document.createElement("details");el.className="trace-item";el.innerHTML='<summary class="trace-head"><span class="method">'+escape(method)+'</span><span>'+escape(path.replace(/ticket=[^&]+/,"ticket=[scoped credential]"))+'</span><span class="status">'+status+'</span></summary><pre>'+escape(JSON.stringify({request:body===undefined?"none":visible(body),response:visible(result)},null,2))+'</pre>';$("trace").prepend(el);while($("trace").children.length>50)$("trace").lastChild.remove();}
async function api(method,path,body,headers={},account=who){const h={...headers};if(tokens[account])h.Authorization="Bearer "+tokens[account];if(body!==undefined)h["Content-Type"]="application/json";const res=await fetch(path,{method,headers:h,body:body===undefined?undefined:JSON.stringify(body)});let data;try{data=res.status===204?{}:await res.json();}catch{data={code:"unexpected_response"};}if(!path.startsWith("/v1/lab/state"))trace(method,path,body,res.status,data);if(!res.ok){const err=new Error(data.code||data.detail?.code||("HTTP "+res.status));err.status=res.status;err.body=data;throw err;}return data;}
async function login(account){const out=await api("POST","/v1/lab/login",{user:account},{},account);tokens[account]=out.accessToken;return out;}
function updateStoreCard(key, title, payload, count = null, changed = false) {
  const stores = $("stores");
  let card = Array.from(stores.children).find(el => el.dataset.store === key);
  if (!card) {
    card = document.createElement("article");
    card.className = "store";
    card.dataset.store = key;
    const heading = document.createElement("h3");
    heading.textContent = title;
    card.append(heading);
    if (count !== null) {
      const counter = document.createElement("div");
      counter.className = "count";
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Inspect rows";
      details.append(summary, document.createElement("pre"));
      card.append(counter, details);
    } else {
      card.append(document.createElement("pre"));
    }
    stores.append(card);
  }
  card.classList.toggle("changed", changed);
  const counter = card.querySelector(".count");
  if (counter && counter.textContent !== String(count)) counter.textContent = count;
  const pre = card.querySelector("pre");
  const text = JSON.stringify(payload, null, 2);
  if (pre.textContent !== text) {
    const top = pre.scrollTop, left = pre.scrollLeft;
    pre.textContent = text;
    pre.scrollTop = top;
    pre.scrollLeft = left;
  }
  // Keep the same details element: its open state, focus, and scroll survive refresh.
}

async function refreshState() {
  if (!tokens.lee) return;
  const state = await api("GET", "/v1/lab/state", undefined, {}, "lee");
  const [localFiles, pending, jobs] = await Promise.all([all("files"), all("pending"), all("jobs")]);
  updateStoreCard("browser", "Browser / IndexedDB", {
    account: who,
    applied: localFiles.filter(x => x.owner === who).map(({fileId, revision, removed}) => ({fileId, revision, removed})),
    pending: pending.filter(x => x.owner === who && x.state === "pending"),
    savedJobs: jobs.filter(x => x.owner === who).length
  });
  for (const [table, rows] of Object.entries(state.postgres)) {
    const serialized = JSON.stringify(rows);
    const changed = storeHashes.has(table) && storeHashes.get(table) !== serialized;
    storeHashes.set(table, serialized);
    updateStoreCard("postgres:" + table, "PostgreSQL / " + table, rows.slice(0, 12), state.counts[table], changed);
  }
  updateStoreCard("redis", "Redis / cache and counters", state.redis);
  updateStoreCard("evidence", "Storage / local evidence", state.evidence);
  updateStoreCard("limits", "Limits / accelerated clocks", {
    limits: state.limits, region: state.regionModel, clock: state.clock
  });
  for (const key of Object.keys(faultNames)) {
    const box = $("fault-" + key);
    if (box) box.checked = state.faults[key] === "1";
  }
  return state;
}
function showJob(job){$("job-title").textContent=(job.kind==="upload"?"Upload · ":"Download · ")+job.name;$("job-status").textContent=job.state;const done=job.chunks.filter(c=>c.verified).length;$("progress").value=job.chunks.length?100*done/job.chunks.length:100;$("chunks").innerHTML=job.chunks.map(c=>'<span class="chunk '+(c.verified?"verified":c.state==="error"?"error":"pending")+'" title="'+escape((c.chunkId||"")+" · "+(c.stored?.byteLength||c.storedSizeBytes||0)+" stored bytes")+'">'+c.ordinal+' '+(c.verified?"✓":"·")+'</span>').join("");$("job-detail").textContent=JSON.stringify({jobId:job.id,owner:job.owner,uploadId:job.uploadId,downloadId:job.downloadId,revision:job.revision,manifestId:job.manifestId,verifiedChunks:done,totalChunks:job.chunks.length,state:job.state,result:job.result||null,scheduler:job.scheduler||null},null,2);}
async function saveJob(job){await write("jobs",job);showJob(job);}
const crcTable=Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=(n&1)?(n>>>1)^0x82f63b78:n>>>1;return n>>>0;});
function crc(bytes){let n=0xffffffff;for(const b of bytes)n=crcTable[(n^b)&255]^(n>>>8);n=(n^0xffffffff)>>>0;return btoa(String.fromCharCode(n>>>24,(n>>>16)&255,(n>>>8)&255,n&255));}
async function sha(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),x=>x.toString(16).padStart(2,"0")).join("");}
function split(bytes,mode,size){if(!bytes.length)return[];if(mode==="whole")return[bytes];if(mode==="fixed"){const out=[];for(let i=0;i<bytes.length;i+=size)out.push(bytes.slice(i,i+size));return out;}const out=[],min=16384,max=131072,mask=65535n,ring=new Uint8Array(64),mod=(1n<<64n)-1n;let power=1n;for(let i=0;i<63;i++)power=(power*257n)&mod;let h=0n,start=0,used=0,head=0;for(let i=0;i<bytes.length;i++){const b=bytes[i];if(used<64){h=(h*257n+BigInt(b))&mod;ring[used++]=b;}else{h=(((h-BigInt(ring[head])*power)&mod)*257n+BigInt(b))&mod;ring[head]=b;head=(head+1)%64;}const count=i-start+1;if(count>=max||(count>=min&&(h&mask)===0n)){out.push(bytes.slice(start,i+1));start=i+1;h=0n;used=0;head=0;}}if(start<bytes.length)out.push(bytes.slice(start));return out;}
async function gzip(bytes){return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new CompressionStream("gzip"))).arrayBuffer());}
async function decodeChunk(bytes,entry){if(entry.encoding==="identity"){if(bytes.length!==entry.logicalSizeBytes)throw new Error("logical_size_mismatch");return bytes;}const reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();let n=0;const parts=[];while(true){const item=await reader.read();if(item.done)break;n+=item.value.length;if(n>entry.logicalSizeBytes||n>16*1024*1024){await reader.cancel();throw new Error("decoded_output_limit");}parts.push(item.value);}if(n!==entry.logicalSizeBytes)throw new Error("logical_size_mismatch");const out=new Uint8Array(n);let at=0;for(const p of parts){out.set(p,at);at+=p.length;}return out;}
async function prepare(bytes){const mode=$("chunking").value,size=Number($("chunk-size").value),compression=mode==="whole"?"identity":$("compression").value;if(mode==="whole"&&bytes.length>16*1024*1024)throw new Error("Whole-object lab limit: 16 MiB");const raw=split(bytes,mode,size),chunks=[];for(let i=0;i<raw.length;i++){const part=raw[i];let stored=part,encoding="identity";if(compression!=="identity"&&typeof CompressionStream!=="undefined"){const started=performance.now();const candidate=await gzip(part);const encodeMs=performance.now()-started;const decodeStart=performance.now();await decodeChunk(candidate,{encoding:"gzip",logicalSizeBytes:part.length});const compressedMs=encodeMs+performance.now()-decodeStart;const expectedSavingMs=(part.length-candidate.length)*8/10000;if(compression==="gzip"||(candidate.length<=part.length*.9&&expectedSavingMs>compressedMs*1.2)){stored=candidate;encoding="gzip";}}chunks.push({ordinal:i,logicalSizeBytes:part.length,storedSizeBytes:stored.length,encoding,storedCrc32c:crc(stored),declaredStoredSha256:await sha(stored),stored:stored,verified:false});}return{chunks,policy:{algorithm:mode,version:"lab-1",parameters:mode==="cdc"?{window:64,min:16384,target:65536,max:131072}:{size}}};}
async function workPool(job,tasks,action){delete job.transferLimit;let limit=$("parallel").value==="adaptive"?2:Number($("parallel").value),active=new Set(),index=0,error=null;const adaptive=$("parallel").value==="adaptive";let began=performance.now(),bytes=0,baseline=null,probe=false,completed=0,totalDuration=0;while((index<tasks.length&&!paused&&!error)||active.size){while(!paused&&!error&&index<tasks.length&&active.size<Math.min(limit,job.transferLimit||8)){const task=tasks[index++];let p;const started=performance.now();p=(async()=>{try{await action(task);bytes+=task.storedSizeBytes||task.stored?.length||0;completed++;totalDuration+=performance.now()-started;}catch(e){error=e;}finally{active.delete(p);}})();active.add(p);}if(active.size)await Promise.race(active);const elapsed=performance.now()-began;if(adaptive&&elapsed>=10000&&completed>=2&&elapsed>=2*totalDuration/completed){const rate=bytes/elapsed;if(probe&&rate<baseline*1.1){limit=Math.max(1,limit-1);probe=false;}else if(limit<8){baseline=rate;limit++;probe=true;}job.scheduler={limit,mode:"adaptive",usefulBytesPerSecond:Math.round(rate*1000)};began=performance.now();bytes=0;completed=0;totalDuration=0;} }if(error)throw error;}
async function sendChunk(job,chunk){for(let attempt=0;attempt<3;attempt++){try{const permissions=await api("POST","/v1/uploads/"+job.uploadId+"/chunk-upload-urls",{ordinals:[chunk.ordinal]});const permission=permissions.chunks[0];const res=await fetch(permission.url,{method:"PUT",headers:permission.headers,body:chunk.stored});trace("PUT",permission.url,{bytes:chunk.stored.length,crc32c:chunk.storedCrc32c},res.status,{receipt:res.headers.get("X-Object-Version")});if(!res.ok&&res.status!==412)throw new Error("storage_"+res.status);await api("POST","/v1/uploads/"+job.uploadId+"/chunks/"+chunk.ordinal+"/complete",{});chunk.verified=true;chunk.state="verified";await saveJob(job);return;}catch(e){if(e.status===409||e.status===410||attempt===2)throw e;job.transferLimit=1;job.scheduler={limit:1,backoffAttempt:attempt+1};await new Promise(r=>setTimeout(r,250*2**attempt+Math.random()*100));}}}
async function finishUpload(job,result){job.state="completed";job.result=result;job.revision=result.revision;job.manifestId=result.manifestId;await saveJob(job);selectFile(result.fileId);await write("files",{id:who+":"+result.fileId,owner:who,fileId:result.fileId,revision:result.revision,name:job.name,dirty:false});await listFiles();toast("Published revision "+result.revision+" · one saved result");}
async function runUpload(job){lastUpload=job;paused=false;try{if(job.uploadId){const status=await api("GET","/v1/uploads/"+job.uploadId);if(status.result)return await finishUpload(job,status.result);for(const c of job.chunks)if(!status.missingOrdinals.includes(c.ordinal))c.verified=true;}else{const created=await api("POST","/v1/uploads",job.request,{"Idempotency-Key":job.key});job.uploadId=created.uploadId;job.fileId=created.fileId;await saveJob(job);}const plan=await api("PUT","/v1/uploads/"+job.uploadId+"/manifest",{chunking:job.policy,chunks:job.chunks.map(({ordinal,logicalSizeBytes,storedSizeBytes,encoding,storedCrc32c,declaredStoredSha256,reuseFrom})=>reuseFrom?{ordinal,reuseFrom}:({ordinal,logicalSizeBytes,storedSizeBytes,encoding,storedCrc32c,declaredStoredSha256}))});for(const row of plan.chunks){job.chunks[row.ordinal].chunkId=row.chunkId;if(!row.uploadRequired)job.chunks[row.ordinal].verified=true;}job.state="transferring";await saveJob(job);await workPool(job,job.chunks.filter(c=>!c.verified),c=>sendChunk(job,c));if(paused){job.state="paused";await saveJob(job);toast("Progress saved. Resume uses the same upload.");return;}job.state="publishing";await saveJob(job);const result=await api("POST","/v1/uploads/"+job.uploadId+"/complete",{});await finishUpload(job,result);}catch(e){job.state=e.body?.code==="revision_conflict"?"conflicted":"waiting_confirmation";job.error=e.body||e.message;await saveJob(job);throw e;}finally{await refreshState();}}
async function startUpload(){const file=$("source").files[0],bytes=file?new Uint8Array(await file.arrayBuffer()):enc.encode($("sample").value);if(bytes.length>64*1024*1024)throw new Error("Local lab limit: 64 MiB");$("job-title").textContent="Preparing stable chunks…";const prepared=await prepare(bytes);const target=$("target").value.trim();const request={name:$("name").value||file?.name||"plan.txt",sizeBytes:bytes.length,mimeType:file?.type||"text/plain",mode:$("chunking").value==="whole"?"whole":"independent-chunks",verificationMode:$("verification").value,conflictPolicy:$("conflict-policy").value,fanoutMode:$("fanout-mode").value};if(target){request.fileId=target;request.baseRevision=Number($("base-revision").value);}if(target){
  // Reuse only authorized current references whose bytes this device already knows.
  const prior=(await all("jobs")).find(j=>j.owner===who&&j.kind==="upload"&&j.result?.fileId===target&&j.result.revision===request.baseRevision);
  if(prior){const known=new Map(prior.chunks.filter(c=>c.verified).map(c=>[[c.declaredStoredSha256,c.encoding,c.logicalSizeBytes,c.storedSizeBytes].join(":"),c]));for(const c of prepared.chunks){const old=known.get([c.declaredStoredSha256,c.encoding,c.logicalSizeBytes,c.storedSizeBytes].join(":"));if(old)c.reuseFrom={fileId:target,manifestId:prior.result.manifestId,ordinal:old.ordinal};}}
}const job={id:crypto.randomUUID(),kind:"upload",owner:who,name:request.name,key:crypto.randomUUID(),request,...prepared,state:"prepared",createdAt:Date.now()};await saveJob(job);await runUpload(job);}
function selectFile(fid){$("file-id").value=fid;$("share-file").value=fid;}
async function listFiles(){const scope=$("list-scope").value;const result=await api("GET","/v1/files?scope="+scope);$("files").className=result.files.length?"file-list":"file-list empty";$("files").textContent=result.files.length?"":"No files in this list.";for(const f of result.files){const row=document.createElement("div");row.className="file-row";row.innerHTML='<div><strong>'+escape(f.name)+'</strong><small>'+escape(f.fileId)+' · revision '+f.revision+' · '+f.sizeBytes.toLocaleString()+' bytes</small></div><button>Choose</button>';row.querySelector("button").onclick=()=>{selectFile(f.fileId);$("target").value=f.fileId;$("base-revision").value=f.revision;toast("Selected "+f.name);};$("files").append(row);}return result.files;}
async function downloadRun(job,automatic=false){lastDownload=job;job.state="downloading";await saveJob(job);if(!job.chunks.every(c=>c.verified)){const manifest=await api("GET","/v1/downloads/"+job.downloadId+"/manifest?cache="+$("manifest-cache").value);if(manifest.manifestId!==job.manifestId)throw new Error("pinned_manifest_changed");}let newly=0;const stop=automatic?0:Number($("download-stop").value);for(const entry of job.chunks){if(entry.verified)continue;const response=await api("POST","/v1/downloads/"+job.downloadId+"/chunk-download-urls",{chunkIds:[entry.chunkId],delivery:$("delivery").value});const url=response.chunks[0].url;const res=await fetch(url);const data=new Uint8Array(await res.arrayBuffer());trace("GET",url,undefined,res.status,{bytes:data.length,cache:res.headers.get("X-Cache")});if(!res.ok)throw new Error("content_"+res.status);if(data.length!==entry.storedSizeBytes||crc(data)!==entry.storedCrc32c)throw new Error("download_checksum_mismatch");if(entry.storedSha256Verified&&await sha(data)!==entry.storedSha256)throw new Error("download_sha256_mismatch");entry.logical=await decodeChunk(data,entry);entry.verified=true;entry.state="verified";await saveJob(job);newly++;if(stop&&newly>=stop){job.state="paused";await saveJob(job);toast("Download paused; pinned revision and verified bytes saved.");return;}}const blob=new Blob(job.chunks.map(c=>c.logical),{type:"application/octet-stream"});if(blob.size!==job.totalSizeBytes)throw new Error("file_size_mismatch");const existing=await read("files",who+":"+job.fileId);if(existing?.dirty)throw new Error("local_dirty_file_preserved");if(existing&&existing.revision>job.revision){job.state="older_result_not_installed";await saveJob(job);return;}await api("POST","/v1/downloads/"+job.downloadId+"/complete",{});await write("files",{id:who+":"+job.fileId,owner:who,fileId:job.fileId,revision:job.revision,name:job.name,blob,dirty:false});job.state="installed";await saveJob(job);const link=document.createElement("a");link.textContent="Save verified revision "+job.revision;link.href=URL.createObjectURL(blob);link.download=job.name;$("download-result").replaceChildren(link);if(!automatic)toast("Installed one complete revision: "+job.revision);await refreshState();}
async function startDownload(fid=$("file-id").value.trim(),automatic=false){if(!fid)throw new Error("Choose a file first");const ds=await api("POST","/v1/downloads",{fileId:fid});const manifest=await api("GET","/v1/downloads/"+ds.downloadId+"/manifest?cache="+$("manifest-cache").value);const job={id:crypto.randomUUID(),kind:"download",owner:who,name:"download-"+fid+".bin",fileId:fid,downloadId:ds.downloadId,revision:ds.revision,manifestId:ds.manifestId,totalSizeBytes:ds.totalSizeBytes,chunks:manifest.chunks.map(c=>({...c,verified:false})),state:"prepared",createdAt:Date.now()};await saveJob(job);await downloadRun(job,automatic);}
async function latestJob(kind){return(await all("jobs")).filter(j=>j.kind===kind&&j.owner===who).sort((a,b)=>b.createdAt-a.createdAt)[0];}
async function copyFile(){const fid=$("file-id").value.trim();const ds=await api("POST","/v1/downloads",{fileId:fid});const m=await api("GET","/v1/downloads/"+ds.downloadId+"/manifest");const copy=await api("POST","/v1/uploads",{name:"reference-copy.txt",sizeBytes:m.totalSizeBytes,mimeType:"application/octet-stream",mode:"independent-chunks"},{"Idempotency-Key":crypto.randomUUID()});await api("PUT","/v1/uploads/"+copy.uploadId+"/manifest",{chunking:{algorithm:"reuse",version:1,parameters:{}},chunks:m.chunks.map(c=>({ordinal:c.ordinal,reuseFrom:{fileId:fid,manifestId:m.manifestId,ordinal:c.ordinal}}))});const result=await api("POST","/v1/uploads/"+copy.uploadId+"/complete",{});selectFile(result.fileId);await listFiles();await refreshState();toast("New private file; existing verified chunks reused.");}
async function processPending(){
  const changes=(await all("pending")).filter(c=>c.owner===who&&c.state==="pending").sort((a,b)=>a.cursor-b.cursor);
  for(const change of changes){
    if(changes.some(later=>later.fileId===change.fileId&&later.cursor>change.cursor)){await write("pending",{...change,state:"done"});continue;}
    const local=await read("files",who+":"+change.fileId);
    if(["deleted","access_removed"].includes(change.type)){
      if(local?.dirty)continue;
      if(local)await write("files",{...local,removed:true});
    }else if(local&&!local.removed&&local.revision>=change.revision){
      // Already installed: a replay must not download the same revision again.
    }else{
      if(!$("auto-sync").checked||!online||local?.dirty)continue;
      try{await startDownload(change.fileId,true);}catch(e){toast("Sync retained pending work: "+e.message,true);continue;}
    }
    await write("pending",{...change,state:"done"});
  }
}
async function pull(){
  if(busyPull)return;busyPull=true;
  try{
    const state=await read("settings","cursor:"+who)||{id:"cursor:"+who,cursor:0};let response;
    do{
      response=await api("GET","/v1/changes?cursor="+state.cursor+"&limit=100");
      for(const change of response.changes)await write("pending",{id:who+":"+change.cursor,owner:who,...change,state:"pending"});
      state.cursor=response.nextCursor;await write("settings",state);
      $("changes").textContent=JSON.stringify(response,null,2);$("cursor-label").textContent="Discovery cursor: "+state.cursor;
    }while(response.hasMore);
    // Retry durable work even when the server returns no new change records.
    await processPending();await listFiles();
  }finally{busyPull=false;}
}
function connect(){sse?.close();online=true;if($("discovery-mode").value==="poll"){$("connection").textContent="Periodic pull · no SSE";return;}sse=new EventSource("/v1/events");sse.onopen=()=>{$("connection").textContent="SSE connected";};sse.onmessage=()=>pull().catch(e=>toast(e.message,true));sse.onerror=()=>{$("connection").textContent="Reconnect / safety pull";};}
$("discovery-mode").onchange=()=>{connect();pull().catch(e=>toast(e.message,true));};
function bind(id,fn){$(id).onclick=async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){toast(e.message,true);}finally{b.disabled=false;}};}
for(const tab of document.querySelectorAll(".tab"))tab.onclick=()=>{document.querySelectorAll(".tab,.panel").forEach(e=>e.classList.remove("active"));tab.classList.add("active");$(tab.dataset.tab).classList.add("active");};
function sampleData(){let x=73129;const parts=[];for(let i=0;i<8192;i++){x=(Math.imul(x,1664525)+1013904223)>>>0;parts.push(x.toString(16).padStart(8,"0")+" - stable content and a useful independent chunk\n");}return parts.join("");}
bind("large-sample",()=>{$("source").value="";$("sample").value=sampleData();$("name").value="large-plan.txt";toast("Prepared a larger sample; choose a boundary policy.");});
bind("upload",startUpload);bind("pause-upload",()=>{paused=true;toast("Pausing after in-flight chunks finish.");});
bind("resume-upload",async()=>{const job=await latestJob("upload");if(!job)throw new Error("No saved upload");await runUpload(job);});
bind("list-files",listFiles);bind("download",()=>startDownload());bind("copy-file",copyFile);
bind("resume-download",async()=>{const job=await latestJob("download");if(!job)throw new Error("No saved download");await downloadRun(job);});
bind("delete-file",async()=>{await api("DELETE","/v1/files/"+$("file-id").value.trim());await listFiles();await refreshState();});
bind("conflict-copy",async()=>{const job=lastUpload||await latestJob("upload");if(!job?.uploadId)throw new Error("No candidate");const result=await api("POST","/v1/uploads/"+job.uploadId+"/conflict-copy",{name:job.name+" (phone conflict)"},{"Idempotency-Key":"resolution-"+job.key});await finishUpload(job,result);await refreshState();});
bind("refresh-jobs",async()=>{const jobs=(await all("jobs")).filter(j=>j.owner===who);$("job-detail").textContent=JSON.stringify(jobs.map(({id,kind,state,uploadId,downloadId,revision})=>({id,kind,state,uploadId,downloadId,revision})),null,2);});
bind("share",async()=>{await api("POST","/v1/files/"+$("share-file").value+"/shares",{recipientId:$("recipient").value,role:"reader"});await refreshState();toast("Reader grant committed.");});
bind("revoke",async()=>{await api("DELETE","/v1/files/"+$("share-file").value+"/shares/"+$("recipient").value);await refreshState();toast("New permission denied. Existing scoped URLs expire independently.");});
bind("online",async()=>{connect();await pull();});bind("offline",()=>{online=false;sse?.close();$("connection").textContent="Offline · cursor retained";});bind("poll",pull);
bind("add-readers",async()=>{await api("POST","/v1/lab/recipients",{fileId:$("file-id").value,count:Number($("recipient-count").value)},{},"lee");await refreshState();});
bind("fanout-step",async()=>{await api("POST","/v1/lab/fanout/run",{batch:Number($("batch-size").value)},{},"lee");await refreshState();});
for(const [name,label] of Object.entries(faultNames)){const el=document.createElement("label");el.innerHTML='<input type="checkbox" id="fault-'+name+'">'+escape(label);$("fault-controls").append(el);el.querySelector("input").onchange=async e=>{try{await api("POST","/v1/lab/faults",{[name]:e.target.checked},{},"lee");await refreshState();}catch(err){toast(err.message,true);}};}
for(const seconds of [40,200,1000])bind("advance-"+seconds,async()=>{await api("POST","/v1/lab/advance",{seconds},{},"lee");await refreshState();});
bind("gc-mark",async()=>{const out=await api("POST","/v1/lab/gc/run",{grace:0,markOnly:true},{},"lee");$("proof").textContent=JSON.stringify(out,null,2);await refreshState();});
bind("gc-finish",async()=>{const out=await api("POST","/v1/lab/gc/run",{grace:0},{},"lee");$("proof").textContent=JSON.stringify(out,null,2);await refreshState();});
bind("encryption-proof",async()=>{const state=await refreshState();const chunk=state.postgres.chunk_objects.find(c=>c.version&&c.state!=="deleted");if(!chunk)throw new Error("Upload a chunk first");$("proof").textContent=JSON.stringify(await api("GET","/v1/lab/storage-proof/"+chunk.id,undefined,{},"lee"),null,2);});
bind("region-config",async()=>{$("region-result").textContent=JSON.stringify(await api("POST","/v1/lab/region",{mode:$("region-mode").value,secondary:$("secondary").value},{},"lee"),null,2);await refreshState();});
for(const [id,action] of [["region-replay","replay"],["region-promote","failover"]])bind(id,async()=>{$("region-result").textContent=JSON.stringify(await api("POST","/v1/lab/region",{action},{},"lee"),null,2);await refreshState();});
bind("variant-sample",()=>{const text=sampleData();$("before").value=text;$("after").value="INSERTED AT THE FRONT\n"+text;});
bind("analyze",async()=>{const a=enc.encode($("before").value),b=enc.encode($("after").value),output={};for(const mode of ["whole","fixed","cdc"]){const before=split(a,mode,65536),after=split(b,mode,65536),known=new Set(await Promise.all(before.map(sha)));let reusable=0,changed=0;for(const chunk of after){if(known.has(await sha(chunk)))reusable+=chunk.length;else changed+=chunk.length;}output[mode]={beforeChunks:before.length,afterChunks:after.length,reusableBytes:reusable,newBytes:changed};}$("analysis").textContent=JSON.stringify(output,null,2);trace("CLIENT","boundary comparison",{beforeBytes:a.length,afterBytes:b.length},200,output);});
bind("refresh-state",refreshState);bind("clear-trace",()=>{$("trace").replaceChildren();});
bind("reset",async()=>{sse?.close();await api("POST","/v1/lab/reset",{},{},"lee");await clearLocal();$("files").textContent="No files yet.";$("files").className="file-list empty";$("chunks").replaceChildren();$("progress").value=0;$("job-title").textContent="Ready for your first transfer";$("job-status").textContent="Idle";$("job-detail").textContent="All application state reset.";$("download-result").replaceChildren();await refreshState();if(online)connect();toast("Empty application state. Old encrypted objects are not silently destroyed.");});
$("identity").value=who;$("identity").onchange=async()=>{who=$("identity").value;localStorage.setItem("drive-demo-user",who);await login(who);$("list-scope").value=who==="lee"?"owned":"shared";connect();await listFiles();const cursor=await read("settings","cursor:"+who);$("cursor-label").textContent="Discovery cursor: "+(cursor?.cursor||0);};
const auto=document.createElement("label");auto.innerHTML='<input id="auto-sync" type="checkbox" checked> Automatically install discovered remote revisions';$("changes").before(auto);
await login("lee");if(who!=="lee")await login(who);
$("list-scope").value=who==="lee"?"owned":"shared";
await listFiles();await refreshState();connect();
setInterval(()=>{if(online&&$("safety-poll").checked)pull().catch(()=>{});},10000);
setInterval(()=>refreshState().catch(()=>{}),5000);
window.driveLab={api,crc,split,read,write,all,pull,startDownload,prepare};
