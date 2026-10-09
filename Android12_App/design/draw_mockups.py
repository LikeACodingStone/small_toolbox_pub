"""Draw precise, editable Android UI concepts. Requires Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
S=3
BG='#F2F6FA'; INK='#182D42'; MUTED='#62758A'; BLUE='#007FAD'; LINE='#DCE5EE'
REG='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def screen(compact=False):
 im=Image.new('RGB',(412*S,892*S),BG); d=ImageDraw.Draw(im)
 def rect(box,fill,r=16,outline=None):
  d.rounded_rectangle(tuple(int(v*S) for v in box),radius=r*S,fill=fill,outline=outline,width=S)
 def text(x,y,t,size=14,color=INK,bold=False,anchor='la'):
  d.text((x*S,y*S),t,font=ImageFont.truetype(BOLD if bold else REG,size*S),fill=color,anchor=anchor)
 def button(x,y,w,label,fill='white',color=INK,border=LINE,size=13,h=48):
  rect((x,y,x+w,y+h),fill,12,border)
  text(x+w/2,y+h/2,label,size,color,True,'mm')
 text(24,16,'9:41',12,bold=True)
 text(388,16,'LTE   100%',11,anchor='ra')
 text(24,53,'RingPlayer',24,bold=True)
 text(24,85,'Listen. Sort. Keep your flow.',12,MUTED)
 button(308,52,80,'OPEN',BLUE,'white',BLUE,h=48)
 rect((20,116,392,174),'white',14,LINE)
 text(34,127,'SOURCE FOLDER',9,MUTED,True)
 text(34,145,'Music / Unsorted',14,bold=True)
 text(376,145,'500 tracks',11,MUTED,anchor='ra')
 rect((20,188,392,397),'white',20,LINE)
 rect((36,204,84,252),'#DDF3FA',12)
 text(60,228,'♫',28,BLUE,anchor='mm')
 text(98,205,'NOW PLAYING',9,BLUE,True)
 text(376,205,'1 / 500',11,MUTED,anchor='ra')
 text(98,224,'Midnight Drive',18,bold=True)
 text(98,249,'The Northbound · Opus',11,MUTED)
 text(36,286,'00:48',12,bold=True)
 text(376,286,'03:40',12,MUTED,anchor='ra')
 rect((36,315,376,319),'#E2EAF1',2)
 rect((36,315,110,319),BLUE,2)
 button(36,337,92,'PREV',h=44)
 button(140,332,132,'PAUSE',BLUE,'white',BLUE,h=54)
 button(284,337,92,'NEXT',h=44)
 button(20,411,100,'VOL−')
 text(206,435,'VOLUME  60%',12,MUTED,True,'mm')
 button(292,411,100,'VOL+')
 button(20,473,88,'SHOW',fill=BLUE if compact else 'white',color='white' if compact else INK)
 button(116,473,88,'HIDE',fill='white' if compact else BLUE,color=INK if compact else 'white')
 button(212,473,86,'SEQ',fill='#C63D47',color='white',border='#C63D47')
 button(306,473,86,'RANDOM',size=10)
 if not compact:
  text(24,543,'MOVE TO GENRE',11,MUTED,True)
  text(388,543,'Playback continues',10,BLUE,anchor='ra')
  genres=['other','rockPOP','blues','country','chinese','punk','hardrock','jPop','solo','metal']
  for i,label in enumerate(genres):
   button(20+(i%2)*192,568+(i//2)*49,180,label,'#DFEDF8','#305576','#D1E1EF',h=42)
 else:
  rect((20,542,392,809),'#E8F1F6',20)
  text(206,627,'Just listening.',22,BLUE,True,'mm')
  text(206,665,'Sorting controls are hidden.',13,MUTED,anchor='mm')
  text(206,690,'Tap SHOW to classify this track.',12,MUTED,anchor='mm')
 # Persistent action strip includes deletion and undo in both modes.
 # Use a taller canvas for generous touch targets in the full view.
 return im,d,rect,text,button

for compact,name in [(False,'full'),(True,'compact')]:
 im,d,rect,text,button=screen(compact)
 # Extend the phone canvas for the fixed bottom actions and system navigation.
 expanded=Image.new('RGB',(412*S,1012*S),BG)
 expanded.paste(im,(0,0))
 im=expanded; d=ImageDraw.Draw(im)
 # Drawing helpers close over the original draw object, so draw footer directly.
 def txt(x,y,t,size=12,color=INK,bold=False,anchor='la'):
  d.text((x*S,y*S),t,font=ImageFont.truetype(BOLD if bold else REG,size*S),fill=color,anchor=anchor)
 d.rounded_rectangle((20*S,824*S,392*S,862*S),radius=10*S,fill='#E2F2E9')
 txt(34,836,'Moved: metal · Still playing',12,'#276648')
 d.line((0,877*S,412*S,877*S),fill=LINE,width=S)
 for x,w,label,fill,col,detail in [(20,108,'DEL','#FCE8E9','#AC3540','Current track'),(140,112,'DEL PRE','#FCE8E9','#AC3540','Previous track'),(264,128,'RESTORE','#007FAD','white','3 / 10 saved')]:
  d.rounded_rectangle((x*S,891*S,(x+w)*S,942*S),radius=12*S,fill=fill)
  txt(x+w/2,916,label,13,col,True,'mm')
  txt(x+w/2,955,detail,10,MUTED,False,'mm')
 d.rounded_rectangle((148*S,991*S,264*S,995*S),radius=2*S,fill=INK)
 im.save(OUT/f'android12-{name}.png')

full=Image.open(OUT/'android12-full.png')
compact=Image.open(OUT/'android12-compact.png')
board=Image.new('RGB',(full.width*2+180,full.height+180),'#E0E8F0')
board.paste(full,(60,100));board.paste(compact,(full.width+120,100))
d=ImageDraw.Draw(board)
f=ImageFont.truetype(BOLD,36)
d.text((60,30),'FULL / CLASSIFY',font=f,fill=INK)
d.text((full.width+120,30),'COMPACT / LISTEN',font=f,fill=INK)
board.save(OUT/'android12-ui-overview.png')
print('Saved full, compact, and overview PNGs.')
