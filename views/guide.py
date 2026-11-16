"""views/guide.py - Panduan Demo sebagai OVERLAY di layar masuk (bukan tab/halaman).

Dibuka dari tombol "Demo Guide" di layar masuk (st.dialog). Berisi diagram arsitektur dan alur pelaksanaan yang
digambar dengan kode (SVG/CSS beranimasi, latar transparan mengikuti tema), tabel hak, dan batasan.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from i18n import L
from ui_kit import table

# ----------------------------------------------------------------------------------------------- palet
PAL = {
    True: dict(text="#E8EEF8", mute="#94A3B8", card="#111B2C", line="#2B3C57", blue="#4C9AFF", green="#34C77B", orange="#F59E4B",
               violet="#A78BFA", gcard="#0F2A22", ocard="#33200F", vcard="#221A3D", bcard="#10243F"),
    False: dict(text="#14213D", mute="#5B6B82", card="#FFFFFF", line="#C9D5E6", blue="#2F80ED", green="#16884A", orange="#D85A10",
                violet="#7C3AED", gcard="#E5F7EC", ocard="#FFE9DC", vcard="#F1E9FF", bcard="#EAF2FF"),
}


def _dark() -> bool:
    return not bool(st.session_state.get("light_mode", False))


def _viewer(body: str, css: str, dark: bool, nat_w: int, mode: str = "contain", hint: str = "") -> str:
    """Pemirsa diagram: roda mouse / tombol +/− untuk zoom, seret dengan kursor tangan untuk menggeser, dua jari untuk cubit.
    Konten vektor (tetap tajam saat diperbesar); tombol ⟲ menyesuaikan ulang ke ukuran bingkai."""
    c = PAL[dark]
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{{margin:0;height:100%;background:transparent;color:{c['text']};font-family:"Source Sans Pro","Segoe UI",Arial,sans-serif;overflow:hidden}}
#vp{{position:relative;height:100vh;box-sizing:border-box;overflow:hidden;cursor:grab;touch-action:none;user-select:none;-webkit-user-select:none;
  border:1px solid {c['line']};border-radius:12px}}
#vp.drag{{cursor:grabbing}}
#stage{{position:absolute;left:0;top:0;width:{nat_w}px;transform-origin:0 0;will-change:transform}}
#tools{{position:absolute;right:10px;top:10px;display:flex;gap:6px;align-items:center;z-index:5}}
#tools button{{width:32px;height:32px;border-radius:8px;border:1px solid {c['line']};background:{c['card']};color:{c['text']};font-size:17px;line-height:1;cursor:pointer}}
#tools button:hover{{border-color:{c['blue']}}}
#zl{{font-size:12px;min-width:44px;text-align:center;color:{c['mute']}}}
#hint{{position:absolute;left:12px;bottom:8px;font-size:12px;color:{c['mute']};z-index:5;pointer-events:none}}
{css}
@media (prefers-reduced-motion: reduce){{*{{animation:none !important}} animateMotion{{display:none}}}}
</style></head><body>
<div id="vp"><div id="tools"><button id="zo" title="Zoom out" aria-label="Zoom out">&minus;</button><span id="zl">100%</span>
<button id="zi" title="Zoom in" aria-label="Zoom in">+</button><button id="zf" title="Fit" aria-label="Fit">&#x27F2;</button></div>
<div id="stage">{body}</div><div id="hint">{hint}</div></div>
<script>
(function(){{
 var vp=document.getElementById('vp'),st=document.getElementById('stage'),zl=document.getElementById('zl');
 var k=1,x=0,y=0,KMIN=0.25,KMAX=6,touched=false,MODE='{mode}';
 function W(){{return st.offsetWidth}} function H(){{return st.offsetHeight}}
 function apply(){{st.style.transform='translate('+x+'px,'+y+'px) scale('+k+')';zl.textContent=Math.round(k*100)+'%'}}
 function fit(){{var vw=vp.clientWidth,vh=vp.clientHeight,kk=MODE==='width'?Math.min(vw/W(),1.3):Math.min(vw/W(),vh/H());
   k=Math.max(KMIN,Math.min(KMAX,kk));x=(vw-W()*k)/2;y=MODE==='width'?8:(vh-H()*k)/2;apply()}}
 function zoomAt(f,px,py){{var nk=Math.max(KMIN,Math.min(KMAX,k*f));if(nk===k)return;x=px-(px-x)*(nk/k);y=py-(py-y)*(nk/k);k=nk;touched=true;apply()}}
 function rect(){{return vp.getBoundingClientRect()}}
 vp.addEventListener('wheel',function(e){{e.preventDefault();var r=rect();zoomAt(Math.exp(-e.deltaY*0.0016),e.clientX-r.left,e.clientY-r.top)}},{{passive:false}});
 var P={{}},last=null;
 vp.addEventListener('pointerdown',function(e){{if(e.target.closest('#tools'))return;vp.setPointerCapture(e.pointerId);P[e.pointerId]={{x:e.clientX,y:e.clientY}};vp.classList.add('drag');last=null}});
 vp.addEventListener('pointermove',function(e){{var p=P[e.pointerId];if(!p)return;var ids=Object.keys(P);
   if(ids.length===2){{var a=P[ids[0]],b=P[ids[1]];var d0=Math.hypot(a.x-b.x,a.y-b.y);p.x=e.clientX;p.y=e.clientY;
     var d1=Math.hypot(a.x-b.x,a.y-b.y);var r=rect();if(d0>0)zoomAt(d1/d0,(a.x+b.x)/2-r.left,(a.y+b.y)/2-r.top);return}}
   x+=e.clientX-p.x;y+=e.clientY-p.y;p.x=e.clientX;p.y=e.clientY;touched=true;apply()}});
 function up(e){{delete P[e.pointerId];if(!Object.keys(P).length)vp.classList.remove('drag')}}
 vp.addEventListener('pointerup',up);vp.addEventListener('pointercancel',up);
 vp.addEventListener('dblclick',function(e){{if(e.target.closest('#tools'))return;touched=false;fit()}});
 function btn(id,f){{document.getElementById(id).addEventListener('click',function(){{var r=rect();zoomAt(f,r.width/2,r.height/2)}})}}
 btn('zi',1.25);btn('zo',0.8);document.getElementById('zf').addEventListener('click',function(){{touched=false;fit()}});
 window.addEventListener('resize',function(){{if(!touched)fit()}});
 fit();setTimeout(function(){{if(!touched)fit()}},120);
}})();
</script></body></html>"""


# ----------------------------------------------------------------------------------------------- diagram arsitektur (SVG)
def architecture_html(dark: bool, lang: str) -> str:
    c = PAL[dark]
    T = (lambda en, idn: en if lang == "en" else idn)

    def node(x, y, w, h, title, sub, fill, stroke):
        lines = "".join(f'<text x="{x + w / 2}" y="{y + 40 + i * 15}" class="sub">{s}</text>' for i, s in enumerate(sub))
        return (f'<g class="node"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
                f'<text x="{x + w / 2}" y="{y + 23}" class="ttl">{title}</text>{lines}</g>')

    def edge(d, color, label="", lx=0, ly=0, dur=1.4):
        lab = f'<text x="{lx}" y="{ly}" class="elab" fill="{color}">{label}</text>' if label else ""
        return (f'<path d="{d}" class="flow" stroke="{color}" style="animation-duration:{dur}s" marker-end="url(#a-{color[1:]})"/>'
                f'<circle r="3.6" fill="{color}"><animateMotion dur="{dur * 2.4}s" repeatCount="indefinite" path="{d}"/></circle>{lab}')

    markers = "".join(f'<marker id="a-{col[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                      f'<path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>' for col in (c["blue"], c["green"], c["orange"], c["violet"]))
    svg = f"""
<svg viewBox="0 0 960 540" width="960" height="540" role="img" aria-label="{T('SOMAT architecture','Arsitektur SOMAT')}">
<defs>{markers}</defs>
<rect x="686" y="10" width="270" height="214" rx="16" fill="none" stroke="{c['green']}" stroke-width="1.4" stroke-dasharray="6 5"/>
<text x="702" y="32" class="cl" fill="{c['green']}">{T('OPERATIONAL','OPERASIONAL')}</text>
<rect x="686" y="250" width="270" height="280" rx="16" fill="none" stroke="{c['orange']}" stroke-width="1.4" stroke-dasharray="6 5"/>
<text x="702" y="272" class="cl" fill="{c['orange']}">{T('RESEARCH DEMO (separate)','DEMO PENELITIAN (terpisah)')}</text>

{node(18, 30, 176, 72, T('User','Pengguna'), [T('sign in / demo account','login / akun demo')], c['card'], c['orange'])}
{node(18, 176, 176, 78, 'app.py', ['OPERATIONAL | DEMO', T('+ DEMO banner','+ banner DEMO')], c['bcard'], c['blue'])}
{node(18, 328, 176, 72, 'repo_router', [T('selects the repository','memilih repositori'), T('per session','per sesi')], c['bcard'], c['blue'])}

{node(284, 150, 230, 250, T('SOMAT engine (same)','Mesin SOMAT (sama)'), ['physics_engine', 'et0 (Hargreaves–Samani)', 'recommendation_service', T('Baseline M0 / M1','Baseline M0 / M1'), T('+ residual M2','+ residual M2')], c['vcard'], c['violet'])}

{node(702, 44, 238, 66, 'Neon PostgreSQL', ['repository.py', T('real records','catatan nyata')], c['gcard'], c['green'])}
{node(702, 126, 238, 80, 'data_hub', [T('Google Sheets sensors','sensor Google Sheets'), T('BMKG forecast (real)','prakiraan BMKG (asli)')], c['gcard'], c['green'])}
{node(702, 284, 238, 62, 'SQLite demo', [T('loaded from seed file','dimuat dari file seed')], c['ocard'], c['orange'])}
{node(702, 360, 238, 62, 'demo_weather', [T('synthetic temperature & rain','suhu & hujan sintetis')], c['ocard'], c['orange'])}
{node(702, 436, 238, 76, 'Random Forest', [T('trained on synthetic data','dilatih data sintetis'), T('(demo only)','(hanya demo)')], c['ocard'], c['orange'])}

{edge('M106,102 L106,172', c['orange'], '', 0, 0, 1.2)}
{edge('M106,254 L106,324', c['blue'], '', 0, 0, 1.2)}
{edge('M194,364 C236,364 244,340 280,340', c['blue'], '', 0, 0, 1.2)}
{edge('M514,190 C610,190 600,77 698,77', c['green'], T('run baseline','run baseline'), 606, 128, 1.6)}
{edge('M698,172 C610,172 600,235 514,235', c['green'], T('forecast (read-only)','prakiraan (baca saja)'), 626, 158, 1.8)}
{edge('M514,300 C600,300 610,315 698,315', c['orange'], T('run DEMO + decisions','run DEMO + keputusan'), 612, 288, 1.6)}
{edge('M698,391 C610,391 600,350 514,350', c['orange'], T('scenario weather','cuaca skenario'), 646, 372, 1.6)}
{edge('M698,474 C610,474 600,385 514,385', c['violet'], T('M2 residual','residual M2'), 652, 458, 1.8)}
</svg>"""
    css = f"""
.ttl{{font-size:14px;font-weight:700;text-anchor:middle;fill:{c['text']}}}
.sub{{font-size:11.5px;text-anchor:middle;fill:{c['mute']}}}
.cl{{font-size:12px;font-weight:700;letter-spacing:.06em}}
.elab{{font-size:11px;font-weight:600;text-anchor:middle}}
.flow{{fill:none;stroke-width:2;stroke-dasharray:6 7;animation:dash 1.2s linear infinite;opacity:.95}}
@keyframes dash{{to{{stroke-dashoffset:-26}}}}
.node{{filter:drop-shadow(0 2px 6px rgba(0,0,0,.18))}}
svg{{display:block}}
"""
    hint = T("Scroll to zoom · drag to pan · double-click to fit", "Gulir untuk zoom · seret untuk menggeser · klik dua kali untuk fit")
    return _viewer(svg, css, dark, 960, "contain", hint)


# ----------------------------------------------------------------------------------------------- alur pelaksanaan (timeline beranimasi)
STEPS = [
    ("🔑", ("Sign in", "Masuk"), ("Choose Demo as Admin / Operator / Viewer on the sign-in screen. The orange DEMO banner appears.",
                                  "Pilih Demo sebagai Admin / Operator / Pengamat di layar masuk. Banner oranye DEMO tampil.")),
    ("🗂️", ("Data is already there", "Data sudah terisi"), ("6 plots, 35+ days of h readings, decisions, irrigation records and a pending recommendation load by themselves.",
                                                            "6 petak, riwayat h 35+ hari, keputusan, irigasi, dan rekomendasi menunggu terisi otomatis.")),
    ("📊", ("Overview", "Ringkasan"), ("Six scenarios (irrigate, safe, rain hold, stale h, missing parameter, target not reachable) with charts.",
                                    "Enam skenario (irigasi, aman, tahan hujan, h usang, parameter hilang, target tak tercapai) beserta grafik.")),
    ("🪣", ("Field observations", "Pengamatan lapangan"), ("Operator enters h from the pipe: Fill example → Save. Try Correct and Void.",
                                                          "Operator mengisi h dari pipa: Isi contoh → Simpan. Coba Koreksi dan VOID.")),
    ("💧", ("Prediction & recommendation", "Prediksi & rekomendasi"), ("Pick temperature source, rain scenario and model M1/M2. “Why this recommendation?” explains every step. Publish.",
                                                                  "Pilih sumber suhu, skenario hujan, dan model M1/M2. “Mengapa rekomendasi ini?” menjelaskan tiap langkah. Terbitkan.")),
    ("👷", ("Operator decision", "Keputusan operator"), ("APPROVE, MODIFY (amount must change + reason) or DELAY. Labelled SIMULATION.",
                                                        "APPROVE, MODIFY (jumlah harus berubah + alasan) atau DELAY. Berlabel SIMULASI.")),
    ("🚿", ("Irrigation execution", "Pelaksanaan irigasi"), ("Record what actually flowed; the chain SOMAT → operator → actual is shown.",
                                                           "Catat air yang benar-benar mengalir; rantai SOMAT → operator → aktual ditampilkan.")),
    ("🤖", ("Evaluation & AI model", "Evaluasi & model AI"), ("Prediction vs observed h; Admin → Demo trains the Random Forest and Prediction compares M1 vs M2.",
                                                           "Prediksi vs h teramati; Admin → Demo melatih Random Forest dan Prediksi membandingkan M1 vs M2.")),
]


def flow_html(dark: bool, lang: str) -> str:
    c = PAL[dark]
    i = 0 if lang == "en" else 1
    items = "".join(
        f'<li style="--d:{k * 0.45}s"><span class="dot"><b>{k + 1}</b></span><div class="card"><div class="h">{ic} {ttl[i]}</div>'
        f'<div class="p">{txt[i]}</div></div></li>' for k, (ic, ttl, txt) in enumerate(STEPS))
    css = f"""
ol{{list-style:none;margin:0;padding:44px 16px 36px 16px;position:relative;box-sizing:border-box;width:760px}}
ol::before{{content:"";position:absolute;left:35px;top:50px;bottom:48px;width:3px;border-radius:3px;
  background:repeating-linear-gradient({c['blue']} 0 10px, transparent 10px 20px);background-size:3px 20px;animation:flowy 1s linear infinite;opacity:.85}}
@keyframes flowy{{to{{background-position:0 20px}}}}
li{{position:relative;display:flex;gap:14px;align-items:flex-start;margin:0 0 12px 0}}
.dot{{flex:0 0 40px;height:40px;border-radius:50%;background:{c['bcard']};border:2px solid {c['blue']};display:grid;place-items:center;z-index:1;
  animation:pulse 4s ease-in-out infinite;animation-delay:var(--d)}}
.dot b{{font-size:15px;color:{c['text']}}}
@keyframes pulse{{0%,100%{{box-shadow:0 0 0 0 transparent}}12%{{box-shadow:0 0 0 7px {c['blue']}33}}28%{{box-shadow:0 0 0 0 transparent}}}}
.card{{flex:1;background:{c['card']};border:1px solid {c['line']};border-radius:12px;padding:9px 13px;min-width:0}}
.h{{font-weight:700;font-size:14.5px;margin-bottom:2px}}
.p{{font-size:13px;color:{c['mute']};line-height:1.4}}
"""
    hint = "Scroll to zoom · drag to pan" if lang == "en" else "Gulir untuk zoom · seret untuk menggeser"
    return _viewer(f"<ol>{items}</ol>", css, dark, 760, "width", hint)


# ----------------------------------------------------------------------------------------------- isi
RIGHTS = [
    # (objek, aksi, Admin, Operator, Pengamat)
    ("Pengamatan h", "Input baru", "ya", "ya", "tidak"),
    ("Pengamatan h", "Koreksi (record baru, lama SUPERSEDED)", "semua", "milik sendiri", "tidak"),
    ("Pengamatan h", "VOID (beralasan, tidak dihapus)", "semua", "milik sendiri", "tidak"),
    ("Rekomendasi", "Terbitkan (immutable)", "ya", "ya", "tidak"),
    ("Rekomendasi", "Edit / hapus", "tidak", "tidak", "tidak"),
    ("Keputusan (APPROVE/MODIFY/DELAY)", "Catat (atomik, idempoten)", "ya", "ya", "tidak"),
    ("Keputusan", "Edit = koreksi (record baru)", "semua", "milik sendiri", "tidak"),
    ("Keputusan", "Delete = VOID (beralasan)", "ya", "tidak", "tidak"),
    ("Pelaksanaan (simulasi)", "Catat", "ya", "ya", "tidak"),
    ("Pelaksanaan (simulasi)", "VOID", "semua", "milik sendiri", "tidak"),
    ("Data awal demo", "Kembalikan skenario awal / Kosongkan / Ekspor", "ya", "tidak", "tidak"),
    ("Model AI demo", "Latih ulang", "ya", "tidak", "tidak"),
]

LIMITS = [
    ("All plots, sensors, parameters, history, decisions and execution in the DEMO space are **synthetic**; parameters are EXAMPLE so the run mode is always DEMO.",
     "Semua petak, sensor, parameter, riwayat, keputusan, dan pelaksanaan di ruang DEMO **sintetis**; parameter berstatus CONTOH sehingga mode run selalu DEMO."),
    ("The AI model is a Random Forest trained on a synthetic corpus; its metrics show the pipeline works, **not field accuracy**.",
     "Model AI adalah Random Forest yang dilatih dari korpus sintetis; metriknya menunjukkan alur bekerja, **bukan akurasi lapangan**."),
    ("BMKG forecast (when chosen) is real, with its real freshness; if it is missing the run becomes INCOMPLETE_FORECAST instead of being filled with invented data. BMKG does not forecast rain here: rain is always an explicit scenario.",
     "Prakiraan BMKG (bila dipilih) adalah data asli dengan keterkinian apa adanya; bila kosong, rekomendasi menjadi INCOMPLETE_FORECAST, bukan diisi data karangan. Hujan BMKG tidak diprakirakan: hujan selalu skenario eksplisit."),
    ("Demo times are re-aligned to “now” automatically; **Restore initial scenario** (Admin → Demo) resets all changes.",
     "Waktu demo diselaraskan ke “sekarang” otomatis; **Kembalikan skenario awal** (Admin → Demo) mengatur ulang semua perubahan."),
]


def render_body():
    dark = _dark()
    lang = st.session_state.get("lang", "en")
    tab1, tab2, tab3 = st.tabs([L("Architecture", "Arsitektur"), L("Walkthrough", "Alur pelaksanaan"), L("Rights & limits", "Hak & batasan")])
    with tab1:
        components.html(architecture_html(dark, lang), height=600, scrolling=False)
        st.caption(L("Both workspaces use the same engine; only the inputs and the storage differ. The demo never writes to the operational database.",
                     "Kedua ruang kerja memakai mesin yang sama; hanya masukan dan penyimpanan yang berbeda. Demo tidak pernah menulis ke database operasional."))
    with tab2:
        components.html(flow_html(dark, lang), height=600, scrolling=False)
    with tab3:
        st.markdown("**" + L("Who may edit, correct or void", "Siapa boleh mengedit, mengoreksi, atau membatalkan") + "**")
        table([{L("Object", "Objek"): o, L("Action", "Aksi"): a, "Admin": ad, "Operator": op, L("Viewer", "Pengamat"): v}
               for o, a, ad, op, v in RIGHTS], key="guide_rights", max_height=360)
        st.caption(L("Nothing is physically deleted: corrections create new records (old = SUPERSEDED); cancellations are VOID with a reason. Permissions are re-checked in the backend, not only on the buttons.",
                     "Tidak ada yang dihapus fisik: koreksi membuat record baru (lama = SUPERSEDED); pembatalan berupa VOID beralasan. Izin diperiksa ulang di backend, bukan hanya pada tombol."))
        st.markdown("**" + L("What is real and what is synthetic", "Yang nyata dan yang sintetis") + "**")
        for en, idn in LIMITS:
            st.markdown("- " + L(en, idn))


@st.dialog(L("📘 Demo Guide", "📘 Panduan Demo"), width="large")
def open_guide():
    st.caption(L("How to present SOMAT with the built-in research demo. Nothing here touches operational data.",
                 "Cara mempresentasikan SOMAT dengan demo penelitian bawaan. Tidak ada yang menyentuh data operasional."))
    render_body()
