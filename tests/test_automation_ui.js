'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {kinds,storagePages,storageReady,pageChoices,defaultPages} = require('../deskrawl_assistant/web/automation-tools.js');

test('new user partition defaults are equipment 1/2/3, rune 4, gem 5',()=>{
  assert.deepEqual(defaultPages,{equipment:[1,2,3],rune:[4],gem:[5]});
});

test('unlocked, locked and pending choices retain saved selections across unlocks',()=>{
  const selected=[1,2,3],first=[{index:1,name:'第 1 页',capacity:50,free:20}];
  const pending=pageChoices(first,selected,false);
  assert.deepEqual(pending.map(r=>r.status),['pending','pending','pending']);
  const locked=pageChoices(first,selected,true);
  assert.deepEqual(locked.map(r=>r.status),['available','locked','locked']);
  assert.ok(locked.every(r=>r.selected));assert.equal(locked[0].free,20);
  const after=pageChoices([...first,{index:3,capacity:50,free:50}],selected,true);
  assert.equal(after[2].status,'available');assert.equal(after[1].status,'locked');
  assert.deepEqual(selected,[1,2,3]);
  assert.equal(pageChoices(first,[5],true).find(r=>r.index===5).status,'locked');
  assert.equal(pageChoices([],[],true).length,0);
});

test('only complete native permission data can mark missing pages locked',()=>{
  const transfer={available:true,page_size:50,storage_indices:[0,49,200]};
  assert.equal(storageReady(transfer),true);
  for(const patch of [{available:false},{page_size:null},{storage_indices:[0,0]},{storage_indices:[-1]}])
    assert.equal(storageReady({...transfer,...patch}),false);
});

test('type choices include all supported physical item families',()=>{
  assert.deepEqual(kinds.map(([key])=>key),['equipment','rune','gem','chest','material']);
});

test('page choices follow noncontiguous permissions and real free slots',()=>{
  const indices=[...Array(50).keys(),200,201,249];
  const items=[{container:'inventory',slot_index:0},{container:'storage',slot_index:200},
    {container:'storage',slot_index:249},{container:'storage',slot_index:99}];
  assert.deepEqual(storagePages({page_size:50,storage_indices:indices},items),[
    {index:1,name:'第 1 页',capacity:50,free:50},
    {index:5,name:'第 5 页',capacity:3,free:1}
  ]);
});

test('unknown or malformed storage cannot create fictional usable pages',()=>{
  for(const transfer of [{},{page_size:50},{page_size:true,storage_indices:[0]},
    {page_size:50,storage_indices:[0,0]},{page_size:50,storage_indices:[-1]},
    {page_size:50,storage_indices:[1.5]}])assert.deepEqual(storagePages(transfer),[]);
});
