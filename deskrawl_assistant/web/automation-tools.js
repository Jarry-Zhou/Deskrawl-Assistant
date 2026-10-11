'use strict';
(function(root){
  const kinds=[['equipment','装备'],['rune','符文'],['gem','宝石'],['chest','宝箱'],['material','材料 / 其他']];
  const defaultPages={equipment:[1,2,3],rune:[4],gem:[5]};
  function storageReady(transfer={}){
    const size=transfer.page_size,indices=transfer.storage_indices;
    return transfer.available===true&&Number.isInteger(size)&&size>0&&Array.isArray(indices)&&indices.every(n=>Number.isInteger(n)&&n>=0)&&new Set(indices).size===indices.length;
  }
  function storagePages(transfer={},items=[]){
    const size=transfer.page_size,indices=transfer.storage_indices;
    if(!Number.isInteger(size)||size<1||!Array.isArray(indices)||indices.some(n=>!Number.isInteger(n)||n<0)||new Set(indices).size!==indices.length)return [];
    const occupied=new Set(items.filter(row=>row.container==='storage').map(row=>row.slot_index)),pages=new Map();
    for(const index of indices){const page=Math.floor(index/size)+1;if(!pages.has(page))pages.set(page,{index:page,name:`第 ${page} 页`,capacity:0,free:0});const row=pages.get(page);row.capacity++;if(!occupied.has(index))row.free++;}
    return [...pages.values()].sort((a,b)=>a.index-b.index);
  }
  function pageChoices(rows=[],selected=[],ready=false){
    const known=new Map(rows.map(row=>[Number(row.index),row]));
    const indices=[...new Set([...known.keys(),...selected])].sort((a,b)=>a-b);
    return indices.map(index=>({...(known.get(index)||{}),index,name:known.get(index)?.name||`第 ${index} 页`,
      selected:selected.includes(index),status:ready?(known.has(index)?'available':'locked'):'pending'}));
  }
  const helpers={kinds,storagePages,storageReady,pageChoices,defaultPages};
  if(typeof module!=='undefined'&&module.exports)module.exports=helpers;
  else root.AutomationTools=helpers;
})(typeof window!=='undefined'?window:globalThis);
