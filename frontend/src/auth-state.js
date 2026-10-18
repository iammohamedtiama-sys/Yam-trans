export function sessionMatches(token,user,company){
 try{
  if(!token||!user?.id||!company?.id)return false;
  const raw=token.split('.')[0].replace(/-/g,'+').replace(/_/g,'/');
  const data=JSON.parse(atob(raw.padEnd(Math.ceil(raw.length/4)*4,'=')));
  return data.uid===user.id&&(company.id==='platform'?!data.cid:data.cid===company.id);
 }catch{return false;}
}
