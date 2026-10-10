// @ts-nocheck
import React, { useEffect } from "react";
import "./index.css";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { PLACE_LATLON, fetchCaseStudies, fetchEventsToday, kmBetween, klTime } from "./model";
import { runModel } from "./model";

export default function App() {
  useEffect(() => {
    
(function(){
  var PLACES=[
    {n:"KL Sentral",s:"Transit hub, Brickfields",x:70,y:84},
    {n:"KLCC",s:"Kuala Lumpur City Centre",x:238,y:58},
    {n:"Pavilion KL",s:"Bukit Bintang",x:212,y:96},
    {n:"Mid Valley City",s:"Lembah Pantai",x:104,y:118},
    {n:"Bangsar",s:"Telawi",x:42,y:118},
    {n:"Axiata Arena",s:"Bukit Jalil",x:252,y:160},
    {n:"Sunway Pyramid",s:"Bandar Sunway",x:56,y:162},
    {n:"Sri Petaling",s:"Just outside the Axiata Arena zone",x:194,y:142},
    {n:"Bandar Tasik Selatan",s:"LRT · KTM · KLIA Transit interchange",x:180,y:104},
    {n:"Petaling Jaya SS2",s:"Petaling Jaya",x:30,y:58}
  ];
  var APPS=["Grab","inDrive","GV Ride","Other app"];
  // Filled by the real model (/api/forecast via ./model.ts) — no sample numbers are shown
  var PCT={0:0,15:0,30:0,45:0,60:0};
  var LO ={0:0,15:0,30:0,45:0,60:0};
  var HI ={0:0,15:0,30:0,45:0,60:0};
  var PDROP=0;
  var MODEL=null,MODEL_ERR=null;
  var REAL_EVENTS=[],EVENTS_LOADED=false;  // real events today from /api/events (each with source_url)
  var NEAR_KM=5;   // "event in the area": product choice, information only
  var HERE_KM=1;   // "event right here": ~ the venue's own taxi zone where NYC data measured post-event effects
  // Example event zone for the design prototype (hidden screens); no numbers — real events come from /api/events
  var fsOpener=null,resOpener=null,zoneOpener=null,zoneBox=null;
  var state={from:"Axiata Arena",to:"KL Sentral",active:"from",prevFrom:null,
    quotes:[{app:"Grab",price:28},{app:"inDrive",price:24}],usual:0,rain:false,fromLatLon:null,toLatLon:null};

  function $(id){return document.getElementById(id)}
  function rm(v){return "RM"+v.toFixed(2)}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}

  /* ---------- map ---------- */
  
  var miniMapL = null;
  var bigMapL = null;
  var miniLayers = null;
  var bigLayers = null;
  
  function initMaps() {
    if (!miniMapL) {
      miniMapL = L.map("miniSvg", {zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false}).setView([3.139, 101.686], 11);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors"}).addTo(miniMapL);
      miniLayers = L.layerGroup().addTo(miniMapL);
    }
    if (!bigMapL) {
      bigMapL = L.map("bigSvg", {zoomControl: false, attributionControl: true})  // OSM tile policy: credit required.setView([3.139, 101.686], 12);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors"}).addTo(bigMapL);
      bigLayers = L.layerGroup().addTo(bigMapL);
    }
  }

  function drawMain(animate){
    if(!miniLayers) return;
    miniLayers.clearLayers();
    var a = PLACE_LATLON[state.from];
    var b = PLACE_LATLON[state.to];
    var near = nearEvents()[0];
    var v = near ? {lat: near.lat, lon: near.lon} : null;
    if(a && b) {
      var bounds = L.latLngBounds([ [a.lat, a.lon], [b.lat, b.lon] ]);
      if(v) bounds.extend([v.lat, v.lon]);
      miniMapL.fitBounds(bounds, {padding: [20,20]});
      
      var tempLine = L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {color: "#101410", weight: 4, dashArray: "5, 5"}).addTo(miniLayers);
      fetch("https://router.project-osrm.org/route/v1/driving/" + a.lon + "," + a.lat + ";" + b.lon + "," + b.lat + "?overview=full&geometries=geojson")
        .then(r => r.json())
        .then(data => {
           if(data.routes && data.routes[0]) {
              miniLayers.removeLayer(tempLine);
              var coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
              L.polyline(coords, {color: "#C4F135", weight: 7, opacity: 0.9}).addTo(miniLayers);
              L.polyline(coords, {color: "#101410", weight: 4}).addTo(miniLayers);
              // Re-add markers so they are on top
              L.circleMarker([a.lat, a.lon], {radius: 6, color: "#101410", fillColor: "#C4F135", fillOpacity: 1, weight: 2}).addTo(miniLayers);
              L.circleMarker([b.lat, b.lon], {radius: 6, color: "#101410", fillColor: "#C4F135", fillOpacity: 1, weight: 2}).addTo(miniLayers);
           }
        }).catch(e => console.error(e));

      L.circleMarker([a.lat, a.lon], {radius: 6, color: "#101410", fillColor: "#C4F135", fillOpacity: 1, weight: 2}).addTo(miniLayers);
      L.circleMarker([b.lat, b.lon], {radius: 6, color: "#101410", fillColor: "#C4F135", fillOpacity: 1, weight: 2}).addTo(miniLayers);
    }
    if(v) {
      L.circle([v.lat, v.lon], {radius: HERE_KM*1000, color: "#F26B1D", fillColor: "#F26B1D", fillOpacity: 0.28, weight: 2, className: "zone-o"}).addTo(miniLayers);
      L.circleMarker([v.lat, v.lon], {radius: 6, color: "#101410", fillColor: "#F26B1D", fillOpacity: 0.95, weight: 2}).addTo(miniLayers);
    }
  }
  // Route time + distance: TomTom traffic-aware "leave now" (via /api/forecast) when the API has it,
  // else the OSRM/OpenStreetMap route, which has no traffic. Minutes and km only — no fare.
  var OSRM_ROUTE = null, routeLine = null, MODEL_ROUTE = "";
  function routeKey(){return JSON.stringify([state.from, state.to, state.fromLatLon || null, state.toLatLon || null])}
  function routeText(){
    var t = MODEL && MODEL_ROUTE === routeKey() && MODEL.traffic;  // only the forecast for this exact route
    if(t && t.minutes && t.minutes["0"] != null && t.km != null)
      return {html: "<b>" + Math.round(t.minutes["0"]) + " min</b> now with traffic · " + t.km.toFixed(1) + " km",
              src: "TomTom traffic prediction"};
    if(OSRM_ROUTE) return {html: "<b>" + OSRM_ROUTE.min + " min</b> without traffic · " + OSRM_ROUTE.km.toFixed(1) + " km",
                           src: "OpenStreetMap route"};
    return null;
  }
  function showRouteStats(){
    var r = routeText(), rs = document.getElementById("routeStats");
    if(rs) rs.innerHTML = r ? '<span>' + r.html + ' <span style="opacity:.6">· ' + esc(r.src) + '</span></span>' : "";
    if(routeLine){
      routeLine.unbindTooltip();
      if(r) routeLine.bindTooltip(r.html, {permanent: true, direction: "center", className: "map-label"}).openTooltip();
    }
  }
  function drawBig(){
    if(!bigLayers) return;
    bigLayers.clearLayers();
    OSRM_ROUTE = null; routeLine = null; showRouteStats();
    var a = PLACE_LATLON[state.from];
    var b = PLACE_LATLON[state.to];
    if(a && b && state.from !== state.to) {
      var tempLine = L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {color: "#101410", weight: 4, dashArray: "5, 5"}).addTo(bigLayers);
      fetch("https://router.project-osrm.org/route/v1/driving/" + a.lon + "," + a.lat + ";" + b.lon + "," + b.lat + "?overview=full&geometries=geojson")
        .then(r => r.json())
        .then(data => {
           if(data.routes && data.routes[0]) {
              bigLayers.removeLayer(tempLine);
              var coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
              L.polyline(coords, {color: "#C4F135", weight: 8, opacity: 0.9}).addTo(bigLayers);
              L.polyline(coords, {color: "#101410", weight: 4}).addTo(bigLayers);
              OSRM_ROUTE = {min: Math.round(data.routes[0].duration / 60), km: data.routes[0].distance / 1000};
              routeLine = L.polyline(coords, {opacity: 0}).addTo(bigLayers);  // anchor for the route label
              showRouteStats();
           }
        }).catch(e => console.error(e));
    }
    REAL_EVENTS.forEach(function(e){  // real venues today (source-linked in the event sheet)
      var ring = L.circle([e.lat, e.lon], {radius: HERE_KM*1000, color: "#F26B1D", fillColor: "#F26B1D", fillOpacity: 0.28, weight: 2.5, className: "zone-o"}).addTo(bigLayers);
      ring.on("click", function(){ openZone($("zoneChip")); });
      var mk = L.circleMarker([e.lat, e.lon], {radius: 9, color: "#101410", fillColor: "#F26B1D", fillOpacity: 0.95, weight: 2}).addTo(bigLayers);
      mk.bindTooltip(e.name.length > 28 ? e.name.slice(0, 27) + "…" : e.name, {direction: "top", offset: [0, -8]});
      mk.on("click", function(){ openZone($("zoneChip")); });
    });
    Object.keys(PLACE_LATLON).forEach(name => {
       var p = PLACE_LATLON[name];
       var isFrom = name === state.from, isTo = name === state.to;
       var color = (isFrom || isTo) ? "#C4F135" : "#fff";
       var radius = (isFrom || isTo) ? 8 : 5;
       var marker = L.circleMarker([p.lat, p.lon], {radius: radius, color: "#101410", fillColor: color, fillOpacity: 1, weight: 2}).addTo(bigLayers);
       marker.bindTooltip(name, {permanent: true, direction: "top", className: "map-label", offset: [0, -10]});
       marker.on("click", function() {
          if (state.active === "from") { state.prevFrom = state.from; state.from = name; }
          else { state.to = name; }
          drawBig(); syncFields(true); renderPrediction();
       });
    });
    var ne = nearEvents()[0];
    if(a && ne) {  // keep the whole 1 km radar circle in view, with pickup and destination
      var vb = L.latLngBounds([[a.lat, a.lon]]).extend(L.latLng(ne.lat, ne.lon).toBounds(HERE_KM*2000));
      if(b) vb.extend([b.lat, b.lon]);
      // keep clear of the search card + chip (top) and the place list sheet (bottom)
      bigMapL.fitBounds(vb, {paddingTopLeft: [30, 170], paddingBottomRight: [30, 290], maxZoom: 15});
    } else if(a) bigMapL.setView([a.lat, a.lon], 12);
  }

  /* ---------- fields ---------- */
  function syncFields(animate){
    $("vFrom").textContent=state.from;
    $("vTo").textContent=state.to;
    drawMain(animate);
  }

  /* ---------- fullscreen map ---------- */
  function setActive(w){
    state.active=w;
    $("rowFrom").classList.toggle("act",w==="from");
    $("rowTo").classList.toggle("act",w==="to");
    $("hint").textContent=w==="from"?"Choose pickup":"Choose destination";
    renderList("");
  }
    var searchTimer = null;
  function renderList(q){
    q=(q||"").toLowerCase();
    var other=state.active==="from"?state.to:state.from;
    
    // Always show local favorites first
    var localItems=PLACES.filter(function(p){return p.n!==other&&(p.n.toLowerCase().indexOf(q)>-1||p.s.toLowerCase().indexOf(q)>-1)});
    
    function renderHTML(items) {
      $("plist").innerHTML=items.length?items.map(function(p){
        return '<li><button type="button" data-p="'+esc(p.n)+'"><span class="pi"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#101410" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></span><span>'+esc(p.n)+'<small>'+esc(p.s)+'</small></span></button></li>';
      }).join(""):'<li class="empty">No match. Try another name.</li>';
    }

    if (q.length < 3) {
      renderHTML(localItems);
      return;
    }
    
    // Show loading state while typing
    $("plist").innerHTML = '<li class="empty">Searching map...</li>';
    
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
       fetch("https://nominatim.openstreetmap.org/search?format=json&q=" + encodeURIComponent(q) + "&countrycodes=my&limit=5")
         .then(r => r.json())
         .then(data => {
            var webItems = data.map(d => {
               var parts = d.display_name.split(",");
               var name = parts[0].trim();
               var sub = parts.slice(1, 3).join(",").trim();
               // Dynamically register into PLACE_LATLON so the map can route to it!
               PLACE_LATLON[name] = { lat: parseFloat(d.lat), lon: parseFloat(d.lon) };
               return { n: name, s: sub, x: 0, y: 0 };
            });
            // Combine local matches and web matches
            var combined = localItems.slice();
            webItems.forEach(w => { if(!combined.find(c => c.n === w.n)) combined.push(w); });
            renderHTML(combined);
         }).catch(e => {
            renderHTML(localItems);
         });
    }, 500);
  }
  function openFs(which,opener,noFocus){
    fsOpener=opener||document.activeElement;
    $("qFrom").value=state.from;$("qTo").value=state.to;
    setActive(which);drawBig();
    $("fs").classList.add("on");$("phone").classList.add("mapopen");$("fs").setAttribute("aria-hidden","false");
    if(!noFocus)setTimeout(function(){var i=$(which==="from"?"qFrom":"qTo");i.focus({preventScroll:true});i.select()},240);
  }
  function closeFs(noFocus){
    $("phone").classList.remove("mapopen");$("fs").classList.remove("on");$("fs").setAttribute("aria-hidden","true");syncFields(true);
    if(!noFocus&&fsOpener&&document.body.contains(fsOpener))fsOpener.focus({preventScroll:true});
  }
  function syncFsFields(){
    if(!$("fs").classList.contains("on"))return;
    $("qFrom").value=state.from;$("qTo").value=state.to;drawBig();renderList("");
  }
  function pick(name){
    state[state.active]=name;
    $(state.active==="from"?"qFrom":"qTo").value=name;
    drawBig();
    if(state.active==="from"){setActive("to");$("qTo").focus({preventScroll:true});$("qTo").select()}
    else renderList("");
  }
  $("fFrom").onclick=function(){openFs("from",this)};
  $("fTo").onclick=function(){openFs("to",this)};
  $("miniMap").onclick=function(){openFs("to",this)};
  $("closeFs").onclick=function(){closeFs()};
  $("confirm").onclick=function(){closeFs();toast("Route set")};
  ["From","To"].forEach(function(k){
    var w=k.toLowerCase(),inp=$("q"+k);
    inp.addEventListener("focus",function(){setActive(w);inp.select()});
    inp.addEventListener("input",function(){renderList(inp.value)});
  });
  $("plist").addEventListener("click",function(e){
    var b=e.target.closest("button[data-p]");if(b)pick(b.getAttribute("data-p"));
  });
  $("bigSvg").addEventListener("click",function(e){
    var g=e.target.closest("g[data-p]");
    if(g){pick(g.getAttribute("data-p"));return}
    var z=e.target.closest("g[data-zone]");
    if(z)openZone(z);
  });
  $("bigSvg").addEventListener("keydown",function(e){
    if(e.key!=="Enter"&&e.key!==" ")return;
    var g=e.target.closest("g[data-p]");
    if(g){e.preventDefault();pick(g.getAttribute("data-p"));return}
    var z=e.target.closest("g[data-zone]");
    if(z){e.preventDefault();openZone(z)}
  });
  $("zoneChip").onclick=function(){openZone(this)};
  $("swap").onclick=function(){var t=state.from;state.from=state.to;state.to=t;syncFields(true)};

  /* ---------- quotes ---------- */
  function renderQuotes(){
    $("quotes").innerHTML=state.quotes.map(function(q,i){
      var opts=APPS.map(function(a){return '<option'+(a===q.app?' selected':'')+'>'+a+'</option>'}).join("");
      var ini=q.app==="Other app"?"?":q.app.charAt(0).toUpperCase()+(q.app==="GV Ride"?"V":q.app==="inDrive"?"D":"");
      return '<div class="qrow">'+
        '<div class="sel"><span class="av">'+esc(ini)+'</span><select id="app'+i+'" data-i="'+i+'" aria-label="E-hailing app '+(i+1)+'">'+opts+'</select>'+
        '<svg class="car" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#101410" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></div>'+
        '<div class="amt"><span>RM</span><input id="price'+i+'" data-i="'+i+'" type="number" inputmode="decimal" min="0" step="0.5" value="'+q.price+'" aria-label="Price shown in '+esc(q.app)+'"></div>'+
        (state.quotes.length>1?'<button class="x" type="button" data-rm="'+i+'" aria-label="Remove '+esc(q.app)+'"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>':'')+
      '</div>';
    }).join("");
    $("addApp").disabled=state.quotes.length>=APPS.length;
    $("bidNote").hidden=!state.quotes.some(function(q){return q.app==="inDrive"});
  }
  $("quotes").addEventListener("input",function(e){
    var t=e.target;if(t.tagName!=="INPUT")return;
    var v=parseFloat(t.value);state.quotes[+t.dataset.i].price=isFinite(v)&&v>0?v:0;renderPrediction();
  });
  $("quotes").addEventListener("change",function(e){
    var t=e.target;if(t.tagName!=="SELECT")return;
    state.quotes[+t.dataset.i].app=t.value;renderQuotes();renderPrediction();
  });
  $("quotes").addEventListener("click",function(e){
    var b=e.target.closest("button[data-rm]");if(!b)return;
    state.quotes.splice(+b.dataset.rm,1);renderQuotes();renderPrediction();
  });
  $("usual").addEventListener("input",function(){var v=parseFloat(this.value);state.usual=isFinite(v)&&v>0?v:0;renderPrediction()});
  $("rain").addEventListener("change",function(){state.rain=this.checked;renderPrediction()});
  $("addApp").onclick=function(){
    var used=state.quotes.map(function(q){return q.app});
    var next=APPS.filter(function(a){return used.indexOf(a)<0})[0];
    if(!next)return;
    state.quotes.push({app:next,price:26});renderQuotes();renderPrediction();
  };

  /* ---------- prediction ---------- */
  var bestMin=30;
  function hhmm(min){
    var d=new Date(Date.now()+min*60000);
    return d.toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",hour12:false});
  }
  function renderChart(){
    var W=320,H=150,L=34,R=14,T=16,B=26;
    // scale fits the forecast and its range in both directions (prices can be predicted to rise or fall)
    var ks0=[0,15,30,45,60],hiV=Math.max.apply(0,ks0.map(function(k){return HI[k]})),loV=Math.min.apply(0,ks0.map(function(k){return LO[k]}));
    var ymax=Math.max(6,Math.ceil((hiV+2)/5)*5),ymin=Math.min(-12,Math.floor((loV-2)/5)*5);
    var xs={0:L,15:L+(W-L-R)*0.25,30:L+(W-L-R)*0.5,45:L+(W-L-R)*0.75,60:W-R};
    function y(v){return T+(ymax-v)/(ymax-ymin)*(H-T-B)}
    var ks=[0,15,30,45,60],o="";
    var grid=[];for(var g0=Math.ceil(ymin/10)*10;g0<=ymax;g0+=10)grid.push(g0);
    grid.forEach(function(g){
      o+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(g)+'" y2="'+y(g)+'" stroke="'+(g===0?'#5B6755':'#D6E7BD')+'" stroke-width="1" '+(g===0?'stroke-dasharray="3 3"':'')+'/>'+
           '<text x="'+(L-6)+'" y="'+(y(g)+3.5)+'" text-anchor="end">'+(g===0?'0%':(g>0?'+':'')+g+'%')+'</text>';
    });
    var up=ks.map(function(k){return xs[k]+","+y(HI[k])}).join(" ");
    var dn=ks.slice().reverse().map(function(k){return xs[k]+","+y(LO[k])}).join(" ");
    o+='<polygon points="'+up+" "+dn+'" fill="rgba(196,241,53,.6)"/>';
    o+='<polyline points="'+ks.map(function(k){return xs[k]+","+y(PCT[k])}).join(" ")+'" fill="none" stroke="#101410" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
    ks.forEach(function(k){
      var best=k===bestMin;
      o+='<circle cx="'+xs[k]+'" cy="'+y(PCT[k])+'" r="'+(best?7:4)+'" fill="'+(best?'#C4F135':'#101410')+'" stroke="#101410" stroke-width="'+(best?3:0)+'"/>';
      if(k>0)o+='<text class="val" x="'+xs[k]+'" y="'+(y(PCT[k])+(best?22:17))+'" text-anchor="middle">'+(PCT[k]>0?'+':'')+PCT[k]+'%</text>';
      o+='<text x="'+xs[k]+'" y="'+(H-6)+'" text-anchor="middle">'+(k===0?"Now":"+"+k+"m")+'</text>';
    });
    $("chart").innerHTML=o;
  }
  /* ---------- real model (./model.ts → /api/forecast) ---------- */
  function applyModel(r){
    r.horizon.forEach(function(h){PCT[h.minutes]=Math.round(h.pct_change*100);LO[h.minutes]=Math.round(h.pct_low*100);HI[h.minutes]=Math.round(h.pct_high*100)});
    // ring = chance at the advised wait (Wait X min), else the 30-min headline chance
    var hw=r.decision==="wait"?r.horizon.filter(function(h){return h.minutes===r.wait_minutes})[0]:null;
    PDROP=hw?hw.p_drop10:r.wait_odds.p_save10;
    var lbl=$("pDropLbl");if(lbl)lbl.innerHTML="drop ≥10%<br>in "+(hw?r.wait_minutes:30)+" min";
    bestMin=r.decision==="wait"?r.wait_minutes:0;
  }
  function requestModel(){
    var rk = routeKey();
    runModel({from:state.from,fromLatLon:state.fromLatLon,to:state.to,toLatLon:state.toLatLon,quotes:state.quotes,usual:state.usual,rain:state.rain})
      .then(function(r){if(r!==MODEL){MODEL=r;MODEL_ERR=null;applyModel(r);remaining=bestMin*60;tick();renderPrediction(true)}MODEL_ROUTE=rk;showRouteStats();if(EARN_PENDING){EARN_PENDING=false;awardForecast()}})
      .catch(function(e){MODEL=null;MODEL_ERR=String(e);renderPrediction(true)});
  }
  function realOnly(){
    if(!MODEL){$("why").innerHTML='<div class="empty">'+esc(MODEL_ERR?"Model offline: start the API (scripts/run_demo.sh).":"Asking the model…")+'</div>';return}
    // reasons → short icon rows; the odds and "Wait" reasons are already on the decision card
    var I={clock:'<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/>',car:'<path d="M5 16v-5l1.7-4.5A2 2 0 0 1 8.6 5h6.8a2 2 0 0 1 1.9 1.5L19 11v5M5 16h14M5 16v2.5M19 16v2.5"/>',
      rain:'<path d="M7 15a4 4 0 1 1 1.2-7.8A5 5 0 0 1 17.5 9 3.5 3.5 0 0 1 17 16H7z"/><path d="M9 19l-1 2M13 19l-1 2M17 19l-1 2"/>',
      tag:'<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.3"/>',cal:'<rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
      info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>'};
    function row(icon,title,text,extra){text=text.charAt(0).toUpperCase()+text.slice(1);return '<div class="wr"><span class="wi">'+ic(I[icon])+'</span><div><b>'+esc(title)+'</b><p>'+esc(text)+'</p>'+(extra||"")+'</div></div>'}
    var html=MODEL.reasons.map(function(t){
      if(/^Chance that waiting|^Wait \d+ min:|^Event (right here|in the area|today|nearby)/.test(t))return "";
      if(/^Book now — jam coming|^Traffic/.test(t))return row("car","Traffic",t.replace(/^Traffic: /,""));
      if(/^Book now/.test(t))return row("clock","Why book now",t.replace(/^Book now: /,""));
      if(/^Odds of a drop/.test(t))return row("clock","Why book now",t);
      if(/^Your quote is/.test(t))return row("tag","Your price",t);
      if(/^Why so pricey\?/.test(t))return row("tag","Why so pricey?",t.replace(/^Why so pricey\? /,""));
      if(/^No usual price/.test(t))return row("tag","No usual price",t.replace(/^No usual price given: /,"Without it, "));
      if(t==="rain"||t==="no rain")return row("rain","Weather",t==="rain"?"Raining (you set Rain on)":"No rain");
      if(/^Event ending right here: /.test(t))return row("cal","Event ending",t.replace(/^Event ending right here: /,""));
      return row("info","Note",t);
    }).join("");
    html+=MODEL.events.map(function(e){
      var lv=e.level==="right_here"?"Event right here":e.level==="in_area"?"Event in the area":"Event today";
      return row("cal",lv+(e.km!=null?" · "+e.km.toFixed(1)+" km":""),e.name,'<small><a href="'+esc(e.source_url)+'" target="_blank" rel="noopener">Source</a> · effect on price not measured in Malaysia</small>')}).join("");
    html+='<div class="why-src">Model '+esc(MODEL.model_version)+', tested on real ride data (reports/metrics.md) + your typed prices</div>';
    $("why").innerHTML=html;
    renderFareReport();
  }
  var DEFAULT_QUOTES=JSON.stringify(state.quotes);
  function renderPrediction(fromModel){
    if(!fromModel)requestModel();
    if($("exTag"))$("exTag").hidden=JSON.stringify(state.quotes)!==DEFAULT_QUOTES;  // "Example prices" until you type yours
    renderRadar();  // pickup may have changed
    var mult=1+PCT[bestMin]/100,o=MODEL&&MODEL.wait_odds;
    var cdBox=$("cd")&&$("cd").parentNode;if(cdBox)cdBox.hidden=!(MODEL&&MODEL.decision==="wait");
    $("dTitle").textContent=!MODEL?(MODEL_ERR?"Model offline":"Predicting…"):MODEL.decision==="wait"?"Wait "+bestMin+" min":"Book now";
    // situation + urgency (API labels on the model outputs; no extra numbers)
    var SIT={jam_coming:"Jam coming",event_exit:"Event ending nearby",surge:"Surge: ≥1.5× your usual",pricey:"Pricier than usual",rush_hour:"Prices edging up",normal:"Normal moment"};
    var URG={urgent:"Urgent: book soon",wait:"Worth waiting",no_gain:"No gain from waiting"};
    $("dChips").innerHTML=MODEL&&MODEL.situation?'<span class="chip sit">'+esc(SIT[MODEL.situation]||"")+'</span><span class="chip urg '+esc(MODEL.urgency)+'">'+esc(URG[MODEL.urgency]||"")+'</span>':"";
    var tung=MODEL&&MODEL.decision==="wait"?MODEL.reasons.filter(function(t){return t.indexOf("Wait ")===0})[0]:null;
    $("dText").textContent=!MODEL?(MODEL_ERR?"Start the API (scripts/run_demo.sh) and try again.":"Asking the model…"):
      tung?(function(t){return t.charAt(0).toUpperCase()+t.slice(1)})(tung.replace(/^Wait \d+ min: /,""))+".":
      "Chance the price drops ≥10% if you wait 30 min: "+Math.round(o.p_save10*100)+"% (usual "+Math.round(o.typical_p_save10*100)+"%). In 30 min likely "+sg(Math.round(o.pct_low*100))+"% to "+sg(Math.round(o.pct_high*100))+"%.";
    $("rt").textContent=bestMin===0?"Your apps now":"Your apps: now vs "+hhmm(bestMin);
    $("pDrop").textContent=Math.round(PDROP*100)+"%";
    $("ringArc").style.strokeDashoffset=String(263.9*(1-PDROP));
    var rows=state.quotes.filter(function(q){return q.price>0}).map(function(q){return{app:q.app,now:q.price,later:q.price*mult}});
    rows.sort(function(a,b){return a.later-b.later});
    $("rank").innerHTML=rows.length?rows.map(function(r,i){
      var ini=r.app==="Other app"?"?":r.app.charAt(0).toUpperCase()+(r.app==="GV Ride"?"V":r.app==="inDrive"?"D":"");
      return '<div class="rk'+(i===0?' best':'')+'"><span class="av">'+esc(ini)+'</span><span><b>'+esc(r.app)+'</b><small>'+(i===0?(bestMin===0?"Cheapest now":"Cheapest at "+hhmm(bestMin)):bestMin===0?rm(r.now-rows[0].now)+" more than "+esc(rows[0].app):"Now "+rm(r.now))+'</small></span>'+
        (bestMin===0?'<span class="p"><strong>'+rm(r.now)+'</strong></span></div>':
        '<span class="p"><s>'+rm(r.now)+'</s><strong>'+rm(r.later)+'</strong><em>Save '+rm(r.now-r.later)+'</em></span></div>');
    }).join(""):'<div class="empty">Enter at least one price to see your apps ranked.</div>';
    renderChart();realOnly();
  }
  function sg(v){return (v>0?"+":v<0?"\u2212":"")+Math.abs(v)}
  function ic(p){return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p+'</svg>'}
  var ICON_CHECK='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  var ICON_WARN='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#B8470C" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.01"/></svg>';



  /* ---------- ride + train ---------- */



  /* ---------- surge zone sheet ---------- */
  function pickupLL(){return state.fromLatLon||PLACE_LATLON[state.from]||null}
  function nearEvents(){
    var a=pickupLL();if(!a)return [];
    return REAL_EVENTS.map(function(e){return Object.assign({km:kmBetween(a,e)},e)})
      .filter(function(e){return e.km<=NEAR_KM}).sort(function(x,y){return x.km-y.km});
  }
  function evWhen(e){return klTime(e.start)+(e.end?"–"+klTime(e.end):" (end not published)")}
  function renderRadar(){
    var near=nearEvents(),t=$("radarText"),g=$("radarTag");
    if(!t)return;
    if(!EVENTS_LOADED){t.textContent="Loading real events…";return}
    if(near.length){
      var e=near[0];
      t.textContent=(e.km<=HERE_KM?"Right here: ":"In the area: ")+e.name+" · "+e.venue+" · "+evWhen(e)+" · "+e.km.toFixed(1)+" km from your pickup"+(near.length>1?" (+"+(near.length-1)+" more)":"");
    }else t.textContent=REAL_EVENTS.length?"No events within "+NEAR_KM+" km of your pickup today · "+REAL_EVENTS.length+" in Klang Valley":"No events listed for today";
    if(g)g.textContent=REAL_EVENTS.length?REAL_EVENTS.length+" today":"Today";
    $("chipText").textContent=near.length?(near[0].km<=HERE_KM?"Event right here · ":"Event in the area · ")+near[0].name:"Events today · "+REAL_EVENTS.length;
  }
  function renderZoneSheet(){
    // Real events today with sources; no price effect is shown (only validated for NYC baseball)
    var a=pickupLL(),list=REAL_EVENTS.map(function(e){return Object.assign({km:a?kmBetween(a,e):null},e)})
      .sort(function(x,y){return (x.km==null?1e9:x.km)-(y.km==null?1e9:y.km)});
    var head='<div class="zs-head"><div><div class="zs-eyebrow"><span class="k2">Event radar</span><span class="tag">Real events</span></div>'+
      '<h3 id="zsTitle">Events today</h3><div class="zs-meta">From '+esc(state.from)+' · right here ≤ '+HERE_KM+' km · in the area ≤ '+NEAR_KM+' km</div></div>'+
      '<button class="x" id="zsClose" type="button" aria-label="Close event list"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>';
    var rows=list.length?list.map(function(e){
      var here=e.km!=null&&e.km<=HERE_KM,area=e.km!=null&&e.km<=NEAR_KM;
      var lvl=here?"Right here (within "+HERE_KM+" km)":area?"In the area (within "+NEAR_KM+" km)":"Further away";
      return '<div class="zs-status '+(here?'in':'out')+'">'+(here?ICON_WARN:ICON_CHECK)+'<span><b>'+esc(e.name)+'</b><br>'+esc(e.venue)+' · '+esc(evWhen(e))+
        (e.km!=null?' · '+e.km.toFixed(1)+' km':'')+'<br><small>'+lvl+'</small> · <a href="'+esc(e.source_url)+'" target="_blank" rel="noopener">Source</a></span></div>';
    }).join(""):'<div class="empty">No real events listed for today.</div>';
    var note='<div class="zs-sec"><p class="sub">The orange '+HERE_KM+' km circle on the map is about the area where our training data saw prices '+
      'rise right after big games. It has not been measured in Malaysia, so no % is shown. '+
      'Each event links to its source.</p></div>';
    var acts='<div class="zs-acts"><button class="go" id="zsForecast" type="button">See forecast</button><button class="ghost" id="zsGot" type="button">Got it</button></div>';
    $("zsBody").innerHTML=head+rows+note+acts;
  }
  function openZone(opener){
    zoneOpener=opener||document.activeElement;
    var box=zoneOpener&&zoneOpener.closest?zoneOpener.closest("#bigSvg"):null;
    zoneBox=box?box.id:null;
    renderZoneSheet();
    $("zoneScrim").classList.add("on");$("zoneSheet").classList.add("on");$("zoneSheet").setAttribute("aria-hidden","false");
    setTimeout(function(){var c=$("zsClose");if(c)c.focus({preventScroll:true})},60);
  }
  function closeZone(noFocus){
    $("zoneScrim").classList.remove("on");$("zoneSheet").classList.remove("on");$("zoneSheet").setAttribute("aria-hidden","true");
    if(noFocus)return;
    var o=zoneOpener;
    if(o&&document.body.contains(o)){o.focus({preventScroll:true});return}
    var b=zoneBox?$(zoneBox):null,t=b&&(b.querySelector("[data-zone]")||b.querySelector("button"));
    if(t)t.focus({preventScroll:true});
  }
  $("zoneScrim").onclick=function(){closeZone()};
  $("zoneSheet").addEventListener("click",function(e){
    var t=e.target.closest("button");if(!t)return;
    if(t.id==="zsClose"||t.id==="zsGot")closeZone();
    else if(t.id==="zsForecast"){closeZone(true);if($("fs").classList.contains("on"))closeFs(true);openRes($("predict"))}
  });

  /* ---------- forecast screen ---------- */
  function reduced(){return !!(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches)}
  function openRes(opener){
    resOpener=opener||$("predict");
    setResRoute();
    remaining=bestMin*60;tick();renderPrediction();
    $("res").classList.add("on");$("res").setAttribute("aria-hidden","false");
    $("resScroll").scrollTop=0;
    setTimeout(function(){$("closeRes").focus({preventScroll:true})},240);
  }
  function closeRes(noFocus){
    $("res").classList.remove("on");$("res").setAttribute("aria-hidden","true");
    var o=resOpener||$("predict");
    if(!noFocus&&document.body.contains(o))o.focus({preventScroll:true});
  }
  $("predict").onclick=function(){EARN_PENDING=true;openRes(this)};  // points only for a forecast the user asked for
  $("closeRes").onclick=function(){closeRes()};
  function setResRoute(){$("resRoute").textContent=state.from+" to "+state.to}


  document.addEventListener("keydown",function(e){
    if(e.key!=="Escape")return;
    if($("lb").classList.contains("on")){closeLb();return}
    if($("zoneSheet").classList.contains("on")){closeZone();return}
    if($("fs").classList.contains("on")){closeFs();return}
    if($("res").classList.contains("on"))closeRes();
  });

  var remaining=bestMin*60;
  function tick(){
    var m=Math.floor(remaining/60),s=remaining%60;
    $("cd").textContent=(m<10?"0":"")+m+":"+(s<10?"0":"")+s;
  }
  setInterval(function(){if(remaining>0){remaining--;tick()}},1000);

  /* ---------- nav + toast ---------- */
  var tt;
  function toast(msg){var t=$("toast");t.textContent=msg;t.classList.add("on");clearTimeout(tt);tt=setTimeout(function(){t.classList.remove("on")},1800)}
  document.querySelector(".nav").addEventListener("click",function(e){
    var b=e.target.closest("button[data-go]");if(!b)return;
    document.querySelectorAll(".nav button").forEach(function(x){x.removeAttribute("aria-current")});
    b.setAttribute("aria-current","page");
    var g=b.dataset.go,sc=$("scroll");
    if(g==="top")sc.scrollTo({top:0,behavior:"smooth"});
    else if(g==="events")sc.scrollTo({top:sc.scrollHeight,behavior:"smooth"});
    else if(g==="leaderboard")openLb();
    else toast("Proof: odds tested on 19M real rides (reports/metrics.md)");
  });
  $("eventBtn").onclick=function(){openZone(this)};

  document.documentElement.setAttribute("lang","en");
  $("chipText").textContent="Events today";
  fetchEventsToday().then(function(ev){REAL_EVENTS=ev||[];EVENTS_LOADED=true;renderRadar();drawMain(false);drawBig()})
    .catch(function(){EVENTS_LOADED=true;renderRadar()});
  fetchCaseStudies().then(renderStudies);
  /* ---------- "Booked? Tell us what you paid" (localStorage only; never sent) ---------- */
  var FARE_KEY="", FARE_STORE="whenyah.fares";
  var APP_NAME={grab:"Grab",indrive:"inDrive",gvride:"GV Ride"};
  function fareList(){try{return JSON.parse(localStorage.getItem(FARE_STORE)||"[]")}catch(e){return []}}
  function renderFareReport(){
    var el=$("fareReport");if(!el)return;
    if(!MODEL){FARE_KEY="";el.innerHTML='<div class="empty">Run a forecast first.</div>';return}
    var key=JSON.stringify([state.from,state.to,state.quotes,state.usual,state.rain]);  // one report per forecast input
    if(key===FARE_KEY)return;  // same forecast: keep what the user is typing
    FARE_KEY=key;
    var done=fareList().filter(function(f){return f.key===key})[0];
    if(done){el.innerHTML=fareThanks(done);return}
    var quoted=Object.keys(APP_NAME).filter(function(a){return MODEL.horizon[0].expected_rm[a]!=null});
    var apps=quoted.length?quoted:Object.keys(APP_NAME);
    el.innerHTML='<form class="fare-form" id="fareForm">'+
      '<label>App<select id="fareApp">'+apps.map(function(a){return '<option value="'+a+'">'+APP_NAME[a]+'</option>'}).join("")+'</select></label>'+
      '<label>You paid (RM)<input id="farePaid" type="number" inputmode="decimal" min="1" max="999" step="0.01" placeholder="e.g. 18.50" required></label>'+
      '<button class="go" type="submit">Submit fare</button></form>';
    $("fareForm").onsubmit=function(ev){
      ev.preventDefault();
      var app=$("fareApp").value,paid=parseFloat($("farePaid").value);
      if(!(paid>0&&paid<1000)){toast("Enter the RM amount you paid");return}
      var q=state.quotes.filter(function(x){return x.price>0&&x.app===APP_NAME[app]})[0];
      var hw=MODEL.decision==="wait"?MODEL.horizon.filter(function(h){return h.minutes===MODEL.wait_minutes})[0]:null;
      var f={key:key,at:new Date().toISOString(),from:state.from,to:state.to,app:app,paid:paid,
             quoted:q?q.price:null,decision:MODEL.decision,wait_minutes:MODEL.wait_minutes,
             expected_after_wait:hw&&hw.expected_rm[app]!=null?hw.expected_rm[app]:null};
      try{var all=fareList();all.push(f);localStorage.setItem(FARE_STORE,JSON.stringify(all))}catch(e){}
      el.innerHTML=fareThanks(f);earn(25,"Fare reported");
    };
  }
  /* ---------- points + leaderboard (points saved on this phone; friends are labelled examples) ---------- */
  var PTS_STORE="whenyah.points",DAY_CAP=150,REPEAT_MIN=10,EARN_PENDING=false;
  function klDay(){return new Date(Date.now()+8*3600000).toISOString().slice(0,10)}
  function klWeek(){  // ISO week id in KL time, e.g. "2026-W41"
    var d=new Date(Date.now()+8*3600000);d.setUTCHours(0,0,0,0);d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));
    var y=new Date(Date.UTC(d.getUTCFullYear(),0,1));return d.getUTCFullYear()+"-W"+Math.ceil(((d-y)/86400000+1)/7);
  }
  function ptsLoad(){
    var p;try{p=JSON.parse(localStorage.getItem(PTS_STORE)||"null")}catch(e){p=null}
    p=p||{total:0,week:{id:"",pts:0},day:{date:"",pts:0},routes:{},anchor:{}};
    if(p.week.id!==klWeek())p.week={id:klWeek(),pts:0};
    if(p.day.date!==klDay())p.day={date:klDay(),pts:0};
    return p;
  }
  function ptsSave(p){try{localStorage.setItem(PTS_STORE,JSON.stringify(p))}catch(e){}}
  function ptsShow(){var p=ptsLoad();$("ptsVal").textContent=String(p.total)}
  function earn(n,why){
    var p=ptsLoad(),got=Math.max(0,Math.min(n,DAY_CAP-p.day.pts));
    if(!got){toast("Daily limit reached ("+DAY_CAP+" pts)");return 0}
    p.total+=got;p.week.pts+=got;p.day.pts+=got;ptsSave(p);ptsShow();
    toast("+"+got+" pts · "+why+(got<n?" (daily limit)":""));
    if($("lb").classList.contains("on"))renderLb();
    return got;
  }
  function awardForecast(){  // 10 pts + 5 per extra quoted app (max 3); same route again within 10 min earns nothing
    var n=state.quotes.filter(function(x){return x.price>0}).length;if(!n)return;
    var p=ptsLoad(),rk=routeKey(),now=Date.now();
    if(p.routes[rk]&&now-p.routes[rk]<REPEAT_MIN*60000){toast("No points: same route in the last "+REPEAT_MIN+" min");return}
    p.routes[rk]=now;ptsSave(p);
    var extra=Math.min(3,n-1);
    earn(10+5*extra,extra?"Prices shared ("+n+" apps)":"Forecast run");
  }
  var FRIENDS=[["Aina","#F26B1D"],["Wei Jie","#3D7BE0"],["Priya","#9B5DE5"],["Hafiz","#2A9D8F"],["Mei Ling","#E63973"],["Arjun","#E9A23B"]];
  // Example friends: scores are set once per week (and once for all time) around your points at first look,
  // so you start 3rd, 20 pts behind 2nd. Not real users.
  var OFFSETS={week:[55,20,-6,-12,-19,-25],all:[240,20,-15,-40,-70,-95]};
  var LB_VIEW="week";
  function lbRows(view){
    var p=ptsLoad(),mine=view==="week"?p.week.pts:p.total,ak=view==="week"?p.week.id:"all";
    if(p.anchor[view]==null||p.anchor[view+"_id"]!==ak){p.anchor[view]=mine;p.anchor[view+"_id"]=ak;ptsSave(p)}
    var rows=FRIENDS.map(function(f,i){return {name:f[0],color:f[1],pts:Math.max(0,p.anchor[view]+OFFSETS[view][i]),me:false}});
    rows.push({name:"You",color:"#101410",pts:mine,me:true});
    rows.sort(function(a,b){return b.pts-a.pts||(a.me?-1:b.me?1:0)});  // ties: you first
    return rows;
  }
  function avatar(r,big){
    return '<span class="lb-av'+(big?" big":"")+'" style="background:'+r.color+'">'+esc(r.me?"You":r.name.split(" ").map(function(w){return w[0]}).join(""))+'</span>';
  }
  function renderLb(){
    var rows=lbRows(LB_VIEW),i=rows.findIndex(function(r){return r.me}),me=rows[i],next=i>0?rows[i-1]:null;
    var toggle='<div class="lb-toggle" role="tablist">'+["week","all"].map(function(v){
      return '<button type="button" role="tab" data-view="'+v+'" aria-selected="'+(LB_VIEW===v)+'">'+(v==="week"?"This week":"All time")+'</button>'}).join("")+'</div>';
    var you='<section class="card lb-you">'+avatar(me,true)+'<div><div class="k2">Your rank</div><b class="lb-rank">#'+(i+1)+' of '+rows.length+'</b>'+
      '<small>'+me.pts+' pts'+(next?' · '+(next.pts-me.pts+1)+' pts to pass '+esc(next.name):' · you are on top')+'</small></div></section>';
    var top=rows.slice(0,3),order=[1,0,2];
    var podium='<div class="lb-podium">'+order.map(function(k){var r=top[k];if(!r)return "";
      return '<div class="lb-step s'+(k+1)+(r.me?" me":"")+'">'+avatar(r)+'<b>'+esc(r.name)+'</b><small>'+r.pts+' pts</small><div class="lb-block">'+(k+1)+'</div></div>'}).join("")+'</div>';
    var list='<div class="rank">'+rows.map(function(r,k){
      return '<div class="rk'+(r.me?" best":"")+'"><span class="lb-n">'+(k+1)+'</span><span class="lb-who">'+avatar(r)+'<b>'+esc(r.name)+'</b></span><span class="p"><strong>'+r.pts+'</strong><small> pts</small></span></div>'}).join("")+'</div>';
    var how='<section class="card"><h2>How to earn points</h2><table class="lb-how"><tbody>'+
      '<tr><td>Run a forecast</td><td>10 pts + 5 per extra app quote (up to 3). Same route again within '+REPEAT_MIN+' min: no points.</td></tr>'+
      '<tr><td>Report what you paid</td><td>25 pts, once per forecast</td></tr></tbody></table>'+
      '<p class="sub">Daily limit '+DAY_CAP+' pts. Your points are saved on this phone.</p></section>';
    $("lbBody").innerHTML=toggle+you+'<section class="card">'+podium+list+
      '<p class="why-src">Example friends — not real users. Friends and sharing are on our roadmap.</p></section>'+how;
  }
  function openLb(){
    renderLb();$("lb").classList.add("on");$("lb").setAttribute("aria-hidden","false");
    setTimeout(function(){$("closeLb").focus({preventScroll:true})},240);
  }
  function closeLb(){
    $("lb").classList.remove("on");$("lb").setAttribute("aria-hidden","true");
    document.querySelectorAll(".nav button").forEach(function(x){
      if(x.dataset.go==="top")x.setAttribute("aria-current","page");else x.removeAttribute("aria-current")});
  }
  $("closeLb").onclick=function(){closeLb()};
  $("ptsChip").onclick=function(){openLb()};
  $("lbBody").addEventListener("click",function(e){
    var b=e.target.closest("button[data-view]");if(!b)return;LB_VIEW=b.dataset.view;renderLb();
  });
  ptsShow();
  function fareThanks(f){
    var line=f.quoted!=null?"You saw "+rm(f.quoted)+" on "+APP_NAME[f.app]+" when you checked and paid "+rm(f.paid)+
      " ("+(f.paid-f.quoted>0.004?rm(f.paid-f.quoted)+" more":f.quoted-f.paid>0.004?rm(f.quoted-f.paid)+" less":"the same")+")."
      :"You paid "+rm(f.paid)+" on "+APP_NAME[f.app]+".";
    var w=f.decision==="wait"&&f.expected_after_wait!=null?" The forecast expected about "+rm(f.expected_after_wait)+" after waiting "+f.wait_minutes+" min.":"";
    return '<div class="wrow ok"><span class="wic">'+ICON_CHECK+'</span><div><b>Thanks — saved</b><small>'+esc(line+w)+'</small></div><span></span></div>';
  }
  /* ---------- study cases (real ride data, reports/case_studies.md) ---------- */
  function renderStudies(d){
    var el=$("studies");if(!el)return;
    if(!d||!d.event_exit||!d.surge_fallback){el.closest(".card").hidden=true;return}
    var p=function(v){return (v>0?"+":"")+Math.round(v*100)+"%"};
    // 1. event exit: learned curve (training games), minutes from the end
    var e=d.event_exit,bins=Object.keys(e.learned_bins).map(Number).sort(function(a,b){return a-b});
    var W=300,H=120,x=function(m){return 24+(m-bins[0])/(bins[bins.length-1]-bins[0])*(W-34)},y=function(v){return H-18-v/0.25*(H-40)};
    var ev='<svg class="chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Price vs a normal day around the end of an event">'+
      '<line x1="'+x(0)+'" y1="6" x2="'+x(0)+'" y2="'+(H-18)+'" stroke="#101410" stroke-width="1"/>'+
      '<text x="'+(x(0)+4)+'" y="'+(H-24)+'" font-size="9" fill="#101410">event ends</text>'+
      '<line x1="24" y1="'+y(0)+'" x2="'+(W-10)+'" y2="'+y(0)+'" stroke="rgba(16,20,16,.25)" stroke-dasharray="3 3"/>'+
      '<polyline points="'+bins.map(function(b){return x(b)+","+y(e.learned_bins[b])}).join(" ")+'" fill="none" stroke="#F26B1D" stroke-width="3" stroke-linejoin="round"/>'+
      bins.map(function(b){return '<circle cx="'+x(b)+'" cy="'+y(e.learned_bins[b])+'" r="3" fill="#F26B1D"/>'}).join("")+
      '<text x="'+(x(e.peak_window_min[0])+6)+'" y="'+(y(e.peak)-6)+'" font-size="10" font-weight="700" fill="#101410">'+p(e.peak)+'</text>'+
      bins.filter(function(b){return b%30===0}).map(function(b){return '<text x="'+x(b)+'" y="'+(H-4)+'" font-size="9" fill="rgba(16,20,16,.6)" text-anchor="middle">'+(b>0?"+":"")+b+'</text>'}).join("")+
      '</svg>';
    // 2. high prices settle: actual vs model change at +30 min, by how high the price was
    var rows=d.surge_fallback,bw=(W-40)/rows.length,y2=function(v){return 14+(-v)/0.12*(H-48)};
    var sg='<svg class="chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Price change 30 minutes later, by how high the price was">'+
      '<line x1="20" y1="14" x2="'+(W-10)+'" y2="14" stroke="rgba(16,20,16,.25)" stroke-dasharray="3 3"/>'+
      rows.map(function(r,i){var cx=24+i*bw,a=Math.min(0,r.actual["30"]),m=Math.min(0,r.model["30"]);
        return '<rect x="'+(cx+4)+'" y="14" width="'+(bw/2-6)+'" height="'+(y2(a)-14)+'" fill="#F26B1D" rx="2"/>'+
          '<rect x="'+(cx+bw/2)+'" y="14" width="'+(bw/2-6)+'" height="'+(y2(m)-14)+'" fill="#101410" opacity=".55" rx="2"/>'+
          '<text x="'+(cx+bw/2)+'" y="'+(Math.max(y2(a),y2(m))+11)+'" font-size="9" fill="#101410" text-anchor="middle">'+p(r.actual["30"])+'</text>'+
          '<text x="'+(cx+bw/2)+'" y="'+(H-14)+'" font-size="9" fill="#101410" text-anchor="middle">'+esc(r.band.replace(/ \(.*\)/,""))+'</text><text x="'+(cx+bw/2)+'" y="'+(H-3)+'" font-size="8" fill="rgba(16,20,16,.55)" text-anchor="middle">'+r.n.toLocaleString()+' cases</text>'}).join("")+
      '</svg>';
    var hi=rows.filter(function(r){return r.band.indexOf("1.5")>=0&&r.band.indexOf("≥")===0})[0];
    el.innerHTML=
      '<div class="study"><h3>When a big event ends</h3>'+ev+
      '<p class="sub">Right next to a baseball stadium, prices were <b>'+p(e.heldout_0_45)+'</b> vs a normal day in the 45 min after '+
      e.heldout_games+' games the model never saw (learned from '+e.train_games+' games: '+p(e.learned_0_45)+'). Peak right after the end.</p></div>'+
      (hi?'<div class="study"><h3>When the price is already high</h3>'+sg+
      '<div class="legend"><span><i style="width:10px;height:10px;background:#F26B1D;border-radius:2px"></i>Actual, 30 min later</span><span><i style="width:10px;height:10px;background:#101410;opacity:.55;border-radius:2px"></i>Model said</span></div>'+
      '<p class="sub">At '+esc(hi.band)+' normal, prices fell <b>'+Math.round(-hi.actual["30"]*100)+'%</b> in 30 min on average; a ≥10% drop happened '+
      Math.round(hi.drop10_actual_30*100)+'% of the time (model said '+Math.round(hi.drop10_model_30*100)+'%). High prices settle back down — a simple time-of-day rule catches this too.</p></div>':'')+
      '<div class="study"><h3>When a jam is coming</h3><p class="sub">With pickup and destination set, we check predicted trip time for leaving now vs in 15–60 min. '+
      'If the trip gets 25% longer, waiting is off: <b>Book now — jam coming</b>. Traffic did not help predict the price itself, so we show minutes, not a %.</p></div>'+
      '<div class="why-src">Measured on real ride-hailing data (2024), test days held out — not measured in Malaysia. Source: reports/case_studies.md</div>';
    // one moment at a time: tabs instead of one long card
    var st=el.querySelectorAll(".study"),names=["Event ends","Price high","Jam coming"];
    var tabs=document.createElement("div");tabs.className="lb-toggle three";tabs.setAttribute("role","tablist");
    tabs.innerHTML=[].map.call(st,function(s,i){return '<button type="button" role="tab" data-i="'+i+'" aria-selected="'+(i===0)+'">'+names[i]+'</button>'}).join("");
    el.insertBefore(tabs,el.firstChild);
    function show(k){[].forEach.call(st,function(s,i){s.hidden=i!==k});[].forEach.call(tabs.children,function(b,i){b.setAttribute("aria-selected",String(i===k))})}
    tabs.onclick=function(e){var b=e.target.closest("button[data-i]");if(b)show(+b.dataset.i)};
    show(0);
  }
  initMaps();
  syncFields(false);renderQuotes();renderPrediction();tick();
})();

  }, []);

  return (
    <>
<div className="stage">
  <div className="caption"><b>When Yah?</b><span>Home screen</span></div>

  <div className="phone" id="phone">
    <div className="island" aria-hidden="true"></div>
    <div className="status" aria-hidden="true"><span>9:41</span><span>5G ▮▮▮</span></div>

    <main className="scroll" id="scroll">
      <div className="stack">

        <header className="top">
          <div className="brand">
            <div className="logo" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C4F135" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 8.5V13l3 2"/><path d="M9 2.5h6"/></svg>
            </div>
            <div>
              <div className="hello">Welcome back</div>
              <div className="title">When Yah?</div>
            </div>
          </div>
          <div className="top-chips">
            <button className="chip pts" id="ptsChip" type="button" aria-label="Your points, open leaderboard">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/></svg>
              <span id="ptsVal">0</span> pts
            </button>
            <div className="chip"><span className="dot"></span>Klang Valley</div>
          </div>
        </header>

        {/* route */}
        <section className="route" aria-label="Trip">
          <div className="rbody">
            <div className="fields">
              <button className="field" id="fFrom" type="button" aria-label="Choose pickup on map">
                <span className="pin" aria-hidden="true"></span>
                <span className="txt"><span className="v" id="vFrom"></span></span>
              </button>
              <button className="field" id="fTo" type="button" aria-label="Choose destination on map">
                <span className="pin sq" aria-hidden="true"></span>
                <span className="txt"><span className="v" id="vTo"></span></span>
              </button>
              <button className="swap" id="swap" type="button" aria-label="Swap pickup and destination">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"><path d="M7 4v16M7 20l-3-3M7 20l3-3M17 20V4M17 4l-3 3M17 4l3 3"/></svg>
              </button>
            </div>
            <button className="thumb" id="miniMap" type="button" aria-label="Open full screen map">
              <div id="miniSvg" style={{ width: "100%", height: "100%", zIndex: 1, borderRadius: "16px" }}></div>
              <b>Map</b>
            </button>
          </div>
        </section>

        {/* price entry */}
        <section className="card" id="quoteCard" aria-labelledby="qt">
          <div className="card-head">
            <div>
              <h2 id="qt">Enter the prices you see</h2>
              <p className="sub">Type the price each app shows you right now.</p>
            </div>
            <span className="tag" id="exTag">Example prices</span>
          </div>
          <div id="quotes" className="stack" style={{gap: "8px"}}></div>
          <p className="note" id="bidNote" hidden>inDrive is bid-based, so enter your offer or the fare you were given.</p>
          <div className="qrow">
            <div className="amt"><span>RM</span><input id="usual" type="number" inputMode="decimal" min="0" step="0.5" placeholder="Usual price" aria-label="Usual price for this trip (optional)" /></div>
            <label className="ghost"><input id="rain" type="checkbox" /> Rain</label>
          </div>
          <p className="note">Know your usual price for this trip? Add it for a sharper forecast.</p>
          <div className="row-actions">
            <button className="ghost" id="addApp" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>Add app
            </button>
            <button className="go" id="predict" type="button">
              When Yah?
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
            </button>
          </div>
        </section>

        <section aria-label="Events near pickup" id="events">
          <button className="event" type="button" id="eventBtn">
            <span className="ic"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/></svg></span>
            <span><b>Event radar</b><small id="radarText">Loading real events…</small></span>
            <span className="tag" id="radarTag">Today</span>
          </button>
        </section>
      </div>
    </main>

    <nav className="nav" aria-label="Main">
      <button type="button" data-go="top" aria-current="page" aria-label="Home">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/></svg>
      </button>
            <button type="button" data-go="events" aria-label="Events">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>
      </button>
      <button type="button" data-go="leaderboard" aria-label="Leaderboard">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/></svg>
      </button>
      <button type="button" data-go="metrics" aria-label="Proof and metrics">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 20V11M12 20V4M19 20v-6"/></svg>
      </button>
    </nav>

    <div className="res" id="lb" role="dialog" aria-modal="true" aria-label="Leaderboard" aria-hidden="true">
      <div className="res-scroll">
        <div className="res-top">
          <button className="back" id="closeLb" type="button" aria-label="Back to home"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg></button>
          <div className="res-ttl"><div className="title">Leaderboard</div><div className="hello">Points for sharing prices and fares</div></div>
        </div>
        <div className="stack" id="lbBody"></div>
      </div>
    </div>

    <div className="res" id="res" role="dialog" aria-modal="true" aria-label="Your forecast" aria-hidden="true">
      <div className="res-scroll" id="resScroll">
        <div className="res-top">
          <button className="back" id="closeRes" type="button" aria-label="Back to home"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg></button>
          <div className="res-ttl"><div className="title">Your forecast</div><div className="hello" id="resRoute"></div></div>
        </div>
        <div className="stack">
        
        
        <section className="decide" aria-live="polite">
          <div>
            <div className="k">Best move</div>
            <div className="chips" id="dChips"></div>
            <div className="big" id="dTitle">Wait 30 min</div>
            <p id="dText"></p>
            <div className="count"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/></svg><span id="cd">30:00</span><span style={{opacity: 0.7}}>to book</span></div>
          </div>
          <div className="ring" role="img" aria-label="Chance of a drop of 10 percent or more within 30 minutes">
            <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="rgba(16,20,16,.15)" strokeWidth="10"/><circle id="ringArc" cx="50" cy="50" r="42" fill="none" stroke="#101410" strokeWidth="10" strokeLinecap="round" strokeDasharray="263.9" strokeDashoffset="263.9"/></svg>
            <div className="n"><div><b id="pDrop">–</b><em id="pDropLbl">drop ≥10%<br />in 30 min</em></div></div>
          </div>
        </section>

        <section className="card" aria-labelledby="rt">
          <div className="card-head">
            <div><h2 id="rt">Your apps</h2><p className="sub" id="rtSub">Cheapest first, from the prices you typed.</p></div>
          </div>
          <div className="rank" id="rank"></div>
        </section>

        <section className="card" aria-labelledby="ct">
          <div className="card-head">
            <div>
              <h2 id="ct">Price change over the next hour</h2>
              <p className="sub">Line is the expected change, shaded area is the likely range.</p>
            </div>
          </div>
          <svg className="chart" id="chart" viewBox="0 0 320 150" role="img" aria-label="Forecast of percent price change at 15, 30, 45 and 60 minutes"></svg>
          <div className="legend"><span><i style={{width:"14px",height:"3px",background:"#101410",borderRadius:"2px"}}></i>Expected</span><span><i style={{width:"14px",height:"10px",background:"rgba(196,241,53,.6)",borderRadius:"3px"}}></i>Likely range</span><span><i style={{width:"10px",height:"10px",background:"#C4F135",border:"2px solid #101410",borderRadius:"50%"}}></i>Best time</span></div>
        </section>

        <section className="card" aria-labelledby="wt">
          <div className="card-head">
            <div><h2 id="wt">Why</h2><p className="sub">What the model and live data say for the next hour.</p></div>
          </div>
          <div className="why2" id="why"></div>
        </section>

        <section className="card" aria-labelledby="ft">
          <div className="card-head">
            <div><h2 id="ft">Booked? Tell us what you paid</h2><p className="sub">Saved on this phone only. Real fares like yours are how the forecast gets checked in Malaysia.</p></div>
          </div>
          <div id="fareReport"></div>
        </section>

        <section className="card" aria-labelledby="st">
          <div className="card-head">
            <div><h2 id="st">What we saw in real ride data</h2><p className="sub">Three moments when prices move, measured on real trips.</p></div>
          </div>
          <div id="studies"></div>
        </section>

        <p className="foot">Trained and tested on 19M real ride-hailing trips (NYC TLC Uber/Lyft records, Aug 2024), applied to your typed prices and local KL time. Not connected to Grab, inDrive or GV Ride. Quotes may exclude tolls and surcharges.</p>

        </div>
      </div>
    </div>

    <div className="fs" id="fs" role="dialog" aria-modal="true" aria-label="Choose route on map" aria-hidden="true">
      <div className="fsmap" id="bigSvg" style={{ zIndex: 1 }}></div>
      <div className="fs-top">
        <button className="back" id="closeFs" type="button" aria-label="Back to home"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#101410" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg></button>
        <div className="fs-card">
          <label className="fs-row" id="rowFrom"><span className="pin" aria-hidden="true"></span><input id="qFrom" type="text" placeholder="Pickup" autoComplete="off" aria-label="Pickup" /></label>
          <label className="fs-row" id="rowTo"><span className="pin sq" aria-hidden="true"></span><input id="qTo" type="text" placeholder="Destination" autoComplete="off" aria-label="Destination" /></label>
        </div>
      </div>
      <button className="fs-chip" id="zoneChip" type="button" aria-haspopup="dialog"><i></i><span id="chipText"></span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg></button>
      <div className="fs-bottom">
        <p className="hint" id="hint">Choose pickup</p>
          <div id="routeStats" className="caption" style={{ justifyContent: "center", margin: "4px 0" }}></div>
        <ul className="plist" id="plist"></ul>
        <button className="go" id="confirm" type="button">Confirm route</button>
      </div>
    </div>

    <div className="zs-scrim" id="zoneScrim"></div>
    <div className="zs" id="zoneSheet" role="dialog" aria-modal="true" aria-labelledby="zsTitle" aria-hidden="true">
      <div className="zs-grab"></div>
      <div className="zs-scroll" id="zsBody"></div>
    </div>

    <div className="toast" id="toast" role="status"></div>
  </div>
</div>
    </>
  );
}
