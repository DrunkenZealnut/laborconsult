'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const feedback=require('./public/answer_feedback.js');

class El {
  constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.dataset={};}
  appendChild(el){this.children.push(el);return el;}
  addEventListener(kind,fn){this.listeners[kind]=fn;}
  insertAdjacentElement(_,el){this.sibling=el;}
  setAttribute(){}
  querySelectorAll(){return this.children.flatMap(c=>[c,...c.querySelectorAll()]).filter(c=>c.tag==='button');}
  async click(){return this.listeners.click();}
}
const doc={createElement:tag=>new El(tag)};
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('render records exposure before a vote, with answer token and captured session',async()=>{
  const sent=[];const el=new El('answer');
  const fetch=async(url,opts)=>{sent.push([url,JSON.parse(opts.body)]);return{ok:true,json:async()=>({saved:true})};};
  feedback.render(el,{token:'signed'},'original-session',{document:doc,fetch});
  await tick();
  assert.equal(sent[0][1].kind,'exposure');
  const yes=el.sibling.children.find(c=>c.textContent==='도움이 됐어요');
  await yes.click();
  assert.equal(sent[1][1].positive,true);
  assert.equal(sent[1][1].token,'signed');
  assert.equal(sent[1][1].session_id,'original-session');
});

test('non-2xx responses never show a successful vote or raw server detail',async()=>{
  const el=new El('answer');
  feedback.render(el,{token:'signed'},'s',{document:doc,fetch:async()=>({ok:false,status:500,json:async()=>({detail:'private database failure'})})});
  await tick();
  await el.sibling.children.find(c=>c.textContent==='도움이 됐어요').click();
  const text=el.sibling.children.map(c=>c.textContent).join(' ');
  assert.match(text,/저장하지 못했습니다/);
  assert.doesNotMatch(text,/private|저장했습니다/);
});

test('negative feedback requires a reason selection',async()=>{
  const sent=[];const el=new El('answer');
  feedback.render(el,{token:'signed'},'s',{document:doc,fetch:async(_,opts)=>{sent.push(JSON.parse(opts.body));return{ok:true};}});
  await tick();
  await el.sibling.children.find(c=>c.textContent==='도움이 안 됐어요').click();
  assert.equal(sent.length,1);
  const choices=el.sibling.children.find(c=>c.className==='feedback-reasons');
  await choices.children.find(c=>c.textContent==='필요한 답이 없음').click();
  assert.equal(sent[1].reason,'missing_answer');
  assert.equal(sent[1].positive,false);
});
