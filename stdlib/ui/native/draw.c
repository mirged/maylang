/* CPU raster surface, font metrics and PNG output. No widget/layout policy. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#define STB_TRUETYPE_IMPLEMENTATION
#include "vendor/stb_truetype.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"
static unsigned char *pixels, *font_data;
static stbtt_fontinfo font;
static long width, height, left, top, right, bottom;
static int ready;
extern void mui_window_present(const unsigned char *, long, long);
static int init_font(void) {
    if (ready) return 1;
    const char *paths[] = {getenv("MAYUI_FONT"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"};
    for (size_t i = 0; i < sizeof(paths)/sizeof(paths[0]); ++i) {
        if (!paths[i]) continue;
        FILE *f = fopen(paths[i], "rb"); if (!f) continue;
        if (fseek(f,0,SEEK_END) || ftell(f) <= 0 || ftell(f) > 16000000) { fclose(f); continue; }
        long n = ftell(f); rewind(f); font_data = malloc(n);
        if (!font_data || fread(font_data,1,n,f) != (size_t)n) { free(font_data); font_data=NULL; fclose(f); continue; }
        fclose(f);
        if (stbtt_InitFont(&font,font_data,stbtt_GetFontOffsetForIndex(font_data,0))) { ready=1; return 1; }
        free(font_data); font_data=NULL;
    }
    return 0;
}
long mui_surface(long w, long h) {
    if (w < 1 || h < 1 || w > 8192 || h > 8192 || !init_font()) return 0;
    if (w != width || h != height || !pixels) {
        unsigned char *next = calloc((size_t)w*h,3); if (!next) return 0;
        free(pixels); pixels=next; width=w; height=h;
    }
    left=top=0; right=width; bottom=height; return 1;
}
void mui_release(void) { free(pixels); pixels=NULL; free(font_data); font_data=NULL; ready=0; width=height=0; }
void mui_clip(long x,long y,long w,long h) {
    left=x>0?x:0; top=y>0?y:0; right=x+w<width?x+w:width; bottom=y+h<height?y+h:height;
}
static void pixel(long x,long y,long color,int alpha) {
    if (!pixels || x<left || y<top || x>=right || y>=bottom) return;
    unsigned char *p=pixels+(y*width+x)*3;
    for (int k=0;k<3;k++) p[k]=(p[k]*(255-alpha)+((color>>(16-8*k))&255)*alpha+127)/255;
}
void mui_rect(long x,long y,long w,long h,long radius,long color) {
    if (!pixels || w<=0 || h<=0) return;
    if (radius<0) radius=0;
    if (radius>w/2) radius=w/2;
    if (radius>h/2) radius=h/2;
    long x0=x>left?x:left, y0=y>top?y:top, x1=x+w<right?x+w:right, y1=y+h<bottom?y+h:bottom;
    for(long py=y0;py<y1;py++) for(long px=x0;px<x1;px++) {
        long dx=px<x+radius?x+radius-px: px>=x+w-radius?px-(x+w-radius-1):0;
        long dy=py<y+radius?y+radius-py: py>=y+h-radius?py-(y+h-radius-1):0;
        if (!dx || !dy || dx*dx+dy*dy<=radius*radius) pixel(px,py,color,255);
    }
}
static unsigned codepoint(const unsigned char **s) {
    unsigned a=*(*s)++; if(a<128) return a;
    int n=a>=240?3:a>=224?2:a>=192?1:0; unsigned c=a&((1u<<(6-n))-1);
    if(!n) return 0xfffd;
    for(int i=0;i<n;i++) { if((**s&192)!=128) return 0xfffd; c=(c<<6)|(*(*s)++&63); }
    return c;
}
long mui_measure(const char *text,long px) {
    if(!init_font() || px<6 || px>96) return 0;
    float scale=stbtt_ScaleForPixelHeight(&font,px), result=0;
    const unsigned char *s=(const unsigned char*)text;
    while(*s) { unsigned c=codepoint(&s); int advance,bearing; stbtt_GetCodepointHMetrics(&font,c,&advance,&bearing); result+=advance*scale;
        if(*s) { const unsigned char *next=s; result+=stbtt_GetCodepointKernAdvance(&font,c,codepoint(&next))*scale; }
    }
    return (long)(result+0.5f);
}
void mui_text(long x,long y,const char *text,long px,long color) {
    if(!pixels || !init_font() || px<6 || px>96) return;
    float scale=stbtt_ScaleForPixelHeight(&font,px), pen=x; int ascent,descent,gap;
    stbtt_GetFontVMetrics(&font,&ascent,&descent,&gap); int baseline=y+(int)(ascent*scale);
    const unsigned char *s=(const unsigned char*)text;
    while(*s) { unsigned c=codepoint(&s); int w,h,ox,oy,advance,bearing;
        unsigned char *mask=stbtt_GetCodepointBitmap(&font,0,scale,c,&w,&h,&ox,&oy);
        if(mask) { for(int j=0;j<h;j++) for(int i=0;i<w;i++) pixel((long)pen+ox+i,baseline+oy+j,color,mask[j*w+i]); stbtt_FreeBitmap(mask,NULL); }
        stbtt_GetCodepointHMetrics(&font,c,&advance,&bearing); pen+=advance*scale;
        if(*s) { const unsigned char *next=s; pen+=stbtt_GetCodepointKernAdvance(&font,c,codepoint(&next))*scale; }
        if(pen>=right) break;
    }
}
void mui_present(void) { if(pixels) mui_window_present(pixels,width,height); }
long mui_snapshot(const char *path) { return pixels && stbi_write_png(path,width,height,3,pixels,width*3); }
long mui_pixel(long x,long y) { if(!pixels || x<0 || y<0 || x>=width || y>=height) return -1; unsigned char *p=pixels+(y*width+x)*3; return (p[0]<<16)|(p[1]<<8)|p[2]; }
