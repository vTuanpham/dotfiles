/* Optional session details from GET /api/context. Scoped to the selected root; never inferred or merged across roots. */
function decodeContext(raw) {
  const ok=raw && typeof raw==='object' && optional(raw.account,account=>typeof account==='object' &&
      optional(account.identity,isText) && optional(account.email,isText) && optional(account.plan,isText) && isText(account.scope)) &&
    list(raw.quotas,q=>isText(q.label) && isNumber(q.used_percent) && optional(q.window_minutes,isNumber) && optional(q.resets_at,isNumber)) &&
    list(raw.metrics,m=>isText(m.label) && isNumber(m.value) && isText(m.unit)) &&
    list(raw.workers,w=>isText(w.id) && isText(w.label) && isText(w.status) && optional(w.model,isText)) &&
    list(raw.tools,t=>isText(t.name) && isText(t.status) && optional(t.tool_count,isNumber)) &&
    Array.isArray(raw.notices) && raw.notices.every(isText) && isNumber(raw.fetched_at) &&
    (raw.origin===undefined || raw.origin===null || readOrigin(raw.origin)!==null);
  if(!ok) throw new Error('Session details were not in a recognized format.');
  return raw;
}
function windowLabel(minutes) {
  if(minutes==null) return '';
  if(minutes%10080===0) return minutes===10080 ? 'weekly' : minutes/10080+' wk';
  if(minutes%1440===0) return minutes/1440+' d';
  if(minutes%60===0) return minutes/60+' h';
  return minutes+' min';
}
function resetLabel(seconds, now=Date.now()) {
  const at=new Date(seconds*1000), ahead=seconds*1000-now;
  if(ahead<=0) return 'Reset time passed';
  const total=Math.max(1,Math.round(ahead/60000));  // round once, then split: never "60 m"
  const days=Math.floor(total/1440), hours=Math.floor(total%1440/60), minutes=total%60;
  const left=days ? days+' d'+(hours ? ' '+hours+' h' : '') : hours ? hours+' h'+(minutes ? ' '+minutes+' m' : '') : minutes+' m';
  const clock=at.toLocaleString([],ahead<20*3600000 ? {hour:'numeric',minute:'2-digit'} : {weekday:'short',hour:'numeric',minute:'2-digit'});
  return 'Resets '+clock+' · in '+left;
}
class ContextPanel {
  /* `lookup(id)` returns a currently listed root or undefined; `open(root)` is the app's own root selection. */
  constructor(api, current, lookup, open) {
    this.api=api; this.current=current; this.lookup=lookup; this.open=open; this.cache=new Map(); this.request=0;
  }
  reset() { this.request++; this.show(this.cache.get(this.current()?.id)); }
  async load() {
    const root=this.current(); if(!root) return;
    const version=++this.request, cached=this.cache.get(root.id);
    this.show(cached, cached ? '' : 'Loading…');
    try {
      const data=decodeContext(await this.api('/api/context?id='+encodeURIComponent(root.id)));
      this.cache.set(root.id,data);
      if(this.current()?.id===root.id && version===this.request) this.show(data);
    } catch(error) {
      if(this.current()?.id===root.id && version===this.request) this.show(cached, error.message);
    }
  }
  show(data, message='') {
    const body=$('details-body'); body.textContent='';
    if(message) body.append(el('p',{class:'muted',role:'status',text:message}));
    const origin=readOrigin(data?.origin) || readOrigin(this.current()?.origin);
    if(origin) body.append(this.graph(origin));
    if(!data) return;
    const {account,quotas,metrics,workers,tools,notices}=data;
    if(account) {
      const name=account.email || account.identity;
      body.append(el('section',{class:'detail'},el('h3',{text:'Account'}),
        name ? el('p',{class:'account-name',text:name}) : null,
        account.plan ? el('p',{class:'pill',text:account.plan}) : null,
        el('p',{class:'muted small',text:account.scope==='connection' ?
          'Account of the current connection. It may differ from the account used for earlier turns.' : account.scope})));
    }
    if(quotas.length) body.append(el('section',{class:'detail'},el('h3',{text:'Usage limits'}),quotas.map(q=>this.quota(q))));
    if(metrics.length) body.append(el('section',{class:'detail'},el('h3',{text:'This session'}),
      el('dl',{class:'metrics'},metrics.map(m=>[el('dt',{text:m.label}),el('dd',{text:m.value.toLocaleString()+(m.unit ? ' '+m.unit : '')})]))));
    if(workers.length) body.append(el('section',{class:'detail'},el('h3',{text:'Sub-agents'}),
      el('ul',{class:'rows'},workers.map(w=>el('li',{data:{status:w.status}},el('span',{text:w.label}),
        el('small',{text:[w.model,statusText(w.status)].filter(Boolean).join(' · ')}))))));
    if(tools.length) body.append(el('section',{class:'detail'},el('h3',{text:'Tools'}),
      el('ul',{class:'rows'},tools.map(t=>el('li',{data:{status:t.status}},el('span',{text:t.name}),
        el('small',{text:[t.tool_count!=null ? t.tool_count+' tools' : null,statusText(t.status)].filter(Boolean).join(' · ')}))))));
    for(const notice of notices) body.append(el('p',{class:'muted small',text:notice}));
    if(!origin && !account && !quotas.length && !metrics.length && !workers.length && !tools.length && !notices.length) {
      body.append(el('p',{class:'muted',text:'This connection does not report session details.'}));
    }
    body.append(el('p',{class:'muted small',text:'Updated '+new Date(data.fetched_at*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}));
  }
  /* Launch chain, only from what the origin states: [known parent] -> launcher -> this session. No parent, no first node. */
  graph(origin) {
    const here=this.current(), parent=origin.parent, parentRoot=parent?.id ? this.lookup(parent.id) : undefined;
    const node=(mark, name, sub, extra={}) => el(extra.open ? 'button' : 'div',{class:'node'+(extra.here ? ' here' : '')+(extra.open ? ' link' : ''),
      type:extra.open ? 'button' : null,onclick:extra.open || null,'aria-current':extra.here ? 'true' : null,
      'aria-label':extra.open ? 'Open '+name : null},mark,el('span',{class:'node-text'},el('strong',{text:name}),sub ? el('small',{text:sub}) : null));
    const rows=[];
    if(parent) rows.push(node(brandMark(parent.harness,{size:'sm'}),parent.label || parent.harness,parent.label ? parent.harness : '',
      parentRoot ? {open:()=>this.open(parentRoot)} : {}));
    rows.push(node(el('span',{class:'mark sm tool'},el('span',{class:'face'},icon('worker'))),origin.tool,origin.job));
    rows.push(node(brandMark(here?.harness,{size:'sm'}),origin.title || here?.label || '',here?.harness || '',{here:true}));
    return el('section',{class:'detail'},el('h3',{text:'Started by'}),el('ol',{class:'graph','aria-label':'Where this session came from'},
      rows.map(row=>el('li',{},row))));
  }
  quota(q) {
    const used=q.used_percent, over=used>100, width=Math.min(100,Math.max(0,used));
    const label=[q.label,windowLabel(q.window_minutes)].filter(Boolean).join(' · ');
    return el('div',{class:'quota',data:{level:over ? 'over' : used>=90 ? 'high' : 'ok'}},
      el('div',{class:'quota-head'},el('span',{text:label}),el('strong',{text:used+'% used'+(over ? ' · over limit' : '')})),
      el('div',{class:'bar',role:'meter','aria-label':label,'aria-valuemin':0,'aria-valuemax':100,'aria-valuenow':width,
        'aria-valuetext':used+'% used'+(over ? ', over limit' : '')},el('i',{style:{width:width+'%'}})),
      q.resets_at!=null ? el('small',{class:'muted',text:resetLabel(q.resets_at)}) : null);
  }
}
