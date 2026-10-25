let selected = null, roots = [], older = null, newer = null, reading = false, historyLoaded = false;
let loading = false, rootSignature = '', discoveryWarning = '', canSend = false, status = '';
let renderedTranscript = '', firstPaint = true, anchorOlder = false, lastNear = true;
let headHarness = null;
const outbox = new Map();
const transcript = new Map();
const activityItems = new Map();
const order = [];
const openBlocks = new Set();
const thread = $('thread');
const sessions = new Sheet($('sessions'), $('switcher'), $('scrim'));
const details = new Sheet($('details'), $('details-toggle'), $('scrim'));
const rootButtons=()=>[...$('roots').children,...$('saved-roots').children];
const STATUS_LABELS = record({active:'Working', idle:'Ready', 'input-needed':'Needs you', native:'Native',
  offline:'Offline',unknown:'Status not reported'});
const DELIVERY_LABELS = record({queued:'Accepted into the session queue.', steered:'Accepted for the current turn.',
  forwarded:'Forwarded to the session. The native app has not confirmed receipt.',
  sending:'Submission is still in progress.',
  unknown:'Delivery could not be confirmed. Check the native conversation before sending again.',
  failed:'Not sent. Refresh the session and try again.'});

for(const [id,name] of [['sessions-close','close'],['switcher','menu'],['native','external'],['details-toggle','info'],
  ['details-close','close'],['latest','down'],['attach','image'],['send','up']]) $(id).append(icon(name));
$('command-menu-button').textContent=''; $('command-menu-button').append(icon('slash'),el('span',{text:'Commands'}));

const THEMES=['system','dark','light'];
let theme='system';
try { const saved=localStorage.getItem('agent-inbox-theme'); if(THEMES.includes(saved)) theme=saved; } catch {}
function showTheme() {
  document.documentElement.dataset.theme=theme;
  const button=$('theme-toggle'), label='Theme: '+theme;
  button.textContent=''; button.append(icon(theme==='dark' ? 'moon' : theme==='light' ? 'sun' : 'system'));
  button.setAttribute('aria-label',label); button.title=label;
}
$('theme-toggle').addEventListener('click',()=>{
  theme=THEMES[(THEMES.indexOf(theme)+1)%THEMES.length]; showTheme();
  try { localStorage.setItem('agent-inbox-theme',theme); } catch {}
});
showTheme();

function composeState(id=selected.id) {
  if(!outbox.has(id)) outbox.set(id,{draft:'',images:[],pending:null,delivery:'',sending:false,uploading:false,receipt:''});
  return outbox.get(id);
}
function messageId() {
  const bytes=crypto.getRandomValues(new Uint8Array(16)); bytes[6]=(bytes[6]&15)|64; bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
}
function fit() {
  const box=$('message');
  if(!box.style || !box.scrollHeight) return;
  box.style.height='auto'; box.style.height=Math.min(box.scrollHeight,200)+'px';
}
function setDraft(text) { $('message').value=text; fit(); }

/* One place decides which composer controls are usable, from the selected root's own state. */
function syncComposer() {
  if(!selected) return;
  const state=composeState(), open=canSend;
  $('message').disabled=!open;
  $('send').disabled=!open || state.sending || state.uploading;
  $('image-file').disabled=!open || state.sending || state.uploading || !!state.pending;
  $('attach').dataset.disabled=$('image-file').disabled ? '1' : '';
  $('resolve').hidden=!state.pending || state.sending || state.receipt!=='unknown';
  $('resolve').disabled=state.sending;
  $('check').hidden=!state.pending || state.sending;
  $('check').disabled=state.sending;
  $('receipt').hidden=$('resolve').hidden && $('check').hidden;
  $('send').dataset.busy=state.sending ? '1' : '';
}
function renderAttachments() {
  const box=$('attachments'), state=composeState(); box.textContent='';
  for(const [index,url] of state.images.entries()) {
    box.append(el('div',{class:'thumb'},
      el('img',{src:url,alt:'Attached image '+(index+1)}),
      el('button',{type:'button',class:'thumb-remove','aria-label':'Remove image '+(index+1),disabled:!!state.pending || state.uploading,
        onclick:()=>{composeState().images.splice(index,1);renderAttachments();}},icon('close'))));
  }
  syncComposer();
}
async function api(path, data) {
  const options = data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)} : {};
  const response = await fetch(path, options);
  const result = await response.json();
  if (response.status === 401) { $('pairing').hidden=false; $('inbox').hidden=true; }
  if (!response.ok) {
    const error=new Error(result.error || 'Connection unavailable'); error.status=response.status; throw error;
  }
  return result;
}

const nearBottom = () => thread.scrollHeight-thread.scrollTop-thread.clientHeight<140;
function toBottom(smooth) {
  if(thread.scrollTo) thread.scrollTo({top:thread.scrollHeight,behavior:smooth?'smooth':'auto'});
  else thread.scrollTop=thread.scrollHeight;
}
function messageNode(item, first, animate) {
  const node=el('article',{class:'msg '+item.role+(item.phase==='commentary'?' progress':'')+(item.answers?' answer':'')+(animate?' enter':''),
    data:{messageId:item.id,version:JSON.stringify([item,first,selected.harness])}});
  const body=el('div',{class:'body'});
  if(typeof item.html==='string') { body.className+=' markdown'; body.innerHTML=item.html; }
  else if(item.answers) {
    for(const reply of item.answers) body.append(el('p',{class:'answer-question',text:reply.question}),el('p',{class:'answer-choice',text:reply.answer}));
  } else body.textContent=item.text;
  for(const [index,url] of (item.images || []).entries()) {
    body.append(el('img',{class:'chat-image',src:url,alt:'Conversation image '+(index+1),loading:'lazy'}));
  }
  if(item.role==='user') node.append(body);
  else node.append(el('span',{class:'slot'},first ? brandMark(selected.harness,{title:true}) : null),body);
  return node;
}
/* The native timeline is the only authority for placing activity among messages: ids are never sorted by time or index.
   Older pages merge their unseen ids before what we have; forward pages slot in after the last id they share with us. */
function mergeOrder(ids, olderPage) {
  if(olderPage) { const known=new Set(order); order.unshift(...ids.filter(id=>!known.has(id))); return; }
  let at=-1;
  for(const id of ids) {
    const index=order.indexOf(id);
    if(index>=0) { at=index; continue; }
    if(at<0) { order.push(id); at=order.length-1; } else { order.splice(at+1,0,id); at++; }
  }
}
function sequence() {
  const seen=new Set(), out=[];
  const push=id=>{
    if(seen.has(id)) return; seen.add(id);
    if(transcript.has(id)) out.push({kind:'message',item:transcript.get(id)});
    else if(activityItems.has(id)) out.push({kind:'activity',item:activityItems.get(id)});
  };
  order.forEach(push); for(const id of transcript.keys()) push(id);
  return out;
}
const isLive = row => row.status==='running' && status==='active';  // a stale "running" row never keeps an idle session spinning
const isFailed = row => row.status==='failed' || row.status==='error';
function collapse(rows) {
  const groups=[];
  for(const row of rows) {
    const last=groups.at(-1);
    if(last && last.row.label===row.label && last.row.status===row.status) last.count++; else groups.push({row,count:1});
  }
  return groups;
}
function stepRow(row, count) {
  const live=isLive(row), failed=isFailed(row);
  const note=live ? '' : failed ? 'failed' : row.status==='running' ? 'not finished' : count===1 ? duration(row.duration_ms) : '';
  return el('div',{class:'step',data:{status:live ? 'running' : failed ? 'failed' : 'done'}},
    el('span',{class:'dot','aria-hidden':'true'}),
    el('span',{class:'label',text:row.label+(count>1 ? ' ×'+count : '')}),
    note ? el('small',{text:note}) : null);
}
function stepSummary(rows) {
  const groups=new Map();
  for(const row of rows) groups.set(row.label,(groups.get(row.label) || 0)+1);
  const names=[...groups].map(([label,count])=>label+(count>1 ? ' ×'+count : ''));
  return names.slice(0,3).join(' · ')+(names.length>3 ? ' · +'+(names.length-3)+' more' : '');
}
/* One run of consecutive native activity: finished steps fold into one expandable line, live steps stay visible. */
function activityBlock(rows, first) {
  const key=rows[0].id, open=openBlocks.has(key), done=rows.filter(row=>!isLive(row)), live=collapse(rows.filter(isLive));
  const body=el('div',{class:'steps'});
  if(done.length===1) body.append(stepRow(done[0],1));
  else if(done.length>1) {
    body.append(el('button',{type:'button',class:'step summary','aria-expanded':String(open),data:{status:done.some(isFailed) ? 'failed' : 'done'},
      onclick:()=>{ if(open) openBlocks.delete(key); else openBlocks.add(key); renderMessages(); }},
      el('span',{class:'dot','aria-hidden':'true'}),el('span',{class:'label',text:stepSummary(done)}),
      el('small',{text:done.length+' steps'}),el('span',{class:'chev','aria-hidden':'true'})));
    if(open) body.append(el('div',{class:'step-list'},collapse(done).map(group=>stepRow(group.row,group.count))));
  }
  for(const group of live) body.append(stepRow(group.row,group.count));
  return el('div',{class:'msg activity',data:{blockId:key}},el('span',{class:'slot'},first ? brandMark(selected.harness,{title:true}) : null),body);
}
/* Shown at the end of the stream while the native session is working or waiting; no invented progress. */
function liveRow(input, first) {
  return el('div',{class:'msg activity live',data:{kind:input ? 'input' : 'active'}},
    el('span',{class:'slot'},first ? brandMark(selected.harness,{title:true}) : null),
    el('div',{class:'steps'},el('div',{class:'step',data:{status:input ? 'input' : 'running'}},
      input ? el('span',{class:'dot','aria-hidden':'true'}) : el('span',{class:'spinner','aria-hidden':'true'},el('i'),el('i'),el('i')),
      el('span',{class:'label',text:input ? (formsPanel.answerable() ? 'Waiting for your answer below.' : 'Needs your input. Answer it in the native session.') : 'Working…'}))));
}
function renderMessages() {
  if(!selected) return;
  const items=sequence();
  const signature=JSON.stringify([selected.id,selected.harness,status,items,[...openBlocks],formsPanel.answerable()]);
  if(signature===renderedTranscript) return;
  renderedTranscript=signature;
  const stick=firstPaint || nearBottom(), top=thread.scrollTop, height=thread.scrollHeight, animate=!firstPaint && !anchorOlder;
  const box=$('messages'), previous=new Map(Array.from(box.children).map(node=>[node.dataset.messageId,node]));
  box.textContent='';
  let before=null;  // the last message in the run, to decide where the harness mark appears
  for(let index=0; index<items.length;) {
    const entry=items[index];
    if(entry.kind==='message') {
      const item=entry.item, first=!before || before.role==='user', existing=previous.get(item.id);
      const version=JSON.stringify([item,first,selected.harness]);
      box.append(existing && existing.dataset.version===version ? existing : messageNode(item,first,animate && !existing));
      before=item; index++; continue;
    }
    let end=index; while(end<items.length && items[end].kind==='activity') end++;
    box.append(activityBlock(items.slice(index,end).map(row=>row.item),!before || before.role==='user'));
    before={role:'assistant'}; index=end;
  }
  if(status==='active' || status==='input-needed') {
    const last=items.at(-1);
    if(status==='input-needed' || !(last?.kind==='activity' && isLive(last.item))) box.append(liveRow(status==='input-needed',!before || before.role==='user'));
  }
  if(!items.length && status!=='active') {
    box.append(el('p',{class:'empty'},$('native').hidden ? 'No chat messages on this page yet.' : 'This conversation continues in its native remote interface.',
      $('native').hidden ? null : el('a',{href:$('native').href,target:'_blank',rel:'noopener noreferrer',text:'Open it ↗'})));
  }
  const filled=items.length>0;
  if(anchorOlder) { thread.scrollTop=top+(thread.scrollHeight-height); anchorOlder=false; lastNear=nearBottom(); }
  else if(stick && filled) { toBottom(!firstPaint); lastNear=true; }
  else { thread.scrollTop=top; lastNear=nearBottom(); }
  if(filled) firstPaint=false;
  $('latest').hidden=lastNear || !filled;
}
function setStatus(next) {
  status=next;
  // Working and Ready are shown in the stream and the session list; the header only flags states that need attention.
  $('state').dataset.status=next; $('state').textContent=next==='active' || next==='idle' ? '' : STATUS_LABELS[next] || next;
  for(const button of rootButtons()) if(button.dataset.id===selected?.id) button.dataset.working=next==='active' ? '1' : '';
  renderMessages(); syncComposer();
}
function setConnection(text) { $('connection').textContent=text==='Connected' ? '' : text; }

async function read(cursor=null) {
  if (!selected || reading || !roots.some(root=>root.id===selected.id)) return;
  reading=true;
  const target=selected.id;
  let reset=false;
  try {
    const query=cursor?'&cursor='+encodeURIComponent(cursor):newer?'&since='+encodeURIComponent(newer):'';
    const page=await api('/api/view?id='+encodeURIComponent(target)+query);
    if (selected.id!==target || !roots.some(root=>root.id===target)) return;
    if (cursor) { const merged=new Map(page.messages.map(m=>[m.id,m])); for(const [id,m] of transcript) merged.set(id,m); transcript.clear(); for(const [id,m] of merged) transcript.set(id,m); anchorOlder=true; }
    else for (const message of page.messages) transcript.set(message.id,message);
    if(cursor || !historyLoaded) older=page.older_cursor;
    if(!cursor) newer=page.newer_cursor || null;
    historyLoaded=true; $('older').hidden=!older;
    for(const row of page.activity || []) activityItems.set(row.id,row);
    if(page.timeline) mergeOrder(page.timeline,!!cursor);
    const statusChanged=status && status!==page.status;
    canSend=page.can_send;
    setStatus(page.status);
    if(statusChanged) commandPanel.load();
    if(!cursor && (page.status==='active' || page.status==='input-needed' || formsPanel.hasAny())) formsPanel.load();
    $('native').hidden=!page.native_url;
    if(page.native_url) $('native').href=page.native_url;
    setConnection(page.catching_up?'Catching up…':discoveryWarning || 'Connected');
    $('delivery').textContent=composeState().delivery || (page.can_send?'':'Continue in the native conversation.');
    renderMessages();
  } catch(error) {
    if(selected.id===target) {
      if(!cursor && newer && error.status===400) {
        newer=null; older=null; historyLoaded=false; transcript.clear(); activityItems.clear(); order.length=0; reset=true;
      } else { setConnection('Unavailable'); $('delivery').textContent=error.message; canSend=false; syncComposer(); }
    }
  }
  finally { reading=false; if(reset || selected.id!==target) read(); }
}
function choose(root) {
  sessions.close(false);
  if (selected?.id===root.id) { read(); return; }
  if(selected) composeState().draft=$('message').value;
  selected=root; older=null; newer=null; historyLoaded=false; transcript.clear(); firstPaint=true; canSend=false;
  activityItems.clear(); order.length=0; openBlocks.clear(); status=''; commandPanel.reset(); contextPanel.reset(); formsPanel.reset();
  if(details.isOpen) contextPanel.load();
  $('details-toggle').disabled=false;
  setDraft(composeState().draft); $('native').hidden=true; $('older').hidden=true; $('delivery').textContent=composeState().delivery;
  rootHeading(root);
  setStatus('');
  for(const button of rootButtons()) button.classList.toggle('active',button.dataset.id===root.id);
  renderAttachments(); renderMessages(); read(); commandPanel.load(); formsPanel.load();
}
function rootHeading(root) {
  const origin=readOrigin(root.origin);
  $('root-title').textContent=root.label; $('root-detail').textContent=root.harness;
  if(origin) $('root-detail').append(originTag(origin,true));
  if(headHarness!==root.harness) {
    headHarness=root.harness;
    $('root-mark').textContent=''; $('root-mark').append(brandMark(root.harness,{size:'lg'}));
  }
  $('message').placeholder='Message '+root.label+'…';
  document.querySelector('label[for="message"]').textContent='Message '+root.label;
}
function renderRoots() {
  $('roots').textContent=''; $('saved-roots').textContent='';
  const search=$('session-search').value.toLocaleLowerCase(), matched=roots.filter(root=>
    !search || (root.label+' '+root.harness+' '+(readOrigin(root.origin)?.job || '')).toLocaleLowerCase().includes(search));
  for(const root of matched) {
    const label=STATUS_LABELS[root.status] || root.status || root.id.slice(-6);
    const working=root.status==='active' || (root.id===selected?.id && status==='active');
    const origin=readOrigin(root.origin);
    const button=el('button',{class:'root',type:'button',data:{id:root.id,working:working ? '1' : ''},
      'aria-label':root.label+', '+root.harness+', '+label+(origin ? ', '+origin.tool+' worker' : ''),onclick:()=>choose(root)},
      brandMark(root.harness),el('span',{class:'root-text'},el('strong',{text:root.label}),
        el('small',{},origin ? originTag(origin,false) : null,root.harness+' · '+label)),
      el('span',{class:'pulse','aria-hidden':'true'}));
    button.classList.toggle('active',root.id===selected?.id);
    $(root.saved ? 'saved-roots' : 'roots').append(button);
  }
  const saved=matched.filter(root=>root.saved).length;
  $('saved-sessions').hidden=!saved;
  $('saved-count').textContent='Saved conversations · '+saved;
  if(search && saved) $('saved-sessions').open=true;
  $('roots-empty').hidden=matched.length>0;
  $('roots-empty').textContent=search ? 'No matching conversations.' : 'No online sessions.';
}
$('session-search').addEventListener('input',renderRoots);
async function load() {
  if(loading) return;
  loading=true;
  try {
    const result=await api('/api/roots'); roots=result.roots;
    discoveryWarning=(result.warnings || []).join(' · ');
    $('pairing').hidden=true; $('inbox').hidden=false;
    setConnection(discoveryWarning || (roots.length?'Connected':'No online sessions'));
    const signature=JSON.stringify(roots);
    if(signature!==rootSignature) { rootSignature=signature; renderRoots(); }
    if(!selected && roots.length) choose(roots[0]);
    const current=selected && roots.find(root=>root.id===selected.id);
    if(current) { selected=current; rootHeading(current); }
    if(selected && !roots.some(root=>root.id===selected.id)) {
      canSend=false; setStatus('offline');
      $('delivery').textContent='This session is offline. Its conversation history is preserved.';
    }
    for(const [id,state] of outbox) {
      if(!roots.some(root=>root.id===id) && !state.draft && !state.images.length && !state.pending && !state.sending) outbox.delete(id);
    }
  } catch(error) {
    setConnection(error.status===401?'Pair device':'Unavailable');
    $('pair-error').textContent=error.status===401?'':error.message;
  }
  finally { loading=false; }
}
$('pair-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('pair-error').textContent='';
  try { await api('/api/pair',{code:$('pair-code').value.trim().toUpperCase(),name:$('device-name').value}); $('pair-code').value=''; await load(); }
  catch(error) { $('pair-error').textContent=error.message; }
});
async function deliver(target,state,payload) {
  const body=payload.text, images=payload.images || [];
  state.sending=true; state.delivery='Sending…';
  renderAttachments(); $('delivery').textContent='Sending…';
  try {
    const result=await api('/api/send',payload); state.receipt=result.status;
    state.delivery=DELIVERY_LABELS[result.status] || 'Unrecognized submission status.';
    if(['queued','steered','forwarded'].includes(result.status)) {
      if(state.draft===body) state.draft='';
      if(JSON.stringify(state.images)===JSON.stringify(images)) state.images=[];
      state.pending=null;
    }
    if(result.status==='failed') state.pending=null;
  } catch(error) {
    state.receipt='unconfirmed';
    state.delivery=error.message+' Your retry will use the same message ID.';
  }
  finally {
    state.sending=false;
    if(selected.id===target) {
      setDraft(state.draft); $('delivery').textContent=state.delivery;
      renderAttachments(); read();
    }
  }
}
$('compose').addEventListener('submit',async event=>{
  event.preventDefault(); if(!selected || composeState().sending || composeState().uploading ||
    (!$('message').value.trim() && !composeState().images.length)) return;
  const body=$('message').value, target=selected.id, state=composeState(target), images=state.images.slice();
  if(!images.length && /^\/(?:[a-z][\w-]*)?(?:\s|$)/i.test(body.trim())) {
    const handled=await commandPanel.slash(body);
    if(handled) {
      if(handled.clear && selected?.id===target && state.draft===body && $('message').value===body) { state.draft=''; setDraft(''); }
      return;
    }
  }
  if(selected.id!==target) return;
  if(state.pending && (state.pending.text!==body || JSON.stringify(state.pending.images || [])!==JSON.stringify(images))) {
    state.delivery='A previous submission is unconfirmed. Check its delivery before sending this new draft.';
    $('delivery').textContent=state.delivery; renderAttachments(); return;
  }
  if(!state.pending) state.pending={id:messageId(),target,text:body,...(images.length?{images}:{})};
  state.draft=body; await deliver(target,state,state.pending);
});
$('check').addEventListener('click',()=>{
  const state=composeState();
  if(state.pending && !state.sending) return deliver(selected.id,state,state.pending);
});
$('message').addEventListener('input',()=>{
  fit(); if(selected) composeState().draft=$('message').value;
  commandPanel.typed($('message').value);
});
$('message').addEventListener('keydown',event=>{
  if(commandPanel.key(event)) return;
  if(event.key==='Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('compose').requestSubmit?.(); }
});
$('image-file').addEventListener('change',async event=>{
  if(!selected) return;
  const target=selected.id, state=composeState(target), files=Array.from(event.target.files);
  if(state.uploading || state.pending) return;
  state.uploading=true; syncComposer();
  try {
    if(files.some(file=>!['image/png','image/jpeg','image/webp','image/gif'].includes(file.type))) throw new Error('Choose PNG, JPEG, WebP or GIF images.');
    const used=state.images.reduce((sum,url)=>sum+(url.length-url.indexOf(',')-1)*3/4,0);
    if(state.images.length+files.length>4 || used+files.reduce((sum,file)=>sum+file.size,0)>8*1024*1024) throw new Error('Choose at most four images, totaling 8 MiB.');
    const urls=await Promise.all(files.map(file=>new Promise((resolve,reject)=>{
      const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(new Error('Could not read image.')); reader.readAsDataURL(file);
    })));
    state.images.push(...urls);
  } catch(error) { state.delivery=error.message; }
  finally {
    state.uploading=false; event.target.value='';
    if(selected.id===target) { renderAttachments(); $('delivery').textContent=state.delivery; }
  }
});
$('resolve').addEventListener('click',()=>{
  if(composeState().sending || composeState().receipt!=='unknown') return;
  composeState().pending=null; composeState().delivery='Receipt cleared. Your draft has not been sent again.';
  $('delivery').textContent=composeState().delivery; renderAttachments();
});
$('older').addEventListener('click',()=>read(older));
$('switcher').addEventListener('click',()=>{ details.close(false); sessions.toggle(); });
$('sessions-close').addEventListener('click',()=>sessions.close());
$('scrim').addEventListener('click',()=>{ sessions.close(false); details.close(false); });
$('details-toggle').addEventListener('click',()=>{ sessions.close(false); details.toggle(); if(details.isOpen) contextPanel.load(); });
$('details-close').addEventListener('click',()=>details.close());
$('latest').addEventListener('click',()=>toBottom(true));
thread.addEventListener('scroll',()=>{ lastNear=nearBottom(); $('latest').hidden=lastNear || !transcript.size; });
document.addEventListener('keydown',event=>{ if(event.key==='Escape') { if(sessions.isOpen) sessions.close(); else if(details.isOpen) details.close(); } });
if(typeof ResizeObserver!=='undefined') new ResizeObserver(()=>{ if(lastNear && transcript.size) toBottom(false); }).observe(thread);
if(window.visualViewport) {
  const fitViewport=()=>{
    document.documentElement.style.setProperty('--app-h',visualViewport.height+'px');
    document.documentElement.style.setProperty('--app-top',visualViewport.offsetTop+'px');
  };
  visualViewport.addEventListener('resize',fitViewport); visualViewport.addEventListener('scroll',fitViewport); fitViewport();
}
const commandPanel=new CommandPanel(api,()=>selected,()=>read(),messageId,{
  set(text) { setDraft(text); if(selected) composeState().draft=text; },
  focus() { $('message').focus?.(); },
});
const contextPanel=new ContextPanel(api,()=>selected,id=>roots.find(root=>root.id===id),root=>{ details.close(false); choose(root); });
const formsPanel=new FormsPanel(api,()=>selected,messageId,()=>{ renderMessages(); if(lastNear) toBottom(false); });
setInterval(()=>{if(!document.hidden) read();},4000);
setInterval(()=>{if(!document.hidden) load();},10000);
document.addEventListener('visibilitychange',async ()=>{if(!document.hidden) { await load(); read(); }});
load();
