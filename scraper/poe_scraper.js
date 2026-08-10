(async function () {
const GAME_SCRAPER_VERSION = 27; // bump whenever game-parsing logic changes, so merges know to re-fetch stale games
const GITHUB_OWNER = 'wcawcawcawcawca';
const GITHUB_REPO = 'fb-vics_league';
const GITHUB_BRANCH = 'main';
const GITHUB_PATH = 'data/pennants_over_easy_unified.json.gz';
const GITHUB_TOKEN_KEY = 'poe_github_pat';
if (document.getElementById('poe-ui')) { alert('Scraper already running.'); return; }
const LEAGUE = 137080;
const SEASON = 2026;
const TEAMS = {1:'Soy Boy',2:'Three Days of the Kondor',3:'Free State Freeloaders',4:'Dominic Toretto',9:'Little Creek Bonkers',10:'Skubal Diving',11:'Bottomless bangers',12:'Hwang out',13:'Ma the Meatloaf Now',14:'Team T',15:'Bilbo Ragans',16:'7th Floor Crew'};
const TIDS = Object.keys(TEAMS).map(Number);
const CATS = ['R','HR','RBI','SB','OBP','SLG','IP','W','SVHD','K','ERA','WHIP'];
const REV = new Set(['ERA','WHIP']);
const SLOT_BENCH = new Set(['Bench','IL']);
const BALL_IDS   = new Set(['5','90']);
const CALLED_IDS = new Set(['36']);
const SWING_IDS  = new Set(['37']);
const FOUL_IDS   = new Set(['21']);
const INPLAY_IDS = new Set(['2','3','4','22','24','28','32','33']);
const ALL_PITCH_IDS = new Set([...BALL_IDS,...CALLED_IDS,...SWING_IDS,...FOUL_IDS,...INPLAY_IDS]);
async function fetchExistingFromGitHub() {
try {
const url = `https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/${GITHUB_BRANCH}/${GITHUB_PATH}?_cb=${Date.now()}`;
const resp = await fetch(url);
if (!resp.ok) {
if (resp.status !== 404) console.warn('GitHub fetch failed:', resp.status);
return null;
}
const compressed = await resp.arrayBuffer();
const ds = new DecompressionStream('gzip');
const writer = ds.writable.getWriter();
writer.write(new Uint8Array(compressed));
writer.close();
const decompressed = await new Response(ds.readable).text();
return JSON.parse(decompressed);
} catch (e) {
console.warn('GitHub fetch/decompress failed:', e.message);
return null;
}
}
async function loadExistingData() {
const ghData = await fetchExistingFromGitHub();
if (ghData) return [ghData];
alert('Could not load existing data from GitHub -- falling back to local file picker.\n\n(Expected on the very first run, before anything has been uploaded yet. If this keeps happening on later runs, check your network connection or that the repo/path in GITHUB_OWNER/REPO/PATH are correct.)');
return await pickLocalFiles();
}
function pickLocalFiles() {
return new Promise(resolve => {
const wantsMerge = confirm('Merge with local JSON file(s) instead?\n\nOK = pick one or more existing JSON files (ctrl/cmd-click to select multiple).\nCancel = start fresh (no merge).');
if (!wantsMerge) { resolve([]); return; }
const input = document.createElement('input');
input.type = 'file';
input.accept = 'application/json';
input.multiple = true;
input.style.display = 'none';
document.body.appendChild(input);
input.addEventListener('change', () => {
const files = Array.from(input.files || []);
document.body.removeChild(input);
if (!files.length) { resolve([]); return; }
Promise.all(files.map(file => new Promise(res => {
const reader = new FileReader();
reader.onload = () => {
try { res(JSON.parse(reader.result)); }
catch (e) { alert(`Could not parse ${file.name} as JSON -- skipping it.`); res(null); }
};
reader.onerror = () => { alert(`Could not read ${file.name} -- skipping it.`); res(null); };
reader.readAsText(file);
}))).then(results => resolve(results.filter(r => r)));
});
input.click();
});
}
function mergePeriods(existingPeriods, newPeriods) {
const byPeriod = new Map();
for (const p of (existingPeriods || [])) byPeriod.set(p.period, p);
for (const p of newPeriods) byPeriod.set(p.period, p);
return Array.from(byPeriod.values()).sort((a,b) => a.period - b.period);
}
function txKey(t) {
const moveSig = (t.moves && t.moves.length) ? t.moves.map(m => m.raw).join('||') : (t.rawFallback || '');
return `${t.date}|${t.time}|${t.activityType}|${moveSig}`;
}
const existingFiles = await loadExistingData();
let existingPeriodsList = [];
let existingTxns = [];
let existingGames = {};
for (const data of existingFiles) {
if (data.periods) existingPeriodsList = mergePeriods(existingPeriodsList, data.periods);
if (data.transactions) existingTxns = existingTxns.concat(data.transactions);
if (data.games) existingGames = { ...existingGames, ...data.games };
}
{
const byKey = new Map();
for (const t of existingTxns) byKey.set(txKey(t), t);
existingTxns = Array.from(byKey.values());
}
const existingTxKeys = new Set(existingTxns.map(txKey));
const isMerging = existingPeriodsList.length > 0 || existingTxns.length > 0 || Object.keys(existingGames).length > 0;
const SEASON_START = new Date(2026, 2, 25); // period 1 = March 25, 2026 -- used only to SUGGEST defaults; actual period dates always come from the page itself, not this formula (see pageDateToYMD)
const SEASON_START_YMD = `${SEASON_START.getFullYear()}${String(SEASON_START.getMonth()+1).padStart(2,'0')}${String(SEASON_START.getDate()).padStart(2,'0')}`; // "20260325" -- used to exclude spring training games from fantasy stats (see isFantasyEligibleGame)
function dateToPeriod(d) {
const dMidnight = new Date(d.getFullYear(), d.getMonth(), d.getDate());
const diffDays = Math.round((dMidnight - SEASON_START) / (1000*60*60*24));
return diffDays + 1;
}
const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);
const suggestedEndPeriod = dateToPeriod(yesterday);
const suggestedStartPeriod = existingPeriodsList.length ? Math.max(1, suggestedEndPeriod - 6) : 1;
const todayStr = (() => {
const d = new Date();
return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
})();
const txDefaultStartStr = (() => {
const d = new Date();
d.setDate(d.getDate() - 7);
return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
})();
function fmtTimestampPrefix(d) { return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${String(d.getHours()).padStart(2,'0')}${String(d.getMinutes()).padStart(2,'0')}`; }
const startPeriod = parseInt(prompt('[Rosters] Start period (defaults to 7 periods back, to catch any MLB stat corrections):', String(suggestedStartPeriod)) || String(suggestedStartPeriod));
const endPeriod   = parseInt(prompt('[Rosters] End period (defaults to yesterday -- today\'s games are usually still in progress):', String(suggestedEndPeriod)) || String(suggestedEndPeriod));
const txStartDate = prompt('[Transactions] Start date (YYYYMMDD, defaults to 7 days back):', txDefaultStartStr);
const txEndDate   = prompt('[Transactions] End date (YYYYMMDD):', todayStr);
const txMaxPages  = parseInt(prompt('[Transactions] Max pages to check (auto-stops early):', '60') || '60');
const waitMs      = parseInt(prompt('Page load wait ms, for roster/transaction pages (3000 recommended):', '3000') || '3000');
if ([startPeriod,endPeriod,txMaxPages,waitMs].some(isNaN) || !txStartDate || !txEndDate) { alert('Invalid input.'); return; }
const ui = document.createElement('div');
ui.id = 'poe-ui';
ui.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1a1a1a;color:#fff;font:13px/1.4 system-ui;padding:10px 16px;display:flex;gap:12px;align-items:center;';
ui.innerHTML = '<span id="poe-msg">Starting...</span><div style="flex:1;height:6px;background:#444;border-radius:3px;overflow:hidden"><div id="poe-fill" style="height:100%;width:0%;background:#2a78d6;border-radius:3px;"></div></div><span id="poe-cnt"></span>';
document.body.appendChild(ui);
const frame = document.createElement('iframe');
frame.id = 'poe-frame';
frame.style.cssText = 'position:fixed;bottom:0;right:0;width:1200px;height:700px;z-index:2147483646;border:2px solid #2a78d6;background:#fff;';
document.body.appendChild(frame);
const setUI = (msg,pct,cnt) => {
const m=document.getElementById('poe-msg'); if(m) m.textContent=msg;
const f=document.getElementById('poe-fill'); if(f) f.style.width=Math.max(0,Math.min(100,Math.round(pct)))+'%';
const c=document.getElementById('poe-cnt'); if(c) c.textContent=cnt;
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const loadPage = url => new Promise(resolve => { frame.onload = () => resolve(); frame.src = url; });
function pNum(s){ if(!s) return 0; s=s.trim(); if(!s||s==='--'||s==='-') return 0; return parseFloat(s)||0; }
function isTotalsRow(row){ return !!row.querySelector('td.total-col'); }
function isSubHeader(row){ return row.classList.contains('Table__sub-header'); }
function extractDate(doc){
try { for (const th of doc.querySelectorAll('th')) { const m=(th.textContent||'').match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d+/); if(m) return m[0]; } } catch(e){}
return null;
}
const MONTH_MAP = {Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11};
function pageDateToYMD(pageDate) {
if (!pageDate) return null;
const m = pageDate.match(/([A-Za-z]{3})\w*\s+(\d+)/);
if (!m) return null;
const mon = MONTH_MAP[m[1].slice(0,3)];
if (mon === undefined) return null;
const d = new Date(SEASON, mon, parseInt(m[2]));
return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
}
function parsePlayerCell(td){
if (!td) return {name:'',team:'',pos:''};
const anchors=Array.from(td.querySelectorAll('a.AnchorLink'));
const nameA=anchors.find(a=>!a.classList.contains('playerinfo__news')&&!a.classList.contains('pro-team-link')&&a.textContent.trim().length>0);
return { name:nameA?nameA.textContent.trim():'', team:(td.querySelector('span.playerinfo__playerteam')||{}).textContent||'', pos:(td.querySelector('span.playerinfo__playerpos')||{}).textContent||'' };
}
function scrapeRosterTable(container, needStatRow) {
const tables=container.querySelectorAll('table');
if (tables.length<2) return {rosterRows:[],statRows:[]};
const rosterTable=tables[0], statsTable=tables[tables.length-1];
const rosterRows=[];
for (const row of rosterTable.querySelectorAll('tr')) {
if (isSubHeader(row)||isTotalsRow(row)) continue;
const tds=row.querySelectorAll('td');
if (!tds.length) continue;
const slotText=tds[0].textContent.trim();
if (!slotText) continue;
const {name,team,pos}=parsePlayerCell(tds[1]||null);
rosterRows.push({slot:slotText,name,team,pos});
}
let statRows=[];
if (needStatRow) {
for (const row of statsTable.querySelectorAll('tr')) {
if (isSubHeader(row)||isTotalsRow(row)) continue;
const tds=row.querySelectorAll('td');
if (!tds.length) continue;
statRows.push(Array.from(tds).map(td=>td.textContent.trim()));
}
}
return {rosterRows,statRows};
}
function scrapePage(doc){
const date=extractDate(doc);
const batters=[],pitchers=[];
try {
const containers=Array.from(doc.querySelectorAll('div.ResponsiveTable'));
let batC=null,pitC=null;
for (const c of containers) {
const h=(c.querySelector('th')||{}).textContent||'';
if (h.includes('Batter')||h.includes('Hitter')) batC=c;
else if (h.includes('Pitcher')) pitC=c;
}
if (!batC&&containers.length>=1) batC=containers[0];
if (!pitC&&containers.length>=2) pitC=containers[1];
if (batC) {
const {rosterRows}=scrapeRosterTable(batC, false);
rosterRows.forEach(r=>{
const isBench=SLOT_BENCH.has(r.slot)||r.slot.startsWith('IL');
batters.push({ slot:r.slot,name:r.name,team:r.team,pos:r.pos,active:!isBench });
});
}
if (pitC) {
const {rosterRows,statRows}=scrapeRosterTable(pitC, true);
rosterRows.forEach((r,i)=>{
const sc=statRows[i]||[];
const isBench=SLOT_BENCH.has(r.slot)||r.slot.startsWith('IL');
pitchers.push({ slot:r.slot,name:r.name,team:r.team,pos:r.pos,active:!isBench, W:pNum(sc[5]),SVHD:pNum(sc[8]) });
});
}
} catch(e) { batters.push({error:e.message}); }
return {batters,pitchers,date};
}
const allPeriods=[];
const neededDates = new Set(); // YYYYMMDD strings the game-fetch phase needs to cover
const perfTotal = (endPeriod-startPeriod+1)*TIDS.length;
let perfDone=0;
for (let period=startPeriod; period<=endPeriod; period++) {
const periodPlayers={};
let periodDate=null;
for (const tid of TIDS) {
setUI(`[Rosters] P${period}/${endPeriod} · ${TEAMS[tid]}`,(perfDone/perfTotal)*100,`${perfDone}/${perfTotal}`);
const url=`https://fantasy.espn.com/baseball/team?leagueId=${LEAGUE}&teamId=${tid}&scoringPeriodId=${period}&statSplit=singleScoringPeriod&_cb=${Date.now()}`;
await loadPage(url);
await sleep(waitMs);
let players={batters:[],pitchers:[],date:null};
try { players=scrapePage(frame.contentDocument||frame.contentWindow.document); } catch(e){}
periodPlayers[tid]=players;
if (!periodDate&&players.date) periodDate=players.date;
perfDone++;
}
const periodYMD = pageDateToYMD(periodDate);
if (periodYMD) neededDates.add(periodYMD);
allPeriods.push({period, date:periodDate, dateYMD:periodYMD, players:periodPlayers});
}
const mergedPeriods = mergePeriods(existingPeriodsList, allPeriods);
for (const p of mergedPeriods) {
if (!p.dateYMD && p.date) p.dateYMD = pageDateToYMD(p.date);
}
for (const p of mergedPeriods) { if (p.dateYMD) neededDates.add(p.dateYMD); }
function teamIdFromHref(href){ if(!href) return null; const m=href.match(/teamId=(\d+)/); return m?parseInt(m[1]):null; }
function parseMoveText(text){
const m=text.match(/^(.*?)\s+(added|dropped|traded)\s+(.*?),\s+([A-Za-z]+)\s+([A-Za-z0-9\/]+)\s+(from|to)\s+(.*)$/);
if (m) {
const [,team,verb,player,playerTeam,playerPos,prep,rest]=m;
const bidM=rest.match(/\$(\d+)/);
return { raw:text,parsed:true,isCash:false, team:team.trim(),verb,player:player.trim(), playerTeam,playerPos,prep,detail:rest.trim(), bid:bidM?parseInt(bidM[1]):null, destTeam:verb==='traded'?rest.trim():null };
}
const mCash=text.match(/^(.*?)\s+(traded)\s+\$(\d+)\s+FAAB\s+(to)\s+(.*)$/);
if (mCash) {
const [,team,verb,amount,prep,rest]=mCash;
return { raw:text,parsed:true,isCash:true, team:team.trim(),verb,player:null, playerTeam:null,playerPos:null,prep,detail:rest.trim(), bid:null,cashAmount:parseInt(amount),destTeam:rest.trim() };
}
const mNoTeam=text.match(/^(.*?)\s+(added|dropped|traded)\s+(.*?),\s*(from|to)\s+(.*)$/);
if (mNoTeam) {
const [,team,verb,player,prep,rest]=mNoTeam;
const bidM=rest.match(/\$(\d+)/);
return { raw:text,parsed:true,isCash:false, team:team.trim(),verb,player:player.trim(), playerTeam:null,playerPos:null,prep,detail:rest.trim(), bid:bidM?parseInt(bidM[1]):null, destTeam:verb==='traded'?rest.trim():null };
}
return { raw:text, parsed:false };
}
function scrapeActivityPage(doc){
const rows=Array.from(doc.querySelectorAll('tr.Table__TR'));
const out=[];
rows.forEach(row=>{
if (!row.querySelector('td.Table__TD')) return;
const dateEl=row.querySelector('.activityDate .date');
const timeEl=row.querySelector('.activityDate .time');
const date=dateEl?dateEl.textContent.trim():null;
const time=timeEl?timeEl.textContent.trim():null;
const typeSpans=row.querySelectorAll('.typeInfo span');
const activityType=typeSpans.length>1?typeSpans[1].textContent.trim():(typeSpans[0]?typeSpans[0].textContent.trim():null);
const actionLinks=Array.from(row.querySelectorAll('.actionCell a.AnchorLink')).map(a=>({text:a.textContent.trim(),href:a.getAttribute('href'),teamId:teamIdFromHref(a.getAttribute('href'))}));
const detailSpans=Array.from(row.querySelectorAll('.transactionCell > span.transaction-details'));
const moves=detailSpans.map(s=>parseMoveText(s.textContent.trim()));
if (moves.length===0) {
const rawEl=row.querySelector('.recentActivityDetail');
out.push({date,time,activityType,moves:[],rawFallback:rawEl?rawEl.textContent.trim():null,actionLinks});
} else {
out.push({date,time,activityType,moves,actionLinks});
}
});
return out;
}
const allTxRows=[];
let txPage=1;
let consecutiveEmpty=0, consecutiveStale=0;
while (txPage<=txMaxPages) {
setUI(`[Transactions] Page ${txPage} (max ${txMaxPages})`, 100, `${allTxRows.length} txns`);
const url=`https://fantasy.espn.com/baseball/recentactivity?leagueId=${LEAGUE}&endDate=${txEndDate}&page=${txPage}&seasonId=${SEASON}&startDate=${txStartDate}&teamId=-1&transactionType=-2&activityType=2`;
await loadPage(url);
await sleep(waitMs);
let rows=[];
try { rows=scrapeActivityPage(frame.contentDocument||frame.contentWindow.document); } catch(e){}
if (rows.length===0) { await sleep(1500); try { rows=scrapeActivityPage(frame.contentDocument||frame.contentWindow.document); } catch (e){} }
if (rows.length===0) {
consecutiveEmpty++;
if (consecutiveEmpty>=2) break;
} else {
consecutiveEmpty=0;
allTxRows.push(...rows);
if (isMerging) {
const newCount=rows.filter(r=>!existingTxKeys.has(txKey(r))).length;
if (newCount===0) { consecutiveStale++; if (consecutiveStale>=2) break; }
else consecutiveStale=0;
}
}
txPage++;
}
let txEdgeWarning = false;
for (const t of allTxRows) {
const tYMD = pageDateToYMD(t.date);
if (tYMD && tYMD === txStartDate) { txEdgeWarning = true; break; }
}
const byKey=new Map();
for (const t of existingTxns) byKey.set(txKey(t), t);
for (const t of allTxRows) byKey.set(txKey(t), t);
const mergedTxns=Array.from(byKey.values());
frame.remove();
async function fetchDaySchedule(dateStr) {
try {
const url = `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=${dateStr}`;
const resp = await fetch(url);
if (!resp.ok) return [];
const data = await resp.json();
return (data.events || []).map(e => ({ id: e.id, date: dateStr }));
} catch (e) { return []; }
}
async function fetchGameBoxscore(gameId, dateStr) {
try {
const url = `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event=${gameId}`;
const resp = await fetch(url);
if (!resp.ok) return null;
const data = await resp.json();
return parseFullBoxscore(data, gameId, dateStr);
} catch (e) { return null; }
}
function statsToObject(labels, stats) {
const out = {};
labels.forEach((label, i) => { out[label] = stats[i] !== undefined ? stats[i] : null; });
return out;
}
function utcToETDateString(isoUTC) {
if (!isoUTC) return null;
const d = new Date(isoUTC);
if (isNaN(d.getTime())) return null;
const fmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });
const parts = fmt.formatToParts(d);
const y = parts.find(p => p.type === 'year').value;
const m = parts.find(p => p.type === 'month').value;
const day = parts.find(p => p.type === 'day').value;
return `${y}${m}${day}`;
}
function extractScheduledGameTime(data) {
const candidates = [
data?.header?.competitions?.[0]?.date,
data?.gameInfo?.date,
data?.header?.gameInfo?.date,
];
for (const c of candidates) { if (c) return c; }
return null;
}
function extractGameStatusDiagnostic(data) {
const status = data?.header?.competitions?.[0]?.status;
if (!status) return null;
return { type: status?.type?.name || null, detail: status?.type?.detail || null, description: status?.type?.description || null };
}
function extractDoubleheaderGameNumber(data) {
const note = data?.header?.gameNote;
if (!note) return null;
const m = String(note).match(/Doubleheader\s*-\s*Game\s*(\d+)/i);
return m ? parseInt(m[1]) : null;
}
function parseFullBoxscore(data, gameId, dateStr) {
const bs = data.boxscore || {};
const teamsMeta = {};
(bs.teams || []).forEach(t => { teamsMeta[(t.team||{}).abbreviation] = t; });
const scheduledStartTimeUTC = extractScheduledGameTime(data);
const gameStatusDiagnostic = extractGameStatusDiagnostic(data);
const doubleheaderGame = extractDoubleheaderGameNumber(data);
const batting = {};
const pitching = {};
const idToPitcherKey = {};
const idToBatterKey = {};
for (const team of (bs.players || [])) {
const teamAbbr = (team.team || {}).abbreviation || '';
batting[teamAbbr] = batting[teamAbbr] || {};
pitching[teamAbbr] = pitching[teamAbbr] || {};
for (const sg of (team.statistics || [])) {
const labels = sg.labels || [];
const isPitching = labels[0] === 'IP';
for (const ath of (sg.athletes || [])) {
const athlete = ath.athlete || {};
const name = athlete.displayName || '';
const statsObj = statsToObject(labels, ath.stats || []);
if (isPitching) {
pitching[teamAbbr][name] = { ...statsObj, balls:0, called:0, swinging:0, foul:0, inplay:0, pure:0, FPS:0, BF:0, GB:0, FB:0 };
idToPitcherKey[athlete.id] = { teamAbbr, name };
} else {
batting[teamAbbr][name] = { ...statsObj, SB:0, CS:0, '1B':0, '2B':0, '3B':0, HBP:0, SF:0 };
idToBatterKey[athlete.id] = { teamAbbr, name };
}
}
}
}
for (const play of (data.plays || [])) {
const typeId = String((play.type||{}).id || '');
if (!ALL_PITCH_IDS.has(typeId)) continue;
const atBatPitch = play.atBatPitchNumber || 0;
if (!atBatPitch) continue;
let pitcherId = null;
for (const p of (play.participants||[])) { if (p.type==='pitcher') { pitcherId=(p.athlete||{}).id; break; } }
if (!pitcherId || !idToPitcherKey[pitcherId]) continue;
const { teamAbbr, name } = idToPitcherKey[pitcherId];
const ps = pitching[teamAbbr] && pitching[teamAbbr][name];
if (!ps) continue;
if (atBatPitch === 1) { ps.BF++; if (!BALL_IDS.has(typeId)) ps.FPS++; }
if (BALL_IDS.has(typeId)) ps.balls++;
else if (CALLED_IDS.has(typeId)) ps.called++;
else if (SWING_IDS.has(typeId)) ps.swinging++;
else if (FOUL_IDS.has(typeId)) ps.foul++;
else if (INPLAY_IDS.has(typeId)) {
ps.inplay++;
const altType = ((play.alternativeType||{}).type || '').toLowerCase();
const traj = (play.trajectory || '').toUpperCase();
if (altType.includes('ground')) ps.GB++;
else if (altType.includes('fly') || altType.includes('pop')) ps.FB++;
else if (traj === 'G') ps.GB++;
else if (traj === 'F' || traj === 'P') ps.FB++;
}
}
for (const team of Object.values(pitching)) { for (const ps of Object.values(team)) ps.pure = ps.called + ps.swinging + ps.foul; }
function normalizeAccents(s) { return s.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
for (const teamRoster of (data.rosters || [])) {
for (const player of (teamRoster.roster || [])) {
const athleteId = (player.athlete || {}).id;
const key = idToBatterKey[athleteId];
if (!key) continue;
const sbStat = (player.stats || []).find(s => s.name === 'stolenBases');
if (sbStat) batting[key.teamAbbr][key.name].SB = sbStat.value || 0;
}
}
function parseNameCountPairs(displayValue, knownNames) {
const results = {};
if (!displayValue) return results;
const normDisplay = normalizeAccents(displayValue).toLowerCase();
for (const name of knownNames) {
const nameParts = normalizeAccents(name).toLowerCase().split(/\s+/);
let matched = false;
for (let i = 0; i < nameParts.length && !matched; i++) {
const candidate = nameParts.slice(i).join(' ');
if (candidate.length < 3) continue;
let searchFrom = 0;
while (true) {
const idx = normDisplay.indexOf(candidate, searchFrom);
if (idx === -1) break;
const before = idx === 0 ? ' ' : normDisplay[idx - 1];
if (!/[\s;,]/.test(before)) { searchFrom = idx + candidate.length; continue; }
const afterIdx = idx + candidate.length;
const rest = displayValue.slice(afterIdx);
const m = rest.match(/^\.?\s*(\d+)?\s*(?:\(|,|;|$)/);
if (m) {
const count = m[1] ? parseInt(m[1]) : 1;
results[name] = (results[name] || 0) + count;
searchFrom = afterIdx + (m[0].endsWith('(') ? m[0].length : Math.max(1, m[0].length));
matched = true;
} else { searchFrom = afterIdx; }
}
}
}
return results;
}
function findDetailStat(team, groupName, statName) {
const group = (team.details || []).find(d => d.name === groupName);
if (!group) return null;
const stat = (group.stats || []).find(s => s.name === statName);
return stat ? stat.displayValue : null;
}
const boxTeamAbbrs = (bs.teams || []).map(t => (t.team || {}).abbreviation).filter(Boolean);
for (const team of (bs.teams || [])) {
const teamAbbr = (team.team || {}).abbreviation || '';
const oppAbbr = boxTeamAbbrs.find(a => a !== teamAbbr) || teamAbbr;
const ownNames = Object.keys(batting[teamAbbr] || {});
const oppNames = Object.keys(batting[oppAbbr] || {});
// "whose" = which team's batters this detail group actually names.
// battingDetails describes a team's OWN batters (their doubles, their sac
// flies, etc). pitchingDetails describes what that team's PITCHERS did TO
// THE OPPONENT -- e.g. team X's hitByPitch names a batter on the OTHER
// team who X's pitcher hit, never X's own batter. Confirmed via a live
// BAL@PIT box score: BAL's pitchingDetails.hitByPitch displayValue was
// "Griffin (by Baz)" -- Baz pitches for BAL, so Griffin is the PIT batter
// who got hit, not a BAL player. Searching teamAbbr's own knownNames for
// pitchingDetails stats silently matched nothing for nearly the entire
// season -- this is the dominant reason HBP was almost never captured.
const fieldMap = [
['battingDetails', 'doubles', '2B', 'own'], ['battingDetails', 'triples', '3B', 'own'],
['pitchingDetails', 'hitByPitch', 'HBP', 'opp'], ['battingDetails', 'sacFly', 'SF', 'own'],
['baserunningDetails', 'caughtStealing', 'CS', 'own'],
];
for (const [groupName, statName, outKey, whose] of fieldMap) {
const displayValue = findDetailStat(team, groupName, statName);
if (!displayValue) continue;
const targetAbbr = whose === 'opp' ? oppAbbr : teamAbbr;
const targetNames = whose === 'opp' ? oppNames : ownNames;
const counts = parseNameCountPairs(displayValue, targetNames);
for (const [name, count] of Object.entries(counts)) {
if (batting[targetAbbr] && batting[targetAbbr][name]) batting[targetAbbr][name][outKey] = count;
}
}
}
for (const players of Object.values(batting)) {
for (const stats of Object.values(players)) {
const h = parseInt(stats.H || 0) || 0;
const hr = parseInt(stats.HR || 0) || 0;
stats['1B'] = Math.max(0, h - stats['2B'] - stats['3B'] - hr);
}
}
const teamAbbrs = Object.keys(teamsMeta);
function sumH(teamPlayers) { return Object.values(teamPlayers || {}).reduce((sum, s) => sum + (parseInt(s.H || 0) || 0), 0); }
let hitsConsistencyCheck = null;
if (teamAbbrs.length === 2) {
const [teamA, teamB] = teamAbbrs;
const pitchingH_A = sumH(pitching[teamA]), pitchingH_B = sumH(pitching[teamB]);
const battingH_A = sumH(batting[teamA]), battingH_B = sumH(batting[teamB]);
hitsConsistencyCheck = {
[`${teamA}PitchingVs${teamB}Batting`]: { pitchingH: pitchingH_A, battingH: battingH_B, match: pitchingH_A === battingH_B },
[`${teamB}PitchingVs${teamA}Batting`]: { pitchingH: pitchingH_B, battingH: battingH_A, match: pitchingH_B === battingH_A }
};
}
return {
gameId, date: dateStr, scheduledStartTimeUTC,
dateET: utcToETDateString(scheduledStartTimeUTC) || dateStr,
gameStatusDiagnostic, doubleheaderGame, hitsConsistencyCheck,
teams: teamAbbrs, batting, pitching,
scraperVersion: GAME_SCRAPER_VERSION
};
}
const games = { ...existingGames };
const sortedNeededDates = Array.from(neededDates).sort();
let fetchedCount = 0, skippedCount = 0, failedCount = 0;
let dayIdx = 0;
for (const dateStr of sortedNeededDates) {
dayIdx++;
setUI(`[Games] Day ${dayIdx}/${sortedNeededDates.length}: fetching schedule for ${dateStr}...`, (dayIdx/sortedNeededDates.length)*100, `${fetchedCount} games fetched`);
const dayGames = await fetchDaySchedule(dateStr);
await sleep(200);
for (const g of dayGames) {
const existing = games[g.id];
const hasBattingData = existing && Object.values(existing.batting || {}).some(team => Object.keys(team).length > 0);
const isCurrentVersion = existing && existing.scraperVersion === GAME_SCRAPER_VERSION;
if (hasBattingData && isCurrentVersion) { skippedCount++; continue; }
setUI(`[Games] Day ${dayIdx}/${sortedNeededDates.length}: game ${g.id}...`, (dayIdx/sortedNeededDates.length)*100, `${fetchedCount} fetched, ${skippedCount} already had`);
const boxscore = await fetchGameBoxscore(g.id, dateStr);
if (boxscore) { games[g.id] = boxscore; fetchedCount++; } else { failedCount++; }
await sleep(200);
}
}
function round3(x) { return x === null || x === undefined ? null : Math.round(x * 1000) / 1000; }
function addRateStatChecks(allGames) {
const byPlayer = {};
for (const [gid, game] of Object.entries(allGames)) {
for (const [teamAbbr, batters] of Object.entries(game.batting || {})) {
for (const [name, stats] of Object.entries(batters)) {
(byPlayer[name] = byPlayer[name] || []).push({ gameId: gid, date: game.date, stats });
}
}
}
for (const appearances of Object.values(byPlayer)) {
appearances.sort((a, b) => a.date.localeCompare(b.date) || a.gameId.localeCompare(b.gameId));
for (const { stats: s } of appearances) {
const ab = parseInt(s.AB || 0) || 0;
const h = parseInt(s.H || 0) || 0;
const bb = parseInt(s.BB || 0) || 0;
const hbp = s.HBP || 0;
const sf = s.SF || 0;
const singles = s['1B'] || 0, doubles = s['2B'] || 0, triples = s['3B'] || 0, hr = parseInt(s.HR || 0) || 0;
const tb = singles * 1 + doubles * 2 + triples * 3 + hr * 4;
s.PA = ab + bb + hbp + sf;
const gObpDen = ab + bb + hbp, gObpNum = h + bb + hbp;
s.thisGame = { AVG: ab > 0 ? round3(h / ab) : null, OBP: gObpDen > 0 ? round3(gObpNum / gObpDen) : null, SLG: ab > 0 ? round3(tb / ab) : null };
if (s.AVG !== undefined) {
s.espnSeasonToDate = { AVG: s.AVG, OBP: s.OBP, SLG: s.SLG };
delete s.AVG; delete s.OBP; delete s.SLG;
}
}
}
}
addRateStatChecks(games);
function linkDoubleheadersAndBuildOrder(allGames) {
const byDateTeams = {};
for (const [gid, g] of Object.entries(allGames)) {
if (!g.doubleheaderGame) continue;
const key = `${g.dateET}|${[...(g.teams || [])].sort().join(',')}`;
(byDateTeams[key] = byDateTeams[key] || []).push(gid);
}
for (const gids of Object.values(byDateTeams)) {
if (gids.length !== 2) continue;
const [a, b] = gids;
allGames[a].doubleheaderCompanionGameId = b;
allGames[b].doubleheaderCompanionGameId = a;
}
function anchorTime(g) {
if (g.doubleheaderGame && g.doubleheaderCompanionGameId) {
const companion = allGames[g.doubleheaderCompanionGameId];
const own = g.scheduledStartTimeUTC || '';
const comp = (companion && companion.scheduledStartTimeUTC) || '';
if (own && comp) return own < comp ? own : comp;
return own || comp;
}
return g.scheduledStartTimeUTC || '';
}
function pairKey(gid, g) {
if (g.doubleheaderGame && g.doubleheaderCompanionGameId) {
return g.gameId < g.doubleheaderCompanionGameId ? g.gameId : g.doubleheaderCompanionGameId;
}
return gid;
}
return Object.keys(allGames).sort((a, b) => {
const ga = allGames[a], gb = allGames[b];
return (ga.dateET || '').localeCompare(gb.dateET || '')
|| anchorTime(ga).localeCompare(anchorTime(gb))
|| pairKey(a, ga).localeCompare(pairKey(b, gb))
|| (ga.doubleheaderGame || 0) - (gb.doubleheaderGame || 0)
|| (ga.scheduledStartTimeUTC || '').localeCompare(gb.scheduledStartTimeUTC || '')
|| a.localeCompare(b);
});
}
const orderedGameIds = linkDoubleheadersAndBuildOrder(games);
function isFantasyEligibleGame(g) {
if (!g.teams) return true;
if (g.teams.includes('AL') || g.teams.includes('NL')) return false;
if (g.dateET && g.dateET < SEASON_START_YMD) return false;
return true;
}
function buildGamesByDate(allGames) {
const idx = {};
for (const [gid, g] of Object.entries(allGames)) {
if (!g.dateET) continue;
if (!isFantasyEligibleGame(g)) continue;
(idx[g.dateET] = idx[g.dateET] || []).push(gid);
}
return idx;
}
function buildCollisionNames(allGames, section) {
const nameDateTeams = {}; // name -> { date -> Set(teams) }
for (const g of Object.values(allGames)) {
const d = g.dateET;
if (!d) continue;
for (const [team, players] of Object.entries(g[section] || {})) {
for (const name of Object.keys(players)) {
const byDate = (nameDateTeams[name] = nameDateTeams[name] || {});
(byDate[d] = byDate[d] || new Set()).add(team);
}
}
}
const collisions = new Set();
for (const [name, byDate] of Object.entries(nameDateTeams)) {
for (const teams of Object.values(byDate)) {
if (teams.size > 1) { collisions.add(name); break; }
}
}
return collisions;
}
function findPlayerAcrossTeams(game, section, name, collisionNames) {
if (collisionNames.has(name)) return null;
const matches = [];
for (const [teamAbbr, players] of Object.entries(game[section] || {})) {
if (players[name]) matches.push(players[name]);
}
return matches.length === 1 ? matches[0] : null;
}
function lookupBatterStats(allGames, gamesByDate, dateYMD, team, name, collisionNames) {
const gids = (dateYMD && gamesByDate[dateYMD]) || [];
let AB=0,H=0,BB=0,HR=0,RBI=0,R=0,SB=0,HBP=0,SF=0,singles=0,doubles=0,triples=0;
for (const gid of gids) {
const game = allGames[gid];
let s = game.batting && game.batting[team] && game.batting[team][name];
if (!s) s = findPlayerAcrossTeams(game, 'batting', name, collisionNames);
if (!s) continue;
AB+=parseInt(s.AB||0)||0; H+=parseInt(s.H||0)||0; BB+=parseInt(s.BB||0)||0;
HR+=parseInt(s.HR||0)||0; RBI+=parseInt(s.RBI||0)||0; R+=parseInt(s.R||0)||0;
SB+=s.SB||0; HBP+=s.HBP||0; SF+=s.SF||0;
singles+=s['1B']||0; doubles+=s['2B']||0; triples+=s['3B']||0;
}
const PA = AB+BB+HBP+SF;
const TB = singles*1+doubles*2+triples*3+HR*4;
return { AB,H,BB,HR,RBI,R,SB,HBP,SF,PA,TB };
}
function lookupPitcherStats(allGames, gamesByDate, dateYMD, team, name, collisionNames) {
const gids = (dateYMD && gamesByDate[dateYMD]) || [];
let IPouts=0,H=0,ER=0,BB=0,K=0;
for (const gid of gids) {
const game = allGames[gid];
let s = game.pitching && game.pitching[team] && game.pitching[team][name];
if (!s) s = findPlayerAcrossTeams(game, 'pitching', name, collisionNames);
if (!s) continue;
H+=parseInt(s.H||0)||0; ER+=parseInt(s.ER||0)||0; BB+=parseInt(s.BB||0)||0; K+=parseInt(s.K||0)||0;
const ipStr = s.IP;
if (ipStr != null) {
const parts = String(ipStr).split('.');
IPouts += (parseInt(parts[0])||0)*3 + (parts[1]?parseInt(parts[1]):0);
}
}
return { IPouts,H,ER,BB,K };
}
function outsToIP(outs){ return parseFloat(Math.floor(outs/3)+'.'+outs%3); }
function addToAccum(acc, periodPlayers, allGames, gamesByDate, dateYMD, batterCollisions, pitcherCollisions) {
(periodPlayers.batters||[]).filter(b=>b.active&&!b.error).forEach(b=>{
const s = lookupBatterStats(allGames, gamesByDate, dateYMD, b.team, b.name, batterCollisions);
acc.R+=s.R; acc.HR+=s.HR; acc.RBI+=s.RBI; acc.SB+=s.SB;
acc.H+=s.H; acc.AB+=s.AB; acc.BB+=s.BB; acc.HBP+=s.HBP; acc.SF+=s.SF;
acc.PA+=s.PA; acc.TB+=s.TB;
});
(periodPlayers.pitchers||[]).filter(p=>p.active&&!p.error).forEach(p=>{
const s = lookupPitcherStats(allGames, gamesByDate, dateYMD, p.team, p.name, pitcherCollisions);
acc.IPouts+=s.IPouts; acc.K+=s.K; acc.ER+=s.ER; acc.Hp+=s.H; acc.BBp+=s.BB;
acc.W+=p.W||0; acc.SVHD+=p.SVHD||0; // from the roster page directly, not the games join
});
}
function snapFromAccum(acc){
const IPfrac=acc.IPouts/3;
const obpN=acc.H+acc.BB+acc.HBP, obpD=acc.AB+acc.BB+acc.HBP+acc.SF; // real HBP/SF now, not the old back-solved estimate
return { R:acc.R,HR:acc.HR,RBI:acc.RBI,SB:acc.SB,PA:acc.PA,
OBP:obpD>0?parseFloat((obpN/obpD).toFixed(4)):0,
SLG:acc.AB>0?parseFloat((acc.TB/acc.AB).toFixed(4)):0,
IP:outsToIP(acc.IPouts),K:acc.K,W:acc.W,SVHD:acc.SVHD,
ERA:IPfrac>0?parseFloat((9*acc.ER/IPfrac).toFixed(3)):0,
WHIP:IPfrac>0?parseFloat(((acc.Hp+acc.BBp)/IPfrac).toFixed(3)):0 };
}
function computeRoto(snaps){
const roto={};
TIDS.forEach(tid=>{roto[tid]={total:0};});
CATS.forEach(cat=>{
const vals=TIDS.map(tid=>({tid,val:(snaps[tid]&&snaps[tid][cat])||0}));
const sorted=[...vals].sort((a,b)=>REV.has(cat)?a.val-b.val:b.val-a.val);
let i=0;
while(i<sorted.length){
let j=i;
while(j+1<sorted.length && sorted[j+1].val===sorted[i].val) j++;
let rankSum=0;
for(let p=i;p<=j;p++) rankSum+=(12-p);
const avgRank=rankSum/(j-i+1);
for(let k=i;k<=j;k++) roto[sorted[k].tid][cat]=avgRank;
i=j+1;
}
TIDS.forEach(tid=>{roto[tid].total+=roto[tid][cat]||0;});
});
return roto;
}
const gamesByDate = buildGamesByDate(games);
const batterCollisions = buildCollisionNames(games, 'batting');
const pitcherCollisions = buildCollisionNames(games, 'pitching');
const recomputeAccum={};
TIDS.forEach(tid=>{ recomputeAccum[tid]={R:0,HR:0,RBI:0,SB:0,H:0,AB:0,BB:0,HBP:0,SF:0,PA:0,TB:0,IPouts:0,K:0,W:0,SVHD:0,ER:0,Hp:0,BBp:0}; });
mergedPeriods.forEach(p => {
TIDS.forEach(tid => {
const players = p.players && p.players[tid];
if (players) addToAccum(recomputeAccum[tid], players, games, gamesByDate, p.dateYMD, batterCollisions, pitcherCollisions);
});
const snaps={};
TIDS.forEach(tid=>{ snaps[tid]=snapFromAccum({...recomputeAccum[tid]}); });
p.snap = snaps;
p.roto = computeRoto(snaps);
});
setUI('Done! Saving...',100,`${mergedPeriods.length} periods, ${Object.keys(games).length} games, ${mergedTxns.length} txns`);
const outMeta = {
league: LEAGUE, season: SEASON, teams: TEAMS,
lastUpdated: new Date().toISOString(),
totalGames: Object.keys(games).length,
orderedGameIds,
architectureNote: "periods[].players[tid] holds roster/slot assignment only (plus W/SVHD for pitchers, read off the page since they're decision stats not in the raw box score). All other stats (AB/H/BB/HR/RBI/R/SB/HBP/SF for batters; IP/ER/BB/K/pitch-level detail for pitchers) come from games{}, joined by team+name+date in period.snap/roto -- see games{} for the raw per-game data those are built from.",
orderedGameIdsNote: "games{} always iterates in ascending numeric game-ID order (a JS object quirk), which can put doubleheader makeup games out of chronological order. Use orderedGameIds instead to walk games in true date order with doubleheader pairs grouped together.",
rateStatsNote: "Within each game object, espnSeasonToDate is ESPN's own season-cumulative AVG/OBP/SLG as of that game; thisGame is computed from only that game's own stats; PA is also this-game-only: AB+BB+HBP+SF."
};
const jsonString = JSON.stringify({ meta:outMeta, periods:mergedPeriods, games, transactions:mergedTxns },null,2);
const blob=new Blob([jsonString],{type:'application/json'});
const a=document.createElement('a');
a.href=URL.createObjectURL(blob);
a.download=`${fmtTimestampPrefix(new Date())}_pennants_over_easy_unified.json`;
document.body.appendChild(a); a.click(); document.body.removeChild(a);

// ---- GitHub auto-upload ----
// Compresses the JSON (gzip, native browser API, no library needed) and
// pushes it to the repo's data/ folder via GitHub's Contents API. The repo's
// GitHub Actions workflow watches that exact path and runs the analytics
// pipeline automatically whenever it changes.
// (GITHUB_OWNER/REPO/BRANCH/PATH/TOKEN_KEY now declared near the top of the
// file, since loadExistingData() needs them too, before this section runs.)

async function gzipToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  const cs = new CompressionStream('gzip');
  const writer = cs.writable.getWriter();
  writer.write(bytes);
  writer.close();
  const compressed = new Uint8Array(await new Response(cs.readable).arrayBuffer());
  let binary = '';
  const chunkSize = 0x8000; // avoid call-stack limits on String.fromCharCode with huge arrays
  for (let i = 0; i < compressed.length; i += chunkSize) {
    binary += String.fromCharCode(...compressed.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function uploadToGitHub(jsonStr) {
  let token = localStorage.getItem(GITHUB_TOKEN_KEY);
  if (!token) {
    token = prompt('GitHub upload: paste your fine-grained Personal Access Token (Contents: Read and write, scoped to this repo only). Leave blank to skip GitHub upload for this run.');
    if (token) localStorage.setItem(GITHUB_TOKEN_KEY, token);
  }
  if (!token) return { skipped: true };

  try {
    const contentBase64 = await gzipToBase64(jsonStr);
    const apiUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_PATH}`;

    // Need the existing file's sha to update it rather than create a duplicate.
    let sha = null;
    const getResp = await fetch(`${apiUrl}?ref=${GITHUB_BRANCH}`, {
      headers: { 'Authorization': `token ${token}`, 'Accept': 'application/vnd.github+json' }
    });
    if (getResp.ok) {
      sha = (await getResp.json()).sha;
    } else if (getResp.status === 401 || getResp.status === 403) {
      localStorage.removeItem(GITHUB_TOKEN_KEY);
      return { error: `Token likely expired or was revoked (${getResp.status}) -- it's been cleared, you'll be re-prompted next run.` };
    } else if (getResp.status !== 404) {
      return { error: `Checking existing file failed: ${getResp.status} ${await getResp.text()}` };
    }

    const putBody = {
      message: `Auto-upload scrape ${new Date().toISOString()}`,
      content: contentBase64,
      branch: GITHUB_BRANCH,
    };
    if (sha) putBody.sha = sha;

    const putResp = await fetch(apiUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `token ${token}`,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(putBody),
    });
    if (!putResp.ok) {
      if (putResp.status === 401 || putResp.status === 403) {
        localStorage.removeItem(GITHUB_TOKEN_KEY); // token expired/revoked -- clear it so next run re-prompts instead of failing silently forever
        return { error: `Upload failed: ${putResp.status} (token likely expired or was revoked -- it's been cleared, you'll be re-prompted next run) ${await putResp.text()}` };
      }
      return { error: `Upload failed: ${putResp.status} ${await putResp.text()}` };
    }
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
}

setUI('Uploading to GitHub...', 100, '');
const ghResult = await uploadToGitHub(jsonString);
let ghMsg;
if (ghResult.skipped) ghMsg = 'GitHub upload skipped (no token entered).';
else if (ghResult.success) ghMsg = 'Uploaded to GitHub -- the pipeline will run automatically.';
else ghMsg = `GitHub upload FAILED: ${ghResult.error}\nThe local download still succeeded -- you can upload it manually as a fallback.`;

setTimeout(()=>{ document.getElementById('poe-ui')?.remove(); },3000);
alert(`Done! ${mergedPeriods.length} periods, ${Object.keys(games).length} games (${fetchedCount} new, ${skippedCount} already had, ${failedCount} failed), ${mergedTxns.length} transactions.\n\n${ghMsg}${txEdgeWarning ? `\n\nHeads up: transaction activity was found right at your start-date cutoff (${txStartDate}), so there could be older transactions just outside this window. If any recent trades/drops seem to have backdated timestamps, consider re-running with an earlier start date just this once.` : ''}`);
})();
