/* Shared DOM helpers. Text is always set as text; only this file's own SVG constants use innerHTML. */
const $ = id => document.getElementById(id);
const DIRECT_PROPS = new Set(['type','value','disabled','hidden','src','alt','id','href','placeholder','rows','maxLength','autocomplete','name','htmlFor','selected','checked']);
/* Strict boundary checks shared by the optional-surface decoders (context, forms). */
/* Records keyed by anything external (field keys, statuses, kinds) have no prototype, so "__proto__", "constructor" or
   "toString" are ordinary keys and never inherited values. Read with own(), never with a bare index on a plain object. */
const record = (entries={}) => Object.assign(Object.create(null), entries);
const own = (object, key) => Object.hasOwn(object, key) ? object[key] : undefined;
const isText = value => typeof value==='string';
const isNumber = value => typeof value==='number' && Number.isFinite(value);
const optional = (value, test) => value===null || test(value);
const list = (value, test) => Array.isArray(value) && value.every(row=>row && typeof row==='object' && test(row));
function el(tag, attrs={}, ...kids) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)) {
    if(value==null || value===false) continue;
    if(key==='class') node.className=value;
    else if(key==='text') node.textContent=value;
    else if(key==='data') Object.assign(node.dataset,value);
    else if(key==='style') Object.assign(node.style,value); // CSSOM only: the page CSP blocks inline style attributes
    else if(key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if(DIRECT_PROPS.has(key)) node[key]=value;
    else node.setAttribute(key,value===true?'':value);
  }
  node.append(...kids.flat(Infinity).filter(kid=>kid!=null && kid!==false));
  return node;
}
const ICONS = {
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  close:'<path d="M6 6l12 12M18 6L6 18"/>',
  image:'<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 4 3.5 3-2.5 4 3.5"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.7v.1"/>',
  external:'<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  up:'<path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/>',
  down:'<path d="M12 5v14M5.5 12.5L12 19l6.5-6.5"/>',
  chevron:'<path d="M6 9l6 6 6-6"/>',
  more:'<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
  stop:'<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
  slash:'<path d="M15.5 4L8.5 20"/>',
  worker:'<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.4 11l7.2-4M8.4 13l7.2 4"/>',
  moon:'<path d="M20.5 13a8.5 8.5 0 1 1-9.5-9.5A6.5 6.5 0 0 0 20.5 13Z"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
  system:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
};
function icon(name) {
  const node=document.createElement('span'); node.className='icon'; node.setAttribute('aria-hidden','true');
  node.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+ICONS[name]+'</svg>';
  return node;
}
/* Harness marks are the vendors' own files under /assets (see assets/NOTICE.md). Unknown harnesses get a letter. */
const BRANDS = [
  {key:'openai', match:/codex|chatgpt|openai/i, src:'/assets/openai.svg'},
  {key:'claude', match:/claude|anthropic/i, src:'/assets/claude.svg'},
  {key:'antigravity', match:/antigravity|agy/i, src:'/assets/antigravity.svg'},
  {key:'opencode', match:/opencode/i, src:'/assets/opencode.svg'},
];
function brandMark(harness, options={}) {
  const brand=BRANDS.find(row=>row.match.test(harness || ''));
  const face=el('span',{class:'face'}, brand ? el('img',{src:brand.src,alt:'',width:64,height:64,decoding:'async'})
    : el('span',{class:'letter',text:(harness || '?').trim().charAt(0).toUpperCase() || '?'}));
  return el('span',{class:'mark'+(options.size?' '+options.size:''),data:{brand:brand?.key || 'other'},title:options.title ? harness : null},face);
}
/* Launcher provenance, identical for every harness (root rows and /api/context):
   {tool, job, title, parent: null | {harness, id: null|string, label: null|string}}. Malformed or absent means no marker. */
function readOrigin(value) {
  if(!value || typeof value!=='object') return null;
  const parent=value.parent;
  const ok=isText(value.tool) && isText(value.job) && isText(value.title) &&
    (parent===null || (!!parent && typeof parent==='object' && isText(parent.harness) && optional(parent.id,isText) && optional(parent.label,isText)));
  return ok ? value : null;
}
function originTag(origin, withText) {
  return el('span',{class:'origin-tag',title:origin.tool+' job '+origin.job},icon('worker'),withText ? el('span',{text:origin.tool+' worker'}) : null);
}
/* Native statuses are shown as reported; an absent one is said plainly instead of "unknown". */
function statusText(status) {
  if(!status || status==='unknown') return 'Status not reported';
  return status.replace(/[_-]+/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase();
}
function duration(ms) {
  if(ms==null) return '';
  return ms<1000 ? Math.round(ms)+' ms' : ms<60000 ? (ms/1000).toFixed(1)+' s' : Math.floor(ms/60000)+' m '+Math.round(ms%60000/1000)+' s';
}
/* A sheet is a side panel or bottom sheet that returns focus to its opener and closes on Escape. */
class Sheet {
  constructor(node, trigger, scrim) {
    this.node=node; this.trigger=trigger; this.scrim=scrim || null; this.isOpen=false;
  }
  open() {
    this.isOpen=true; this.node.classList.toggle('open',true);
    if(this.scrim) this.scrim.hidden=false;
    this.trigger?.setAttribute('aria-expanded','true');
    this.node.querySelector?.('[data-autofocus]')?.focus?.();
  }
  close(restoreFocus=true) {
    this.isOpen=false; this.node.classList.toggle('open',false);
    if(this.scrim) this.scrim.hidden=true;
    this.trigger?.setAttribute('aria-expanded','false');
    if(restoreFocus) this.trigger?.focus?.();
  }
  toggle() { if(this.isOpen) this.close(); else this.open(); }
}
