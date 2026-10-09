"""Rebuild crisp 4x button artwork. Development dependency: Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'Icons'
SCALE = 4
FONT = next((p for p in [Path('C:/Windows/Fonts/seguisb.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')] if p.exists()), None)


def draw_icon(name, text, width=55, height=29, fill='#8fbc8f', color='#333333', size=12, radius=4):
    im = Image.new('RGBA',(width*SCALE,height*SCALE))
    d = ImageDraw.Draw(im)
    bounds = (2,2,width*SCALE-3,height*SCALE-3)
    if name=='EXIT':
        d.ellipse(bounds,fill=fill)
    else:
        d.rounded_rectangle(bounds,radius=radius*SCALE,fill=fill,outline='#657d85',width=3)
    font = ImageFont.truetype(str(FONT),size*SCALE) if FONT else ImageFont.load_default()
    d.multiline_text((width*SCALE/2,height*SCALE/2),text,font=font,fill=color,anchor='mm',align='center',spacing=0)
    im.save(ICONS/(name+'.png'))


def main():
    for label in ['other','rockPOP','blues','country','chinese','punk','hardrock','jPop','solo','metal']:
        draw_icon(label.upper(),label,95,fill='#abc7e3',color='#a00080',radius=6)
    for name,label in [('SHOW','SHOW'),('HIDE','HIDE'),('DEL','DEL'),('OPEN','OPEN'),('VOL-','VOL-'),('VOL+','VOL+'),('DEL_PRE','DEL\nPRE')]:
        draw_icon(name,label,size=11 if name=='DEL_PRE' else 12)
    for name,label,w,size in [('SEQ','SEQ',78,12),('RANDOM','RANDOM',79,10),('RESTORE','RESTORE',60,9),('PlayPre','<<',78,12),('PlayNext','>>',79,12),('Play','|>',60,12),('Pause','Ⅱ',60,15)]:
        draw_icon(name,label,w,size=size)
    draw_icon('SEQ_ACTIVE','SEQ',78,fill='#e64b42')
    draw_icon('RANDOM_ACTIVE','RANDOM',79,fill='#e64b42',size=10)
    draw_icon('EXIT','X',30,30,fill='#d52c2c',color='#563535',size=15)


if __name__=='__main__':
    main()
