/* Native controls live in the composer. Selects are chip buttons (never OS <select> pickers); a chip, typing "/" or the
   Commands button opens one menu anchored to the composer: command list -> native choices / text argument / action. Everything stays bound to the root
   that opened it, including late responses and unknown receipts. Option values are always the exact native ids. */
class CommandPanel {
  constructor(api, current, refresh, makeId, draft) {
    this.api=api; this.current=current; this.refresh=refresh; this.makeId=makeId; this.draft=draft;
    this.pending=new Map(); this.controls=[]; this.unavailable=''; this.request=0; this.loading=false;
    this.loaded=false; this.message=''; this.view=null; this.source='typed'; this.active=0; this.opener='typed';
    $('command-menu-button').addEventListener('click',()=>{ if(this.view && this.source==='button') this.close(); else this.openList(); });
    $('command-menu').addEventListener('keydown',event=>{ if(this.key(event)) return; });
    $('command-check').addEventListener('click',()=>this.check());
    $('command-clear').addEventListener('click',()=>{
      const root=this.current(), pending=root && this.pending.get(root.id);
      if(pending?.status==='unknown' && !pending.sending) {
        this.pending.delete(root.id); this.message='Receipt cleared.'; this.render();
      }
    });
    document.addEventListener('click',event=>{ if(this.view && !this.inside(event)) this.close(false); });
  }
  /* Outside-click test that survives re-rendering. A click handler may replace the clicked node (chip, menu option) before the
     event reaches `document`, leaving a detached target whose ancestors no longer include the menu. The path fixed at dispatch
     time still does, so it is the primary check; closest() only covers environments without composedPath. */
  inside(event) {
    const ids=['command-menu','command-menu-button','command-chips','message'], path=event.composedPath?.() || [];
    return ids.some(id=>path.includes($(id))) || ids.some(id=>!!event.target?.closest?.('#'+id));
  }
  reset() {
    this.request++; this.controls=[]; this.unavailable=''; this.loaded=false; this.loading=false;
    this.message=''; this.view=null; this.render();
  }
  async load() {
    const root=this.current(); if(!root) return;
    if(!root.capabilities.commands) { this.reset(); return; }
    const version=++this.request; this.loading=true;
    try {
      const result=await this.api('/api/commands?id='+encodeURIComponent(root.id));
      if(this.current()?.id!==root.id || version!==this.request) return;
      this.controls=result.controls.filter(row=>row.id!=='interrupt' || root.capabilities.interrupt);
      this.unavailable=result.unavailable || ''; this.loaded=true;
      if(this.view?.command) {  // keep an open picker on the refreshed native values, or close it if the control is gone
        const next=this.controls.find(row=>row.id===this.view.command.id);
        this.view=next ? {...this.view,command:next} : null;
      }
    } catch(error) {
      if(this.current()?.id!==root.id || version!==this.request) return;
      this.controls=[]; this.unavailable=error.message; this.loaded=true;
    } finally { if(version===this.request) { this.loading=false; this.render(); } }
  }
  notice(message) {
    this.message=message; this.render();
    if(message==='Applied' && typeof setTimeout==='function') {
      const root=this.current()?.id, version=this.request;
      setTimeout(()=>{ if(this.message==='Applied' && this.current()?.id===root && version===this.request) { this.message=''; this.render(); } },2500);
    }
  }

  /* --- command lookup and the slash grammar --- */
  nameOf(command) { return command.id.replace(/^slash:/,''); }
  find(name) {
    const wanted=name.toLowerCase();
    return this.controls.find(row=>this.nameOf(row).toLowerCase()===wanted || row.label.toLowerCase().replace(/\s+/g,'')===wanted);
  }
  parse(value) {
    const match=value.match(/^\/([\w:-]*)(?:[ \t]([\s\S]*))?$/);
    if(!match) return null;
    const command=match[2]!==undefined && this.find(match[1]);
    if(command) return {mode:command.kind==='select' ? 'choices' : command.kind==='text' ? 'text' : 'action',command,query:match[2]};
    return {mode:'list',query:match[1]};
  }
  currentLabel(command) {
    if(command.kind!=='select') return '';
    return command.choices.find(choice=>choice.value===command.current)?.label || command.current || '';
  }
  /* Called on every composer edit: the menu follows what is typed. */
  typed(value) {
    const view=this.parse(value);
    if(!view) { if(this.view && this.source==='typed') this.close(false); return; }
    const same=this.view && this.source==='typed' && this.view.mode===view.mode && this.view.command===view.command;
    this.source='typed'; this.view=view; if(!same || view.mode==='choices' || view.mode==='list') this.active=0;
    this.render();
  }
  openList() { this.source='button'; this.opener='button'; this.view={mode:'list',query:''}; this.active=0; this.render(); $('command-menu').focus?.(); }
  /* A chip opens its own native choices in the same menu. The draft is never touched. */
  openChoices(command) {
    if(this.view?.command?.id===command.id && this.opener==='chip:'+command.id) { this.close(); return; }
    this.source='button'; this.opener='chip:'+command.id; this.view={mode:'choices',command,query:''};
    this.active=Math.max(0,command.choices.findIndex(choice=>choice.value===command.current));
    this.render(); $('command-menu').focus?.();
  }
  focusOpener() {
    const target=this.opener==='button' ? $('command-menu-button') : this.opener==='typed' ? $('message') :
      Array.from($('command-chips').children).find(node=>node.dataset.command===this.opener.slice(5));
    (target || $('message')).focus?.();
  }
  close(restoreFocus=true) {
    this.view=null; this.render();
    if(restoreFocus) this.focusOpener();
  }

  /* --- menu content --- */
  items() {
    const view=this.view, busy=this.pending.has(this.current()?.id);
    if(!view) return [];
    const query=view.query.trim().toLowerCase();
    if(view.mode==='list') {
      if(!this.loaded) return [{info:this.loading ? 'Loading commands…' : 'Commands are not loaded yet.'}];
      const rows=this.controls.filter(row=>!query || this.nameOf(row).toLowerCase().includes(query) || row.label.toLowerCase().includes(query));
      if(!rows.length) return [{info:this.controls.length ? 'No matching native command.' : this.unavailable || 'No native commands.'}];
      return rows.map(row=>({title:row.label,name:'/'+this.nameOf(row),value:this.currentLabel(row),detail:row.description,disabled:busy,
        run:()=>this.pick(row)}));
    }
    const command=view.command;
    if(view.mode==='choices') {
      const rows=command.choices.filter(choice=>!query || choice.label.toLowerCase().includes(query) || choice.value.toLowerCase().includes(query));
      if(!rows.length) return [{info:'No native option matches. Values are exact native ids.'}];
      return rows.map(choice=>({title:choice.label,value:choice.value!==choice.label ? choice.value : '',
        mark:choice.value===command.current,disabled:busy,run:()=>this.choose(command,choice.value)}));
    }
    if(view.mode==='text') {
      const argument=view.query.trim();
      if(this.source==='button') return [{form:command}];
      return [argument ? {title:command.label+': '+argument,detail:'Enter to apply',disabled:busy,run:()=>this.choose(command,argument)}
        : {info:'Type the value after /'+this.nameOf(command)+'. '+(command.description || '')}];
    }
    return [{title:'Run '+command.label,detail:command.description || 'Enter to run',disabled:busy,run:()=>this.choose(command,'')}];
  }
  pick(command) {
    if(command.kind==='action') { this.choose(command,''); return; }
    if(this.source==='typed') { this.draft.set('/'+this.nameOf(command)+' '); this.typed('/'+this.nameOf(command)+' '); this.draft.focus(); return; }
    this.view={mode:command.kind==='select' ? 'choices' : 'text',command,query:''};
    this.active=Math.max(0,command.kind==='select' ? command.choices.findIndex(choice=>choice.value===command.current) : 0);
    this.render();
  }
  choose(command, value) {
    if(this.source==='typed') this.draft.set('');
    this.view=null; this.render();
    this.apply(command,value);
    if(this.source==='typed') this.draft.focus(); else this.focusOpener();
  }
  key(event) {
    if(!this.view) return false;
    const rows=this.items(), count=rows.length;
    if(event.key==='ArrowDown' || event.key==='ArrowUp') {
      event.preventDefault(); this.active=(this.active+(event.key==='ArrowDown' ? 1 : -1)+count)%count; this.render(); return true;
    }
    if(event.key==='Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.isComposing) {
      event.preventDefault(); const row=rows[this.active]; if(row?.run && !row.disabled) row.run(); return true;
    }
    if(event.key==='Home' || event.key==='End') { event.preventDefault(); this.active=event.key==='Home' ? 0 : count-1; this.render(); return true; }
    if(event.key==='Escape') { event.preventDefault(); this.close(); return true; }
    if(event.key==='Tab') { this.close(false); return false; }
    return false;
  }

  render() {
    const root=this.current(), pending=root && this.pending.get(root.id), busy=!!pending;
    const chips=$('command-chips'), focused=chips.contains?.(document.activeElement) ? document.activeElement.dataset.command : null;
    chips.textContent='';
    for(const command of this.controls.filter(row=>row.kind==='select')) {
      const shown=pending?.payload.command===command.id ? pending.payload.value : command.current;
      const known=command.choices.some(choice=>choice.value===shown);
      const label=command.choices.find(choice=>choice.value===shown)?.label || (known ? shown : 'Choose…');
      const open=this.view?.command?.id===command.id && this.opener==='chip:'+command.id;
      // aria-disabled, not disabled: the chip keeps focus while a command is applying and ignores activation.
      const inert=busy || !command.choices.length;
      chips.append(el('button',{type:'button',class:'chip select','aria-haspopup':'listbox','aria-expanded':String(open),'aria-disabled':String(inert),
        'aria-label':command.label+': '+label,title:command.description || null,data:{command:command.id},
        onclick:()=>{ if(!inert) this.openChoices(command); }},
        el('small',{text:command.label}),el('span',{class:'chip-value',text:label}),el('span',{class:'chev','aria-hidden':'true'})));
    }
    if(focused!==null) Array.from(chips.children).find(node=>node.dataset.command===focused)?.focus?.();
    $('command-menu-button').hidden=!(this.loaded && (this.controls.length || this.unavailable));
    this.renderMenu();
    const text=pending ? (pending.sending ? 'Applying…' : pending.status==='unknown' ?
      'Result unconfirmed. Check the native session before clearing.' : pending.status==='sending' ?
      'Still applying. Check again shortly.' : 'Check this command’s delivery.') : this.message;
    $('command-status').textContent=text;
    $('command-check').hidden=!pending || pending.sending;
    $('command-clear').hidden=!pending || pending.status!=='unknown' || pending.sending;
    $('command-notice').hidden=!text;
  }
  renderMenu() {
    const menu=$('command-menu'), open=!!this.view, rows=this.items();
    menu.hidden=!open; menu.textContent='';
    $('command-menu-button').setAttribute('aria-expanded',String(open && this.source==='button'));
    $('message').setAttribute('aria-expanded',String(open && this.source==='typed'));
    const owner=this.source==='typed' ? $('message') : menu;  // whichever element has focus names the highlighted option
    $('message').setAttribute('aria-activedescendant',''); menu.setAttribute('aria-activedescendant','');
    if(!open) return;
    menu.setAttribute('role',rows[0]?.form ? 'group' : 'listbox');
    if(this.view.command) menu.append(el('div',{class:'menu-head'},el('strong',{text:this.view.command.label}),
      this.view.command.description ? el('small',{text:this.view.command.description}) : null));
    rows.forEach((row,index)=>{
      if(row.info) { menu.append(el('p',{class:'menu-note',role:'status',text:row.info})); return; }
      if(row.form) { menu.append(this.textForm(row.form)); return; }
      const id='command-option-'+index, selected=index===this.active;
      const node=el('button',{class:'menu-item',type:'button',role:'option',id,disabled:row.disabled,'aria-selected':String(!!row.mark),
        data:{active:selected ? '1' : ''},onmousedown:event=>event.preventDefault(),onclick:()=>row.run()},
        el('span',{class:'menu-title'},el('span',{text:row.title}),row.name ? el('small',{text:row.name}) : null),
        row.value ? el('small',{class:'menu-value',text:row.value}) : null,
        row.mark ? el('span',{class:'menu-check','aria-hidden':'true'}) : null,
        row.detail ? el('small',{class:'menu-detail',text:row.detail}) : null);
      menu.append(node);
      if(selected) { owner.setAttribute('aria-activedescendant',id); node.scrollIntoView?.({block:'nearest'}); }
    });
  }
  textForm(command) {
    const input=el('input',{type:'text',maxLength:16384,autocomplete:'off',placeholder:command.description || command.label,'aria-label':command.label});
    return el('form',{class:'menu-form',onsubmit:event=>{
      event.preventDefault();
      if(input.value) this.choose(command,input.value);
    }},el('span',{class:'menu-row'},input,el('button',{type:'submit',class:'primary',text:'Apply'})));
  }

  /* --- delivery of one native command, idempotent per root --- */
  async apply(command, value) {
    const root=this.current(); if(!root || this.pending.has(root.id)) return;
    if(command.kind==='action') value='';
    const pending={payload:{id:this.makeId(),target:root.id,command:command.id,value},sending:false,status:''};
    this.pending.set(root.id,pending); await this.deliver(root.id,pending);
  }
  async check() {
    const root=this.current(), pending=root && this.pending.get(root.id);
    if(pending && !pending.sending) await this.deliver(root.id,pending);
  }
  async deliver(root, pending) {
    pending.sending=true; this.render();
    try {
      const result=await this.api('/api/command',pending.payload); pending.status=result.status;
      if(result.status==='applied' || result.status==='failed') this.pending.delete(root);
      if(this.current()?.id!==root) return;
      if(result.status==='applied') { this.message=''; await this.load(); this.notice('Applied'); this.refresh(); }
      else if(result.status==='failed') { this.notice('Not applied. The session may have changed; try again.'); await this.load(); }
    } catch(error) {
      pending.status='unconfirmed';
      if(this.current()?.id===root) this.message=error.message;
    } finally {
      pending.sending=false;
      if(this.current()?.id===root) this.render();
    }
  }
  /* Send tapped on a "/command ..." draft: never chat. An exact native value applies; anything else shows the menu. */
  async slash(body) {
    const view=this.parse(body.trim());
    if(!view) return false;
    if(!this.loaded) await this.load();
    const name=body.trim().slice(1).split(/\s/)[0], command=name && this.find(name);
    if(!name) { this.typed('/'); this.draft.focus(); return {clear:false}; }
    if(!command) { this.notice('This command is not exposed by the connection. Use the native session.'); return {clear:false}; }
    const argument=body.trim().slice(1+name.length).trim();
    const choice=command.kind==='select' && argument && command.choices.find(row=>row.value===argument);
    if(choice) { this.source='typed'; this.apply(command,choice.value); return {clear:true}; }
    if(command.kind==='text' && argument) { this.apply(command,argument); return {clear:true}; }
    this.typed(body.trim()+(command.kind==='action' || argument ? '' : ' '));
    this.draft.focus();
    return {clear:false};
  }
}
