/* Native question forms (GET /api/forms, POST /api/answer), rendered at the tail of the chat.
   Input and receipts live in tab memory per root and form. Form cards are built once and reused, so polling never
   re-renders a focused input or replaces a typed answer with a default. Native owns format/pattern validation. */
const FIELD_KINDS = ['string','number','integer','boolean','multiselect'];
const isScalar = value => typeof value==='string' || typeof value==='boolean' || isNumber(value);
const isStringList = value => Array.isArray(value) && value.every(isText);
const hasHtml = (value,key) => value[key+'_html']===undefined || isText(value[key+'_html']);
/* HTML comes only from the server's shared, HTML-disabled Markdown renderer; older responses stay plain text. */
function formText(tag,value,key,attrs={}) {
  const node=el(tag,{...attrs,text:value[key]});
  if(typeof value[key+'_html']==='string') node.innerHTML=value[key+'_html'];
  return node;
}
function decodeField(field) {
  return field && typeof field==='object' && isText(field.key) && isText(field.label) && FIELD_KINDS.includes(field.kind) &&
    hasHtml(field,'label') && hasHtml(field,'description') &&
    typeof field.required==='boolean' && list(field.choices,c=>isText(c.value) && isText(c.label) && hasHtml(c,'label')) && typeof field.custom==='boolean' &&
    (field.default===null || field.default===undefined || isScalar(field.default) || isStringList(field.default)) &&
    list(field.when,w=>isText(w.key) && ['eq','neq'].includes(w.op) && isScalar(w.value)) &&
    (field.constraints===null || field.constraints===undefined || typeof field.constraints==='object') && isText(field.description);
}
function decodeForms(raw) {
  const ok=raw && typeof raw==='object' && isText(raw.unavailable) &&
    list(raw.forms,form=>isText(form.id) && isText(form.title) && hasHtml(form,'title') && isText(form.unavailable) && Array.isArray(form.fields) && form.fields.every(decodeField));
  if(!ok) throw new Error('Questions were not in a recognized format.');
  return raw;
}
/* Missing answers make both eq and neq false; a multiselect answer matches by containing the value. */
function conditionHolds(when, answers) {
  const answer=own(answers,when.key);
  if(answer===undefined) return false;
  const has=Array.isArray(answer) ? answer.includes(when.value) : answer===when.value;
  return when.op==='eq' ? has : !has;
}
const DECIMAL = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
/* `raw` holds what the user has actually chosen or typed. A key that is present is an answer, even [] or "" for a choice;
   a key that is absent is "no answer". Free text is passed through untrimmed. */
function typedValue(field, raw) {
  if(field.kind==='boolean') return typeof raw==='boolean' ? {value:raw} : {};
  if(field.kind==='multiselect') {
    if(!Array.isArray(raw)) return {};
    const values=[...new Set(raw)];
    if(!field.custom && values.some(value=>!field.choices.some(choice=>choice.value===value))) return {error:'Choose from the listed options.'};
    return {value:values};
  }
  if(typeof raw!=='string') return {};
  if(field.kind==='number' || field.kind==='integer') {
    if(!DECIMAL.test(raw) || !Number.isFinite(Number(raw))) return {error:'Enter a number.'};
    if(field.kind==='integer' && !Number.isInteger(Number(raw))) return {error:'Enter a whole number.'};
    return {value:Number(raw)};
  }
  if(!field.custom && field.choices.length && !field.choices.some(choice=>choice.value===raw)) return {error:'Choose one of the options.'};
  return {value:raw};
}
/* Earlier answers decide which later fields are active; inactive fields are neither required nor sent. */
function readAnswers(form, raw) {
  const answer=record(), errors=record(), active=new Set();
  for(const field of form.fields) {
    if(!field.when.every(condition=>conditionHolds(condition,answer))) continue;
    active.add(field.key);
    const result=typedValue(field,own(raw,field.key));
    if(result.error) errors[field.key]=result.error;
    else if(result.value!==undefined) answer[field.key]=result.value;
    else if(field.required) errors[field.key]='An answer is required.';
  }
  return {answer,errors,active};
}
function initialRaw(form) {
  const raw=record(), other=record();
  for(const field of form.fields) {
    const value=field.default;
    if(value===null || value===undefined) continue;
    if(field.kind==='multiselect') { if(isStringList(value)) raw[field.key]=[...value]; }
    else if(field.kind==='boolean') { if(typeof value==='boolean') raw[field.key]=value; }
    else if(field.kind==='string') { raw[field.key]=String(value); other[field.key]=field.choices.length>0 && !field.choices.some(choice=>choice.value===String(value)); }
    else raw[field.key]=String(value);
  }
  return {raw,other};
}

class FormsPanel {
  constructor(api, current, makeId, onChange) {
    this.api=api; this.current=current; this.makeId=makeId; this.onChange=onChange;
    this.roots=new Map(); this.request=0; this.loading=false;
  }
  rootData(id) {
    if(!this.roots.has(id)) this.roots.set(id,{forms:[],states:new Map()});
    return this.roots.get(id);
  }
  /* A card is answerable only when it has fields; one with an `unavailable` reason is explanation only. */
  answerable() {
    const root=this.current(); return !!root && this.rootData(root.id).forms.some(form=>form.fields.length>0);
  }
  hasAny() { const root=this.current(); return !!root && this.rootData(root.id).forms.length>0; }
  reset() { this.request++; this.loading=false; this.render(); }
  async load() {
    const root=this.current(); if(!root || this.loading) return;
    if(!root.capabilities.questions) { this.accept(root.id,[]); this.render(); return; }
    const version=++this.request; this.loading=true;
    try {
      const result=decodeForms(await this.api('/api/forms?id='+encodeURIComponent(root.id)));
      if(version!==this.request) return;
      this.accept(root.id,result.forms);
    } catch(error) {
      // Questions are optional: a connection without them just shows none. Pending receipts stay visible.
      if(version!==this.request) return;
      if(error.status!==404) this.accept(root.id,null);
    } finally { if(version===this.request) { this.loading=false; this.render(); } }
  }
  accept(rootId, forms) {
    if(!forms) return;
    const data=this.rootData(rootId), listed=new Set(forms.map(form=>form.id));
    data.forms=forms.slice();
    for(const [id,state] of data.states) {
      state.gone=!listed.has(id);
      if(state.gone && !state.pending) data.states.delete(id);
    }
    // A form that vanished while its receipt is unconfirmed stays visible so the user can check or clear it.
    for(const [id,state] of data.states) if(state.gone && !data.forms.some(form=>form.id===id)) data.forms.push(state.form);
  }
  stateFor(rootId, form) {
    const data=this.rootData(rootId);
    let state=data.states.get(form.id);
    const sig=JSON.stringify(form);
    if(!state) {
      state={form,sig,...initialRaw(form),errors:record(),pending:null,message:'',node:null,gone:false};
      data.states.set(form.id,state);
    } else if(state.sig!==sig) { state.form=form; state.sig=sig; state.node=null; }
    return state;
  }
  render() {
    const root=this.current(), box=$('forms');
    const nodes=root ? this.rootData(root.id).forms.map(form=>{
      const state=this.stateFor(root.id,form);
      if(!state.node) state.node=this.card(root.id,state);
      state.sync();
      return state.node;
    }) : [];
    const same=box.children.length===nodes.length && nodes.every((node,index)=>box.children[index]===node);
    if(!same) { box.textContent=''; box.append(...nodes); }
    this.onChange();
  }

  /* --- one card per form --- */
  card(rootId, state) {
    const form=state.form, fields=new Map();
    const touch=key=>{ delete state.errors[key]; state.message=''; state.sync(); };
    const fieldset=el('fieldset',{class:'q-fields'});
    for(const field of form.fields) {
      const part=this.field(form,state,field,touch);
      fields.set(field.key,part); fieldset.append(part.node);
    }
    const note=form.fields.length ? null : el('p',{class:'q-note',text:(form.unavailable || 'This question cannot be answered here.')+' Answer it in the native session.'});
    const status=el('p',{class:'q-status',role:'status'});
    const send=el('button',{type:'submit',class:'primary',text:'Send answer'});
    const cancel=el('button',{type:'button',class:'quiet',text:'Cancel question',onclick:()=>this.submit(rootId,state,true)});
    const check=el('button',{type:'button',class:'quiet',text:'Check delivery',onclick:()=>this.deliver(rootId,state)});
    const clear=el('button',{type:'button',class:'quiet',text:'Checked natively, clear receipt',onclick:()=>{
      if(state.pending?.status==='unknown' && !state.pending.sending) { state.pending=null; state.message='Receipt cleared.'; state.sync(); }
    }});
    const actions=el('div',{class:'q-actions'},send,cancel,check,clear);
    const node=el('form',{class:'msg question',novalidate:true,'aria-label':form.title,data:{formId:form.id},
      onsubmit:event=>{ event.preventDefault(); this.submit(rootId,state,false); }},
      el('span',{class:'slot'}),
      el('div',{class:'q-card'},formText('h3',form,'title'),note,fieldset,status,form.fields.length ? actions : null));
    state.sync=()=>{
      const {active}=readAnswers(form,state.raw), pending=state.pending;
      for(const [key,part] of fields) {
        part.node.hidden=!active.has(key);
        if(part.error.textContent!==(state.errors[key] || '')) part.error.textContent=state.errors[key] || '';
        part.node.dataset.invalid=state.errors[key] ? '1' : '';
        part.refresh();
      }
      fieldset.disabled=!!pending || state.gone;
      send.disabled=!!pending || state.gone; cancel.disabled=!!pending || state.gone;
      check.hidden=!pending || pending.sending;
      clear.hidden=!pending || pending.status!=='unknown' || pending.sending;
      status.textContent=pending ? (pending.sending ? 'Sending…' : pending.status==='unknown' ?
        'Delivery could not be confirmed. Check the native session before clearing.' : pending.status==='sending' ?
        'Still being accepted. Check again shortly.' : 'Delivery not confirmed. Checking uses the same request.') :
        state.gone ? 'This question is no longer pending in the session.' : state.message;
    };
    return node;
  }
  field(form, state, field, touch) {
    // DOM ids and radio group names are generated; raw field keys and form ids may contain spaces or anything else.
    const name='q'+(this.sequence=(this.sequence || 0)+1), labelId=name+'-label', hintId=name+'-hint';
    const error=el('p',{class:'q-error',role:'alert'});
    const hint=field.description ? formText('p',field,'description',{class:'q-hint',id:hintId}) : null;
    const head=el('div',{class:'q-label',id:labelId},formText('span',field,'label'),field.required ? null : el('small',{text:'optional'}));
    const control=this.control(state,field,name,{'aria-labelledby':labelId,'aria-describedby':hint ? hintId : null},touch);
    const node=el('div',{class:'q-field',data:{key:field.key,kind:field.kind}},
      head,hint,control.node,error);
    return {node,error,refresh:control.refresh};
  }
  control(state, field, name, aria, touch) {
    const c=field.constraints || {}, raw=state.raw, key=field.key;
    if(field.kind==='boolean') {
      const buttons=[[true,'Yes'],[false,'No']].map(([value,text])=>el('button',{type:'button',class:'q-seg',text,
        onclick:()=>{ if(state.pending) return; if(raw[key]===value) delete raw[key]; else raw[key]=value; touch(key); }}));
      const refresh=()=>buttons.forEach((button,index)=>button.setAttribute('aria-pressed',String(raw[key]===(index===0))));
      return {node:el('div',{class:'q-segs',role:'group',...aria},...buttons),refresh};
    }
    if(field.kind==='multiselect') return this.multiselect(state,field,name,aria,touch);
    if(field.kind==='string' && field.choices.length) {
      const radios=field.choices.map(choice=>({choice,input:el('input',{type:'radio',name,value:choice.value,checked:raw[key]===choice.value && !state.other[key],
        onchange:()=>{ state.other[key]=false; raw[key]=choice.value; touch(key); }})}));
      const rows=radios.map(({choice,input})=>el('label',{class:'q-opt'},input,formText('span',choice,'label')));
      let customRadio=null, customText=null;
      if(field.custom) {
        customRadio=el('input',{type:'radio',name,value:'',checked:!!state.other[key] && !!raw[key],
          onchange:()=>{
            state.other[key]=true;
            if(customText.value==='') delete raw[key]; else raw[key]=customText.value;
            touch(key); customText.focus?.();
          }});
        customText=el('input',{type:'text',class:'q-other',placeholder:'Something else…','aria-label':field.label+', other answer',autocomplete:'off',
          value:state.other[key] ? raw[key] || '' : '',
          oninput:()=>{
            state.other[key]=true; customRadio.checked=true;
            if(customText.value==='') delete raw[key]; else raw[key]=customText.value;
            touch(key);
          }});
        rows.push(el('label',{class:'q-opt'},customRadio,customText));
      }
      return {node:el('div',{class:'q-opts',role:'radiogroup',...aria},...rows),refresh:()=>{}};
    }
    const numeric=field.kind==='number' || field.kind==='integer';
    const type=numeric ? 'number' : c.format==='email' ? 'email' : c.format==='uri' ? 'url' : c.format==='date' ? 'date' : 'text';
    const long=field.kind==='string' && !c.format && !(c.maxLength<=200);  // free text gets room; short or formatted answers stay one line
    const input=el(long ? 'textarea' : 'input',{type:long ? null : type,class:'q-input',value:raw[key] ?? '',autocomplete:'off',
      placeholder:c.placeholder || null,maxLength:isNumber(c.maxLength) ? c.maxLength : null,rows:long ? 2 : null,...aria,
      inputmode:numeric ? (field.kind==='integer' ? 'numeric' : 'decimal') : null,
      step:numeric ? (field.kind==='integer' ? '1' : 'any') : null,min:isNumber(c.minimum) ? String(c.minimum) : null,max:isNumber(c.maximum) ? String(c.maximum) : null,
      oninput:()=>{ if(input.value==='') delete raw[key]; else raw[key]=input.value; touch(key); }});  // cleared = no answer; text is never trimmed
    return {node:input,refresh:()=>{}};
  }
  multiselect(state, field, name, aria, touch) {
    // No array yet means no answer; once the user ticks anything, an array (even after unticking everything) is an explicit answer.
    const raw=state.raw, key=field.key, selected=()=>Array.isArray(raw[key]) ? raw[key] : [];
    const boxes=new Map(field.choices.map(choice=>[choice.value,el('input',{type:'checkbox',name,value:choice.value,checked:selected().includes(choice.value),
      onchange:()=>{ const now=selected().filter(v=>v!==choice.value); if(boxes.get(choice.value).checked) now.push(choice.value); raw[key]=now; touch(key); }})]));
    const rows=field.choices.map(choice=>el('label',{class:'q-opt'},boxes.get(choice.value),formText('span',choice,'label')));
    const tokens=el('div',{class:'q-tokens'});
    let draft=null;
    const addCustom=()=>{
      const text=draft.value; if(!text.trim()) return;
      if(!selected().includes(text)) raw[key]=[...selected(),text];
      draft.value=''; touch(key);
    };
    if(field.custom) draft=el('input',{type:'text',class:'q-other',placeholder:'Add your own…','aria-label':field.label+', add another',autocomplete:'off',
      onkeydown:event=>{ if(event.key==='Enter') { event.preventDefault(); addCustom(); } }});
    const refresh=()=>{
      tokens.textContent='';
      for(const value of selected().filter(v=>!boxes.has(v))) {
        tokens.append(el('span',{class:'q-token'},el('span',{text:value}),el('button',{type:'button','aria-label':'Remove '+value,text:'×',
          onclick:()=>{ if(state.pending) return; raw[key]=selected().filter(v=>v!==value); touch(key); }})));
      }
      for(const [value,box] of boxes) box.checked=selected().includes(value);
    };
    const add=field.custom ? el('div',{class:'q-add'},draft,el('button',{type:'button',class:'quiet',text:'Add',onclick:addCustom})) : null;
    return {node:el('div',{class:'q-opts',role:'group',...aria},...rows,tokens,add),refresh};
  }

  /* --- delivery: one stable UUID per answer or cancel, checked with the very same payload --- */
  async submit(rootId, state, cancel) {
    if(state.pending || state.gone) return;
    let answer={};
    if(!cancel) {
      const result=readAnswers(state.form,state.raw);
      state.errors=result.errors;
      if(Object.keys(result.errors).length) { state.message='Check the highlighted answers.'; state.sync(); return; }
      answer=result.answer;
    }
    const payload={id:this.makeId(),target:rootId,form:state.form.id,answer,...(cancel ? {cancel:true} : {})};
    state.pending={payload,sending:false,status:''};
    await this.deliver(rootId,state);
  }
  async deliver(rootId, state) {
    const pending=state.pending; if(!pending || pending.sending) return;
    pending.sending=true; state.sync();
    try {
      const result=await this.api('/api/answer',pending.payload); pending.status=result.status;
      if(['applied','already_answered','no_longer_pending'].includes(result.status)) {
        this.rootData(rootId).states.delete(state.form.id); state.pending=null;
      }
      else if(result.status==='failed') { state.pending=null; state.message='Not accepted. Review your answer; the question may have changed.'; }
    } catch(error) { pending.status='unconfirmed'; }
    finally {
      pending.sending=false; state.sync();
      if(!state.pending && !this.rootData(rootId).states.has(state.form.id)) {
        const data=this.rootData(rootId); data.forms=data.forms.filter(form=>form.id!==state.form.id);
      }
      if(this.current()?.id===rootId) { this.render(); this.load(); }
    }
  }
}
