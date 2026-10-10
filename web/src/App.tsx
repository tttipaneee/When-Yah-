// @ts-nocheck
import React, { useEffect } from "react";
import "./index.css";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { PLACE_LATLON } from "./model";
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
  var EVENT={
    at:"Axiata Arena",r:46,
    name:"Example concert",
    venue:"Axiata Arena, Bukit Jalil",
    start:"14:00",
    ends:"16:30",
    crowd:"about 15,000",
    surge:"+15 to +25%",
    easeMin:45,
    nearbyPts:4,
    source:"Event page (example)",
    reasons:[
      {title:"Event crowd booking rides at the same moment",text:"Thousands of riders request cars within minutes of each other, so demand jumps well above the number of nearby drivers.",dir:"up",pts:8,source:"Event page (example)"},
      {title:"Fewer drivers willing to enter jammed roads around the venue",text:"Traffic makes pickups slow, so drivers avoid the area unless the fare is higher.",dir:"up",pts:5,source:"Model: distance to event"},
      {title:"Exit wave expected around the end time",text:"Much of the crowd leaves within minutes of the finish, so requests spike in a short window.",dir:"up",pts:7,source:"Model: minutes to event end"},
      {title:"Drivers repositioning toward the venue after it ends",text:"Later, more drivers head to the area, which pulls prices back down.",dir:"down",pts:5,source:"Model: minutes since event end"}
    ]
  };
  // Example data. Production will use Prasarana GTFS static + realtime feeds from data.gov.my
  var TRANSIT={
    STATIONS:[
      {n:"Bukit Jalil",line:"LRT Sri Petaling line",x:238,y:148,lx:-9,ly:-7,a:"end"},
      {n:"Sungai Besi",line:"LRT Sri Petaling line",x:218,y:124,lx:9,ly:3,a:"start"},
      {n:"Bandar Tasik Selatan",line:"LRT Sri Petaling line, KTM Komuter, KLIA Transit",x:180,y:104,lx:9,ly:-8,a:"start"},
      {n:"KL Sentral",line:"Rail hub",x:70,y:84,lx:9,ly:-9,a:"start"}
    ],
    COMBOS:{
      "Axiata Arena":{
        walkTo:"Bukit Jalil",walkMin:5,
        board:"Bukit Jalil",alight:"Bandar Tasik Selatan",stops:2,
        trainMin:6,waitMin:5,
        trainFare:1.60,
        rideRatio:0.5,
        rideMin:18,
        rideNowMin:35,
        crowdNote:"Bukit Jalil station gets crowded right after events; leave before the exit wave or expect a longer wait."
      }
    },
    RAIL_HUBS:["KL Sentral","KLCC","Mid Valley City"],
    HUB_TRIPS:{
      "Axiata Arena":{
        "KL Sentral":{via:"LRT to Bandar Tasik Selatan, then KTM Komuter or KLIA Transit",fare:3.60,min:38},
        "KLCC":{via:"LRT to Masjid Jamek, then the Kelana Jaya line",fare:3.50,min:52},
        "Mid Valley City":{via:"LRT to Bandar Tasik Selatan, then KTM Komuter",fare:3.80,min:46}
      },
      "Bandar Tasik Selatan":{
        "KL Sentral":{via:"KTM Komuter or KLIA Transit",fare:2.60,min:22},
        "KLCC":{via:"LRT to Masjid Jamek, then the Kelana Jaya line",fare:3.00,min:36},
        "Mid Valley City":{via:"KTM Komuter",fare:2.80,min:28}
      }
    }
  };
  var fsOpener=null,resOpener=null,zoneOpener=null,zoneBox=null;
  var WALK={n:"Sri Petaling",pct:-8,min:15};
  var state={from:"Axiata Arena",to:"KL Sentral",active:"from",prevFrom:null,
    quotes:[{app:"Grab",price:28},{app:"inDrive",price:24}],usual:0,rain:false,fromLatLon:null,toLatLon:null};

  function $(id){return document.getElementById(id)}
  function place(n){for(var i=0;i<PLACES.length;i++)if(PLACES[i].n===n)return PLACES[i];return PLACES[0]}
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

  function baseMap(){
    var h="",y;
    for(y=-280;y<480;y+=56){h+='M-60 '+y+'H400';}
    var h2="";
    for(y=-240;y<480;y+=64){h2+='M-60 '+y+'H400';}
    return '<rect x="-200" y="-500" width="800" height="1200" fill="var(--map-bg)"/>'+
    '<path d="M-200 140 C60 130 90 162 160 148 S290 124 600 138 L600 164 C290 150 220 174 160 172 S50 156 -200 166Z" fill="var(--map-water)"/>'+
    '<rect x="150" y="12" width="46" height="34" rx="10" fill="var(--map-park)"/>'+
    '<rect x="8" y="64" width="38" height="24" rx="10" fill="var(--map-park)"/>'+
    '<rect x="270" y="86" width="52" height="30" rx="12" fill="var(--map-park)"/>'+
    '<rect x="60" y="-150" width="70" height="46" rx="14" fill="var(--map-park)"/>'+
    '<rect x="220" y="230" width="64" height="50" rx="14" fill="var(--map-park)"/>'+
    '<rect x="20" y="300" width="80" height="40" rx="14" fill="var(--map-park)"/>'+
    '<g stroke="#fff" stroke-width="7" stroke-linecap="round" fill="none">'+
      '<path d="'+h+'"/>'+
      '<path d="M40 -400V600M130 -400V600M215 -400V600M296 -400V600"/>'+
      '<path d="M-40 200L120 70 400 -10" stroke-width="5"/>'+
    '</g>'+
    '<g stroke="#EEF8DD" stroke-width="3" fill="none"><path d="'+h2+'"/><path d="M86 -400V600M172 -400V600M255 -400V600"/></g>';
  }
  function pinMarkup(p,kind,label,k){
    k=k||1;
    var r=9*k,sw=3.5*k,lx=p.x>230?p.x-8*k-3:p.x+12*k,anchor=p.x>230?"end":"start";
    var shape=kind==="from"
      ?'<circle cx="'+p.x+'" cy="'+p.y+'" r="'+r+'" fill="#C4F135" stroke="#101410" stroke-width="'+sw+'"/><circle cx="'+p.x+'" cy="'+p.y+'" r="'+(2.8*k)+'" fill="#101410"/>'
      :kind==="walk"
      ?'<circle cx="'+p.x+'" cy="'+p.y+'" r="'+(7*k)+'" fill="#fff" stroke="#101410" stroke-width="'+(3*k)+'"/>'
      :'<rect x="'+(p.x-r)+'" y="'+(p.y-r)+'" width="'+(2*r)+'" height="'+(2*r)+'" rx="'+(5*k)+'" fill="#101410" stroke="#C4F135" stroke-width="'+sw+'"/><rect x="'+(p.x-3*k)+'" y="'+(p.y-3*k)+'" width="'+(6*k)+'" height="'+(6*k)+'" rx="'+(1.5*k)+'" fill="#C4F135"/>';
    if(!label)return shape;
    return shape+'<text x="'+lx+'" y="'+(p.y+4*k)+'" text-anchor="'+anchor+'" font-family="Plus Jakarta Sans,system-ui,sans-serif" font-size="'+(10.5*k)+'" font-weight="800" fill="#101410" stroke="#F5FBEA" stroke-width="'+(3.5*k)+'" paint-order="stroke" stroke-linejoin="round">'+esc(label)+'</text>';
  }
  var FONT='font-family="Plus Jakarta Sans,system-ui,sans-serif"';
  function zoneMarkup(label,k,o){
    k=k||1;o=o||{};
    var v=place(EVENT.at),r=EVENT.r;
    var sh='<circle class="zone-o" cx="'+v.x+'" cy="'+v.y+'" r="'+r+'" fill="#F26B1D" fill-opacity=".2" stroke="#F26B1D" stroke-width="2" stroke-dasharray="7 5" vector-effect="non-scaling-stroke"/>'+
          '<circle cx="'+v.x+'" cy="'+v.y+'" r="'+(r*.52)+'" fill="#F26B1D" fill-opacity=".28"/>';
    if(label){
      var below=!!o.tap;
      var ly=below?v.y+r+12*k:v.y-r-4*k;
      sh+='<text x="'+v.x+'" y="'+ly+'" text-anchor="middle" '+FONT+' font-size="'+(9.5*k)+'" font-weight="800" fill="#B8470C" stroke="#F5FBEA" stroke-width="'+(3*k)+'" paint-order="stroke">Surge zone</text>';
      if(o.tap)sh+='<text x="'+v.x+'" y="'+(ly+11*k)+'" text-anchor="middle" '+FONT+' font-size="'+(8*k)+'" font-weight="700" fill="#B8470C" stroke="#F5FBEA" stroke-width="'+(3*k)+'" paint-order="stroke">Tap for details</text>';
    }
    if(o.hit)return '<g class="zone-hit" data-zone="1" role="button" tabindex="0" aria-label="Surge zone around '+esc(EVENT.at)+'. Show event details" style="cursor:pointer">'+sh+'</g>';
    return sh;
  }
  function stationMarker(st,k,label){
    var s=8*k,o='<rect x="'+(st.x-s/2)+'" y="'+(st.y-s/2)+'" width="'+s+'" height="'+s+'" rx="'+(2.4*k)+'" fill="#101410" stroke="#fff" stroke-width="'+(1.6*k)+'"/>'+
      '<rect x="'+(st.x-1.8*k)+'" y="'+(st.y-1.8*k)+'" width="'+(3.6*k)+'" height="'+(3.6*k)+'" rx="'+k+'" fill="#C4F135"/>';
    if(label)o+='<text x="'+(st.x+(st.lx||9)*k)+'" y="'+(st.y+(st.ly||3)*k)+'" text-anchor="'+(st.a||"start")+'" '+FONT+' font-size="'+(8.5*k)+'" font-weight="800" fill="#101410" stroke="#F5FBEA" stroke-width="'+(3*k)+'" paint-order="stroke" stroke-linejoin="round">'+esc(st.n)+'</text>';
    return o;
  }
  function railLine(sts,w){
    return '<polyline points="'+sts.map(function(p){return p.x+","+p.y}).join(" ")+'" fill="none" stroke="#101410" stroke-width="'+w+'" stroke-dasharray="5 4" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" pointer-events="none"/>';
  }
  function stn(n){for(var i=0;i<TRANSIT.STATIONS.length;i++)if(TRANSIT.STATIONS[i].n===n)return TRANSIT.STATIONS[i];return null}
  function fitBox(pts,pad,asp){
    var xs=pts.map(function(p){return p.x}),ys=pts.map(function(p){return p.y});
    var x0=Math.min.apply(0,xs),x1=Math.max.apply(0,xs),y0=Math.min.apply(0,ys),y1=Math.max.apply(0,ys);
    var w=Math.max(x1-x0+2*pad,(y1-y0+2*pad)*asp),h=w/asp,cx=(x0+x1)/2,cy=(y0+y1)/2;
    return {w:w,h:h,vb:(cx-w/2)+" "+(cy-h/2)+" "+w+" "+h};
  }
  function inZone(){
    var a = PLACE_LATLON[state.from], v = PLACE_LATLON[EVENT.at];
    if(!a || !v) return false;
    return Math.hypot(a.lat-v.lat, a.lon-v.lon) <= 0.03;
  }
  function routePath(a,b){
    var ym=(a.y+b.y)/2;
    return "M"+a.x+" "+a.y+" L"+a.x+" "+ym+" L"+b.x+" "+ym+" L"+b.x+" "+b.y;
  }
  function drawMain(animate){
    if(!miniLayers) return;
    miniLayers.clearLayers();
    var a = PLACE_LATLON[state.from];
    var b = PLACE_LATLON[state.to];
    var v = PLACE_LATLON[EVENT.at];
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
      L.circle([v.lat, v.lon], {radius: 2000, color: "#F26B1D", fillColor: "#F26B1D", fillOpacity: 0.2, weight: 1}).addTo(miniLayers);
    }
  }
  function drawBig(){
    if(!bigLayers) return;
    bigLayers.clearLayers();
    var a = PLACE_LATLON[state.from];
    var b = PLACE_LATLON[state.to];
    var v = PLACE_LATLON[EVENT.at];
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
              var distKm = (data.routes[0].distance / 1000).toFixed(1);
              var durMin = Math.round(data.routes[0].duration / 60);
              var rs = document.getElementById("routeStats");
              if (rs) rs.innerHTML = "<b>" + durMin + " min</b> driving (" + distKm + " km)";
           }
        }).catch(e => console.error(e));
    }
    if(v) {
      L.circle([v.lat, v.lon], {radius: 2000, color: "#F26B1D", fillColor: "#F26B1D", fillOpacity: 0.2, weight: 1}).addTo(bigLayers);
    }
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
    if(a) bigMapL.setView([a.lat, a.lon], 12);
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
    var W=320,H=150,L=34,R=14,T=16,B=26,ymax=6,ymin=-26;
    var xs={0:L,15:L+(W-L-R)*0.25,30:L+(W-L-R)*0.5,45:L+(W-L-R)*0.75,60:W-R};
    function y(v){return T+(ymax-v)/(ymax-ymin)*(H-T-B)}
    var ks=[0,15,30,45,60],o="";
    [0,-10,-20].forEach(function(g){
      o+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(g)+'" y2="'+y(g)+'" stroke="'+(g===0?'#5B6755':'#D6E7BD')+'" stroke-width="1" '+(g===0?'stroke-dasharray="3 3"':'')+'/>'+
           '<text x="'+(L-6)+'" y="'+(y(g)+3.5)+'" text-anchor="end">'+(g===0?'0%':g+'%')+'</text>';
    });
    var up=ks.map(function(k){return xs[k]+","+y(HI[k])}).join(" ");
    var dn=ks.slice().reverse().map(function(k){return xs[k]+","+y(LO[k])}).join(" ");
    o+='<polygon points="'+up+" "+dn+'" fill="rgba(196,241,53,.6)"/>';
    o+='<polyline points="'+ks.map(function(k){return xs[k]+","+y(PCT[k])}).join(" ")+'" fill="none" stroke="#101410" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
    ks.forEach(function(k){
      var best=k===bestMin;
      o+='<circle cx="'+xs[k]+'" cy="'+y(PCT[k])+'" r="'+(best?7:4)+'" fill="'+(best?'#C4F135':'#101410')+'" stroke="#101410" stroke-width="'+(best?3:0)+'"/>';
      if(k>0)o+='<text class="val" x="'+xs[k]+'" y="'+(y(PCT[k])+(best?22:17))+'" text-anchor="middle">'+PCT[k]+'%</text>';
      o+='<text x="'+xs[k]+'" y="'+(H-6)+'" text-anchor="middle">'+(k===0?"Now":"+"+k+"m")+'</text>';
    });
    $("chart").innerHTML=o;
  }
  /* ---------- real model (./model.ts → /api/forecast) ---------- */
  function applyModel(r){
    r.horizon.forEach(function(h){PCT[h.minutes]=Math.round(h.pct_change*100);LO[h.minutes]=Math.round(h.pct_low*100);HI[h.minutes]=Math.round(h.pct_high*100)});
    PDROP=r.wait_odds.p_save10;
    bestMin=r.decision==="wait"?r.wait_minutes:0;
  }
  function requestModel(){
    runModel({from:state.from,fromLatLon:state.fromLatLon,to:state.to,toLatLon:state.toLatLon,quotes:state.quotes,usual:state.usual,rain:state.rain})
      .then(function(r){if(r!==MODEL){MODEL=r;MODEL_ERR=null;applyModel(r);remaining=bestMin*60;tick();renderPrediction(true)}})
      .catch(function(e){MODEL=null;MODEL_ERR=String(e);renderPrediction(true)});
  }
  function realOnly(){
    // Cards without a traceable source stay hidden until they have one (evidence rule)
    $("walkCard").hidden=true;$("transitCard").hidden=true;
    $("opts").querySelectorAll('[data-go="transit"]').forEach(function(n){n.remove()});
    var wc=$("wt").closest(".card"),tg=wc&&wc.querySelector(".tag");if(tg)tg.hidden=true;
    if(!MODEL){$("why").innerHTML='<div class="empty">'+esc(MODEL_ERR?"Model offline: start the API (scripts/run_demo.sh).":"Asking the model…")+'</div>';return}
    var html=MODEL.reasons.filter(function(t){return t.indexOf("Event nearby:")!==0}).map(function(t){return '<div><div class="why-top"><span>'+esc(t)+'</span></div></div>'}).join("");
    html+=MODEL.events.map(function(e){return '<div><div class="why-top"><span>Event nearby: '+esc(e.name)+'</span></div><div class="why-src"><a href="'+esc(e.source_url)+'" target="_blank" rel="noopener">Source</a> · effect on price not measured for Malaysian events</div></div>'}).join("");
    html+='<div class="why-src">Source: '+esc(MODEL.model_version)+', tested on real ride data (reports/metrics.md) + your typed prices</div>';
    $("why").innerHTML=html;
  }
  function renderPrediction(fromModel){
    if(!fromModel)requestModel();
    var mult=1+PCT[bestMin]/100,o=MODEL&&MODEL.wait_odds;
    var cdBox=$("cd")&&$("cd").parentNode;if(cdBox)cdBox.hidden=!(MODEL&&MODEL.decision==="wait");
    $("dTitle").textContent=!MODEL?(MODEL_ERR?"Model offline":"Ramal…"):MODEL.decision==="wait"?"Tunggu "+bestMin+" min":"Tempah sekarang";
    var tung=MODEL&&MODEL.decision==="wait"?MODEL.reasons.filter(function(t){return t.indexOf("Tunggu")===0})[0]:null;
    $("dText").textContent=!MODEL?(MODEL_ERR?"Start the API (scripts/run_demo.sh) and try again.":"Asking the model…"):
      tung?(function(t){return t.charAt(0).toUpperCase()+t.slice(1)})(tung.replace(/^Tunggu \d+ min: /,""))+".":
      "Chance the price drops ≥10% if you wait 30 min: "+Math.round(o.p_save10*100)+"% (usual "+Math.round(o.typical_p_save10*100)+"%). In 30 min likely "+sg(Math.round(o.pct_low*100))+"% to "+sg(Math.round(o.pct_high*100))+"%.";
    $("bestAt").textContent=hhmm(bestMin);
    $("pDrop").textContent=Math.round(PDROP*100)+"%";
    $("ringArc").style.strokeDashoffset=String(263.9*(1-PDROP));
    var rows=state.quotes.filter(function(q){return q.price>0}).map(function(q){return{app:q.app,now:q.price,later:q.price*mult}});
    rows.sort(function(a,b){return a.later-b.later});
    $("rank").innerHTML=rows.length?rows.map(function(r,i){
      var ini=r.app==="Other app"?"?":r.app.charAt(0).toUpperCase()+(r.app==="GV Ride"?"V":r.app==="inDrive"?"D":"");
      return '<div class="rk'+(i===0?' best':'')+'"><span class="av">'+esc(ini)+'</span><span><b>'+esc(r.app)+'</b><small>'+(i===0?(bestMin===0?"Cheapest now":"Cheapest at "+hhmm(bestMin)):"Now "+rm(r.now))+'</small></span>'+
        (bestMin===0?'<span class="p"><strong>'+rm(r.now)+'</strong></span></div>':
        '<span class="p"><s>'+rm(r.now)+'</s><strong>'+rm(r.later)+'</strong><em>Save '+rm(r.now-r.later)+'</em></span></div>');
    }).join(""):'<div class="empty">Enter at least one price to see your apps ranked.</div>';
    renderChart();renderWalk();renderTransit();renderOpts();renderWhy();realOnly();
  }
  function lowest(){var p=state.quotes.map(function(q){return q.price}).filter(function(v){return v>0});return p.length?Math.min.apply(0,p):0}
  function sg(v){return (v>0?"+":v<0?"\u2212":"")+Math.abs(v)}
  var ICON_WALK='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="4.5" r="1.8"/><path d="M9 21l2.5-6-2-2 1-5 3-1 2 4 3 1M12.5 15l3 2.5 .5 3.5M10.5 8L8 11"/></svg>';
  var TRAIN_PATH='<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 11h14M9 21l2-4M15 21l-2-4"/><circle cx="9" cy="14" r=".7"/><circle cx="15" cy="14" r=".7"/>';
  var CAR_PATH='<path d="M5 16v-5l1.7-4.5A2 2 0 0 1 8.6 5h6.8a2 2 0 0 1 1.9 1.5L19 11v5M5 16h14M5 16v2.5M19 16v2.5"/><circle cx="8.5" cy="13.2" r=".7"/><circle cx="15.5" cy="13.2" r=".7"/>';
  function ic(p){return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p+'</svg>'}
  var ICON_TRAIN=ic(TRAIN_PATH),ICON_CAR=ic(CAR_PATH);
  var ICON_CHECK='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  var ICON_WARN='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#B8470C" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.01"/></svg>';

  function legendSw(kind){
    if(kind==="zone")return '<span><i style="background:#FFE6D4;border:2px dashed #F26B1D"></i>Surge zone</span>';
    if(kind==="walk")return '<span><svg width="18" height="8" viewBox="0 0 18 8" aria-hidden="true" style="margin-right:5px"><path d="M2 4h14" stroke="#101410" stroke-width="3" stroke-dasharray="0.1 5" stroke-linecap="round"/></svg>Walk</span>';
    if(kind==="train")return '<span><svg width="20" height="8" viewBox="0 0 20 8" aria-hidden="true" style="margin-right:5px"><path d="M1 4h18" stroke="#101410" stroke-width="2.5" stroke-dasharray="5 3" stroke-linecap="round"/></svg>Train</span>';
    return '<span><svg width="20" height="10" viewBox="0 0 20 10" aria-hidden="true" style="margin-right:5px"><path d="M2 5h16" stroke="#C4F135" stroke-width="8" stroke-linecap="round"/><path d="M2 5h16" stroke="#101410" stroke-width="3" stroke-linecap="round"/></svg>Ride</span>';
  }

  function doWalk(){
    state.prevFrom=state.from;state.from=WALK.n;
    syncFields(true);setResRoute();renderPrediction();syncFsFields();toast("Pickup moved outside the zone");
  }
  function doTransit(){
    var c=TRANSIT.COMBOS[state.from];if(!c)return;
    state.prevFrom=state.from;state.from=c.alight;
    syncFields(true);setResRoute();renderPrediction();syncFsFields();toast("Pickup moved to "+c.alight);
  }
  function doUndo(){
    state.from=state.prevFrom;state.prevFrom=null;
    syncFields(true);setResRoute();renderPrediction();syncFsFields();toast("Pickup restored");
  }

  function renderWalk(){
    var z=inZone(),low=lowest(),a=place(state.from),v=place(EVENT.at),w=place(WALK.n);
    var fb=fitBox([a,w,v],50,340/190),k=fb.w/300;
    var map='<svg class="wmap" viewBox="'+fb.vb+'" preserveAspectRatio="xMidYMid slice" role="group" aria-label="Map with the event surge zone and the walking route out of it">'+
      baseMap()+zoneMarkup(true,k,{hit:true})+
      (z?'<path d="M'+a.x+' '+a.y+' L'+w.x+' '+w.y+'" fill="none" stroke="#101410" stroke-width="3" stroke-dasharray="0.1 6" stroke-linecap="round" vector-effect="non-scaling-stroke" pointer-events="none"/>'+pinMarkup(w,"walk",w.n,k):'')+
      pinMarkup(a,"from",a.n,k)+'</svg>';
    var legend='<div class="maplegend">'+legendSw("zone")+'<span><i style="background:#C4F135;border:2px solid #101410"></i>Pickup</span>'+(z?'<span><i style="background:#fff;border:2px solid #101410"></i>Walk-out point</span>':'')+'</div>';
    var head='<div class="card-head"><div><div class="k2">2nd best option</div><h2>Walk out of the zone</h2></div><span class="tag">Example</span></div>';
    var body;
    if(z){
      var after=low*(1+WALK.pct/100);
      body='<div class="wrow"><span class="wic">'+ICON_WALK+'</span><div><b>Walk to '+esc(WALK.n)+'</b><small>About '+WALK.min+' min on foot, just outside the zone</small></div><span class="wpct">'+WALK.pct+'%</span></div>'+
        '<p class="sub">Your pickup is inside the surge zone of '+esc(EVENT.name)+' at '+esc(EVENT.at)+'. Prices are lower outside it, so walk first, then book.'+(low?' Your lowest quote of '+rm(low)+' could be about '+rm(after)+'.':'')+'</p>'+
        '<button class="go" id="walkGo" type="button">Set pickup to '+esc(WALK.n)+'</button>';
    }else{
      body='<div class="wrow ok"><span class="wic">'+ICON_CHECK+'</span><div><b>Your pickup is outside the surge zone</b><small>No need to walk</small></div><span></span></div>'+
        (state.prevFrom?'<button class="ghost" id="walkUndo" type="button" style="width:100%;justify-content:center">Back to '+esc(state.prevFrom)+'</button>':'');
    }
    $("walkCard").innerHTML=head+map+legend+body;
  }

  /* ---------- ride + train ---------- */
  var transitInfo={full:false};
  function step(icon,title,sub,time){
    return '<div class="wrow"><span class="wic">'+icon+'</span><div><b>'+esc(title)+'</b><small>'+esc(sub)+'</small></div><span class="wtime">'+esc(time)+'</span></div>';
  }
  function transitRows(low,combo,hubTrip){
    var rows=[];
    if(combo){
      rows.push({k:"ride",name:"Ride from here now",ic:ICON_CAR,total:low,min:combo.rideNowMin});
      rows.push({k:"walk",name:"Walk out, then ride",ic:ICON_WALK,total:low*(1+WALK.pct/100),min:WALK.min+combo.rideNowMin});
      rows.push({k:"train",name:"Train + ride",ic:ICON_TRAIN,total:combo.trainFare+low*combo.rideRatio,min:combo.walkMin+combo.waitMin+combo.trainMin+combo.rideMin});
    }
    if(hubTrip)rows.push({k:"all",name:"Train all the way",ic:ICON_TRAIN,total:hubTrip.fare,min:hubTrip.min,note:hubTrip.via});
    return rows;
  }
  function cmpHtml(rows,low,noBest){
    var best=-1,bv=1e9;
    rows.forEach(function(r,i){if(r.total<bv){bv=r.total;best=i}});
    return '<div class="rank">'+rows.map(function(r,i){
      var diff=low-r.total,saving=diff>0.004&&r.k!=="ride";
      var tag=r.k==="ride"?"Baseline":diff>0.004?"Save "+rm(diff):diff<-0.004?rm(-diff)+" more":"Same price";
      return '<div class="rk'+(!noBest&&i===best?' best':'')+'"><span class="av">'+r.ic+'</span><span><b>'+esc(r.name)+'</b><small>'+Math.round(r.min)+' min total'+(r.note?' · '+esc(r.note):'')+'</small></span>'+
        '<span class="p"><strong>'+rm(r.total)+'</strong><em'+(saving?'':' style="background:var(--mint)"')+'>'+tag+'</em></span></div>';
    }).join("")+'</div>';
  }
  function renderTransit(){
    var el=$("transitCard"),z=inZone(),low=lowest();
    var combo=TRANSIT.COMBOS[state.from]||null;
    var hubs=TRANSIT.HUB_TRIPS[state.from];
    var hubTrip=(TRANSIT.RAIL_HUBS.indexOf(state.to)>-1&&hubs&&hubs[state.to])||null;
    transitInfo={full:false};
    var head='<div class="card-head"><div><div class="k2">Skip the surge</div><h2>Ride + train</h2></div><span class="tag">Example</span></div>';
    if(z&&!combo){el.hidden=true;el.innerHTML="";return}
    el.hidden=false;
    if(!z){
      var ok='<div class="wrow ok"><span class="wic">'+ICON_CHECK+'</span><div><b>You’re outside the surge zone, so a ride from here is already the best value.</b></div><span></span></div>';
      var extra=hubTrip?(low?cmpHtml(transitRows(low,null,hubTrip),low,true):'<div class="empty">Enter a price to compare</div>'):'';
      el.innerHTML=head+ok+extra;
      return;
    }
    var sB=stn(combo.board),sA=stn(combo.alight),a=place(state.from),dst=place(state.to),v=place(EVENT.at);
    var line=TRANSIT.STATIONS.slice(TRANSIT.STATIONS.indexOf(sB),TRANSIT.STATIONS.indexOf(sA)+1);
    var fb=fitBox([a,sB,sA,v],40,340/240),k=fb.w/300;
    var d=routePath(sA,dst);
    var map='<svg class="wmap tall" viewBox="'+fb.vb+'" preserveAspectRatio="xMidYMid slice" role="group" aria-label="Map showing the surge zone, a walk to the station, the train out of the zone and a shorter ride to the destination">'+
      baseMap()+zoneMarkup(true,k,{hit:true})+
      '<path d="'+d+'" fill="none" stroke="#C4F135" stroke-width="'+(8*k)+'" stroke-linecap="round" stroke-linejoin="round" pointer-events="none"/>'+
      '<path d="'+d+'" fill="none" stroke="#101410" stroke-width="'+(3.2*k)+'" stroke-linecap="round" stroke-linejoin="round" pointer-events="none"/>'+
      '<path d="M'+a.x+' '+a.y+' L'+sB.x+' '+sB.y+'" fill="none" stroke="#101410" stroke-width="3" stroke-dasharray="0.1 6" stroke-linecap="round" vector-effect="non-scaling-stroke" pointer-events="none"/>'+
      railLine(line,3)+
      '<g pointer-events="none">'+line.map(function(st){return stationMarker(st,k,true)}).join("")+'</g>'+
      '<text x="'+(sA.x-9*k)+'" y="'+(sA.y+16*k)+'" text-anchor="end" '+FONT+' font-size="'+(8.5*k)+'" font-weight="800" fill="#101410" stroke="#F5FBEA" stroke-width="'+(3*k)+'" paint-order="stroke">Ride to '+esc(dst.n)+' \u2192</text>'+
      pinMarkup(dst,"to",dst.n,k)+pinMarkup(a,"from",a.n,k)+'</svg>';
    var legend='<div class="maplegend">'+legendSw("zone")+legendSw("walk")+legendSw("train")+legendSw("ride")+'</div>';
    var rideFare=low?low*combo.rideRatio:0;
    var steps='<div class="steps">'+
      step(ICON_WALK,"Walk "+combo.walkMin+" min to "+combo.walkTo+" LRT","Head for the platform before the exit wave",combo.walkMin+" min")+
      step(ICON_TRAIN,"LRT "+combo.stops+" stops to "+combo.alight,"About "+rm(combo.trainFare)+", wait about "+combo.waitMin+" min",(combo.waitMin+combo.trainMin)+" min")+
      step(ICON_CAR,"Book a ride to "+state.to,low?"About "+rm(rideFare)+", a shorter trip outside the zone":"Enter a price to see the fare",combo.rideMin+" min")+
      '</div>';
    var cmp='<div class="k2" style="margin-bottom:-4px">Compare your options</div>'+(low?cmpHtml(transitRows(low,combo,hubTrip),low):'<div class="empty">Enter a price to compare</div>');
    var note='<div class="heads">'+ICON_WARN+'<span>'+esc(combo.crowdNote)+'</span></div>';
    var go='<button class="go" id="transitGo" type="button">Set pickup to '+esc(combo.alight)+'</button>';
    if(low){
      var tot=combo.trainFare+low*combo.rideRatio;
      transitInfo={full:true,total:tot,save:low-tot,min:combo.walkMin+combo.waitMin+combo.trainMin+combo.rideMin};
    }else transitInfo={full:true,total:null};
    el.innerHTML=head+map+legend+steps+cmp+note+go;
  }

  function renderOpts(){
    var out=[],q=state.quotes.filter(function(x){return x.price>0}).slice().sort(function(a,b){return a.price-b.price});
    if(q.length>1&&q[0].price<q[q.length-1].price){
      out.push({t:"Book "+q[0].app+" now",s:"Lowest of your quotes, "+rm(q[q.length-1].price-q[0].price)+" less than "+q[q.length-1].app+".",i:'<path d="M7 4v16M7 20l-3-3M7 20l3-3M17 20V4M17 4l-3 3M17 4l3 3"/>'});
    }
    if(transitInfo.full){
      var ts=transitInfo.total!=null?"About "+rm(transitInfo.total)+" in total"+(transitInfo.save>0.004?", save "+rm(transitInfo.save):"")+", "+Math.round(transitInfo.min)+" min.":"Enter a price to compare.";
      out.push({t:"Take the train out of the zone",s:ts,i:TRAIN_PATH,go:"transit"});
    }
    out.push({t:"Check again in 15 min",s:"Expected "+sg(PCT[15])+"%, likely between "+sg(LO[15])+"% and "+sg(HI[15])+"%.",i:'<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/>'});
    $("opts").innerHTML=out.map(function(o){
      var inner='<span class="oi"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#101410" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+o.i+'</svg></span><span><b>'+esc(o.t)+'</b><small>'+esc(o.s)+'</small></span>';
      return o.go?'<button type="button" class="opt" data-go="'+o.go+'">'+inner+'</button>':'<div class="opt">'+inner+'</div>';
    }).join("");
  }

  function whyRow(r){
    var w=Math.min(50,Math.abs(r.v)/14*50);
    var bar=r.v===0?'':'<span class="bar '+(r.v<0?'dn':'up')+'" style="width:'+w+'%"></span>';
    return '<div><div class="why-top"><span>'+esc(r.t)+'</span><span class="n">'+(r.v===0?"0":sg(r.v))+' pts</span></div><div class="why-src">'+esc(r.d)+' <em style="font-style:normal;opacity:.8">('+esc(r.src)+')</em></div><div class="track" role="img" aria-label="'+esc(r.t)+' moves the price '+(r.v<0?'down':r.v>0?'up':'not at all')+' by '+Math.abs(r.v)+' points">'+bar+'</div></div>';
  }
  function renderWhy(){
    var z=inZone(),evt=z?EVENT.nearbyPts:0,wx=-5,tm=PCT[30]-wx-evt;
    var rows=[
      {t:"Time of day and weekday",d:"Saturday afternoons usually cool off after the lunch rush.",v:tm,src:"Model: time and weekday"},
      {t:"Weather",d:"No rain expected, so fewer last-minute bookings.",v:wx,src:"Model: weather"},
      {t:"Event nearby",d:z?"Your pickup is inside the surge zone of "+EVENT.name+", which pushes prices up.":"Your pickup is outside the surge zone of "+EVENT.name+", so the event adds nothing.",v:evt,src:EVENT.source+", pickup location"}
    ];
    var html=rows.map(whyRow).join("");
    html+='<div class="axis"><span>← Cheaper</span><span>Pricier →</span></div>';
    html+='<div class="net"><span>Net change at +30 min</span><b>'+sg(PCT[30])+'%</b></div>';
    if(z)html+='<div class="heads">'+ICON_WARN+'<span>When '+esc(EVENT.name)+' ends (about '+esc(EVENT.ends)+' in this example), prices near the venue are likely to rise again.</span></div>';
    $("why").innerHTML=html;
  }

  /* ---------- surge zone sheet ---------- */
  function mins(t){var p=t.split(":");return (+p[0])*60+(+p[1])}
  function fmtMin(m){m=((m%1440)+1440)%1440;var h=Math.floor(m/60),n=m%60;return (h<10?"0":"")+h+":"+(n<10?"0":"")+n}
  function phaseNow(){
    var d=new Date(),m=d.getHours()*60+d.getMinutes(),s=mins(EVENT.start),e=mins(EVENT.ends);
    if(m<s)return 0;
    if(m<e-15)return 1;
    if(m<e+EVENT.easeMin)return 2;
    return 3;
  }
  function renderZoneSheet(){
    var z=inZone(),canTrain=!!TRANSIT.COMBOS[state.from],ph=phaseNow();
    var s=mins(EVENT.start),e=mins(EVENT.ends);
    var surgeBig=EVENT.surge.replace(/ to \+?/,"–");
    var head='<div class="zs-head"><span class="zs-ic"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8" stroke-dasharray="3 3"/></svg></span>'+
      '<div><div class="zs-eyebrow"><span class="k2">Surge zone</span><span class="tag">Example</span></div><h3 id="zsTitle">'+esc(EVENT.name)+'</h3>'+
      '<div class="zs-meta">'+esc(EVENT.venue)+'<br>Today, '+esc(EVENT.start)+'–'+esc(EVENT.ends)+'</div></div>'+
      '<button class="x" id="zsClose" type="button" aria-label="Close event details"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>';
    var status=z
      ?'<div class="zs-status in">'+ICON_WARN+'<span>Your pickup ('+esc(state.from)+') is inside this zone</span></div>'
      :'<div class="zs-status out">'+ICON_CHECK+'<span>Your pickup is outside this zone</span></div>';
    var est='<div class="zs-est"><div><div class="k2">Estimated surge</div><div class="zs-big">'+esc(surgeBig)+'</div></div>'+
      '<p>Expected crowd '+esc(EVENT.crowd)+'. Prices peak in the exit wave around '+esc(EVENT.ends)+', then ease within about '+EVENT.easeMin+' minutes as drivers return.</p></div>';
    var why='<div class="zs-sec"><h4>Why prices are higher here</h4><div class="why-list">'+EVENT.reasons.map(function(r){
      return whyRow({t:r.title,d:r.text,v:r.dir==="down"?-r.pts:r.pts,src:r.source});
    }).join("")+'<div class="axis"><span>← Cheaper</span><span>Pricier →</span></div></div></div>';
    var phases=[
      {n:"Before event",t:"until "+EVENT.start},
      {n:"During",t:EVENT.start+"–"+fmtMin(e-15)},
      {n:"Exit wave",t:"around "+EVENT.ends},
      {n:"Back to normal",t:"after "+fmtMin(e+EVENT.easeMin)}
    ];
    var tl='<div class="zs-sec"><h4>How the evening unfolds</h4><ol class="tl">'+phases.map(function(p,i){
      var cls=i<ph?"past":i===ph?"now":"";
      return '<li class="'+cls+'"'+(i===ph?' aria-current="step"':'')+'><i></i><b>'+p.n+'</b>'+esc(p.t)+(i===ph?'<br><b>Now</b>':'')+'</li>';
    }).join("")+'</ol></div>';
    var acts=z
      ?'<div class="zs-acts"><button class="go" id="zsWalk" type="button">Walk to '+esc(WALK.n)+' (about '+WALK.min+' min)</button>'+
        (canTrain?'<button class="ghost" id="zsTrain" type="button">Take the train out</button>':'')+
        '<button class="ghost" id="zsForecast" type="button">See forecast</button></div>'
      :'<div class="zs-acts"><button class="go" id="zsGot" type="button">Got it</button></div>';
    $("zsBody").innerHTML=head+status+est+why+tl+acts;
  }
  function openZone(opener){
    zoneOpener=opener||document.activeElement;
    var box=zoneOpener&&zoneOpener.closest?zoneOpener.closest("#walkCard,#transitCard,#bigSvg"):null;
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
    else if(t.id==="zsWalk"){doWalk();closeZone()}
    else if(t.id==="zsTrain"){closeZone(true);if($("fs").classList.contains("on"))closeFs(true);showTransit()}
    else if(t.id==="zsForecast"){closeZone(true);if($("fs").classList.contains("on"))closeFs(true);openRes($("predict"))}
  });

  /* ---------- forecast screen ---------- */
  function reduced(){return !!(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches)}
  function scrollToCard(id){
    var sc=$("resScroll"),c=$(id);if(!c||c.hidden)return;
    var top=c.getBoundingClientRect().top-sc.getBoundingClientRect().top+sc.scrollTop-12;
    sc.scrollTo({top:top,behavior:reduced()?"auto":"smooth"});
  }
  function showTransit(){
    if($("res").classList.contains("on"))scrollToCard("transitCard");
    else{openRes($("predict"));setTimeout(function(){scrollToCard("transitCard")},320)}
  }
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
  $("predict").onclick=function(){openRes(this)};
  $("closeRes").onclick=function(){closeRes()};
  function setResRoute(){$("resRoute").textContent=state.from+" to "+state.to}

  $("walkCard").addEventListener("click",function(e){
    var z=e.target.closest("[data-zone]");
    if(z){openZone(z);return}
    if(e.target.closest("#walkGo"))doWalk();
    else if(e.target.closest("#walkUndo"))doUndo();
  });
  $("transitCard").addEventListener("click",function(e){
    var z=e.target.closest("[data-zone]");
    if(z){openZone(z);return}
    if(e.target.closest("#transitGo"))doTransit();
  });
  function zoneKey(e){
    if(e.key!=="Enter"&&e.key!==" ")return;
    var z=e.target.closest&&e.target.closest("[data-zone]");
    if(z){e.preventDefault();openZone(z)}
  }
  $("walkCard").addEventListener("keydown",zoneKey);
  $("transitCard").addEventListener("keydown",zoneKey);
  $("opts").addEventListener("click",function(e){
    var b=e.target.closest("button[data-go]");
    if(b&&b.dataset.go==="transit")scrollToCard("transitCard");
  });

  document.addEventListener("keydown",function(e){
    if(e.key!=="Escape")return;
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
    else toast("Proof: odds tested on 19M real rides (reports/metrics.md)");
  });
  $("eventBtn").onclick=function(){openFs("from",this,true);openZone($("zoneChip"))};

  document.documentElement.setAttribute("lang","en");
  $("chipText").textContent="Surge zone \u00b7 "+EVENT.name+" at "+EVENT.at;
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
          <div className="chip"><span className="dot"></span>Klang Valley</div>
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
            <span className="tag">Example</span>
          </div>
          <div id="quotes" className="stack" style={{gap: "8px"}}></div>
          <p className="note" id="bidNote" hidden>inDrive is bid-based, so enter your offer or the fare you were given.</p>
          <div className="qrow">
            <div className="amt"><span>RM</span><input id="usual" type="number" inputMode="decimal" min="0" step="0.5" placeholder="Harga biasa (optional)" aria-label="Usual price for this trip (optional)" /></div>
            <label className="ghost"><input id="rain" type="checkbox" /> Hujan</label>
          </div>
          <p className="note">Tahu harga biasa? Masukkan untuk ramalan lebih tepat.</p>
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
            <span><b>Event radar</b><small>Surge zone near your pickup is shown on the map</small></span>
            <span className="tag">Example</span>
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
      <button type="button" data-go="metrics" aria-label="Proof and metrics">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 20V11M12 20V4M19 20v-6"/></svg>
      </button>
    </nav>

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
            <div className="big" id="dTitle">Wait 30 min</div>
            <p id="dText"></p>
            <div className="count"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 1.5"/></svg><span id="cd">30:00</span><span style={{opacity: 0.7}}>to book</span></div>
          </div>
          <div className="ring" role="img" aria-label="Chance of a drop of 10 percent or more within 30 minutes">
            <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="rgba(16,20,16,.15)" strokeWidth="10"/><circle id="ringArc" cx="50" cy="50" r="42" fill="none" stroke="#101410" strokeWidth="10" strokeLinecap="round" strokeDasharray="263.9" strokeDashoffset="263.9"/></svg>
            <div className="n"><div><b id="pDrop">62%</b><em>drop ≥10%<br />in 30 min</em></div></div>
          </div>
        </section>

        <section className="card" id="walkCard" aria-label="Walk out of the zone"></section>

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

        <section className="card" id="transitCard" aria-label="Ride plus train" hidden></section>

        <section aria-label="Other options"><div className="k2" style={{margin: "0 2px 8px"}}>Other options</div><div className="opts" id="opts"></div></section>

        <section className="card" aria-labelledby="wt">
          <div className="card-head">
            <div><h2 id="wt">Why the price may move</h2><p className="sub">What is pushing it down or up in the next 30 minutes.</p></div>
            <span className="tag">Example</span>
          </div>
          <div className="why-list" id="why"></div>
        </section>

        <section className="card" aria-labelledby="rt">
          <div className="card-head">
            <div><h2 id="rt">Your apps, now vs <span id="bestAt">18:40</span></h2><p className="sub">Cheapest first, based on the prices you typed.</p></div>
          </div>
          <div className="rank" id="rank"></div>
        </section>

        <p className="foot">Forecast from our model, tested on 19M real ride-hailing trips (NYC, Aug 2024), applied to your typed prices and local time. Not connected to Grab, inDrive or GV Ride. Quotes may exclude tolls and surcharges.</p>

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
