(function(){var t=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');document.documentElement.dataset.theme=t;
addEventListener('DOMContentLoaded',function(){var b=document.createElement('button');b.className='btn theme';b.setAttribute('aria-label','Toggle dark mode');
function s(){b.textContent=document.documentElement.dataset.theme=='dark'?'Light':'Dark'}s();
b.onclick=function(){var n=document.documentElement.dataset.theme=='dark'?'light':'dark';document.documentElement.dataset.theme=n;localStorage.setItem('theme',n);s()};document.body.appendChild(b)})})();
window.api=async function(u,o){o=o||{};var h={'Content-Type':'application/json','X-Requested-With':'fetch'};
var r=await fetch(u,Object.assign({},o,{headers:h,body:o.body?JSON.stringify(o.body):undefined}));var d=await r.json().catch(function(){return{}});
if(!r.ok){var e=new Error(d.error||'Something went wrong. Check your connection and try again.');e.status=r.status;throw e}return d};
window.esc=function(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})};
