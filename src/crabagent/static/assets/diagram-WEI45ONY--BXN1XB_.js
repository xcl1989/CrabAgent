import{p as k}from"./chunk-JWPE2WC7-Cz36UT0K.js";import{aE as F,M as R,Q as E,aH as I,N as D,aF as _,a as c,aD as P,n as z,m as y,O as w,F as G,aj as B,a0 as W,w as H}from"./mermaid.core-CH-7_Ozz.js";import{p as V}from"./cynefin-VYW2F7L2-Dhd78qQW.js";import"./index-ByQ8w0Zg.js";import"./vendor-react-BEFBu0qs.js";import"./vendor-ui-CGcz8alN.js";import"./vendor-charts-BLKufy57.js";import"./vendor-markdown-C0jI_Wfn.js";var x={showLegend:!0,ticks:5,max:null,min:0,graticule:"circle"},C={axes:[],curves:[],options:x},m=structuredClone(C),j=G.radar,N=c(()=>y({...j,...w().radar}),"getConfig"),b=c(()=>m.axes,"getAxes"),Q=c(()=>m.curves,"getCurves"),U=c(()=>m.options,"getOptions"),X=c(a=>{m.axes=a.map(t=>({name:t.name,label:t.label??t.name}))},"setAxes"),Y=c(a=>{m.curves=a.map(t=>({name:t.name,label:t.label??t.name,entries:Z(t.entries)}))},"setCurves"),Z=c(a=>{if(a[0].axis==null)return a.map(e=>e.value);const t=b();if(t.length===0)throw new Error("Axes must be populated before curves for reference entries");return t.map(e=>{const r=a.find(n=>{var s;return((s=n.axis)==null?void 0:s.$refText)===e.name});if(r===void 0)throw new Error("Missing entry for axis "+e.label);return r.value})},"computeCurveEntries"),q=c(a=>{var e,r,n,s,l;const t=a.reduce((o,i)=>(o[i.name]=i,o),{});m.options={showLegend:((e=t.showLegend)==null?void 0:e.value)??x.showLegend,ticks:((r=t.ticks)==null?void 0:r.value)??x.ticks,max:((n=t.max)==null?void 0:n.value)??x.max,min:((s=t.min)==null?void 0:s.value)??x.min,graticule:((l=t.graticule)==null?void 0:l.value)??x.graticule}},"setOptions"),J=c(()=>{z(),m=structuredClone(C)},"clear"),$={getAxes:b,getCurves:Q,getOptions:U,setAxes:X,setCurves:Y,setOptions:q,getConfig:N,clear:J,setAccTitle:_,getAccTitle:D,setDiagramTitle:I,getDiagramTitle:E,getAccDescription:R,setAccDescription:F},K=c(a=>{k(a,$);const{axes:t,curves:e,options:r}=a;$.setAxes(t),$.setCurves(e),$.setOptions(r)},"populate"),tt={parse:c(async a=>{const t=await V("radar",a);B.debug(t),K(t)},"parse")},et=c((a,t,e,r)=>{const n=r.db,s=n.getAxes(),l=n.getCurves(),o=n.getOptions(),i=n.getConfig(),d=n.getDiagramTitle(),p=P(t),u=at(p,i),g=o.max??Math.max(...l.map(f=>Math.max(...f.entries))),h=o.min,v=Math.min(i.width,i.height)/2;rt(u,s,v,o.ticks,o.graticule),nt(u,s,v,i),A(u,s,l,h,g,o.graticule,i),T(u,l,o.showLegend,i),u.append("text").attr("class","radarTitle").text(d).attr("x",0).attr("y",-i.height/2-i.marginTop)},"draw"),at=c((a,t)=>{const e=t.width+t.marginLeft+t.marginRight,r=t.height+t.marginTop+t.marginBottom,n={x:t.marginLeft+t.width/2,y:t.marginTop+t.height/2};return H(a,r,e,t.useMaxWidth??!0),a.attr("viewBox",`0 0 ${e} ${r}`).attr("overflow","visible"),a.append("g").attr("transform",`translate(${n.x}, ${n.y})`)},"drawFrame"),rt=c((a,t,e,r,n)=>{if(n==="circle")for(let s=0;s<r;s++){const l=e*(s+1)/r;a.append("circle").attr("r",l).attr("class","radarGraticule")}else if(n==="polygon"){const s=t.length;for(let l=0;l<r;l++){const o=e*(l+1)/r,i=t.map((d,p)=>{const u=2*p*Math.PI/s-Math.PI/2,g=o*Math.cos(u),h=o*Math.sin(u);return`${g},${h}`}).join(" ");a.append("polygon").attr("points",i).attr("class","radarGraticule")}}},"drawGraticule"),nt=c((a,t,e,r)=>{const n=t.length;for(let s=0;s<n;s++){const l=t[s].label,o=2*s*Math.PI/n-Math.PI/2,i=Math.cos(o),d=Math.sin(o);a.append("line").attr("x1",0).attr("y1",0).attr("x2",e*r.axisScaleFactor*i).attr("y2",e*r.axisScaleFactor*d).attr("class","radarAxisLine");const p=i>.01?"start":i<-.01?"end":"middle",u=d>.01?"hanging":d<-.01?"auto":"central",g=4;a.append("text").text(l).attr("x",e*r.axisLabelFactor*i+g*i).attr("y",e*r.axisLabelFactor*d+g*d).attr("text-anchor",p).attr("dominant-baseline",u).attr("class","radarAxisLabel")}},"drawAxes");function A(a,t,e,r,n,s,l){const o=t.length,i=Math.min(l.width,l.height)/2;e.forEach((d,p)=>{if(d.entries.length!==o)return;const u=d.entries.map((g,h)=>{const v=2*Math.PI*h/o-Math.PI/2,f=M(g,r,n,i),O=f*Math.cos(v),S=f*Math.sin(v);return{x:O,y:S}});s==="circle"?a.append("path").attr("d",L(u,l.curveTension)).attr("class",`radarCurve-${p}`):s==="polygon"&&a.append("polygon").attr("points",u.map(g=>`${g.x},${g.y}`).join(" ")).attr("class",`radarCurve-${p}`)})}c(A,"drawCurves");function M(a,t,e,r){const n=Math.min(Math.max(a,t),e);return r*(n-t)/(e-t)}c(M,"relativeRadius");function L(a,t){const e=a.length;let r=`M${a[0].x},${a[0].y}`;for(let n=0;n<e;n++){const s=a[(n-1+e)%e],l=a[n],o=a[(n+1)%e],i=a[(n+2)%e],d={x:l.x+(o.x-s.x)*t,y:l.y+(o.y-s.y)*t},p={x:o.x-(i.x-l.x)*t,y:o.y-(i.y-l.y)*t};r+=` C${d.x},${d.y} ${p.x},${p.y} ${o.x},${o.y}`}return`${r} Z`}c(L,"closedRoundCurve");function T(a,t,e,r){if(!e)return;const n=(r.width/2+r.marginRight)*3/4,s=-(r.height/2+r.marginTop)*3/4,l=20;t.forEach((o,i)=>{const d=a.append("g").attr("transform",`translate(${n}, ${s+i*l})`);d.append("rect").attr("width",12).attr("height",12).attr("class",`radarLegendBox-${i}`),d.append("text").attr("x",16).attr("y",0).attr("class","radarLegendText").text(o.label)})}c(T,"drawLegend");var st={draw:et},ot=c((a,t)=>{let e="";for(let r=0;r<a.THEME_COLOR_LIMIT;r++){const n=a[`cScale${r}`];e+=`
		.radarCurve-${r} {
			color: ${n};
			fill: ${n};
			fill-opacity: ${t.curveOpacity};
			stroke: ${n};
			stroke-width: ${t.curveStrokeWidth};
		}
		.radarLegendBox-${r} {
			fill: ${n};
			fill-opacity: ${t.curveOpacity};
			stroke: ${n};
		}
		`}return e},"genIndexStyles"),it=c(a=>{const t=W(),e=w(),r=y(t,e.themeVariables),n=y(r.radar,a);return{themeVariables:r,radarOptions:n}},"buildRadarStyleOptions"),lt=c(({radar:a}={})=>{const{themeVariables:t,radarOptions:e}=it(a);return`
	.radarTitle {
		font-size: ${t.fontSize};
		color: ${t.titleColor};
		dominant-baseline: hanging;
		text-anchor: middle;
	}
	.radarAxisLine {
		stroke: ${e.axisColor};
		stroke-width: ${e.axisStrokeWidth};
	}
	.radarAxisLabel {
		font-size: ${e.axisLabelFontSize}px;
		color: ${e.axisColor};
	}
	.radarGraticule {
		fill: ${e.graticuleColor};
		fill-opacity: ${e.graticuleOpacity};
		stroke: ${e.graticuleColor};
		stroke-width: ${e.graticuleStrokeWidth};
	}
	.radarLegendText {
		text-anchor: start;
		font-size: ${e.legendFontSize}px;
		dominant-baseline: hanging;
	}
	${ot(t,e)}
	`},"styles"),vt={parser:tt,db:$,renderer:st,styles:lt};export{vt as diagram};
