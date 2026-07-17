import{p as et}from"./chunk-JWPE2WC7-BRCmx2gP.js";import{M as at,aE as rt,N as it,aF as nt,Q as ot,aH as st,a as l,aj as z,P as lt,m as ct,aD as dt,aq as gt,w as pt,n as ht,F as ft}from"./mermaid.core-CwayTbWL.js";import{p as ut}from"./cynefin-VYW2F7L2-DoCVgDlA.js";import{D as U,_ as mt,E as vt}from"./vendor-charts-Br5QTkJr.js";import"./index-02QdknRG.js";import"./vendor-react-BEFBu0qs.js";import"./vendor-ui-DQ-ZhZpk.js";import"./vendor-markdown-C0jI_Wfn.js";var St=ft.pie,F={sections:new Map,showData:!1},T=F.sections,R=F.showData,xt=structuredClone(St),wt=l(()=>structuredClone(xt),"getConfig"),Ct=l(()=>{T=new Map,R=F.showData,ht()},"clear"),Dt=l(({label:t,value:a})=>{if(a<0)throw new Error(`"${t}" has invalid value: ${a}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);T.has(t)||(T.set(t,a),z.debug(`added new section: ${t}, with value: ${a}`))},"addSection"),$t=l(()=>T,"getSections"),yt=l(t=>{R=t},"setShowData"),Tt=l(()=>R,"getShowData"),j={getConfig:wt,clear:Ct,setDiagramTitle:st,getDiagramTitle:ot,setAccTitle:nt,getAccTitle:it,setAccDescription:rt,getAccDescription:at,addSection:Dt,getSections:$t,setShowData:yt,getShowData:Tt},bt=l((t,a)=>{et(t,a),a.setShowData(t.showData),t.sections.map(a.addSection)},"populateDb"),At={parse:l(async t=>{const a=await ut("pie",t);z.debug(a),bt(a,j)},"parse")},_t=l(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieCircle.highlighted{
    scale: 1.05;
    opacity: 1;
  }
  .pieCircle.highlightedOnHover:hover{
    transition-duration: 250ms;
    scale: 1.05;
    opacity: 1;
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),kt=_t,Et=l(t=>{const a=[...t.values()].reduce((o,m)=>o+m,0),H=[...t.entries()].map(([o,m])=>({label:o,value:m})).filter(o=>o.value/a*100>=1);return vt().value(o=>o.value).sort(null)(H)},"createPieArcs"),zt=l((t,a,H,L)=>{var I;z.debug(`rendering pie chart
`+t);const o=L.db,m=lt(),h=ct(o.getConfig(),m.pie),M=40,i=18,c=4,C=450,S=C,b=dt(a),D=b.append("g");D.attr("transform","translate("+S/2+","+C/2+")");const{themeVariables:n}=m;let[P]=gt(n.pieOuterStrokeWidth);P??(P=2);const q=h.legendPosition,W=h.textPosition,Q=h.donutHole>0&&h.donutHole<=.9?h.donutHole:0,f=Math.min(S,C)/2-M,V=U().innerRadius(Q*f).outerRadius(f),X=U().innerRadius(f*W).outerRadius(f*W),x=D.append("g");x.append("circle").attr("cx",0).attr("cy",0).attr("r",f+P/2).attr("class","pieOuterCircle");const $=o.getSections(),Z=Et($),J=[n.pie1,n.pie2,n.pie3,n.pie4,n.pie5,n.pie6,n.pie7,n.pie8,n.pie9,n.pie10,n.pie11,n.pie12];let A=0;$.forEach(e=>{A+=e});const O=Z.filter(e=>(e.data.value/A*100).toFixed(0)!=="0"),_=mt(J).domain([...$.keys()]);x.selectAll("mySlices").data(O).enter().append("path").attr("d",V).attr("fill",e=>_(e.data.label)).attr("class",e=>{let r="pieCircle";return h.highlightSlice==="hover"?r+=" highlightedOnHover":h.highlightSlice===e.data.label&&(r+=" highlighted"),r}),x.selectAll("mySlices").data(O).enter().append("text").text(e=>(e.data.value/A*100).toFixed(0)+"%").attr("transform",e=>"translate("+X.centroid(e)+")").style("text-anchor","middle").attr("class","slice");const K=D.append("text").text(o.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText"),w=[...$.entries()].map(([e,r])=>({label:e,value:r})),u=D.selectAll(".legend").data(w).enter().append("g").attr("class","legend");u.append("rect").attr("width",i).attr("height",i).style("fill",e=>_(e.label)).style("stroke",e=>_(e.label)),u.append("text").attr("x",i+c).attr("y",i-c).text(e=>o.getShowData()?`${e.label} [${e.value}]`:e.label);const v=Math.max(...u.selectAll("text").nodes().map(e=>(e==null?void 0:e.getBoundingClientRect().width)??0));let y=C,k=S+M;const s=i+c,E=w.length*s;switch(q){case"center":u.attr("transform",(e,r)=>{const d=s*w.length/2,g=-v/2-(i+c),p=r*s-d;return"translate("+g+","+p+")"});break;case"top":y+=E,u.attr("transform",(e,r)=>{const d=f,g=-v/2-(i+c),p=r*s-d;return`translate(${g}, ${p})`}),x.attr("transform",()=>`translate(0, ${E+s})`);break;case"bottom":y+=E,u.attr("transform",(e,r)=>{const d=-f-s,g=-v/2-(i+c),p=r*s-d;return"translate("+g+","+p+")"});break;case"left":k+=i+c+v,u.attr("transform",(e,r)=>{const d=s*w.length/2,g=-f-(i+c),p=r*s-d;return"translate("+g+","+p+")"}),x.attr("transform",()=>`translate(${v+i+c}, 0)`);break;case"right":default:k+=i+c+v,u.attr("transform",(e,r)=>{const d=s*w.length/2,g=12*i,p=r*s-d;return"translate("+g+","+p+")"});break}const G=((I=K.node())==null?void 0:I.getBoundingClientRect().width)??0,Y=S/2-G/2,tt=S/2+G/2,N=Math.min(0,Y),B=Math.max(k,tt)-N;b.attr("viewBox",`${N} 0 ${B} ${y}`),pt(b,y,B,h.useMaxWidth)},"draw"),Ft={draw:zt},Bt={parser:At,db:j,renderer:Ft,styles:kt};export{Bt as diagram};
