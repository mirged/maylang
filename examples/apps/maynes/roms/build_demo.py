#!/usr/bin/env python3
"""Build Starfall, an original NROM/6502 game. No assembler or game ROM download.

Code and generated ROM are offered under the MIT license in roms/LICENSE.
Zero page: 0 paddle X, 1 star X, 2 star Y, 3 score ones, 4 score tens,
5 lives, 6 game over, 7 random seed, 8 buttons, 9 speed, 10 scratch.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
code = bytearray()
labels = {}
fixups = []

def emit(*values): code.extend(values)
def label(name): labels[name] = 0x8000 + len(code)
def absolute(op, name):
    emit(op, 0, 0); fixups.append((len(code)-2, name, False))
def branch(op, name):
    emit(op, 0); fixups.append((len(code)-1, name, True))
def imm(op, n): emit(op, n)
def store(addr): emit(0x8d, addr & 255, addr >> 8)
def load(addr): emit(0xad, addr & 255, addr >> 8)
def setreg(addr, value): imm(0xa9, value); store(addr)
def text_at(table, row, col, text):
    for i, c in enumerate(text): table[row*32+col+i] = ord(c)

label('reset')
emit(0x78, 0xd8); imm(0xa2, 0xff); emit(0x9a, 0xe8)
store(0x2000); store(0x2001); store(0x4010)
setreg(0x4017, 0x40)
label('vblank1'); emit(0x2c, 2, 0x20); branch(0x10,'vblank1')
imm(0xa9,0); imm(0xa2,0)
label('clear');
for page in (0,1,3,4,5,6,7): emit(0x9d,0,page)
emit(0xe8); branch(0xd0,'clear')
imm(0xa9,0xff); imm(0xa2,0)
label('oamclear'); emit(0x9d,0,2,0xe8); branch(0xd0,'oamclear')
label('vblank2'); emit(0x2c,2,0x20); branch(0x10,'vblank2')
setreg(0x2006,0x3f); setreg(0x2006,0)
imm(0xa2,0)
label('palette_loop'); absolute(0xbd,'palette'); store(0x2007); emit(0xe8); imm(0xe0,32); branch(0xd0,'palette_loop')
setreg(0x2006,0x20); setreg(0x2006,0)
for page in range(4):
    imm(0xa2,0); label('nametable'+str(page)); absolute(0xbd,'nt'+str(page)); store(0x2007); emit(0xe8); branch(0xd0,'nametable'+str(page))
absolute(0x20,'restart')
setreg(0x4015,1); setreg(0x2005,0); setreg(0x2005,0); setreg(0x2000,0x80); setreg(0x2001,0x1e)
label('forever'); absolute(0x4c,'forever')
label('restart')
for addr,val in ((0,112),(1,120),(2,48),(3,0),(4,0),(5,3),(6,0),(7,43)):
    imm(0xa9,val); emit(0x85,addr)
emit(0x60)
label('nmi'); emit(0x48,0x8a,0x48,0x98,0x48)
setreg(0x4016,1); setreg(0x4016,0); imm(0xa2,8); imm(0xa9,0); emit(0x85,8)
label('readpad'); load(0x4016); emit(0x4a,0x26,8,0xca); branch(0xd0,'readpad')
emit(0xa5,8); imm(0x29,16); branch(0xf0,'no_restart'); absolute(0x20,'restart')
label('no_restart'); emit(0xa5,6); branch(0xf0,'play'); absolute(0x4c,'draw')
label('play'); imm(0xa9,2); emit(0x85,9); emit(0xa5,8); imm(0x29,128); branch(0xf0,'speed_set'); imm(0xa9,4); emit(0x85,9)
label('speed_set'); emit(0xa5,8); imm(0x29,2); branch(0xf0,'right'); emit(0xa5,0,0x38,0xe5,9); imm(0xc9,16); branch(0xb0,'left_store'); imm(0xa9,16)
label('left_store'); emit(0x85,0)
label('right'); emit(0xa5,8); imm(0x29,1); branch(0xf0,'fall'); emit(0xa5,0,0x18,0x65,9); imm(0xc9,217); branch(0x90,'right_store'); imm(0xa9,216)
label('right_store'); emit(0x85,0)
label('fall'); emit(0xe6,2,0xe6,2,0xa5,2); imm(0xc9,204); branch(0x90,'draw')
emit(0xa5,1,0x38,0xe5,0); imm(0xc9,25); branch(0xb0,'miss')
emit(0xe6,3,0xa5,3); imm(0xc9,10); branch(0x90,'catch_sound'); imm(0xa9,0); emit(0x85,3,0xe6,4,0xa5,4); imm(0xc9,10); branch(0x90,'catch_sound'); imm(0xa9,0); emit(0x85,4)
label('catch_sound'); setreg(0x4000,0x9a); setreg(0x4002,0xfd); setreg(0x4003,0x08); absolute(0x4c,'respawn')
label('miss'); emit(0xc6,5); branch(0xd0,'miss_sound'); imm(0xa9,1); emit(0x85,6)
label('miss_sound'); setreg(0x4000,0x9a); setreg(0x4002,0xfc); setreg(0x4003,0x1a)
label('respawn'); imm(0xa9,48); emit(0x85,2,0xa5,7,0x18); imm(0x69,73); branch(0x90,'random_no_carry'); imm(0x69,18)
label('random_no_carry'); emit(0x85,7); imm(0x29,0xbf); emit(0x18); imm(0x69,24); emit(0x85,1)
label('draw')
# star sprite
emit(0xa5,2); store(0x0200); setreg(0x0201,128); setreg(0x0202,0); emit(0xa5,1); store(0x0203)
# three-segment paddle
for i,tile in enumerate((129,130,131)):
    setreg(0x0204+4*i,212); setreg(0x0205+4*i,tile); setreg(0x0206+4*i,1)
    emit(0xa5,0,0x18); imm(0x69,i*8); store(0x0207+4*i)
setreg(0x2003,0); setreg(0x4014,2)
# score and lives text updates during vblank
for addr,var in ((0x2068,4),(0x2069,3),(0x2079,5)):
    setreg(0x2006,addr>>8); setreg(0x2006,addr&255); emit(0xa5,var,0x18); imm(0x69,48); store(0x2007)
# GAME OVER text uses palette swap to alert while keeping screen playable
setreg(0x2006,0x3f); setreg(0x2006,0x11); emit(0xa5,6); branch(0xf0,'alive_palette'); imm(0xa9,0x16); absolute(0x4c,'write_palette')
label('alive_palette'); imm(0xa9,0x28)
label('write_palette'); store(0x2007)
setreg(0x2000,0x80); setreg(0x2005,0); setreg(0x2005,0)
emit(0x68,0xa8,0x68,0xaa,0x68,0x40)
label('irq'); emit(0x40)
label('palette'); emit(*([0x0f,0x21,0x30,0x12]*4+[0x0f,0x28,0x38,0x30]+[0x0f,0x21,0x31,0x30]*3))
nt=bytearray(1024)
text_at(nt,1,12,'STARFALL')
text_at(nt,3,2,'SCORE 00'); text_at(nt,3,18,'LIVES  3')
text_at(nt,6,4,'CATCH THE FALLING STARS')
text_at(nt,28,4,'ARROWS MOVE   X BOOSTS')
text_at(nt,29,8,'ENTER RESTARTS')
# scattered backdrop stars and a ground line
for row in range(9,24):
    for col in range(2,30):
        if (row*31+col*17)%89==0: nt[row*32+col]=132
for col in range(2,30): nt[27*32+col]=133
for page in range(4): label('nt'+str(page)); emit(*nt[page*256:(page+1)*256])
for offset,name,relative in fixups:
    value=labels[name]
    if relative:
        delta=value-(0x8000+offset+1)
        assert -128<=delta<=127,(name,delta)
        code[offset]=delta&255
    else: code[offset:offset+2]=value.to_bytes(2,'little')
assert len(code)<0x3ffa
prg=code+bytes([0xea])*(0x3ffa-len(code))
for vector in ('nmi','reset','irq'): prg+=labels[vector].to_bytes(2,'little')
# 5x7 glyphs, drawn as NES 2bpp tiles. Hand-authored, original graphics.
font={
'A':['01110','10001','10001','11111','10001','10001','10001'],
'B':['11110','10001','10001','11110','10001','10001','11110'],
'C':['01111','10000','10000','10000','10000','10000','01111'],
'E':['11111','10000','10000','11110','10000','10000','11111'],
'F':['11111','10000','10000','11110','10000','10000','10000'],
'G':['01111','10000','10000','10111','10001','10001','01111'],
'H':['10001','10001','10001','11111','10001','10001','10001'],
'I':['11111','00100','00100','00100','00100','00100','11111'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'M':['10001','11011','10101','10101','10001','10001','10001'],
'N':['10001','11001','10101','10011','10001','10001','10001'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'S':['01111','10000','10000','01110','00001','00001','11110'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'U':['10001','10001','10001','10001','10001','10001','01110'],
'V':['10001','10001','10001','10001','10001','01010','00100'],
'W':['10001','10001','10001','10101','10101','11011','10001'],
'X':['10001','10001','01010','00100','01010','10001','10001'],
'0':['01110','10001','10011','10101','11001','10001','01110'],
'1':['00100','01100','00100','00100','00100','00100','01110'],
'2':['01110','10001','00001','00010','00100','01000','11111'],
'3':['11110','00001','00001','01110','00001','00001','11110'],
'4':['00010','00110','01010','10010','11111','00010','00010'],
'5':['11111','10000','10000','11110','00001','00001','11110'],
'6':['01110','10000','10000','11110','10001','10001','01110'],
'7':['11111','00001','00010','00100','01000','01000','01000'],
'8':['01110','10001','10001','01110','10001','10001','01110'],
'9':['01110','10001','10001','01111','00001','00001','01110'],
}
chrdata=bytearray(8192)
for char,rows in font.items():
    for y,row in enumerate(rows): chrdata[ord(char)*16+y]=int(row,2)<<2
# little yellow star; cool blue paddle; subtle background dots
for tile,rows in {128:[0x10,0x38,0x7c,0xfe,0x7c,0x38,0x54,0],129:[0,0x3f,0x7f,0xff,0xff,0x7f,0,0],130:[0,255,255,255,255,255,0,0],131:[0,0xfc,0xfe,255,255,0xfe,0,0],132:[0,0,0,0x10,0,0,0,0],133:[0,0xff,0,0,0,0,0,0]}.items():
    chrdata[tile*16:tile*16+8]=bytes(rows)
rom=b'NES\x1a'+bytes([1,1,0,0])+bytes(8)+prg+chrdata
(ROOT/'roms/starfall.nes').write_bytes(rom)
(ROOT/'native/demo.h').write_text('/* Original Starfall cartridge, generated by roms/build_demo.py. */\nstatic const unsigned char demo_rom[] = {\n'+''.join('    '+','.join(str(v) for v in rom[i:i+32])+',\n' for i in range(0,len(rom),32))+'};\n')
print('Starfall:',len(rom),'bytes; code and data:',len(code),'bytes')
