#!/usr/bin/env python3
"""Convert the Claude Design canvas (project/*.dc.html) into a static site for GitHub Pages.

Usage: python3 export.py <project_dir> <assets_dir> <out_dir>
  project_dir : folder with Main.dc.html, *.dc.html, downloads/
  assets_dir  : folder with <blob_id>.<ext> files (images referenced as /_blob/<id>)
  out_dir     : static site output (index.html, <Page>.html, assets/, downloads/)
"""
import json, os, re, shutil, subprocess, sys, html

ACCENT = "#2B4EFF"
proj, assets_dir, out = sys.argv[1:4]
os.makedirs(os.path.join(out, "assets"), exist_ok=True)

blobs = {os.path.splitext(f)[0]: f for f in os.listdir(assets_dir)}
used, missing = set(), set()


def page_name(f):
    return "index.html" if f == "Main.dc.html" else f.replace(".dc.html", ".html")


def fix_links(s):
    s = re.sub(r'(href=")Main\.dc\.html', r'\1index.html', s)
    s = re.sub(r"([\"'])Main\.dc\.html", r"\1index.html", s)
    s = re.sub(r'([A-Za-z0-9_-]+)\.dc\.html', r'\1.html', s)
    return s


def fix_blobs(s):
    # drop image wrappers whose asset is unavailable
    def drop(m):
        bid = m.group(1)
        if bid in blobs:
            return m.group(0)
        missing.add(bid)
        return ""
    s = re.sub(r'<div class="hx-media"[^>]*>\s*<img[^>]*src="/_blob/([0-9a-f]{32})"[^>]*>\s*</div>', drop, s)

    def rep(m):
        bid = m.group(1)
        if bid in blobs:
            used.add(bid)
            return "assets/" + blobs[bid]
        missing.add(bid)
        return "assets/missing.png"
    return re.sub(r'/_blob/([0-9a-f]{32})', rep, s)


def eval_js_array(src):
    """Evaluate a JS array literal with node and return it as Python data."""
    r = subprocess.run(["node", "-e", f"process.stdout.write(JSON.stringify({src}))"], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def render_main(body, script):
    all_src = re.search(r"const all = (\[.*?\])\s*\.map", script, re.S).group(1)
    defs_src = re.search(r"const defs = (\[.*?\]);", script, re.S).group(1)
    projects, defs = eval_js_array(all_src), eval_js_array(defs_src)

    # filter buttons
    tabs_tpl = re.search(r'<sc-for list="\{\{tabs\}\}".*?</sc-for>', body, re.S).group(0)
    on_btn = re.search(r'<sc-if value="\{\{t\.on\}\}"[^>]*>\s*(<button.*?</button>)', tabs_tpl, re.S).group(1)
    btns = []
    for i, d in enumerate(defs):
        b = on_btn.replace('onClick="{{t.pick}}" ', '').replace("{{t.label}}", html.escape(d["label"]))
        b = b.replace('<button ', f'<button data-filter="{d["id"]}" class="pf-tab" ', 1)
        if i:
            b = b.replace('aria-pressed="true"', 'aria-pressed="false"').replace("background: #0A0A0A; color: #FFFFFF", "background: transparent; color: #3A3F47")
        btns.append(b)
    body = body.replace(tabs_tpl, "\n".join(btns))

    # project cards
    proj_tpl = re.search(r'<sc-for list="\{\{projects\}\}"[^>]*>(.*?)</sc-for>', body, re.S)
    card_tpl = proj_tpl.group(1)
    cards = []
    for p in projects:
        c = card_tpl
        img_if = re.search(r'<sc-if value="\{\{p\.hasImg\}\}"[^>]*>(.*?)</sc-if>', c, re.S)
        noimg_if = re.search(r'<sc-if value="\{\{p\.noImg\}\}"[^>]*>(.*?)</sc-if>', c, re.S)
        link_if = re.search(r'<sc-if value="\{\{p\.hasLink\}\}"[^>]*>(.*?)</sc-if>', c, re.S)
        c = c.replace(img_if.group(0), img_if.group(1) if p.get("img") else "")
        c = c.replace(noimg_if.group(0), "" if p.get("img") else noimg_if.group(1))
        c = c.replace(link_if.group(0), link_if.group(1) if p.get("href") else "")
        for k in ("img", "alt", "pos", "meta", "title", "line", "href"):
            c = c.replace("{{p.%s}}" % k, html.escape(p.get(k, ""), quote=True))
        c = c.replace('<article ', f'<article data-cat="{p["cat"]}" ', 1)
        cards.append(c)
    body = body.replace(proj_tpl.group(0), "".join(cards))

    filter_js = """
<script>
document.querySelectorAll('.pf-tab').forEach(function (b) {
  b.addEventListener('click', function () {
    var f = b.getAttribute('data-filter');
    document.querySelectorAll('.pf-tab').forEach(function (o) {
      var on = o === b;
      o.setAttribute('aria-pressed', on ? 'true' : 'false');
      o.style.background = on ? '#0A0A0A' : 'transparent';
      o.style.color = on ? '#FFFFFF' : '#3A3F47';
    });
    document.querySelectorAll('article[data-cat]').forEach(function (a) {
      a.style.display = (f === 'all' || a.getAttribute('data-cat') === f) ? '' : 'none';
    });
  });
});
</script>"""
    return body, filter_js


for f in sorted(os.listdir(proj)):
    if not f.endswith(".dc.html"):
        continue
    src = open(os.path.join(proj, f), encoding="utf-8").read()
    title = re.search(r"<title>(.*?)</title>", src, re.S).group(1)
    helmet = re.search(r"<helmet>(.*?)</helmet>", src, re.S).group(1)
    body = re.search(r"</helmet>(.*?)</x-dc>", src, re.S).group(1)
    script = re.search(r'<script type="text/x-dc"[^>]*>(.*?)</script>', src, re.S).group(1)
    extra_js = ""
    if "<sc-for" in body:
        body, extra_js = render_main(body, script)
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="Engineering portfolio of Hamza Houir Alami — Arts et Métiers.">
{helmet.strip()}
<style>html,body{{overflow-x:clip}}</style>
</head>
<body>
{body.strip()}
{extra_js}
</body>
</html>
"""
    doc = doc.replace("{{accent}}", ACCENT)
    doc = fix_links(fix_blobs(doc))
    left = re.findall(r"\{\{[^}]*\}\}|<sc-|</?x-dc|support\.js", doc)
    if left:
        raise SystemExit(f"{f}: unresolved template bits {set(left)}")
    open(os.path.join(out, page_name(f)), "w", encoding="utf-8").write(doc)
    print("page", page_name(f), len(doc))

for bid in used:
    shutil.copy(os.path.join(assets_dir, blobs[bid]), os.path.join(out, "assets", blobs[bid]))
if os.path.isdir(os.path.join(proj, "downloads")):
    shutil.copytree(os.path.join(proj, "downloads"), os.path.join(out, "downloads"), dirs_exist_ok=True)
open(os.path.join(out, ".nojekyll"), "w").close()
print("assets", len(used), "missing", sorted(missing))
