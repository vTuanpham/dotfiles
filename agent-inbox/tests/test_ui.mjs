import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = name => readFileSync(new URL('../src/agent_inbox/'+name, import.meta.url), 'utf8');
const scripts = ['kit.js', 'controls.js', 'context.js', 'forms.js', 'app.js'].map(name => [name, read(name)]);
const roots = [{id:'a',label:'First root',harness:'One'}, {id:'b',label:'Second root',harness:'Two'}];
const capabilities={queued_messages:true,mid_turn_steering:true,approvals_survive_restart:true,
  history_while_unloaded:true,images:true,interrupt:true,commands:true,questions:true,reply_mode:'direct'};
const withCapabilities=root=>({capabilities:{...capabilities},...root});
const tick = () => new Promise(resolve => setImmediate(resolve));
const modelControl = (current, values) => ({id:'model',label:'Model',kind:'select',current,description:'Next turns',
  choices:values.map(value => ({value,label:value.toUpperCase()}))});

class Element {
  constructor() {
    this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this.style = {};
    this.value = ''; this.hidden = false; this.disabled = false; this.className = '';
    this.classList = {toggle() {}}; this.parent = null; this.id = '';
  }
  set textContent(value) { for(const child of this.children) if(child && typeof child === 'object') child.parent = null; this.text = value; this.children = []; }
  get textContent() { return this.text; }
  append(...children) { for(const child of children) if(child && typeof child === 'object') child.parent = this; this.children.push(...children); }
  closest(selector) {  // like the DOM: ancestors as they are NOW, so a detached node no longer reaches its old container
    const ids = selector.split(',').map(part => part.trim().replace(/^#/, ''));
    for(let node = this; node; node = node.parent) if(node.id && ids.includes(node.id)) return node;
    return null;
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  focus() { Element.focused=this; }
}
function* walk(node) {
  yield node;
  for(const child of node.children || []) if(child && typeof child === 'object') yield* walk(child);
}
const find = (node, test) => [...walk(node)].find(test);
const findAll = (node, test) => [...walk(node)].filter(test);
const hasClass = (node, name) => node.className.split(' ').includes(name);
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };

async function boot(options={}) {
  const view = options.view;
  const elements = new Map();
  const element = id => {
    if(!elements.has(id)) { const created = new Element(); created.id = id; elements.set(id, created); }
    return elements.get(id);
  };
  const requests = [], commandRequests = [], answerRequests = [], paths = [], timers = [], readers = [], contextCalls = [], fetches=[];
  let liveRoots = (options.roots || roots).map(withCapabilities);
  const document = {
    hidden:false, body:{scrollHeight:0}, documentElement:new Element(), getElementById:element,
    createElement:() => new Element(), querySelector:() => element('compose-label'),
    handlers:{}, addEventListener(name, handler) { (document.handlers[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document, window:{innerHeight:844,scrollY:0,scrollTo() {}}, crypto:webcrypto,
    localStorage:options.storage || {getItem:()=>null,setItem() {}},
    setInterval(handler, delay) { timers.push({handler,delay}); },
    setTimeout() {},
    FileReader:class {
      readAsDataURL(file) { this.result=file.data; readers.push(this); }
    },
    fetch:async (path, request) => {
      paths.push(path);
      fetches.push({path,request});
      const response = (data, status=200) => ({status,ok:status===200,json:async () => data});
      const id = new URL(path, 'http://localhost').searchParams.get('id');
      if(path === '/api/roots') return response({roots:liveRoots});
      if(path === '/api/pair') return response({device:'fixture'});
      if(path.startsWith('/api/view')) {
        if(view) return response(view(path));
        return response({status:'idle',can_send:true,older_cursor:null,native_url:null,
          messages:[{id,role:'assistant',text:'Reply from '+id}]});
      }
      if(path.startsWith('/api/commands')) {
        const result = options.commands ? await options.commands(id) : {controls:[],unavailable:'No native commands.'};
        return response(result);
      }
      if(path === '/api/command') {
        return new Promise((resolve,reject) => {
          commandRequests.push({data:JSON.parse(request.body),reject,finish:status => resolve(response({status}))});
        });
      }
      if(path.startsWith('/api/forms')) return response(options.forms ? await options.forms(id) : {forms:[],unavailable:'none'});
      if(path === '/api/answer') {
        return new Promise((resolve,reject) => {
          answerRequests.push({data:JSON.parse(request.body),reject,finish:status => resolve(response({status}))});
        });
      }
      if(path.startsWith('/api/context')) {
        contextCalls.push(id);
        return response(await (options.context ? options.context(id) : {error:'none'}), options.context ? 200 : 404);
      }
      if(path === '/api/send') {
        return new Promise((resolve,reject) => {
          requests.push({data:JSON.parse(request.body),reject,
            finish:status => resolve(response({status}))});
        });
      }
      throw new Error('Unexpected request: '+path);
    },
  });
  for(const [name, source] of scripts) new vm.Script(source, {filename:name}).runInContext(context);
  await tick();
  const ui = {
    element, document, focused:() => Element.focused, requests, commandRequests, answerRequests, paths, readers, contextCalls, fetches, run:code => vm.runInContext(code, context),
    addFiles(files) { return element('image-file').listeners.change({target:{files,value:'images'}}); },
    // A browser-like click: the propagation path is fixed at dispatch, the target's own handler may re-render (detaching it),
    // and only afterwards do ancestors and `document` see the event.
    click(node) {
      const path = []; for(let at = node; at; at = at.parent) path.push(at);
      const event = {target:node, composedPath:() => path.slice()};
      for(const at of path) at.listeners.click?.(event);
      for(const handler of document.handlers.click || []) handler(event);
    },
    async choose(index) { element('roots').children[index].listeners.click(); await tick(); },
    type(text) { element('message').value=text; element('message').listeners.input(); },
    submit() { return element('compose').listeners.submit({preventDefault() {}}); },
    // Chips are buttons: `value` is the shown native label lower-cased (fixtures use label = value.toUpperCase()), `disabled` is aria-disabled.
    chips() { return element('command-chips').children.map(chip => ({node:chip,value:chip.children[1].text.toLowerCase(),disabled:chip.attributes['aria-disabled']==='true'})); },
    // Choosing a value is a real interaction: open the chip's menu, then press the option carrying that exact native value.
    async pick(index, value) {
      ui.chips()[index].node.listeners.click();
      const option=findAll(element('command-menu'),node=>node.attributes.role==='option').find(node=>textOf(node).includes(value));
      option.listeners.click(); await tick();
    },
    async refresh(nextRoots) {
      liveRoots=nextRoots.map(withCapabilities);
      timers.find(timer=>timer.delay===10000).handler(); await tick();
      timers.find(timer=>timer.delay===4000).handler(); await tick();
    },
    async poll() { timers.find(timer=>timer.delay===4000).handler(); await tick(); },
    messages() { return element('messages').children; },
    bodyOf(node) { return find(node, child => hasClass(child, 'body')); },
  };
  return ui;
}

test('capabilities hide unavailable controls without guessing from harness names', async () => {
  const ui=await boot({roots:[{...roots[0],harness:'Codex',capabilities:{...capabilities,
    images:false,interrupt:false,commands:false,questions:false,mid_turn_steering:false}}]});
  assert.equal(ui.element('attach').hidden,true);
  assert.equal(ui.element('image-file').disabled,true);
  assert.equal(ui.element('steer').hidden,true);
  assert.equal(ui.element('command-menu-button').hidden,true);
  assert.equal(ui.paths.some(path=>path.startsWith('/api/commands') || path.startsWith('/api/forms')),false);
  const missing={...capabilities}; delete missing.images;
  assert.throws(()=>ui.run('decodeRoots')({roots:[{...roots[0],capabilities:missing}]}),/recognized format/);
});

test('active turns steer by default and an explicit queue choice stays with that root', async () => {
  const ui=await boot({view:()=>({status:'active',can_send:true,messages:[]})});
  assert.equal(ui.element('steer').hidden,false);
  assert.equal(ui.element('steer').attributes['aria-pressed'],'true');
  assert.equal(ui.element('send').attributes['aria-label'],'Steer current turn');
  ui.type('Steer me');
  let sending=ui.submit(); await tick();
  assert.equal(ui.requests[0].data.delivery,'steer');
  ui.requests[0].finish('steered'); await sending;
  assert.equal(ui.element('steer').attributes['aria-pressed'],'true');
  ui.element('steer').listeners.click();
  assert.equal(ui.element('steer').attributes['aria-pressed'],'false');
  ui.type('Queue me'); sending=ui.submit(); await tick();
  assert.equal(ui.requests[1].data.delivery,'queue');
  ui.requests[1].finish('queued'); await sending;
  assert.equal(ui.element('steer').attributes['aria-pressed'],'false');
  await ui.choose(1);
  assert.equal(ui.element('steer').attributes['aria-pressed'],'true');
  await ui.choose(0);
  assert.equal(ui.element('steer').attributes['aria-pressed'],'false');
});

test('idle roots and harnesses without steering use their supported queue path', async () => {
  const idle=await boot({view:()=>({status:'idle',can_send:true,messages:[]})});
  idle.type('Start a turn');
  let sending=idle.submit(); await tick();
  assert.equal(idle.requests[0].data.delivery,'queue');
  assert.equal(idle.element('send').attributes['aria-label'],'Send');
  idle.requests[0].finish('queued'); await sending;
  const unsupported=await boot({roots:[{...roots[0],capabilities:{...capabilities,mid_turn_steering:false}}],
    view:()=>({status:'active',can_send:true,messages:[]})});
  unsupported.type('Next turn');
  sending=unsupported.submit(); await tick();
  assert.equal(unsupported.requests[0].data.delivery,'queue');
  assert.equal(unsupported.element('steer').hidden,true);
  assert.equal(unsupported.element('send').attributes['aria-label'],'Queue message');
  unsupported.requests[0].finish('queued'); await sending;
});

test('pairing and authenticated requests refuse redirects and keep credentials on their origin', async () => {
  const ui=await boot();
  ui.element('pair-code').value='FIXTURE';
  await ui.element('pair-form').listeners.submit({preventDefault(){}});
  const pairing=ui.fetches.find(call=>call.path==='/api/pair');
  assert.ok(pairing);
  assert.equal(pairing.path.includes('FIXTURE'),false);
  assert.equal(JSON.parse(pairing.request.body).code,'FIXTURE');
  for(const {request} of ui.fetches) {
    assert.equal(request.redirect,'error');
    assert.equal(request.mode,'same-origin');
    assert.equal(request.credentials,'same-origin');
  }
});

test('theme follows system by default and cycles through persistent night and day choices', async () => {
  const saved=[];
  const storage={getItem:()=>null,setItem:(key,value)=>saved.push([key,value])};
  const ui=await boot({storage});
  assert.equal(ui.run('document.documentElement.dataset.theme'),'system');
  ui.element('theme-toggle').listeners.click();
  assert.equal(ui.run('document.documentElement.dataset.theme'),'dark');
  assert.equal(ui.element('theme-toggle').getAttribute('aria-label'),'Theme: dark');
  ui.element('theme-toggle').listeners.click();
  assert.equal(ui.run('document.documentElement.dataset.theme'),'light');
  assert.deepEqual(saved,[['agent-inbox-theme','dark'],['agent-inbox-theme','light']]);
  const returning=await boot({storage:{getItem:()=>saved.at(-1)[1],setItem() {}}});
  assert.equal(returning.run('document.documentElement.dataset.theme'),'light');
  const restricted=await boot({storage:{getItem() {throw new Error('blocked');},setItem() {throw new Error('blocked');}}});
  restricted.element('theme-toggle').listeners.click();
  assert.equal(restricted.run('document.documentElement.dataset.theme'),'dark');
});

test('saved history stays separate and search reaches both groups without changing the selected root', async () => {
  const ui=await boot();
  await ui.refresh([{id:'a',label:'Current work',harness:'One',status:'active'},
                    {id:'b',label:'Older task',harness:'Two',status:'idle',saved:true}]);
  assert.equal(ui.element('roots').children.length,1);
  assert.equal(ui.element('saved-roots').children.length,1);
  assert.equal(ui.element('saved-count').textContent,'Saved conversations · 1');
  assert.equal(ui.element('saved-sessions').hidden,false);
  ui.element('session-search').value='older'; ui.element('session-search').listeners.input();
  assert.equal(ui.element('roots').children.length,0);
  assert.equal(ui.element('saved-sessions').open,true);
  assert.equal(ui.run('selected.id'),'a');
  ui.element('saved-roots').children[0].listeners.click(); await tick();
  assert.equal(ui.run('selected.id'),'b');
  assert.equal(ui.element('message').disabled,false);
});

test('native controls refresh when a session starts a turn so stop is available without switching roots', async () => {
  let busy=false;
  const ui=await boot({view:()=>({status:busy?'active':'idle',can_send:true,messages:[],older_cursor:null}),
    commands:()=>({controls:busy?[{id:'interrupt',label:'Stop turn',kind:'action',choices:null,current:null,description:''}]:[],unavailable:''})});
  assert.equal(ui.run('commandPanel.controls.length'),0);
  busy=true; await ui.poll(); await tick();
  assert.equal(ui.run('commandPanel.controls[0].id'),'interrupt');
  busy=false; await ui.poll(); await tick();
  assert.equal(ui.run('commandPanel.controls.length'),0);
});

test('an offline root keeps receipt checks available without enabling a new message', async () => {
  const ui=await boot(); ui.type('Original input');
  const sending=ui.submit(); await tick();
  ui.requests[0].finish('unknown'); await sending;
  await ui.refresh([]);
  assert.equal(ui.element('message').disabled,true);
  assert.equal(ui.element('send').disabled,true);
  assert.equal(ui.element('check').disabled,false);
  const checking=ui.element('check').listeners.click(); await tick();
  assert.deepEqual(ui.requests[1].data,ui.requests[0].data);
  ui.requests[1].finish('unknown'); await checking;
  ui.element('resolve').listeners.click();
  assert.equal(ui.run('composeState().pending'),null);
  assert.equal(ui.element('send').disabled,true);
});

test('ambiguous retries keep their ID across root switches and cannot unlock another send', async () => {
  const ui = await boot();
  ui.type('message A');
  const first = ui.submit();
  await tick();
  await ui.choose(1);
  ui.type('message B');
  const second = ui.submit();
  await tick();
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.requests[0].data.target, 'a');
  assert.equal(ui.requests[1].data.target, 'b');
  ui.requests[0].reject(new Error('Response lost'));
  await first;
  assert.equal(ui.element('send').disabled, true);
  assert.equal(ui.element('message').value, 'message B');
  ui.requests[1].finish('queued');
  await second;
  await ui.choose(0);
  assert.equal(ui.element('message').value, 'message A');
  assert.match(ui.element('delivery').textContent, /same message ID/);
  const retry = ui.submit();
  await tick();
  assert.deepEqual(ui.requests[2].data, ui.requests[0].data);
  ui.requests[2].finish('queued');
  await retry;
  assert.equal(ui.element('message').value, '');
});

test('a queued reply does not erase a newer draft typed while sending', async () => {
  const ui = await boot();
  ui.type('first message');
  const sending = ui.submit();
  await tick();
  ui.type('new unsent draft');
  ui.requests[0].finish('queued');
  await sending;
  assert.equal(ui.element('message').value, 'new unsent draft');
  await ui.choose(1);
  await ui.choose(0);
  assert.equal(ui.element('message').value, 'new unsent draft');
});

test('confirmed steering clears only its own draft and displays a steering receipt', async () => {
  const ui = await boot();
  ui.type('Steer this task');
  const sending = ui.submit();
  await tick();
  ui.requests[0].finish('steered');
  await sending;
  assert.equal(ui.element('message').value, '');
  assert.equal(ui.element('delivery').textContent, 'Accepted for steering at the native turn boundary.');
});

test('a forwarded message is labelled as not natively confirmed and is not resent', async () => {
  const ui = await boot();
  ui.type('Hello channel');
  const sending = ui.submit();
  await tick();
  ui.requests[0].finish('forwarded');
  await sending;
  assert.match(ui.element('delivery').textContent, /not confirmed receipt/);
  assert.equal(ui.element('message').value, '');
  assert.equal(ui.element('check').hidden, true);
  assert.equal(ui.requests.length, 1);
});

test('disconnected roots disappear and reappear without losing pending retries or rerouting', async () => {
  const ui = await boot();
  ui.type('First root draft');
  const sending = ui.submit();
  await tick();
  ui.requests[0].reject(new Error('Connection lost'));
  await sending;
  await ui.refresh([roots[1]]);
  assert.equal(ui.element('roots').children.length, 1);
  assert.equal(ui.element('state').textContent, 'Offline');
  assert.equal(ui.element('send').disabled, true);
  assert.equal(ui.element('root-title').textContent, 'First root');
  assert.equal(ui.element('message').value, 'First root draft');
  await ui.refresh(roots);
  assert.equal(ui.element('roots').children.length, 2);
  assert.equal(ui.element('send').disabled, false);
  const retry = ui.submit();
  await tick();
  assert.deepEqual(ui.requests[1].data, ui.requests[0].data);
  ui.requests[1].finish('steered');
  await retry;
});

test('polling catches up from its native cursor and older history cannot overwrite that position', async () => {
  const ui = await boot({view:path=>{
    const query=new URL(path,'http://localhost').searchParams;
    const message=(id,text,phase=null)=>({id,role:'assistant',text,phase});
    if(query.has('cursor')) return {status:'idle',can_send:true,older_cursor:null,
      newer_cursor:'old-position',messages:[message('old','Earlier history')]};
    if(query.has('since')) return {status:'idle',can_send:true,older_cursor:null,
      newer_cursor:'tail',messages:[message('update','Work update','commentary'),message('new','New response')]};
    return {status:'idle',can_send:true,older_cursor:'past',newer_cursor:'start',
      messages:[message('initial','Original response')]};
  }});
  await ui.poll();
  assert.match(ui.paths.at(-1), /since=start/);
  await ui.element('older').listeners.click();
  await ui.poll();
  assert.match(ui.paths.at(-1), /since=tail/);
  const bubbles=ui.messages();
  assert.deepEqual(bubbles.map(b=>ui.bodyOf(b).textContent),
    ['Earlier history','Original response','Work update','New response']);
  const marks=bubbles.map(b=>!!find(b,node=>node.dataset.brand));
  assert.deepEqual(marks, [true,false,false,false], 'only the first message of a run carries the harness mark');
  assert.equal(hasClass(bubbles[2],'progress'), true);
});

test('structured question replies show human answers instead of the transport envelope', async () => {
  const ui = await boot({view:()=>({status:'idle',can_send:true,older_cursor:null,
    messages:[{id:'answer',role:'user',text:'unused transport text',
      answers:[{question:'Which cleanup?',answer:'Inbox only'}]}]})});
  const bubble=ui.messages()[0];
  assert.equal(hasClass(bubble,'answer'), true);
  assert.deepEqual(ui.bodyOf(bubble).children.map(p=>p.textContent), ['Which cleanup?','Inbox only']);
});

test('structured replies use shared server-rendered links when available', async () => {
  const html='<p class="answer-choice"><a href="https://example.test:18000/" target="_blank" rel="noopener noreferrer">Open preview</a></p>';
  const ui=await boot({view:()=>({status:'idle',can_send:true,older_cursor:null,
    messages:[{id:'answer',role:'user',text:'transport',html,answers:[{question:'Open?',answer:'Yes'}]}]})});
  assert.equal(ui.bodyOf(ui.messages()[0]).innerHTML,html);
  assert.equal(hasClass(ui.bodyOf(ui.messages()[0]),'markdown'),true);
});

test('image imports stay bound to their root and image-only messages can be sent', async () => {
  const ui=await boot();
  const data='data:image/png;base64,fixture';
  const importing=ui.addFiles([{type:'image/png',size:20,data}]);
  assert.equal(ui.element('send').disabled,true);
  const overlap=ui.addFiles([{type:'image/png',size:20,data:'ignored'}]);
  await overlap;
  assert.equal(ui.readers.length,1);
  await ui.choose(1);
  ui.readers[0].onload(); await importing;
  assert.equal(ui.element('attachments').children.length,0);
  await ui.choose(0);
  assert.equal(ui.element('attachments').children.length,1);
  const thumb=ui.element('attachments').children[0];
  assert.equal(find(thumb,node=>node.src===data)!==undefined,true);
  assert.equal(find(thumb,node=>node.attributes['aria-label']==='Remove image 1')!==undefined,true);
  const sending=ui.submit(); await tick();
  assert.equal(ui.requests[0].data.target,'a');
  assert.equal(ui.requests[0].data.text,'');
  assert.deepEqual(ui.requests[0].data.images,[data]);
  ui.requests[0].finish('steered'); await sending;
  assert.equal(ui.element('attachments').children.length,0);
});

test('bad image selection is rejected without reading it', async () => {
  const ui=await boot();
  await ui.addFiles([{type:'text/html',size:10,data:'bad'}]);
  assert.match(ui.element('delivery').textContent,/PNG, JPEG/);
  await ui.addFiles([{type:'image/png',size:9*1024*1024,data:'too big'}]);
  assert.match(ui.element('delivery').textContent,/8 MiB/);
  assert.equal(ui.readers.length,0);
});

test('uncertain deliveries cannot be replaced or cleared while the server is still sending', async () => {
  const ui=await boot(); ui.type('Original');
  const sending=ui.submit(); await tick(); ui.requests[0].reject(new Error('Response lost')); await sending;
  assert.equal(ui.element('resolve').hidden,true);
  ui.type('New draft'); await ui.submit();
  assert.equal(ui.requests.length,1);
  const checking=ui.element('check').listeners.click(); await tick();
  assert.deepEqual(ui.requests[1].data,ui.requests[0].data);
  ui.requests[1].finish('sending'); await checking;
  assert.equal(ui.element('resolve').hidden,true);
  const checkingAgain=ui.element('check').listeners.click(); await tick();
  ui.requests[2].finish('unknown'); await checkingAgain;
  assert.equal(ui.element('resolve').hidden,false);
  assert.equal(ui.element('message').value,'New draft');
  await ui.refresh([roots[1]]);
  assert.equal(ui.element('resolve').disabled,false);
  assert.equal(ui.element('send').disabled,true);
});

test('new progress retains existing inline image elements', async () => {
  let polls=0;
  const ui=await boot({view:()=>({status:'active',can_send:true,messages:[
    {id:'image',role:'assistant',text:'',images:['/api/image?id=fixture']},
    {id:'progress',role:'assistant',text:'Progress '+polls++,phase:'commentary'},
  ]})});
  const imageIn=() => find(ui.messages()[0],node=>node.src==='/api/image?id=fixture');
  const image=imageIn();
  assert.ok(image);
  await ui.poll();
  assert.equal(imageIn(),image);
});

const textOf = node => typeof node === 'string' ? node : [node.text ?? '', ...(node.children || []).map(textOf)].join('');
const stream = ui => ui.messages().map(node => node.dataset.messageId || node.dataset.blockId || (hasClass(node,'live') ? 'live' : '?'));
const activity = (id, label, status, duration_ms=null) => ({id:'activity:'+id,label,status,duration_ms,started_at_ms:null});

test('activity sits inline in the native timeline, folds finished steps and keeps live ones visible', async () => {
  let view={status:'active',can_send:true,older_cursor:null,
    messages:[{id:'m1',role:'user',text:'run it'},{id:'m2',role:'assistant',text:'Running now'}],
    activity:[activity('a1','pytest','completed',900),activity('a2','pytest','completed',700),activity('a3','git diff','running')],
    timeline:['m1','activity:a1','activity:a2','activity:a3','m2']};
  const ui=await boot({view:()=>view});
  assert.deepEqual(stream(ui),['m1','activity:a1','m2','live'], 'finished and live steps are one block between the two messages');
  const block=ui.messages()[1];
  assert.equal(hasClass(find(block,n=>hasClass(n,'summary')),'step'),true);
  assert.match(textOf(find(block,n=>hasClass(n,'summary'))),/pytest ×2/);
  assert.match(textOf(find(block,n=>n.dataset.status==='running')),/git diff/);
  assert.equal(findAll(block,n=>hasClass(n,'step-list')).length,0, 'finished steps start folded');
  find(block,n=>hasClass(n,'summary')).listeners.click();
  assert.equal(findAll(ui.messages()[1],n=>hasClass(n,'step-list')).length,1, 'expanding is on demand');
  assert.match(textOf(find(ui.messages().at(-1),n=>hasClass(n,'step'))),/Working…/);
  view={...view,status:'idle'}; await ui.poll();
  assert.deepEqual(stream(ui),['m1','activity:a1','m2'], 'an idle session shows no live row');
  assert.equal(findAll(ui.element('messages'),n=>n.dataset.status==='running').length,0, 'a stale running row never keeps spinning');
  view={...view,status:'input-needed'}; await ui.poll();
  assert.match(textOf(ui.messages().at(-1)),/Needs your input/);
});

test('older pages and forward catch-up merge into one chronological stream without sorting', async () => {
  const msg = (id, role='assistant') => ({id,role,text:id});
  const ui=await boot({view:path=>{
    const query=new URL(path,'http://localhost').searchParams;
    if(query.has('cursor')) return {status:'idle',can_send:true,older_cursor:null,newer_cursor:'x',messages:[msg('m0','user')],
      activity:[activity('a0','ls','completed')],timeline:['m0','activity:a0']};
    if(query.get('since')==='n1') return {status:'idle',can_send:true,older_cursor:null,newer_cursor:'n2',messages:[msg('m3')],
      activity:[activity('a2','make','completed')],timeline:['m2','activity:a2','m3']};
    if(query.get('since')==='n2') return {status:'idle',can_send:true,older_cursor:null,newer_cursor:'n3',messages:[msg('m9')],
      activity:[],timeline:['m9']};
    return {status:'idle',can_send:true,older_cursor:'past',newer_cursor:'n1',messages:[msg('m1','user'),msg('m2')],
      activity:[activity('a1','pytest','completed')],timeline:['m1','activity:a1','m2']};
  }});
  assert.deepEqual(stream(ui),['m1','activity:a1','m2']);
  await ui.element('older').listeners.click();
  assert.deepEqual(stream(ui),['m0','activity:a0','m1','activity:a1','m2'], 'older ids go before the current order');
  await ui.poll();
  assert.deepEqual(stream(ui),['m0','activity:a0','m1','activity:a1','m2','activity:a2','m3'], 'forward ids follow the anchor they share');
  await ui.poll();
  assert.deepEqual(stream(ui).at(-1),'m9','ids with no known anchor are appended');
});

const slashFixture = id => ({controls:id==='a' ? [modelControl('m1',['m1','m2']),
  {id:'rename',label:'Rename',kind:'text',choices:null,current:null,description:'Session title'},
  {id:'compact',label:'Compact',kind:'action',choices:null,current:null,description:''}] : [],unavailable:'Nothing here.'});
const press = (ui, key) => { const event={key,prevented:false,preventDefault() { this.prevented=true; }}; ui.element('message').listeners.keydown(event); return event; };
const options = ui => findAll(ui.element('command-menu'),node=>node.attributes.role==='option');

test('typing / opens the command menu in the composer with native current values', async () => {
  const ui=await boot({commands:slashFixture});
  assert.equal(ui.element('command-menu').hidden,true);
  ui.type('/');
  assert.equal(ui.element('command-menu').hidden,false);
  const rows=options(ui).map(textOf);
  assert.equal(rows.length,3);
  assert.match(rows[0],/^Model\/modelM1/, 'a select shows its native current value');
  assert.match(rows[1],/^Rename\/rename/);
  assert.match(rows[2],/^Compact\/compact/);
  ui.type('/com');
  assert.equal(options(ui).length,1);
  ui.type('/zzz');
  assert.equal(options(ui).length,0);
  assert.match(textOf(ui.element('command-menu')),/No matching native command/);
  ui.type('hello');
  assert.equal(ui.element('command-menu').hidden,true,'normal text closes the menu');
  assert.equal(ui.requests.length+ui.commandRequests.length,0);
});

test('/model opens the real native picker and Enter applies the exact native value, not chat text', async () => {
  const ui=await boot({commands:slashFixture});
  ui.type('/mod');
  assert.equal(press(ui,'Enter').prevented,true);
  assert.equal(ui.element('message').value,'/model ', 'picking a command continues in the composer');
  assert.equal(options(ui).length,2);
  assert.equal(options(ui)[0].attributes['aria-selected'],'true','the current native value is the selected option');
  assert.equal(findAll(options(ui)[0],n=>hasClass(n,'menu-check')).length,1, 'and carries a check');
  assert.equal(findAll(options(ui)[1],n=>hasClass(n,'menu-check')).length,0);
  press(ui,'ArrowDown'); press(ui,'Enter'); await tick();
  assert.equal(ui.commandRequests.length,1);
  assert.deepEqual([ui.commandRequests[0].data.command,ui.commandRequests[0].data.value],['model','m2']);
  assert.equal(ui.element('message').value,'', 'the consumed slash text leaves no draft');
  assert.equal(ui.element('command-menu').hidden,true);
  assert.equal(ui.requests.length,0);
});

test('slash menu keys: Escape closes without losing text, filters narrow the picker, text and actions run natively', async () => {
  const ui=await boot({commands:slashFixture});
  ui.type('/'); press(ui,'Escape');
  assert.equal(ui.element('command-menu').hidden,true);
  assert.equal(ui.element('message').value,'/');
  ui.type('/model 2');
  assert.equal(options(ui).length,1, 'text after the command filters native choices');
  ui.type('/rename Fresh title');
  assert.match(textOf(ui.element('command-menu')),/Fresh title/);
  press(ui,'Enter'); await tick();
  assert.deepEqual([ui.commandRequests[0].data.command,ui.commandRequests[0].data.value],['rename','Fresh title']);
  ui.commandRequests[0].finish('applied'); await tick();
  ui.type('/compact'); press(ui,'Enter'); await tick();
  assert.deepEqual([ui.commandRequests[1].data.command,ui.commandRequests[1].data.value],['compact','']);
  ui.commandRequests[1].finish('unknown'); await tick();
  assert.match(ui.element('command-status').textContent,/unconfirmed/);
});

test('a root without native commands says so in the menu and never sends the slash as chat', async () => {
  const ui=await boot({commands:slashFixture});
  await ui.choose(1);
  ui.type('/');
  assert.match(textOf(ui.element('command-menu')),/Nothing here/);
  await ui.submit();
  assert.equal(ui.requests.length,0);
});

const commandFixture = id => ({controls:id==='a'
  ? [modelControl('m1',['m1','m2']),{id:'compact',label:'Compact',kind:'action',description:''}]
  : [modelControl('m3',['m3','m4'])],unavailable:''});

test('native selects live in the composer and a late result cannot touch another root', async () => {
  const ui=await boot({commands:commandFixture});
  assert.equal(ui.chips().length,1);
  assert.equal(ui.chips()[0].value,'m1');
  await ui.pick(0,'m2');
  assert.deepEqual(ui.commandRequests[0].data.command,'model');
  assert.equal(ui.commandRequests[0].data.value,'m2');
  assert.equal(ui.commandRequests[0].data.target,'a');
  assert.equal(ui.chips()[0].disabled,true);
  await ui.choose(1);
  assert.equal(ui.chips()[0].value,'m3');
  assert.equal(ui.chips()[0].disabled,false, 'a pending command on root a does not lock root b');
  ui.commandRequests[0].finish('applied'); await tick();
  assert.equal(ui.chips()[0].value,'m3');
  assert.equal(ui.element('command-notice').hidden,true);
  assert.equal(ui.element('root-title').textContent,'Second root');
});

test('an unknown command result keeps one UUID, locks the controls and never runs twice on its own', async () => {
  const ui=await boot({commands:commandFixture});
  await ui.pick(0,'m2');
  ui.commandRequests[0].finish('unknown'); await tick();
  assert.match(ui.element('command-status').textContent,/unconfirmed/);
  assert.equal(ui.chips()[0].disabled,true);
  assert.equal(ui.chips()[0].value,'m2','the chip shows the requested value, not a guess that it applied');
  assert.equal(ui.element('command-clear').hidden,false);
  ui.chips()[0].node.listeners.click();
  assert.equal(ui.element('command-menu').hidden,true,'a locked chip does not open its picker');
  assert.equal(ui.commandRequests.length,1, 'a second choice cannot start while the first is unconfirmed');
  ui.element('command-check').listeners.click(); await tick();
  assert.deepEqual(ui.commandRequests[1].data,ui.commandRequests[0].data);
  ui.commandRequests[1].finish('unknown'); await tick();
  await ui.element('command-clear').listeners.click(); await tick();
  assert.equal(ui.chips()[0].disabled,false);
  await ui.pick(0,'m1');
  assert.notEqual(ui.commandRequests[2].data.id,ui.commandRequests[0].data.id);
});

test('a slow command list for a previous root is ignored', async () => {
  const slow=deferred();
  const ui=await boot({commands:id=>id==='a' ? slow.promise : commandFixture(id)});
  await ui.choose(1);
  assert.equal(ui.chips()[0].value,'m3');
  slow.resolve(commandFixture('a')); await tick();
  assert.equal(ui.chips()[0].value,'m3');
  assert.equal(ui.chips().length,1);
});

test('a leading slash command is never sent as chat and only exact native values apply', async () => {
  const ui=await boot({commands:commandFixture});
  ui.type('/nosuch'); await ui.submit();
  assert.equal(ui.requests.length,0);
  assert.match(ui.element('command-status').textContent,/not exposed/);
  assert.equal(ui.element('message').value,'/nosuch','an unhandled command keeps the draft');
  ui.type('/model M2'); await ui.submit();
  assert.equal(ui.commandRequests.length,0,'a label is not a native value');
  ui.type('/model m2'); await ui.submit(); await tick();
  assert.equal(ui.requests.length,0);
  assert.equal(ui.commandRequests[0].data.value,'m2');
  assert.equal(ui.element('message').value,'');
  ui.commandRequests[0].finish('applied'); await tick();
});

test('session details keep the account scope and never invent a capped usage reading', async () => {
  const sample={account:{identity:'acct-1',email:'user@example.test',plan:'Plus',scope:'connection'},
    quotas:[{label:'Primary',used_percent:120,window_minutes:300,resets_at:null}],
    metrics:[{label:'Tokens',value:1200,unit:'tokens'}],workers:[{id:'w',label:'Reviewer',status:'running',model:null}],
    tools:[],notices:[],fetched_at:1700000000};
  const ui=await boot({context:()=>sample});
  await ui.element('details-toggle').listeners.click(); await tick();
  const body=ui.element('details-body');
  assert.ok(findAll(body,node=>node.text==='user@example.test').length);
  assert.match(findAll(body,node=>hasClass(node,'muted')&&/current connection/.test(node.text||''))[0].text,/may differ/);
  const meter=find(body,node=>node.attributes.role==='meter');
  assert.equal(meter.attributes['aria-valuenow'],'100');
  assert.match(meter.attributes['aria-valuetext'],/120% used, over limit/);
  assert.equal(findAll(body,node=>node.text==='120% used · over limit').length,1);
});

test('reset times round once and never show 60 minutes', async () => {
  const ui = await boot();
  const label = minutes => ui.run('resetLabel')(Date.now()/1000+minutes*60-1,Date.now()-1).replace(/^.*in /,'');
  assert.equal(label(59.6),'1 h');
  assert.equal(label(70),'1 h 10 m');
  assert.equal(label(60*24+29.7),'1 d');
  assert.equal(label(2*1440+125),'2 d 2 h');
  assert.equal(label(0.2),'1 m');
});

test('late session details for a previous root are dropped and malformed details are refused', async () => {
  const late=deferred();
  const ui=await boot({context:id=>id==='a' ? late.promise : {account:null,quotas:[],metrics:[],workers:[],tools:[],notices:[],fetched_at:1}});
  await ui.element('details-toggle').listeners.click(); await tick();
  await ui.choose(1);
  late.resolve({account:{identity:null,email:'first@example.test',plan:null,scope:'connection'},quotas:[],metrics:[],workers:[],tools:[],notices:[],fetched_at:1});
  await tick();
  assert.equal(findAll(ui.element('details-body'),node=>node.text==='first@example.test').length,0);
  assert.throws(()=>ui.run('decodeContext')({account:null,quotas:[{label:'x',used_percent:'50',window_minutes:null,resets_at:null}],
    metrics:[],workers:[],tools:[],notices:[],fetched_at:1}),/recognized format/);
});

/* --- native question forms --- */
const field = (key, kind, extra={}) => ({key,label:key,kind,required:false,hidden:false,choices:[],custom:false,default:null,when:[],constraints:null,description:'',...extra});
const choices = (...values) => values.map(value => ({value,label:value.toUpperCase()}));
const json = value => JSON.parse(JSON.stringify(value));

test('question answers follow earlier answers: omitted when inactive, false and zero are real answers, blanks are not zero', async () => {
  const ui = await boot();
  const form = {id:'f',title:'t',unavailable:'',fields:[
    field('pick','string',{required:true,choices:choices('a','b')}),
    field('why','string',{required:true,when:[{key:'pick',op:'eq',value:'b'}]}),
    field('quiet','boolean',{when:[{key:'pick',op:'neq',value:'b'}]}),
    field('flag','boolean',{required:true}),
    field('count','integer'),
    field('ratio','number'),
    field('tags','multiselect',{choices:choices('x','y'),custom:true}),
    field('followup','string',{when:[{key:'tags',op:'eq',value:'x'}]}),
    field('ghost','string',{when:[{key:'missing',op:'neq',value:'z'}]}),
  ]};
  const read = raw => json(ui.run('readAnswers')(form,raw));
  let result = read({pick:'a',flag:false,count:'0',tags:['x','mine'],followup:'yes',why:'ignored'});
  assert.deepEqual(result.answer,{pick:'a',flag:false,count:0,tags:['x','mine'],followup:'yes'});
  assert.deepEqual(result.errors,{}, 'an unanswered optional number is skipped, inactive "why" is not required, missing reference never matches neq');
  result = read({pick:'b',flag:true,tags:[],followup:'dropped'});
  assert.deepEqual(result.errors,{why:'An answer is required.'});
  assert.equal('quiet' in result.answer,false);
  result = read({pick:'a'});
  assert.deepEqual(result.errors,{flag:'An answer is required.'}, 'required booleans need an explicit answer, but false counts');
  result = read({pick:'a',flag:true,count:'1.5',ratio:'1e2'});
  assert.deepEqual(result.errors,{count:'Enter a whole number.'});
  assert.equal(read({pick:'a',flag:true,ratio:'1e2'}).answer.ratio,100);
  assert.equal(read({pick:'a',flag:true,ratio:'0x10'}).errors.ratio,'Enter a number.');
  assert.throws(()=>ui.run('decodeForms')({forms:[{id:'f',title:'t',unavailable:'',fields:[{...field('k','color')}]}],unavailable:''}),/recognized format/);
});

const pickForm = {id:'f1',title:'Which cleanup should run?',unavailable:'',fields:[
  field('scope','string',{required:true,choices:choices('inbox','all'),custom:true}),
  field('why','string',{when:[{key:'scope',op:'eq',value:'all'}]}),
  field('sure','boolean',{required:true,default:false}),
]};
const formUi = ui => {
  const card = () => ui.element('forms').children[0];
  return {card,
    key:key => find(card(),node=>node.dataset.key===key),
    radios:() => findAll(card(),node=>node.type==='radio'),
    button:text => find(card(),node=>node.text===text),
    submit:() => card().listeners.submit({preventDefault() {}})};
};

test('native hidden fields stay hidden across polling while their defaults round-trip', async () => {
  const question={id:'hidden',title:'Choose',unavailable:'',fields:[
    field('context','string',{hidden:true,default:'native-context'}),
    field('choice','boolean',{required:true,default:false}),
  ]};
  const ui=await boot({forms:()=>({forms:[question],unavailable:''})});
  const form=formUi(ui);
  assert.equal(form.key('context').hidden,true);
  await ui.poll();
  assert.equal(form.key('context').hidden,true);
  const sending=form.submit(); await tick();
  assert.deepEqual(ui.answerRequests[0].data.answer,{context:'native-context',choice:false});
  ui.answerRequests[0].finish('applied'); await sending;
});

test('native questions render shared links without changing choice values and reject malformed HTML fields', async () => {
  const link='<a href="https://example.test:18000/" target="_blank" rel="noopener noreferrer">Preview</a>';
  const form={id:'linked',title:'Open preview?',title_html:link,unavailable:'',fields:[
    field('scope','string',{label_html:link,description:'Check the preview',description_html:link,
      choices:[{value:'yes',label:'Open',label_html:link}]}),
  ]};
  const ui=await boot({forms:()=>({forms:[form],unavailable:''})});
  assert.equal(findAll(formUi(ui).card(),node=>node.innerHTML===link).length,4);
  assert.equal(formUi(ui).radios()[0].value,'yes');
  for(const invalid of [
    {...form,title_html:42},
    {...form,fields:[{...form.fields[0],label_html:{}}]},
    {...form,fields:[{...form.fields[0],description_html:null}]},
    {...form,fields:[{...form.fields[0],choices:[{value:'yes',label:'Open',label_html:false}]}]},
  ]) assert.throws(()=>ui.run('decodeForms')({forms:[invalid],unavailable:''}),/recognized format/);
});

test('a pending question renders in the chat, keeps typed answers across polls and root switches, and sends typed values', async () => {
  let answered=false;
  const ui=await boot({forms:id=>({forms:id==='a' && !answered ? [pickForm] : [],unavailable:''})});
  const form=formUi(ui), node=form.card();
  assert.ok(node,'the question is rendered in the chat container');
  assert.equal(form.key('why').hidden,true,'a conditional field starts hidden');
  assert.equal(form.button('Send answer')!==undefined,true);
  form.radios()[1].listeners.change(); // scope = all
  assert.equal(form.key('why').hidden,false);
  const why=find(form.key('why'),n=>n.className==='q-input'); why.value='because'; why.listeners.input();
  await ui.poll(); await ui.poll();
  assert.equal(form.card(),node,'polling does not rebuild the card');
  assert.equal(why.value,'because');
  await ui.choose(1);
  assert.equal(ui.element('forms').children.length,0,'another root shows none of root a’s questions');
  await ui.choose(0);
  assert.equal(form.card(),node);
  const sending=form.submit(); await tick();
  assert.deepEqual(json(ui.answerRequests[0].data),{id:ui.answerRequests[0].data.id,target:'a',form:'f1',answer:{scope:'all',why:'because',sure:false}});
  assert.equal(form.button('Send answer').disabled,true);
  answered=true; ui.answerRequests[0].finish('applied'); await sending; await tick();
  assert.equal(ui.element('forms').children.length,0,'an applied answer leaves the stream');
});

test('duplicate and reordered choice labels submit the exact native value', async () => {
  for(const options of [
    [{value:'native-b',label:'Same'},{value:'native-a',label:'Same'}],
    [{value:'native-a',label:'Same'},{value:'native-b',label:'Same'}],
  ]) {
    const ui=await boot({forms:()=>({forms:[{id:'f',title:'Choose',unavailable:'',fields:[
      field('pick','string',{required:true,choices:options}),
    ]}],unavailable:''})});
    formUi(ui).radios().find(radio=>radio.value==='native-a').listeners.change();
    const sending=formUi(ui).submit(); await tick();
    assert.equal(ui.answerRequests[0].data.answer.pick,'native-a');
    ui.answerRequests[0].finish('failed'); await sending;
  }
});

for(const outcome of ['already_answered','no_longer_pending']) {
  test('a '+outcome+' receipt releases a withdrawn question without a second delivery', async () => {
    let pending=true;
    const ui=await boot({forms:()=>({forms:pending ? [pickForm] : [],unavailable:''})});
    formUi(ui).radios()[0].listeners.change();
    const sending=formUi(ui).submit(); await tick();
    pending=false; ui.answerRequests[0].finish(outcome); await sending; await tick();
    assert.equal(ui.element('forms').children.length,0);
    assert.equal(ui.answerRequests.length,1);
  });
}

test('an unconfirmed answer keeps its ID, locks the form, survives a root switch and is only re-checked with the same payload', async () => {
  const ui=await boot({forms:id=>({forms:id==='a' ? [pickForm] : [],unavailable:''})});
  const form=formUi(ui);
  form.radios()[0].listeners.change(); // inbox
  const sending=form.submit(); await tick();
  await ui.choose(1);
  ui.answerRequests[0].finish('unknown'); await sending;
  assert.equal(ui.element('forms').children.length,0,'a late result for root a never touches root b');
  await ui.choose(0);
  assert.match(textOf(form.card()),/could not be confirmed/);
  assert.equal(form.button('Send answer').disabled,true);
  assert.equal(form.button('Cancel question').disabled,true);
  await form.submit(); assert.equal(ui.answerRequests.length,1,'no second answer can be started');
  const checking=form.button('Check delivery').listeners.click(); await tick();
  assert.deepEqual(json(ui.answerRequests[1].data),json(ui.answerRequests[0].data));
  ui.answerRequests[1].finish('unknown'); await checking;
  assert.equal(form.button('Checked natively, clear receipt').hidden,false);
  form.button('Checked natively, clear receipt').listeners.click();
  assert.equal(form.button('Send answer').disabled,false);
});

test('cancelling sends an empty answer with cancel, and a form without fields offers no answer button', async () => {
  const ui=await boot({forms:()=>({forms:[pickForm,{id:'ext',title:'Sign in',unavailable:'Needs the native app.',fields:[]}],unavailable:''})});
  const cards=ui.element('forms').children;
  assert.equal(cards.length,2);
  assert.equal(findAll(cards[1],n=>n.text==='Send answer').length,0);
  assert.match(textOf(cards[1]),/Needs the native app\. Answer it in the native session/);
  const cancelling=find(cards[0],n=>n.text==='Cancel question').listeners.click(); await tick();
  assert.deepEqual(json(ui.answerRequests[0].data),{id:ui.answerRequests[0].data.id,target:'a',form:'f1',answer:{},cancel:true});
  ui.answerRequests[0].finish('failed'); await cancelling; await tick();
  assert.match(textOf(cards[0]),/Not accepted/);
  assert.equal(find(cards[0],n=>n.text==='Send answer').disabled,false);
});

test('hostile native field keys are ordinary data: nothing is inherited, polluted or confused with an answer', async () => {
  const ui = await boot();
  const keys = ['__proto__','constructor','toString','hasOwnProperty'];
  const form = {id:'f',title:'t',unavailable:'',fields:[
    field('__proto__','string'), field('constructor','boolean',{required:true}), field('toString','multiselect',{choices:choices('a')}),
    field('hasOwnProperty','integer',{when:[{key:'constructor',op:'eq',value:true}]}),
  ]};
  const read = text => ui.run('readAnswers')(form,JSON.parse(text));  // JSON.parse makes "__proto__" an own key, like a native payload
  let result = read('{}');
  assert.deepEqual(Object.keys(result.errors),['constructor'], 'an inherited Object constructor is never an answer');
  assert.equal(Object.getPrototypeOf(result.answer),null);
  result = read('{"__proto__":"x","constructor":true,"toString":[],"hasOwnProperty":"0"}');
  assert.equal(JSON.stringify(result.answer),'{"__proto__":"x","constructor":true,"toString":[],"hasOwnProperty":0}');
  assert.deepEqual(Object.keys(result.answer),keys);
  assert.equal(Object.getPrototypeOf(result.answer),null);
  assert.equal({}.x,undefined); assert.equal(Object.prototype.hasOwnProperty('x'),false);
  assert.equal(ui.run('conditionHolds')({key:'toString',op:'neq',value:'a'},ui.run('record')()),false,'a missing answer makes neq false too');
  for(const label of ['constructor','__proto__','toString']) assert.equal(ui.run('STATUS_LABELS')[label],undefined,'external statuses never hit inherited properties');
});

test('explicit empty selections are answers, absence is not, and free text is never trimmed', async () => {
  const ui = await boot();
  const form = {id:'f',title:'t',unavailable:'',fields:[
    field('tags','multiselect',{required:true,choices:choices('a','b')}),
    field('opt','multiselect',{choices:choices('a')}),
    field('pick','string',{required:true,choices:[{value:'',label:'None'},{value:'a',label:'A'}]}),
    field('note','string'), field('size','integer'),
  ]};
  const read = raw => ui.run('readAnswers')(form,raw);
  let result = read({tags:[],pick:'',note:'  keep  '});
  assert.equal(JSON.stringify(result.answer),'{"tags":[],"pick":"","note":"  keep  "}');
  assert.equal(Object.keys(result.errors).length,0,'required means present: [] and an empty-string choice satisfy it');
  assert.equal('opt' in result.answer,false,'an untouched optional multiselect stays absent');
  result = read({pick:'a',note:'   '});
  assert.deepEqual(Object.keys(result.errors),['tags']);
  assert.equal(result.answer.note,'   ', 'whitespace-only text is the user’s answer, not a blank to drop');
  assert.equal(read({tags:[],pick:'a',size:' 5'}).errors.size,'Enter a number.', 'numbers are parsed as typed, not trimmed into validity');
});

test('unticking every option sends an explicit empty array while an untouched multiselect sends nothing', async () => {
  const ui=await boot({forms:()=>({forms:[{id:'m',title:'Pick',unavailable:'',fields:[
    field('opt','multiselect',{choices:choices('a','b')}), field('tags','multiselect',{choices:choices('x')})]}],unavailable:''})});
  const form=formUi(ui);
  const boxes=findAll(form.card(),node=>node.type==='checkbox');
  boxes[0].checked=true; boxes[0].listeners.change();
  boxes[0].checked=false; boxes[0].listeners.change();
  const sending=form.submit(); await tick();
  assert.equal(JSON.stringify(ui.answerRequests[0].data.answer),'{"opt":[]}');
  ui.answerRequests[0].finish('failed'); await sending;
});

test('generated DOM ids stay valid for spaced, unicode and hostile native keys while data-key stays raw', async () => {
  const keys=['Pool size','Connection string note','Ünï 名前','__proto__'];
  const ui=await boot({forms:()=>({forms:[{id:'form with spaces',title:'Setup',unavailable:'',fields:[
    field(keys[0],'integer',{description:'How many'}), field(keys[1],'string',{constraints:{maxLength:50}}),
    field(keys[2],'string',{choices:choices('a','b')}), field(keys[3],'boolean')]}],unavailable:''})});
  const card=formUi(ui).card();
  const nodes=[...walk(card)];
  const ids=nodes.filter(n=>n.id).map(n=>n.id);
  assert.equal(new Set(ids).size,ids.length,'ids are unique');
  assert.ok(ids.every(id=>/^\S+$/.test(id)),'ids contain no whitespace');
  const labelled=nodes.filter(n=>n.attributes?.['aria-labelledby']);
  assert.ok(labelled.length>=4);
  for(const n of labelled) assert.ok(ids.includes(n.attributes['aria-labelledby']),'aria-labelledby points at a real id');
  const described=nodes.find(n=>n.attributes?.['aria-describedby']);
  assert.ok(ids.includes(described.attributes['aria-describedby']));
  assert.deepEqual(findAll(card,n=>n.dataset.key!==undefined).map(n=>n.dataset.key),keys);
  assert.ok(findAll(card,n=>n.type==='radio').every(n=>/^\S+$/.test(n.name)));
});

test('a command or question fetch for a root that was switched away from cannot stick or leak into the next root', async () => {
  const slowCommands=deferred(), slowForms=deferred();
  let commandCalls=0, formCalls=0;
  const ui=await boot({
    commands:id=>id==='a' && commandCalls++===0 ? slowCommands.promise : commandFixture(id),
    forms:id=>id==='a' && formCalls++===0 ? slowForms.promise : {forms:id==='a' ? [pickForm] : [{id:'bq',title:'B question',unavailable:'',fields:[]}],unavailable:''},
  });
  await ui.choose(1);
  assert.equal(ui.chips()[0].value,'m3');
  assert.match(textOf(ui.element('forms')),/B question/);
  slowCommands.resolve(commandFixture('a')); slowForms.resolve({forms:[pickForm],unavailable:''}); await tick();
  assert.equal(ui.chips()[0].value,'m3','the late list for root a is dropped');
  assert.doesNotMatch(textOf(ui.element('forms')),/Which cleanup/);
  await ui.choose(0);
  assert.equal(ui.chips()[0].value,'m1','coming back loads root a again: the abandoned fetch did not leave loading stuck');
  assert.match(textOf(ui.element('forms')),/Which cleanup/);
  assert.equal(commandCalls,2); assert.equal(formCalls,2);
});

/* --- native selects are chip buttons that reuse the composer menu --- */
const effortFixture = id => ({controls:id==='a' ? [modelControl('m1',['m1','m2','m3']),
  {id:'effort',label:'Reasoning',kind:'select',current:'high',description:'Next turns',choices:['low','medium','high','xhigh'].map(value=>({value,label:value}))}] : [],unavailable:''});
const menuOptions = ui => findAll(ui.element('command-menu'),node=>node.attributes.role==='option');
const keydown = (node, key) => { const event={key,prevented:false,preventDefault() { this.prevented=true; }}; node.listeners.keydown(event); return event; };

test('select controls are buttons, never OS selects, and their picker is the composer menu with the current value checked', async () => {
  const ui=await boot({commands:effortFixture});
  const chips=ui.element('command-chips').children;
  assert.equal(chips.length,2);
  assert.equal(findAll(ui.element('command-chips'),n=>n.tagName==='SELECT' || n.type==='select-one').length,0);
  assert.ok(chips.every(chip=>chip.attributes['aria-haspopup']==='listbox' && chip.attributes['aria-expanded']==='false'));
  assert.equal(chips[1].attributes['aria-label'],'Reasoning: high');
  ui.type('half-written draft');
  chips[1].listeners.click();
  assert.equal(ui.element('command-menu').hidden,false);
  assert.equal(ui.element('command-menu').attributes.role,'listbox');
  assert.equal(ui.element('command-chips').children[1].attributes['aria-expanded'],'true');
  assert.deepEqual(menuOptions(ui).map(node=>node.attributes['aria-selected']),['false','false','true','false'],'the current native value is selected');
  assert.equal(ui.element('message').value,'half-written draft','opening a chip never touches the draft');
  assert.equal(ui.element('command-menu').attributes['aria-activedescendant'],menuOptions(ui)[2].id,'the menu starts on the current value');
});

test('chip picker keys: arrows, Home/End, Enter applies the exact native id, Escape closes and returns focus to the chip', async () => {
  const ui=await boot({commands:effortFixture});
  ui.element('command-chips').children[1].listeners.click();
  const menu=ui.element('command-menu');
  assert.equal(keydown(menu,'ArrowDown').prevented,true); // high -> xhigh
  keydown(menu,'ArrowDown'); // wraps to low
  keydown(menu,'End'); keydown(menu,'Home');
  keydown(menu,'ArrowDown'); // medium
  assert.equal(menu.attributes['aria-activedescendant'],menuOptions(ui)[1].id);
  keydown(menu,'Escape');
  assert.equal(menu.hidden,true);
  assert.equal(ui.commandRequests.length,0,'Escape applies nothing');
  assert.equal(ui.focused().dataset.command,'effort','Escape returns focus to the chip');
  assert.equal(ui.element('message').value,'');
  ui.element('command-chips').children[0].listeners.click();
  keydown(menu,'ArrowDown'); keydown(menu,'Enter'); await tick();
  assert.deepEqual([ui.commandRequests[0].data.command,ui.commandRequests[0].data.value],['model','m2']);
  assert.equal(ui.commandRequests[0].data.target,'a');
  assert.equal(ui.focused().dataset.command,'model','choosing returns focus to the chip that opened the picker');
  assert.equal(ui.element('message').value,'','the draft is not replaced by a /command');
  ui.commandRequests[0].finish('applied'); await tick();
});

test('a chip toggles its own picker, another chip switches pickers and an outside click closes it, all without touching the draft', async () => {
  const ui=await boot({commands:effortFixture});
  ui.type('keep me');
  const chip=index => ui.element('command-chips').children[index];
  chip(0).listeners.click();
  assert.match(textOf(ui.element('command-menu')),/Model/);
  chip(1).listeners.click();
  assert.match(textOf(ui.element('command-menu')),/Reasoning/);
  assert.equal(chip(0).attributes['aria-expanded'],'false');
  assert.equal(chip(1).attributes['aria-expanded'],'true');
  chip(1).listeners.click();
  assert.equal(ui.element('command-menu').hidden,true,'tapping the open chip again closes it');
  chip(0).listeners.click();
  const inside={target:{closest:selector=>/command-chips/.test(selector) ? {} : null}}, outside={target:{closest:()=>null}};
  ui.document.handlers.click.forEach(handler=>handler(inside));
  assert.equal(ui.element('command-menu').hidden,false,'a click on a chip is not an outside click');
  ui.document.handlers.click.forEach(handler=>handler(outside));
  assert.equal(ui.element('command-menu').hidden,true);
  assert.equal(ui.element('message').value,'keep me');
  assert.equal(ui.commandRequests.length,0);
});

test('a busy or unconfirmed root keeps its chips focusable but inert, with the requested value shown', async () => {
  const ui=await boot({commands:effortFixture});
  await ui.pick(1,'xhigh');
  const [,effort]=ui.element('command-chips').children;
  assert.equal(effort.attributes['aria-disabled'],'true');
  assert.equal(effort.disabled,false,'aria-disabled keeps keyboard focus on the chip during the request');
  assert.equal(effort.children[1].text,'xhigh','the chip shows what was requested');
  effort.listeners.click();
  assert.equal(ui.element('command-menu').hidden,true);
  await ui.choose(1);
  assert.equal(ui.element('command-chips').children.length,0,'another root shows none of root a’s chips');
  ui.commandRequests[0].finish('unknown'); await tick();
  assert.equal(ui.element('command-chips').children.length,0);
});

/* --- Bridge worker provenance: marker + launch graph, same for every harness --- */
const origin = (parent, extra={}) => ({tool:'Agent Bridge',job:'owner/task-7',title:'Review the importer',parent,...extra});
const workerRoots = parent => [{id:'p',label:'Planner',harness:'Claude'},{id:'w',label:'Worker session',harness:'Codex',origin:origin(parent)}];
const emptyContext = extra => ({account:null,quotas:[],metrics:[],workers:[],tools:[],notices:[],fetched_at:1,...extra});
const graphOf = ui => find(ui.element('details-body'),node=>hasClass(node,'graph'));
const graphNodes = ui => graphOf(ui).children.map(li=>li.children[0]);

test('a Bridge worker is marked in its session row and header; plain roots carry no marker', async () => {
  const ui=await boot({roots:workerRoots(null)});
  const rows=ui.element('roots').children;
  assert.equal(findAll(rows[0],n=>hasClass(n,'origin-tag')).length,0);
  assert.equal(findAll(rows[1],n=>hasClass(n,'origin-tag')).length,1);
  assert.match(rows[1].attributes['aria-label'],/Agent Bridge worker/);
  await ui.choose(1);
  assert.equal(findAll(ui.element('root-detail'),n=>hasClass(n,'origin-tag')).length,1);
  assert.match(textOf(ui.element('root-detail')),/Agent Bridge worker/);
  await ui.choose(0);
  assert.equal(findAll(ui.element('root-detail'),n=>hasClass(n,'origin-tag')).length,0);
});

test('malformed origin metadata is ignored in the list and refused in details', async () => {
  const bad=[{id:'w',label:'W',harness:'Codex',origin:{tool:'Agent Bridge',job:'j',title:'t',parent:{harness:'Claude'}}}];
  const ui=await boot({roots:bad,context:()=>emptyContext({origin:{tool:'Agent Bridge',job:'j',title:'t',parent:{harness:'Claude'}}})});
  assert.equal(findAll(ui.element('roots'),n=>hasClass(n,'origin-tag')).length,0);
  await ui.element('details-toggle').listeners.click(); await tick();
  assert.match(textOf(ui.element('details-body')),/not in a recognized format/);
  assert.equal(graphOf(ui),undefined);
});

test('details graph runs known parent, launcher, this session; an unknown parent adds no node or arrow', async () => {
  let ui=await boot({roots:workerRoots({harness:'Claude',id:'p',label:'Planner'}),context:()=>emptyContext({origin:origin({harness:'Claude',id:'p',label:'Planner'})})});
  await ui.choose(1);
  await ui.element('details-toggle').listeners.click(); await tick();
  let nodes=graphNodes(ui);
  assert.equal(nodes.length,3);
  assert.deepEqual(nodes.map(n=>textOf(find(n,c=>hasClass(c,'node-text'))).replace(/\s+/g,'')),['PlannerClaude','Agent Bridgeowner/task-7'.replace(/\s+/g,''),'Review the importerCodex'.replace(/\s+/g,'')]);
  assert.equal(nodes[0].dataset.brand,undefined);
  assert.equal(findAll(nodes[0],n=>n.dataset.brand==='claude').length,1,'the parent shows its own harness mark');
  assert.equal(findAll(nodes[2],n=>n.dataset.brand==='openai').length,1,'this session shows its own harness mark');
  assert.equal(nodes[2].attributes['aria-current'],'true');
  assert.equal(hasClass(nodes[1],'link'),false);
  ui=await boot({roots:workerRoots(null),context:()=>emptyContext({origin:origin(null)})});
  await ui.choose(1);
  await ui.element('details-toggle').listeners.click(); await tick();
  nodes=graphNodes(ui);
  assert.equal(nodes.length,2,'no parent: the chain starts at the launcher');
  assert.match(textOf(nodes[0]),/Agent Bridge/);
  assert.doesNotMatch(textOf(graphOf(ui)),/[Uu]nknown/);
});

test('a parent with a listed root id opens that root through the normal selection and leaks no transcript', async () => {
  const parent={harness:'Claude',id:'p',label:'Planner'};
  const ui=await boot({roots:workerRoots(parent),context:()=>emptyContext({origin:origin(parent)})});
  await ui.choose(1);
  await ui.element('details-toggle').listeners.click(); await tick();
  const link=graphNodes(ui)[0];
  assert.equal(hasClass(link,'link'),true);
  assert.equal(link.attributes['aria-label'],'Open Planner');
  link.listeners.click(); await tick();
  assert.equal(ui.element('root-title').textContent,'Planner');
  assert.ok(ui.paths.some(path=>path==='/api/view?id=p'),'selection reads the parent through the normal view');
  assert.equal(ui.paths.filter(path=>path.includes('/api/')&&path.includes('id=p')&&!/view|commands|forms|context/.test(path)).length,0);
});

test('a parent id that is not a listed root or not given stays a plain node', async () => {
  const gone={harness:'Antigravity',id:'missing',label:null};
  const ui=await boot({roots:workerRoots(gone),context:()=>emptyContext({origin:origin(gone)})});
  await ui.choose(1);
  await ui.element('details-toggle').listeners.click(); await tick();
  const first=graphNodes(ui)[0];
  assert.equal(hasClass(first,'link'),false);
  assert.match(textOf(first),/Antigravity/);
  assert.equal(findAll(first,n=>n.dataset.brand==='antigravity').length,1);
});

test('absent native tool and worker status is said plainly while reported statuses stay as reported', async () => {
  const ui=await boot({context:()=>emptyContext({
    tools:[{name:'github',status:'unknown',tool_count:3},{name:'node_repl',status:'connected',tool_count:2},{name:'x',status:'needs_auth',tool_count:null}],
    workers:[{id:'w',label:'Reviewer',status:'',model:null}]})});
  await ui.element('details-toggle').listeners.click(); await tick();
  const text=textOf(ui.element('details-body'));
  assert.match(text,/github3 tools · Status not reported/);
  assert.match(text,/node_repl2 tools · connected/);
  assert.match(text,/needs auth/);
  assert.match(text,/ReviewerStatus not reported/);
  assert.doesNotMatch(text,/unknown/);
});

test('clicking a chip or a menu option keeps the picker open although the click re-renders its own target', async () => {
  const ui=await boot({commands:effortFixture});
  const chip=index => ui.element('command-chips').children[index];
  const reasoning=chip(1);
  ui.click(reasoning);
  assert.equal(reasoning.closest('#command-chips'),null,'the clicked chip really was detached by the render');
  assert.equal(ui.element('command-menu').hidden,false,'the picker survives the document-level outside-click handler');
  assert.equal(chip(1).attributes['aria-expanded'],'true');
  ui.click(chip(1));
  assert.equal(ui.element('command-menu').hidden,true,'tapping the same chip again toggles it closed');
  // list -> choices through the Commands button: the clicked option is replaced by the next view
  ui.click(ui.element('command-menu-button'));
  assert.equal(ui.element('command-menu').hidden,false);
  const modelRow=menuOptions(ui)[0];
  ui.click(modelRow);
  assert.equal(modelRow.closest('#command-menu'),null);
  assert.equal(ui.element('command-menu').hidden,false,'picking a command from the list opens its choices in the same menu');
  assert.match(textOf(ui.element('command-menu')),/M3/);
  // choosing a value applies, closes and keeps the draft
  ui.type('draft stays');
  ui.click(menuOptions(ui)[2]); await tick();
  assert.equal(ui.element('command-menu').hidden,true);
  assert.equal(ui.commandRequests[0].data.value,'m3');
  assert.equal(ui.element('message').value,'draft stays');
  ui.commandRequests[0].finish('applied'); await tick();
});

test('typed slash menu rows survive their own re-render, while real outside clicks still close the menu', async () => {
  const ui=await boot({commands:effortFixture});
  ui.type('/');
  ui.click(menuOptions(ui)[1]);  // Reasoning: typed mode rewrites the draft and swaps the rows
  assert.equal(ui.element('command-menu').hidden,false);
  assert.equal(ui.element('message').value,'/effort ');
  ui.click(ui.element('message'));
  assert.equal(ui.element('command-menu').hidden,false,'clicking the composer is not an outside click');
  const elsewhere=new (ui.element('older').constructor)();
  ui.click(elsewhere);
  assert.equal(ui.element('command-menu').hidden,true,'a click elsewhere closes it');
  const noPath={target:{closest:selector=>/command-chips/.test(selector) ? {} : null}};  // old environments without composedPath
  ui.element('command-chips').children[0].listeners.click();
  ui.document.handlers.click.forEach(handler=>handler(noPath));
  assert.equal(ui.element('command-menu').hidden,false);
});
