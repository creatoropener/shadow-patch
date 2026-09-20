"""Render accurately labelled evidence graphics, not simulated GitHub screens.

Requires Pillow and DejaVu Sans fonts. Does not run any application or test.
"""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/visuals"
OUT.mkdir(exist_ok=True)
P = json.loads((ROOT / "docs/evidence/green-run-v0.5.5.json").read_text())
FONT = Path("/usr/share/fonts/truetype/dejavu")
BG, PANEL, WHITE, MINT, MUTED, RED = '#0a1420', '#142637', '#eff6fb', '#79ebc4', '#acc1d2', '#ffa4a4'


def font(size, bold=False, mono=False):
    family = 'DejaVuSansMono' if mono else 'DejaVuSans'
    return ImageFont.truetype(str(FONT / (family + ('-Bold' if bold else '') + '.ttf')), size)


def wrap(draw, text, f, width):
    lines=[]
    for paragraph in text.split('\n'):
        current=''
        for word in paragraph.split():
            trial=(current+' '+word).strip()
            if draw.textlength(trial,font=f)>width and current:
                lines.append(current);current=word
            else: current=trial
        lines.append(current)
    return lines


def text(draw, x, y, value, size=26, color=WHITE, width=1400, bold=False, mono=False):
    f=font(size,bold,mono)
    for line in wrap(draw,value,f,width):
        draw.text((x,y),line,font=f,fill=color);y+=int(size*1.4)
    return y


def base(title, subtitle):
    im=Image.new('RGB',(1600,900),BG);d=ImageDraw.Draw(im)
    text(d,64,38,'SHADOW ENGINEER / PATCHPROOF',22,MINT,bold=True)
    text(d,1120,40,'RECORDED EVIDENCE',18,MUTED,width=430)
    d.line((64,90,1536,90),fill='#304759',width=2)
    text(d,64,120,title,52,bold=True)
    text(d,64,208,subtitle,25,MUTED,width=1450)
    d.line((64,810,1536,810),fill='#304759',width=2)
    text(d,64,835,'Evidence card from saved proof.json · Not a live run or a GitHub screenshot',18,MUTED)
    return im,d


im,d=base('A repair backed by test evidence.','File-sharing app #1 · NVIDIA Nemotron on Nebius Token Factory · v0.5.5')
metrics=[(str(len(P['candidates'])),'candidates evaluated'),(str(sum(c['passed'] for c in P['candidates'])),'candidates passed'),(str(P['baseline']['tests_passed']),'baseline tests'),(str(P['clean_replay']['tests_passed']),'replay regression tests')]
for i,(n,label) in enumerate(metrics):
    x=64+i*374;d.rounded_rectangle((x,300,x+350,487),18,fill=PANEL)
    text(d,x+25,322,n,64,MINT,bold=True);text(d,x+25,425,label,21,MUTED,width=310)
text(d,70,535,'Bug reproduced before repair',30)
text(d,70,600,'Same frozen regression; clean-image replay passed',30)
text(d,70,665,f"Selected candidate {P['winner']['candidate']} · Human merge approval required",30,MINT)
im.save(OUT/'01-verification.png')

im,d=base('The verifier reproduced a real bug.','Expected behavior comes from the issue. The test is created before a candidate patch.')
d.rounded_rectangle((64,305,1536,680),18,fill=PANEL)
text(d,100,335,'formatBytes(1024)',34,MINT,mono=True)
text(d,100,412,'Expected: "1.0 KB"',34,WHITE,mono=True)
text(d,100,483,'Before repair: literal v.toFixed(...) fragments',29,RED,mono=True)
text(d,100,567,'Recorded outcome: accepted assertion failure',28)
text(d,70,725,'An import error or an already-passing test would not establish reproduction.',23,MUTED)
im.save(OUT/'07-reproduction.png')

im,d=base('One candidate failed the hidden test.','Three strategies ran sequentially in separate sandbox branches.')
for i,c in enumerate(P['candidates']):
    y=300+i*104;d.rounded_rectangle((64,y,1536,y+85),13,fill=PANEL)
    text(d,90,y+20,f"Candidate {c['candidate']}",28)
    text(d,470,y+20,'PASSED' if c['passed'] else 'REJECTED',28,MINT if c['passed'] else RED,bold=True)
    text(d,900,y+20,f"{c['duration_seconds']:.2f}s",26,MUTED)
    if c['candidate']==P['winner']['candidate']:text(d,1140,y+20,'WINNER',25,MINT,bold=True)
text(d,70,647,'Candidate 2: "1.0KB" did not equal "1.0 KB".',30,RED,mono=True)
text(d,70,717,'Its hidden-test result was not sent back to the solver.',24,MUTED)
im.save(OUT/'04-candidates.png')

im,d=base('Replay starts from a clean base image.','Original repository archive + selected source changes + the frozen regression')
d.rounded_rectangle((64,310,1536,700),18,fill=PANEL)
text(d,100,345,f"Baseline: {P['baseline']['tests_passed']} passed",36,MINT,bold=True)
text(d,100,412,f"Regression: {P['clean_replay']['tests_passed']} passed",36,MINT,bold=True)
text(d,100,492,f"Replay exit code: {P['clean_replay']['exit_code']}",28)
text(d,100,550,'Regression hash unchanged at measured checkpoints',27)
text(d,100,610,P['regression_test']['sha256'],19,MUTED,mono=True,width=1380)
text(d,70,739,'Recorded test evidence is not a formal proof of complete correctness.',24,MUTED)
im.save(OUT/'05-replay.png')

im,d=base('Inspect the evidence. Keep human review.','GitHub Actions MVP · One demonstrated TypeScript utility repair')
text(d,70,310,'Source: github.com/creatoropener/shadow-patch',28,MINT)
text(d,70,390,'PR: github.com/creatoropener/file-sharing-app/pull/2',28)
text(d,70,470,'Green run: 35464615209',28)
text(d,70,565,'No automatic merge. No claim of universal correctness.',30,MINT,bold=True)
text(d,70,660,'Next: broader runtime evidence and stronger commit-bound reports.',26,MUTED)
im.save(OUT/'06-sources.png')
print('Rendered five evidence cards from the captured green-run report.')
